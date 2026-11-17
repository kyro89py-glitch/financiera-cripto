"""v0.30 · Servicios financieros: herramientas y simulador con precios históricos reales del historial guardado."""
from datetime import timedelta
from decimal import Decimal

import pytest

from financiera import db, simulador
from financiera.tiempo import ahora_dt, iso


def _historia(activo="ETH", dias=400, precio=lambda d: 1000 + d):
    """Un punto diario: el precio sube 1 dólar por día (precio del día d antes de hoy = 1000 + (dias - d))."""
    db.ejecutar("DELETE FROM precios_historial WHERE activo = ?", (activo,))
    for d in range(dias, 0, -1):
        db.ejecutar("INSERT INTO precios_historial (activo, precio, ts) VALUES (?, ?, ?)", (activo, str(precio(dias - d)), iso(ahora_dt() - timedelta(days=d))))


def test_dca_con_historial(ctx):
    _historia()
    from financiera import precios
    precios.registrar("ETH", Decimal("1400"), Decimal("0"), "pruebas")
    r = simulador.dca("ETH", 10000, "mensual", 12, 0)
    assert r["compras"] == 13 and r["invertido"] == 130000
    assert 1000 < r["precio_medio"] < 1400 and r["resultado"] > 0 and r["valor"] > r["invertido"]
    assert r["unico_valor"] > r["valor"]                         # en una suba constante, comprar todo al inicio rinde más
    assert r["serie"][-1][1] == 1300 and len(r["serie"]) == 14
    con_com = simulador.dca("ETH", 10000, "mensual", 12, 1)
    assert con_com["valor"] < r["valor"]
    assert simulador.dca("ETH", 10000, "semanal", 3, 0)["compras"] in (13, 14)


def test_dca_valida(ctx):
    for args in (("NOEXISTE", 10000), ("ETH", 50), ("ETH", 10000, "diaria"), ("ETH", 10000, "mensual", 7)):
        with pytest.raises(simulador.ErrorSimulacion):
            simulador.dca(*args)
    _historia(dias=30)
    with pytest.raises(simulador.ErrorSimulacion, match="historial"):
        simulador.dca("ETH", 10000, "mensual", 12)


def test_pantalla_y_api(nav, ctx):
    _historia()
    n = nav("laura@x.com")
    h = n.get("/herramientas").get_data(as_text=True)
    for t in ("Conversor", "Comisiones", "Rentabilidad", "Riesgo", "Simulador con precios históricos", "Calendario de acontecimientos",
              "no garantizan rendimientos futuros", "datos-herramientas"):
        assert t in h, t
    j = n.get("/herramientas/simular.json?activo=ETH&monto=100&frecuencia=mensual&meses=12").get_json()
    assert j["compras"] == 13 and j["invertido"] == 130000 and j["fuente"]
    assert n.get("/herramientas/simular.json?activo=ETH&monto=abc").status_code == 400
    assert n.get("/herramientas/simular.json?activo=ETH&monto=100&meses=x").status_code == 400
    assert nav().get("/herramientas/simular.json?activo=ETH&monto=100").status_code == 401
    assert nav("op@x.com").get("/herramientas").status_code == 200
