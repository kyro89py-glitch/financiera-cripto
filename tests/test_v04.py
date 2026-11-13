"""Rentabilidad ponderada por tiempo, desvío frente a la cartera modelo y mercado."""
from decimal import Decimal

from financiera import cartera, graficos, operaciones, precios

from .conftest import cliente, usuario


def _aporte(monto, ts):
    laura = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(laura, monto, "equilibrio", "T", None, ts=ts)
    operaciones.aprobar(opid, usuario("op@x.com"), ts=ts)


def test_rentabilidad_no_se_distorsiona_con_los_aportes(ctx):
    laura = cliente("laura@x.com")
    assert cartera.rendimiento(laura["id"]) is None
    _aporte(100000, "2026-11-01T12:00:00Z")
    r = cartera.rendimiento(laura["id"])
    assert abs(r["twr"]) < 0.05 and r["dias"] >= 1
    # Un aporte grande posterior no cambia la rentabilidad: no hubo movimiento de precios.
    _aporte(900000, "2026-11-05T12:00:00Z")
    assert abs(cartera.rendimiento(laura["id"])["twr"]) < 0.05
    # Todos los activos de la cartera suben 10 %: la rentabilidad sigue esa suba, ponderada por lo invertido en cripto.
    filas, total = cartera.posiciones(laura["id"])
    for f in filas:
        if f["activo"] not in ("USD", "USDT"):
            precios.registrar(f["activo"], Decimal(f["precio"]) * Decimal("1.1"), None, "pruebas")
    r = cartera.rendimiento(laura["id"])
    assert 8.0 < r["twr"] < 9.0 and 9.5 < r["btc"] < 10.5      # 85 % en cripto x 10 %


def test_desvio_frente_al_modelo(ctx):
    _aporte(100000, "2026-11-01T12:00:00Z")
    laura = cliente("laura@x.com")
    filas, total = cartera.posiciones(laura["id"])
    desv, mayor = cartera.desvio(filas, total, "equilibrio")
    assert mayor < 1 and {d["activo"] for d in desv} >= {"BTC", "ETH", "SOL", "USDT"}
    precios.registrar("BTC", Decimal(next(f["precio"] for f in filas if f["activo"] == "BTC")) * 2, None, "pruebas")
    filas, total = cartera.posiciones(laura["id"])
    desv, mayor = cartera.desvio(filas, total, "equilibrio")
    assert mayor > 10 and next(d for d in desv if d["activo"] == "BTC")["dif"] > 10


def test_mercado_y_minigraficos(nav, ctx):
    assert graficos.chispa([1]) is None
    c = graficos.chispa([1, 3, 2, 5])
    assert c["sube"] and len(c["puntos"].split()) == 4
    m = precios.mercado()
    assert {x["codigo"] for x in m} >= {"BTC", "ETH", "USDT"} and all(x["precio"] for x in m)
    for quien in ("laura@x.com", "op@x.com"):
        r = nav(quien).get("/mercado")
        assert r.status_code == 200 and b"data-escena3d" in r.data
    r = nav("laura@x.com").get("/cliente/")
    assert r.status_code == 200 and b"hero3d" in r.data
