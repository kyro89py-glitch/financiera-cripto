"""Órdenes por precio (límite y stop), conversión entre monedas, velas y portada pública."""
from decimal import Decimal

import pytest

from financiera import cartera, db, graficos, notificaciones, operaciones, precios, programadas

from .conftest import cliente, usuario


def _saldo(monto=100000):
    laura = cliente("laura@x.com")
    operaciones.aprobar(operaciones.solicitar_aporte(laura, monto, "saldo", "T", None), usuario("op@x.com"))
    return laura, usuario("laura@x.com")


def test_orden_limite_y_stop(ctx):
    laura, u = _saldo()
    adm = usuario("admin@x.com")
    with pytest.raises(operaciones.ErrorNegocio, match="distinto del actual"):
        programadas.crear(laura, "BTC", "compra", Decimal("70000"), 20000, u)
    with pytest.raises(operaciones.ErrorNegocio, match="No tienes BTC"):
        programadas.crear(laura, "BTC", "venta", Decimal("80000"), 20000, u)
    with pytest.raises(operaciones.ErrorNegocio, match="saldo en dólares"):
        programadas.crear(laura, "BTC", "compra", Decimal("60000"), 200000, u)
    with pytest.raises(operaciones.ErrorNegocio, match="mínimo"):
        programadas.crear(laura, "BTC", "compra", Decimal("60000"), 500, u)
    oid = programadas.crear(laura, "BTC", "compra", Decimal("65000"), 26000, u)
    o = db.uno("SELECT * FROM programadas WHERE id = ?", (oid,))
    assert (o["condicion"], programadas.nombre(o)) == ("menor", "Compra límite")
    precios.actualizar_manual("BTC", Decimal("68000"), adm)                 # todavía no llega
    assert db.uno("SELECT estado FROM programadas WHERE id = ?", (oid,))["estado"] == "abierta"
    precios.actualizar_manual("BTC", Decimal("65000"), adm)                 # llega: se ejecuta sola
    o = db.uno("SELECT * FROM programadas WHERE id = ?", (oid,))
    assert o["estado"] == "ejecutada" and o["operacion_id"]
    assert cartera.tenencias(laura["id"]) == {"USD": 74000, "BTC": 400000}  # US$ 260 a 65.000
    assert "Se ejecutó tu orden programada" in notificaciones.listar(u["id"])[0]["texto"]
    # Stop: vender todo si baja; y venta límite si sube. Solo se dispara el stop.
    stop = programadas.crear(laura, "BTC", "venta", Decimal("60000"), 0, u, todo=True)
    lim = programadas.crear(laura, "BTC", "venta", Decimal("90000"), 10000, u)
    assert programadas.nombre(db.uno("SELECT * FROM programadas WHERE id = ?", (stop,))) == "Stop (venta si baja)"
    precios.actualizar_manual("BTC", Decimal("59000"), adm)
    assert db.uno("SELECT estado FROM programadas WHERE id = ?", (stop,))["estado"] == "ejecutada"
    # La venta límite por US$ 100 a 90.000 reservó 0,00111111 BTC: el stop «vender todo» vende solo el resto.
    assert cartera.tenencias(laura["id"]) == {"USD": 74000 + 17044, "BTC": 111111}
    assert cartera.bloqueado(laura["id"]) == {"BTC": 111111}
    with pytest.raises(operaciones.ErrorNegocio, match="reservado"):
        operaciones.operar(laura, "BTC", "venta", 1000, u)
    precios.actualizar_manual("BTC", Decimal("91000"), adm)
    o = db.uno("SELECT * FROM programadas WHERE id = ?", (lim,))
    assert o["estado"] == "ejecutada" and cartera.tenencias(laura["id"])["USD"] == 74000 + 17044 + 10000
    assert programadas.revisar(precios.vigentes()) == (0, 0)                # nada se repite


def test_cancelar_orden_programada(nav, ctx):
    laura, u = _saldo()
    n = nav("laura@x.com")
    assert n.post("/cliente/programadas", {"activo": "ETH", "lado": "compra", "precio": "1.500", "monto": "100"}).status_code == 302
    o = programadas.del_cliente(laura["id"], "ETH")[0]
    assert Decimal(o["precio"]) == 1500 and b"Compra l" in n.get("/mercado/ETH").data
    assert not programadas.cancelar(o["id"], cliente("pedro@x.com"), usuario("pedro@x.com"))
    assert n.post(f"/cliente/programadas/{o['id']}/cancelar", {"activo": "ETH"}).status_code == 302
    assert not programadas.del_cliente(laura["id"])
    precios.actualizar_manual("ETH", Decimal("1400"), usuario("admin@x.com"))
    assert "ETH" not in cartera.tenencias(laura["id"])                      # cancelada: no se ejecuta


def test_convertir_entre_monedas(nav, ctx):
    laura, u = _saldo()
    assert "Compraste BTC" in operaciones.convertir(laura, "USD", "BTC", 70000, u)
    with pytest.raises(operaciones.ErrorNegocio, match="distintas"):
        operaciones.convertir(laura, "BTC", "BTC", 1000, u)
    texto = operaciones.convertir(laura, "BTC", "ETH", 35000, u)             # la mitad del BTC a ETH
    assert "de BTC a ETH" in texto
    ten = cartera.tenencias(laura["id"])
    assert ten == {"USD": 30000, "BTC": 500000, "ETH": 17500000}            # 0,005 BTC y 0,175 ETH
    n = nav("laura@x.com")
    assert n.get("/cliente/convertir?de=BTC&a=SOL").status_code == 200
    r = n.post("/cliente/convertir", {"de": "BTC", "a": "USD", "monto": "", "todo": "si"})
    assert r.status_code == 302 and "BTC" not in cartera.tenencias(laura["id"])
    r = n.post("/cliente/convertir", {"de": "ETH", "a": "SOL", "monto": "999999"})
    assert r.status_code == 200 and "no puedes vender".encode() in r.data


def test_velas_y_portada(nav, ctx):
    serie = [(f"2026-11-{d:02d}T{h:02d}:00:00Z", 100 + d * 3 + (h % 5)) for d in range(1, 8) for h in range(0, 24, 3)]
    g = graficos.velas(serie, n=10)
    assert len(g["velas"]) == 10 and all(v["y1"] <= v["y"] and v["y2"] >= v["y"] + v["h"] - 1.3 for v in g["velas"])
    assert graficos.velas(serie[:2]) is None
    n = nav("laura@x.com")
    assert n.get("/mercado/BTC?g=velas&r=30").status_code == 200
    # Portada pública para quien no inició sesión; con sesión, va directo a su inicio.
    from flask import current_app
    anon = current_app.test_client()
    r = anon.get("/")
    assert r.status_code == 200 and b"Hecho en Paraguay" in r.data and "Aviso de riesgo".encode() in r.data
    assert n.get("/").status_code == 302
