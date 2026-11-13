"""Motor de ejecución contra un Binance imitado: rellenos reales, comisiones, mínimos, fallas, reintentos y pausa."""
import sqlite3
from importlib import resources
from decimal import Decimal

import pytest

from financiera import cartera, create_app, db, ejecucion, exchange, operaciones, precios

from .binance_falso import CLAVE, SECRETO, BinanceFalso
from .conftest import cliente, usuario

PRECIOS = {"BTC": "70000", "ETH": "2000", "SOL": "100", "BNB": "600", "XRP": "1", "LINK": "10"}


@pytest.fixture
def bx(ctx):
    falso = BinanceFalso(PRECIOS)
    ctx.config["EJECUCION"] = "binance"
    ctx.extensions["broker_pruebas"] = exchange.Binance(CLAVE, SECRETO, exchange.URL_BINANCE_PRUEBAS, sesion=falso)
    exchange.Binance._cache_reglas.clear()
    yield falso
    ctx.extensions.pop("broker_pruebas", None)
    exchange.Binance._cache_reglas.clear()


def _aporte(monto=100000, modelo="equilibrio", **kw):
    laura = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(laura, monto, modelo, "T-1", None, **kw)
    return opid, operaciones.aprobar(opid, usuario("op@x.com"))


def _tramo(opid, activo):
    return db.uno("SELECT * FROM ejecuciones WHERE operacion_id = ? AND activo = ?", (opid, activo))


def _envios(falso, simbolo):
    return sum(1 for s, _, _ in falso.envios if s == simbolo)


def test_aporte_se_ejecuta_en_binance_con_cantidades_y_comisiones_reales(bx):
    opid, r = _aporte(100000)
    assert r == "liquidada"
    ten = cartera.tenencias(cliente("laura@x.com")["id"])
    # BTC: 500 USDT a 70.000 con paso 0,00001 -> 0,00714 BTC; Binance cobra 0,1 % en BTC.
    assert ten["BTC"] == 714000 - 714
    assert ten["ETH"] == 12500000 - 12500
    assert ten["SOL"] == 100000000 - 100000
    assert ten["USDT"] == 150 * 10 ** 8          # el USDT es la moneda de cotización: conversión interna, sin orden
    assert ten["USD"] == 100000 - 49980 - 25000 - 15000 - 10000
    assert {s for s, _, _ in bx.envios} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    ords = {o["activo"]: o for o in db.todos("SELECT * FROM ordenes WHERE operacion_id = ?", (opid,))}
    assert ords["BTC"]["venue"] == "binance" and ords["BTC"]["ref_exchange"] and ords["BTC"]["comision_activo"] == "BTC"
    assert ords["BTC"]["importe_cent"] == 49980 and Decimal(ords["BTC"]["precio"]) == Decimal("70000")
    assert ords["USDT"]["venue"] == "interno"
    assert _tramo(opid, "BTC")["id_orden"] == f"fc-{opid}-C-BTC"
    op = db.uno("SELECT * FROM operaciones WHERE id = ?", (opid,))
    assert op["estado"] == "liquidada" and op["liquidado_cent"] == 100000
    assert bx.saldos["USDT"] == Decimal("1000000") - Decimal("849.8")


def test_sin_usdt_suficiente_no_se_aprueba(bx):
    bx.saldos["USDT"] = Decimal("100")
    laura = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(laura, 100000, "equilibrio", "T-1", None)
    with pytest.raises(operaciones.ErrorNegocio, match="No hay USDT suficiente"):
        operaciones.aprobar(opid, usuario("op@x.com"))
    assert db.uno("SELECT estado FROM operaciones WHERE id = ?", (opid,))["estado"] == "pendiente"
    assert not db.uno("SELECT 1 FROM ejecuciones WHERE operacion_id = ?", (opid,))
    assert not bx.envios


def test_tramo_rechazado_queda_incompleto_y_el_reintento_no_duplica(bx):
    bx.fallas["ETHUSDT"] = ["rechazo"]
    opid, r = _aporte()
    assert r == "incompleta"
    assert db.uno("SELECT estado FROM operaciones WHERE id = ?", (opid,))["estado"] == "ejecutando"
    eth = _tramo(opid, "ETH")
    assert eth["estado"] == "fallida" and "-2010" in eth["nota"]
    assert _tramo(opid, "BTC")["estado"] == "ejecutada"
    assert not db.uno("SELECT 1 FROM libro WHERE operacion_id = ?", (opid,))  # nada se asienta hasta completar
    assert any(n == "alta" and e == ("op", opid) for n, _, e in operaciones.alertas())
    # No se puede rechazar ni volver a aprobar una operación que ya mandó órdenes.
    with pytest.raises(operaciones.ErrorNegocio, match="ya se está ejecutando"):
        operaciones.aprobar(opid, usuario("op@x.com"))
    with pytest.raises(operaciones.ErrorNegocio):
        operaciones.rechazar(opid, usuario("op@x.com"), "motivo de prueba")
    assert ejecucion.reintentar(opid, usuario("op@x.com")) == "liquidada"
    assert _envios(bx, "BTCUSDT") == 1 and _envios(bx, "ETHUSDT") == 1
    assert db.uno("SELECT 1 FROM bitacora WHERE accion = 'ejecucion.reintento'")


@pytest.mark.parametrize("falla", ["procesada_sin_respuesta", "red", "error_500"])
def test_resultado_desconocido_se_consulta_antes_de_reenviar(bx, falla):
    bx.fallas["BTCUSDT"] = [falla]
    opid, r = _aporte()
    assert r == "incompleta"
    btc = _tramo(opid, "BTC")
    assert btc["estado"] == "enviada" and "consultará" in btc["nota"]
    assert ejecucion.continuar(opid, usuario("op@x.com")) == "liquidada"
    assert _envios(bx, "BTCUSDT") == 1          # nunca dos órdenes para el mismo tramo
    assert cartera.tenencias(cliente("laura@x.com")["id"])["BTC"] == 714000 - 714
    assert _tramo(opid, "BTC")["intentos"] == (1 if falla == "procesada_sin_respuesta" else 2)


def test_tramo_menor_al_minimo_queda_en_dolares(bx):
    bx.minimo["LINKUSDT"] = "10"
    opid, r = _aporte(10000, "impulso", acepta_riesgo=True)   # LINK 7 % = US$ 7 < mínimo de 10
    assert r == "liquidada"
    link = _tramo(opid, "LINK")
    assert link["estado"] == "omitida" and "mínimo" in link["nota"]
    assert _envios(bx, "LINKUSDT") == 0
    ten = cartera.tenencias(cliente("laura@x.com")["id"])
    assert "LINK" not in ten and ten["USD"] >= 700


def test_ejecucion_parcial_deja_el_resto_en_dolares(bx):
    bx.parcial["ETHUSDT"] = "0.5"
    opid, r = _aporte()
    assert r == "liquidada"
    eth = _tramo(opid, "ETH")
    assert eth["estado"] == "ejecutada" and "parcial" in eth["nota"]
    ten = cartera.tenencias(cliente("laura@x.com")["id"])
    assert ten["ETH"] == 6250000 - 6250
    assert ten["USD"] == 100000 - 49980 - 12500 - 15000 - 10000


def test_comision_en_bnb_la_paga_la_casa(bx):
    bx.comision_bnb = True
    opid, _ = _aporte()
    assert cartera.tenencias(cliente("laura@x.com")["id"])["BTC"] == 714000
    assert db.uno("SELECT comision_activo FROM ordenes WHERE operacion_id = ? AND activo = 'BTC'", (opid,))["comision_activo"] == "BNB"


def test_retiro_vende_respetando_el_paso_y_paga_lo_pedido(bx):
    _aporte()
    bx.paso["BTCUSDT"] = "0.0001"
    exchange.Binance._cache_reglas.clear()
    laura = cliente("laura@x.com")
    opid = operaciones.solicitar_retiro(laura, 30000, None)
    assert operaciones.aprobar(opid, usuario("op@x.com")) == "liquidada"
    op = db.uno("SELECT * FROM operaciones WHERE id = ?", (opid,))
    assert op["liquidado_cent"] == 30000
    btc = _tramo(opid, "BTC")
    assert btc["cantidad_pedida"] % 10000 == 0           # múltiplo de 0,0001 BTC
    assert _tramo(opid, "USDT")["venue"] == "interno"
    ten = cartera.tenencias(laura["id"])
    assert ten["USD"] >= 0 and all(v >= 0 for v in ten.values())
    pago = db.uno("SELECT cantidad FROM libro WHERE operacion_id = ? AND concepto = 'pago_retiro'", (opid,))
    assert pago["cantidad"] == -30000


def test_retiro_chico_se_junta_en_una_sola_venta_sobre_el_minimo(bx):
    _aporte()
    laura = cliente("laura@x.com")
    opid = operaciones.solicitar_retiro(laura, 200, None)  # US$ 2: menos que el mínimo de 5 por orden
    assert operaciones.aprobar(opid, usuario("op@x.com")) == "liquidada"
    vendidas = db.todos("SELECT * FROM ejecuciones WHERE operacion_id = ? AND estado = 'ejecutada' AND venue = 'binance'", (opid,))
    assert len(vendidas) == 1 and vendidas[0]["importe_cent"] >= 500
    assert db.uno("SELECT liquidado_cent FROM operaciones WHERE id = ?", (opid,))["liquidado_cent"] == 200


def test_cambio_de_reglas_del_par_se_corrige_al_reintentar(bx):
    _aporte()
    bx.paso["BTCUSDT"] = "0.0001"   # Binance cambió el paso; el sistema todavía tiene en memoria el anterior
    laura = cliente("laura@x.com")
    opid = operaciones.solicitar_retiro(laura, 30000, None)
    assert operaciones.aprobar(opid, usuario("op@x.com")) == "incompleta"
    assert "LOT_SIZE" in _tramo(opid, "BTC")["nota"]
    assert ejecucion.reintentar(opid, usuario("op@x.com")) == "liquidada"
    assert _tramo(opid, "BTC")["cantidad_pedida"] % 10000 == 0


def test_retiro_total_vende_todo_lo_posible(bx):
    _aporte()
    laura = cliente("laura@x.com")
    _, total = cartera.posiciones(laura["id"])
    opid = operaciones.solicitar_retiro(laura, total, None)
    assert operaciones.aprobar(opid, usuario("op@x.com")) == "liquidada"
    pagado = db.uno("SELECT liquidado_cent FROM operaciones WHERE id = ?", (opid,))["liquidado_cent"]
    assert total * 0.99 < pagado <= total


def test_pausa_de_emergencia(bx):
    ejecucion.pausar(True, usuario("admin@x.com"), "prueba")
    laura = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(laura, 100000, "equilibrio", "T-1", None)
    with pytest.raises(operaciones.ErrorNegocio, match="pausa"):
        operaciones.aprobar(opid, usuario("op@x.com"))
    assert any("pausa" in t for _, t, _ in operaciones.alertas())
    assert not bx.envios
    ejecucion.pausar(False, usuario("admin@x.com"))
    assert operaciones.aprobar(opid, usuario("op@x.com")) == "liquidada"


def test_precios_desde_binance(bx, ctx):
    ctx.config["FUENTE_PRECIOS"] = "binance"
    assert precios.fuente() == "Binance"
    bx.precios["BTC"] = Decimal("71234.5")
    precios.actualizar()
    v = precios.vigentes()
    assert v["BTC"]["precio"] == Decimal("71234.5") and v["BTC"]["fuente"] == "Binance"
    assert v["USDT"]["precio"] == 1 and v["BTC"]["cambio"] == Decimal("-1.25")


def test_verificacion_de_la_clave(bx, ctx):
    cli = ctx.extensions["broker_pruebas"]
    textos = cli.verificar()
    assert any(ok is None and "pruebas" in t for ok, t in textos)
    real = exchange.Binance(CLAVE, SECRETO, exchange.URL_BINANCE, sesion=bx)
    bx.restricciones["enableWithdrawals"] = True
    textos = dict((t, ok) for ok, t in real.verificar())
    assert textos["La clave permite RETIROS: deshabilítalos en Binance."] is False


def test_firma_incorrecta_se_detecta(bx):
    malo = exchange.Binance(CLAVE, "otro-secreto", exchange.URL_BINANCE_PRUEBAS, sesion=bx)
    with pytest.raises(AssertionError, match="firma"):
        malo.saldos()


def test_saldos_y_traduccion_de_unidades(bx):
    bx.saldos = {"USDT": Decimal("1234.56789"), "BTC": Decimal("0.5")}
    cli = exchange.cliente_binance()
    assert cli.saldos() == {"USDT": 123456789000, "BTC": 50000000}
    assert cli.disponible("USDT") == 123456789000
    r = exchange.traducir("BTC", "venta", Decimal("0.1"), Decimal("7000"), {"USDT": Decimal("7")})
    assert r.cantidad == 10000000 and r.importe_cent == 699300


def test_simulador_por_defecto_equivale_al_motor_anterior(ctx):
    opid, r = _aporte(100000)
    assert r == "liquidada"
    assert {e["venue"] for e in db.todos("SELECT venue FROM ejecuciones WHERE operacion_id = ?", (opid,))} == {"simulado"}
    assert cartera.tenencias(cliente("laura@x.com")["id"])["BTC"] == 714285


def test_migracion_0002_conserva_los_datos(tmp_path):
    ruta = tmp_path / "v1.db"
    con = sqlite3.connect(ruta)
    sql = resources.files("financiera").joinpath("migraciones/0001_inicial.sql").read_text(encoding="utf-8")
    con.executescript(sql + "\nPRAGMA user_version = 1;")
    con.execute("INSERT INTO clientes (id, nombre, documento, tipo, perfil_riesgo, modelo, kyc_estado, creado)"
                " VALUES (1, 'Ana', 'CI 9', 'persona', 'moderado', 'reserva', 'verificado', '2026-01-01T00:00:00Z')")
    con.execute("INSERT INTO operaciones (id, cliente_id, tipo, monto_cent, modelo, estado, creado)"
                " VALUES (7, 1, 'aporte', 5000, 'reserva', 'liquidada', '2026-01-01T00:00:00Z')")
    con.execute("INSERT INTO libro (cliente_id, activo, cantidad, concepto, operacion_id, ts)"
                " VALUES (1, 'USD', 5000, 'deposito', 7, '2026-01-01T00:00:00Z')")
    con.commit()
    con.close()
    app = create_app({"ENTORNO": "pruebas", "SECRET_KEY": "x", "DATABASE": str(ruta)})
    with app.app_context():
        assert db.version() == len(db._migraciones())
        op = db.uno("SELECT * FROM operaciones WHERE id = 7")
        assert op["estado"] == "liquidada" and op["monto_cent"] == 5000 and op["ejecucion_inicio"] is None
        assert db.uno("SELECT venue FROM ordenes LIMIT 1") is None
        assert db.todos("PRAGMA foreign_key_check") == []
        assert db.uno("PRAGMA foreign_keys")[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.ejecutar("UPDATE operaciones SET estado = 'inventado' WHERE id = 7")


# ---------- pantallas ----------

def test_pantalla_de_ejecucion_y_pausa_por_roles(bx, nav):
    adm, cum, op = nav("admin@x.com"), nav("cum@x.com"), nav("op@x.com")
    r = adm.get("/admin/ejecucion")
    assert r.status_code == 200 and "Binance (red de pruebas)".encode() in r.data
    assert cum.get("/admin/ejecucion").status_code == 200
    assert op.get("/admin/ejecucion").status_code == 403
    assert cum.get("/admin/precios").status_code == 403          # el resto de Ajustes sigue siendo solo de Administración
    r = adm.post("/admin/ejecucion", {"accion": "probar"})
    assert r.status_code == 200 and "Spot".encode() in r.data
    r = adm.post("/admin/ejecucion", {"accion": "saldos"})
    assert r.status_code == 200 and b"1.000.000" in r.data
    assert cum.post("/admin/ejecucion", {"accion": "pausar", "motivo": "precios raros"}).status_code == 302
    assert ejecucion.pausada()
    assert cum.post("/admin/ejecucion", {"accion": "reanudar"}).status_code == 403
    assert adm.post("/admin/ejecucion", {"accion": "reanudar"}).status_code == 302
    assert not ejecucion.pausada()
    assert db.uno("SELECT 1 FROM bitacora WHERE accion = 'ejecucion.pausa'")


def test_operacion_incompleta_se_reintenta_desde_la_pantalla(bx, nav):
    bx.fallas["SOLUSDT"] = ["rechazo"]
    laura = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(laura, 100000, "equilibrio", "T-1", None)
    op = nav("op@x.com")
    r = op.post(f"/equipo/operaciones/{opid}/aprobar")
    assert r.status_code == 302
    pagina = op.get(f"/equipo/operaciones/{opid}").data.decode()
    assert "Reintentar la ejecución" in pagina and "-2010" in pagina and "En ejecución" in pagina
    assert op.post(f"/equipo/operaciones/{opid}/reintentar").status_code == 302
    assert db.uno("SELECT estado FROM operaciones WHERE id = ?", (opid,))["estado"] == "liquidada"
    assert "Reintentar la ejecución" not in op.get(f"/equipo/operaciones/{opid}").data.decode()
    assert nav("laura@x.com").get("/cliente/movimientos").status_code == 200


def test_conciliacion_con_saldos_traidos_de_binance(bx, nav):
    _aporte()
    cum = nav("cum@x.com")
    r = cum.get("/equipo/conciliacion?desde=exchange")
    assert r.status_code == 200 and "Saldos de Binance cargados".encode() in r.data
    valores = {a: v for a, v in __import__("financiera").conciliacion.valores_exchange().items()}
    datos = {f"real_{a}": v for a, v in valores.items()}
    datos["real_USD"] = "0,20"
    assert cum.post("/equipo/conciliacion", datos).status_code == 302
    ult = db.uno("SELECT * FROM conciliaciones ORDER BY id DESC LIMIT 1")
    assert ult["diferencias"] >= 1   # el exchange tiene USDT propio de la casa además del de los clientes
