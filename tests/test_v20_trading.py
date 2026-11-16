"""v0.20 · Módulo 2: terminal de trading. OCO, toma de ganancia y corte de pérdida, reservas, pausa y análisis."""
from datetime import timedelta
from decimal import Decimal

import pytest

from financiera import analisis, cartera, db, ejecucion, operaciones, precios, programadas
from financiera.tiempo import ahora_dt, iso

from .conftest import cliente, usuario


def _saldo(monto=500000):
    cli = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(cli, monto, None, "T-saldo", None)
    operaciones.aprobar(opid, usuario("op@x.com"))
    return cli


def _precio(activo, p):
    precios.registrar(activo, Decimal(p), Decimal("0"), "pruebas")
    return precios.vigentes()


def test_oco_de_venta_reserva_una_vez_y_la_primera_cancela_la_otra(ctx):
    cli = _saldo()
    operaciones.operar(cli, "BTC", "compra", 200000, usuario("laura@x.com"))  # US$ 2.000 de BTC a 70.000
    tengo = cartera.tenencias(cli["id"])["BTC"]
    a, b = programadas.crear_oco(cli, "BTC", "venta", Decimal("77000"), Decimal("63000"), 0, usuario("laura@x.com"), todo=True)
    filas = db.todos("SELECT * FROM programadas WHERE grupo IS NOT NULL ORDER BY id")
    assert [f["id"] for f in filas] == [a, b] and filas[0]["grupo"] == filas[1]["grupo"]
    assert cartera.bloqueado(cli["id"]) == {}  # «vender todo» no reserva
    programadas.cancelar(a, cli, usuario("laura@x.com"))
    assert {f["estado"] for f in db.todos("SELECT estado FROM programadas WHERE id IN (?, ?)", (a, b))} == {"cancelada"}
    # Por monto: reserva la pata más exigente una sola vez (a menor precio, más unidades).
    a, b = programadas.crear_oco(cli, "BTC", "venta", Decimal("77000"), Decimal("63000"), 100000, usuario("laura@x.com"))
    reservado = cartera.bloqueado(cli["id"])["BTC"]
    assert reservado == 100000 * 10 ** 8 // 100 // 63000 or abs(reservado - int(Decimal(1000) / Decimal(63000) * 10 ** 8)) <= 1
    assert reservado < tengo
    hechas, fallidas = programadas.revisar(_precio("BTC", "77500"))
    assert (hechas, fallidas) == (1, 0)
    ea, eb = (db.uno("SELECT * FROM programadas WHERE id = ?", (x,)) for x in (a, b))
    assert ea["estado"] == "ejecutada" and eb["estado"] == "cancelada" and f"#{a}" in eb["nota"]
    assert programadas.revisar(_precio("BTC", "60000")) == (0, 0)  # la otra pata ya no se ejecuta


def test_oco_valida_el_orden_de_los_precios(ctx):
    cli = _saldo()
    with pytest.raises(operaciones.ErrorNegocio, match="OCO de compra"):
        programadas.crear_oco(cli, "BTC", "compra", Decimal("75000"), Decimal("65000"), 50000, usuario("laura@x.com"))
    a, b = programadas.crear_oco(cli, "BTC", "compra", Decimal("65000"), Decimal("75000"), 50000, usuario("laura@x.com"))
    assert cartera.bloqueado(cli["id"]) == {"USD": 50000}  # dos compras enlazadas reservan los dólares una vez
    assert programadas.revisar(_precio("BTC", "76000")) == (1, 0)
    assert db.uno("SELECT estado FROM programadas WHERE id = ?", (a,))["estado"] == "cancelada"


def test_compra_con_toma_de_ganancia_y_corte_de_perdida(nav, ctx):
    cli = _saldo()
    n = nav("laura@x.com")
    r = n.post("/cliente/operar", {"activo": "BTC", "lado": "compra", "monto": "1000", "tp": "80000", "sl": "65000"})
    assert r.status_code == 302
    ops = db.todos("SELECT * FROM programadas WHERE cliente_id = ? ORDER BY id", (cli["id"],))
    assert [o["origen"] for o in ops] == ["tp", "sl"] and ops[0]["grupo"] == ops[1]["grupo"]
    compradas = db.uno("SELECT SUM(cantidad) AS u FROM libro WHERE cliente_id = ? AND activo = 'BTC'", (cli["id"],))["u"]
    assert ops[0]["cantidad"] == compradas and ops[0]["monto_cent"] == 0
    assert cartera.bloqueado(cli["id"])["BTC"] == compradas  # protege exactamente lo comprado
    assert programadas.nombre(ops[0]) == "Toma de ganancia"
    # Baja el precio: se activa el corte de pérdida, vende lo comprado y cancela la toma de ganancia.
    assert programadas.revisar(_precio("BTC", "64000")) == (1, 0)
    assert cartera.tenencias(cli["id"]).get("BTC", 0) == 0
    assert db.uno("SELECT estado FROM programadas WHERE id = ?", (ops[0]["id"],))["estado"] == "cancelada"
    pagina = n.get("/trading/BTC").data.decode()
    assert "Canceladas (1)" in pagina and "OCO" in pagina


def test_proteccion_invalida_no_compra(nav, ctx):
    cli = _saldo()
    antes = db.uno("SELECT COUNT(*) AS n FROM operaciones")["n"]
    r = nav("laura@x.com").post("/cliente/operar", {"activo": "BTC", "lado": "compra", "monto": "1000", "tp": "60000"})
    assert r.status_code == 302
    assert db.uno("SELECT COUNT(*) AS n FROM operaciones")["n"] == antes  # la compra no se hizo sin su protección
    assert not db.uno("SELECT 1 FROM programadas WHERE cliente_id = ?", (cli["id"],))


def test_oco_desde_el_formulario(nav, ctx):
    cli = _saldo()
    r = nav("laura@x.com").post("/cliente/programadas", {"activo": "ETH", "lado": "compra", "tipo": "oco", "monto": "200",
                                                          "precio": "1800", "precio_stop": "2200"})
    assert r.status_code == 302
    assert db.uno("SELECT COUNT(*) AS n FROM programadas WHERE cliente_id = ? AND grupo IS NOT NULL", (cli["id"],))["n"] == 2


def test_pausa_frena_las_operaciones_del_cliente(ctx):
    cli = _saldo()
    ejecucion.pausar(True, usuario("admin@x.com"), "control")
    with pytest.raises(operaciones.ErrorNegocio, match="pausa"):
        operaciones.operar(cli, "BTC", "compra", 10000, usuario("laura@x.com"))
    with pytest.raises(operaciones.ErrorNegocio, match="pausa"):
        programadas.crear(cli, "BTC", "compra", Decimal("60000"), 10000, usuario("laura@x.com"))


def test_analisis_del_activo_y_exposicion(nav, ctx):
    hoy = ahora_dt()
    for i in range(60, 0, -1):
        precios.registrar("BTC", Decimal(60000 + (60 - i) * 150), Decimal("0"), "pruebas", ts=iso(hoy - timedelta(days=i)), historial_min=0)
    precios.registrar("BTC", Decimal("70000"), Decimal("0"), "pruebas")
    from financiera import velas
    velas._CACHE.clear()
    a = analisis.activo("BTC", Decimal("70000"))
    assert a["dias"] >= 30 and a["rend"]["30 días"] > 0 and a["tendencia"][0] == "alcista" and a["rsi"] > 50
    cli = _saldo()
    operaciones.operar(cli, "BTC", "compra", 100000, usuario("laura@x.com"))
    e = analisis.exposicion(cli["id"], "BTC", precios.vigentes())
    assert 15 < e["peso"] < 25 and e["costo"] and e["promedio"]
    pagina = nav("laura@x.com").get("/trading/BTC").data.decode()
    assert "Análisis de BTC" in pagina and "Tu posición y riesgo" in pagina and "no son una recomendación" in pagina
