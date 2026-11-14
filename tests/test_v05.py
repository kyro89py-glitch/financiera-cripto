"""Compra y venta libre de monedas, depósito a saldo, favoritos, página de cada moneda y tema."""
from decimal import Decimal

import pytest

from financiera import cartera, db, ejecucion, exchange, operaciones

from .binance_falso import CLAVE, SECRETO, BinanceFalso
from .conftest import cliente, usuario


def _deposito(monto=100000):
    laura = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(laura, monto, "saldo", "T", None)
    assert operaciones.aprobar(opid, usuario("op@x.com")) == "liquidada"
    return opid


def test_deposito_a_saldo_no_compra_nada(ctx):
    opid = _deposito()
    laura = cliente("laura@x.com")
    assert cartera.tenencias(laura["id"]) == {"USD": 100000}
    assert db.uno("SELECT modelo FROM operaciones WHERE id = ?", (opid,))["modelo"] is None
    assert cliente("laura@x.com")["modelo"] == laura["modelo"]          # no cambia su cartera modelo
    assert not db.uno("SELECT 1 FROM ordenes WHERE operacion_id = ?", (opid,))


def test_compra_y_venta_de_una_moneda(ctx):
    _deposito()
    laura = cliente("laura@x.com")
    opid, r = operaciones.operar(laura, "BTC", "compra", 35000, usuario("laura@x.com"))
    assert r == "liquidada"
    ten = cartera.tenencias(laura["id"])
    assert ten["USD"] == 65000 and ten["BTC"] == 500000              # US$ 350 a 70.000
    op = db.uno("SELECT * FROM operaciones WHERE id = ?", (opid,))
    assert (op["tipo"], op["activo"], op["estado"], op["liquidado_cent"]) == ("compra", "BTC", "liquidada", 35000)
    assert db.uno("SELECT 1 FROM bitacora WHERE accion = 'orden.ejecutada'")
    # Vende la mitad por monto y después todo lo que queda.
    _, r = operaciones.operar(laura, "BTC", "venta", 17500, usuario("laura@x.com"))
    assert r == "liquidada" and cartera.tenencias(laura["id"]) == {"USD": 82500, "BTC": 250000}
    _, r = operaciones.operar(laura, "BTC", "venta", 0, usuario("laura@x.com"), todo=True)
    assert r == "liquidada" and cartera.tenencias(laura["id"]) == {"USD": 100000}
    # Comprar y vender no son aportes ni retiros: no cambian lo aportado ni la rentabilidad.
    assert cartera.aportado_neto(laura["id"]) == 100000
    assert abs(cartera.rendimiento(laura["id"])["twr"]) < 0.01


def test_controles_de_las_ordenes(ctx):
    _deposito(50000)
    laura, u = cliente("laura@x.com"), usuario("laura@x.com")
    with pytest.raises(operaciones.ErrorNegocio, match="saldo en dólares suficiente"):
        operaciones.operar(laura, "BTC", "compra", 50001, u)
    with pytest.raises(operaciones.ErrorNegocio, match="No tienes ETH"):
        operaciones.operar(laura, "ETH", "venta", 1000, u)
    with pytest.raises(operaciones.ErrorNegocio, match="no está disponible"):
        operaciones.operar(laura, "DOGE", "compra", 1000, u)
    with pytest.raises(operaciones.ErrorNegocio, match="mayor que cero"):
        operaciones.operar(laura, "BTC", "compra", 0, u)
    ctx.config["ORDEN_MAXIMA_USD"] = 100
    with pytest.raises(operaciones.ErrorNegocio, match="máximo por orden"):
        operaciones.operar(laura, "BTC", "compra", 20000, u)
    ctx.config["ORDEN_MAXIMA_USD"] = 25000
    with pytest.raises(operaciones.ErrorNegocio, match="verificar tu identidad"):
        operaciones.operar(cliente("pedro@x.com"), "BTC", "compra", 1000, usuario("pedro@x.com"))
    operaciones.operar(laura, "BTC", "compra", 10000, u)
    with pytest.raises(operaciones.ErrorNegocio, match="no puedes vender más"):
        operaciones.operar(laura, "BTC", "venta", 20000, u)
    db.ejecutar("UPDATE precios SET ts = '2020-01-01T00:00:00Z' WHERE activo = 'BTC'")
    with pytest.raises(operaciones.ErrorNegocio, match="no está actualizado"):
        operaciones.operar(laura, "BTC", "compra", 1000, u)
    ejecucion.pausar(True, usuario("admin@x.com"))
    with pytest.raises(operaciones.ErrorNegocio):
        operaciones.operar(laura, "ETH", "compra", 1000, u)
    assert db.uno("SELECT COUNT(*) AS n FROM operaciones WHERE tipo IN ('compra', 'venta')")["n"] == 1


def test_orden_en_binance_con_minimo_y_falla(ctx):
    falso = BinanceFalso({"BTC": "70000", "ETH": "2000", "SOL": "100", "BNB": "600", "XRP": "1", "LINK": "10"})
    ctx.config["EJECUCION"] = "binance"
    ctx.extensions["broker_pruebas"] = exchange.Binance(CLAVE, SECRETO, exchange.URL_BINANCE_PRUEBAS, sesion=falso)
    exchange.Binance._cache_reglas.clear()
    try:
        _deposito()
        laura, u = cliente("laura@x.com"), usuario("laura@x.com")
        with pytest.raises(operaciones.ErrorNegocio, match="mínimo para comprar"):
            operaciones.operar(laura, "ETH", "compra", 300, u)            # US$ 3 < mínimo de 5
        opid, r = operaciones.operar(laura, "ETH", "compra", 20000, u)
        assert r == "liquidada" and cartera.tenencias(laura["id"])["ETH"] == 10000000 - 10000   # 0,1 ETH menos 0,1 %
        assert db.uno("SELECT venue FROM ordenes WHERE operacion_id = ?", (opid,))["venue"] == "binance"
        falso.fallas["ETHUSDT"] = ["rechazo"]
        opid, r = operaciones.operar(laura, "ETH", "venta", 0, u, todo=True)
        assert r == "incompleta" and db.uno("SELECT estado FROM operaciones WHERE id = ?", (opid,))["estado"] == "ejecutando"
        assert ejecucion.reintentar(opid, usuario("op@x.com")) == "liquidada"
        assert "ETH" not in cartera.tenencias(laura["id"])
    finally:
        ctx.extensions.pop("broker_pruebas", None)
        exchange.Binance._cache_reglas.clear()


def test_pantallas_del_exchange(nav, ctx):
    _deposito()
    laura = nav("laura@x.com")
    r = laura.get("/mercado/BTC")
    assert r.status_code == 200 and b'id="operar"' in r.data and "Comprar BTC".encode() in r.data
    assert laura.get("/mercado/btc?r=30").status_code == 200 and laura.get("/mercado/NADA").status_code == 404
    r = laura.post("/cliente/operar", {"activo": "BTC", "lado": "compra", "monto": "350"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/mercado/BTC")
    assert "Compraste 0,005".encode() in laura.get("/mercado/BTC").data
    r = laura.post("/cliente/operar", {"activo": "BTC", "lado": "venta", "monto": "", "todo": "si"})
    assert r.status_code == 302 and "BTC" not in cartera.tenencias(cliente("laura@x.com")["id"])
    assert laura.post("/cliente/operar", {"activo": "BTC", "lado": "compra", "monto": "abc"}).status_code == 302
    # favoritos
    assert laura.post("/mercado/SOL/favorito", {"volver": "/mercado?ver=favoritos"}).headers["Location"].endswith("/mercado?ver=favoritos")
    r = laura.get("/mercado?ver=favoritos")
    assert b'class="fila" href="/mercado/SOL"' in r.data and b'class="fila" href="/mercado/ETH"' not in r.data
    laura.post("/mercado/SOL/favorito", {})
    assert not db.uno("SELECT 1 FROM favoritos")
    # precios en vivo, billetera, movimientos y estado de cuenta con compras y ventas
    j = laura.get("/mercado/precios.json").get_json()
    assert j["BTC"]["precio"].startswith("US$") and "valor" in j["BTC"]
    for url in ("/cliente/cartera", "/cliente/movimientos", "/cliente/", "/mercado?orden=suben"):
        assert laura.get(url).status_code == 200, url
    periodo = cartera.periodos_cliente(cliente("laura@x.com"))[0]
    assert "Compra de BTC".encode() in laura.get(f"/cliente/estado-de-cuenta/{periodo}").data
    # el equipo ve la moneda y las órdenes, pero no puede operar por el cliente
    op = nav("op@x.com")
    r = op.get("/mercado/BTC")
    assert r.status_code == 200 and b'id="operar"' not in r.data
    assert op.post("/cliente/operar", {"activo": "BTC", "lado": "compra", "monto": "10"}).status_code in (302, 403)
    assert db.uno("SELECT COUNT(*) AS n FROM operaciones WHERE tipo = 'compra'")["n"] == 1
    oid = db.uno("SELECT id FROM operaciones WHERE tipo = 'compra'")["id"]
    assert op.get(f"/equipo/operaciones/{oid}").status_code == 200 and op.get("/equipo/operaciones?ver=todas").status_code == 200


def test_tema_claro_y_oscuro(nav):
    laura = nav("laura@x.com")
    assert b'data-tema="oscuro"' in laura.get("/cliente/").data
    r = laura.post("/cuenta/tema", {"volver": "/cliente/"})
    assert r.status_code == 302 and "tema=claro" in r.headers["Set-Cookie"]
    assert b'data-tema="claro"' in laura.get("/cliente/").data
