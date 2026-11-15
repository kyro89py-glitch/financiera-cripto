"""Guaraníes, compras automáticas, alertas de precio y resumen anual de criptoactivos."""
from decimal import Decimal

import pytest

from financiera import alertas, cartera, db, guarani, notificaciones, operaciones, planes, precios

from .conftest import cliente, usuario


def _saldo(monto=100000):
    laura = cliente("laura@x.com")
    operaciones.aprobar(operaciones.solicitar_aporte(laura, monto, "saldo", "T", None), usuario("op@x.com"))


def test_tipo_de_cambio_y_deposito_en_guaranies(nav, ctx):
    laura, adm = cliente("laura@x.com"), usuario("admin@x.com")
    assert guarani.referencia() is None
    with pytest.raises(operaciones.ErrorNegocio, match="no hay tipo de cambio"):
        operaciones.solicitar_aporte(laura, 0, "saldo", "T", None, monto_pyg=1_000_000)
    with pytest.raises(guarani.ErrorCambio):
        guarani.fijar(6000, 6500, adm)          # el de retiro no puede ser mayor
    with pytest.raises(guarani.ErrorCambio, match="5 %"):
        guarani.fijar(7000, 6000, adm)
    guarani.fijar(6350, 6250, adm)
    assert guarani.cambios()["deposito"] == 6350 and guarani.referencia() == 6300
    assert guarani.leer("₲ 1.500.000") == 1500000 and guarani.fmt(1500000) == "₲ 1.500.000"
    with pytest.raises(ValueError):
        guarani.leer("1.500,50")
    opid = operaciones.solicitar_aporte(laura, 0, "saldo", "T", None, monto_pyg=3_175_000)
    op = db.uno("SELECT * FROM operaciones WHERE id = ?", (opid,))
    assert (op["monto_cent"], op["monto_pyg"], op["cambio_pyg"]) == (50000, 3_175_000, 6350)      # US$ 500
    operaciones.aprobar(opid, usuario("op@x.com"))
    assert cartera.tenencias(laura["id"]) == {"USD": 50000}
    # El tipo de cambio queda fijado en la operación aunque después cambie.
    guarani.fijar(6500, 6400, adm)
    assert db.uno("SELECT cambio_pyg FROM operaciones WHERE id = ?", (opid,))["cambio_pyg"] == 6350
    rid = operaciones.solicitar_retiro(laura, 10000, None, en_guaranies=True)
    r = db.uno("SELECT * FROM operaciones WHERE id = ?", (rid,))
    assert (r["monto_pyg"], r["cambio_pyg"]) == (640000, 6400)
    # Por pantalla
    n = nav("laura@x.com")
    r = n.post("/cliente/invertir", {"monto": "1.270.000", "moneda": "PYG", "modelo": "saldo", "referencia": "X"})
    assert r.status_code == 302
    assert db.uno("SELECT monto_cent FROM operaciones ORDER BY id DESC LIMIT 1")["monto_cent"] == 1_270_000 * 100 // 6500
    assert "₲".encode() in n.get("/cliente/").data and "₲".encode() in n.get("/cliente/movimientos").data
    assert nav("op@x.com").get("/admin/guaranies").status_code == 403
    a = nav("admin@x.com")
    assert a.get("/admin/guaranies").status_code == 200
    assert a.post("/admin/guaranies", {"deposito": "6.360", "retiro": "6.260"}).status_code == 302
    assert guarani.cambios()["retiro"] == 6260


def test_compra_automatica(nav, ctx):
    _saldo(10000)
    laura, u = cliente("laura@x.com"), usuario("laura@x.com")
    with pytest.raises(operaciones.ErrorNegocio, match="mínimo"):
        planes.crear(laura, "BTC", 500, "semanal", u)
    with pytest.raises(operaciones.ErrorNegocio):
        planes.crear(laura, "BTC", 2000, "diaria", u)
    pid = planes.crear(laura, "BTC", 6000, "semanal", u, ts="2026-11-02T12:00:00Z")
    assert db.uno("SELECT proxima FROM planes WHERE id = ?", (pid,))["proxima"] == "2026-11-09T12:00:00Z"
    assert planes.ejecutar_pendientes(ts="2026-11-08T12:00:00Z") == (0, 0)             # todavía no toca
    pr = precios.vigentes()
    assert planes.ejecutar_pendientes(ts="2026-11-09T12:05:00Z", precios_usar=pr) == (1, 0)
    assert cartera.tenencias(laura["id"])["USD"] == 4000
    p = db.uno("SELECT * FROM planes WHERE id = ?", (pid,))
    assert p["proxima"] == "2026-11-16T12:00:00Z" and p["ejecuciones"] == 1
    assert planes.ejecutar_pendientes(ts="2026-11-09T12:10:00Z", precios_usar=pr) == (0, 0)   # no se repite
    # Sin saldo: avisa, no compra, y salta a la fecha siguiente aunque hayan pasado varias semanas.
    antes = notificaciones.no_leidas(u["id"])
    assert planes.ejecutar_pendientes(ts="2026-12-01T12:00:00Z", precios_usar=pr) == (0, 1)
    p = db.uno("SELECT * FROM planes WHERE id = ?", (pid,))
    assert p["proxima"] == "2026-12-07T12:00:00Z" and p["ejecuciones"] == 1 and "saldo" in p["ultima_nota"]
    assert notificaciones.no_leidas(u["id"]) == antes + 1
    assert planes._siguiente(planes.leer("2026-01-31T12:00:00Z"), "mensual").day == 28
    n = nav("laura@x.com")
    assert n.post("/cliente/planes", {"activo": "ETH", "monto": "25", "frecuencia": "mensual"}).status_code == 302
    assert len(planes.del_cliente(laura["id"])) == 2
    assert b"automatica" in n.get("/mercado/ETH").data and n.get("/cliente/cartera").status_code == 200
    assert n.post(f"/cliente/planes/{pid}/cancelar", {"volver": "/cliente/cartera"}).status_code == 302
    assert [x["activo"] for x in planes.del_cliente(laura["id"])] == ["ETH"]
    assert not planes.cancelar(pid, cliente("pedro@x.com"), usuario("pedro@x.com"))


def test_alertas_de_precio(nav, ctx):
    u = usuario("laura@x.com")
    btc = precios.vigentes()["BTC"]["precio"]
    with pytest.raises(operaciones.ErrorNegocio, match="distinto"):
        alertas.crear(u, "BTC", btc, btc)
    aid, sentido = alertas.crear(u, "BTC", btc * 2, btc)
    _, baja = alertas.crear(u, "BTC", btc / 2, btc)
    assert (sentido, baja) == ("sube", "baja")
    assert alertas.revisar(precios.vigentes()) == 0
    antes = notificaciones.no_leidas(u["id"])
    precios.actualizar_manual("BTC", btc * 2 + 1, usuario("admin@x.com"))     # la actualización de precios dispara la alerta
    assert notificaciones.no_leidas(u["id"]) == antes + 1
    assert "subió" in notificaciones.listar(u["id"])[0]["texto"]
    assert alertas.revisar(precios.vigentes()) == 0                            # avisa una sola vez
    assert len(alertas.del_usuario(u["id"])) == 1
    n = nav("laura@x.com")
    assert n.post("/cliente/alertas", {"activo": "ETH", "precio": "3.000"}).status_code == 302
    x = alertas.del_usuario(u["id"], "ETH")[0]
    assert Decimal(x["precio"]) == 3000 and b"Sube a" in n.get("/mercado/ETH").data
    n.post(f"/cliente/alertas/{x['id']}/borrar", {"activo": "ETH"})
    assert not alertas.del_usuario(u["id"], "ETH")


def test_resumen_anual_de_criptoactivos(nav, ctx):
    _saldo()
    laura = cliente("laura@x.com")
    operaciones.operar(laura, "BTC", "compra", 35000, usuario("laura@x.com"))
    operaciones.operar(laura, "BTC", "venta", 7000, usuario("laura@x.com"))
    r = nav("cum@x.com").get("/equipo/reportes/criptoactivos.csv")
    texto = r.data.decode("utf-8-sig")
    fila = next(linea for linea in texto.splitlines() if linea.startswith(texto.splitlines()[1][:4]) and "Laura" in linea).split(";")
    assert r.status_code == 200 and fila[4:9] == ["350,00", "70,00", "2", "1.000,00", "0,00"] and "BTC 0,00400000" in fila[10]
    assert "Pedro" not in texto                                     # sin movimientos ni saldo no aparece
    assert nav("op@x.com").get("/equipo/reportes/criptoactivos.csv").status_code == 403
