import sqlite3
from decimal import Decimal

import pytest

from financiera import auditoria, cartera, cuentas, db, dinero, operaciones, precios
from financiera.tiempo import hace

from .conftest import cliente, usuario


def _saldo(cid):
    return cartera.posiciones(cid)[1]


def test_aporte_completo_por_pantallas(nav, ctx):
    c = nav("laura@x.com")
    r = c.post("/cliente/invertir", {"monto": "1.000", "modelo": "equilibrio", "referencia": "TRF-1"})
    assert r.status_code == 302
    op = db.uno("SELECT * FROM operaciones ORDER BY id DESC LIMIT 1")
    assert op["estado"] == "pendiente" and op["monto_cent"] == 100000

    e = nav("op@x.com")
    r = e.post(f"/equipo/operaciones/{op['id']}/aprobar")
    assert r.status_code == 302
    op = db.uno("SELECT * FROM operaciones WHERE id = ?", (op["id"],))
    assert op["estado"] == "liquidada"
    ten = cartera.tenencias(op["cliente_id"])
    assert ten["BTC"] == dinero.unidades_por(50000, Decimal("70000"))
    assert ten["USDT"] == 15000 * 10 ** 6                      # US$ 150 a US$ 1
    assert _saldo(op["cliente_id"]) <= 100000 and _saldo(op["cliente_id"]) > 99990
    assert "Liquidada" in c.get("/cliente/movimientos").get_data(as_text=True)


def test_el_libro_cuadra_en_dolares(ctx):
    cli = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(cli, 123457, "impulso", None, None, acepta_riesgo=True)
    operaciones.aprobar(opid, usuario("op@x.com"))
    usd = db.uno("SELECT SUM(cantidad) s FROM libro WHERE activo = 'USD' AND cliente_id = ?", (cli["id"],))["s"]
    compras = db.uno("SELECT SUM(importe_cent) s FROM ordenes WHERE operacion_id = ?", (opid,))["s"]
    assert usd + compras == 123457                               # lo no invertido queda como saldo en dólares


def test_no_se_aprueba_sin_identidad_verificada(ctx):
    opid = operaciones.solicitar_aporte(cliente("pedro@x.com"), 50000, "reserva", None, None)
    with pytest.raises(operaciones.ErrorNegocio, match="identidad"):
        operaciones.aprobar(opid, usuario("op@x.com"))
    assert db.uno("SELECT estado FROM operaciones WHERE id = ?", (opid,))["estado"] == "pendiente"


def test_origen_de_fondos_desde_el_umbral(ctx):
    cli = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(cli, 1000000, "equilibrio", None, None)      # US$ 10.000
    with pytest.raises(operaciones.ErrorNegocio, match="origen"):
        operaciones.aprobar(opid, usuario("op@x.com"))
    cuentas.registrar_origen(cli["id"], "Ahorros con recibos de sueldo", usuario("cum@x.com"))
    assert operaciones.aprobar(opid, usuario("op@x.com")) == "liquidada"


def test_doble_firma(ctx):
    cli = cliente("laura@x.com")
    cuentas.registrar_origen(cli["id"], "Venta de vehículo con contrato", usuario("cum@x.com"))
    opid = operaciones.solicitar_aporte(cli, 3000000, "equilibrio", None, None)      # US$ 30.000
    op, op2, cum = usuario("op@x.com"), usuario("op2@x.com"), usuario("cum@x.com")
    assert operaciones.aprobar(opid, op) == "primera_firma"
    assert not cartera.tenencias(cli["id"])                                          # todavía no se compró nada
    with pytest.raises(operaciones.ErrorNegocio, match="otra persona"):
        operaciones.aprobar(opid, op)
    with pytest.raises(operaciones.ErrorNegocio, match="Cumplimiento"):
        operaciones.aprobar(opid, op2)
    assert operaciones.aprobar(opid, cum) == "liquidada"
    fila = db.uno("SELECT * FROM operaciones WHERE id = ?", (opid,))
    assert fila["firma1_por"] == op["id"] and fila["firma2_por"] == cum["id"]


def test_precio_desactualizado_bloquea(ctx):
    cli = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(cli, 50000, "equilibrio", None, None)
    precios.registrar("SOL", Decimal("100"), None, "pruebas", ts=hace(minutes=90))
    with pytest.raises(operaciones.ErrorNegocio, match="SOL"):
        operaciones.aprobar(opid, usuario("op@x.com"))


def test_retiro(ctx):
    cli = cliente("laura@x.com")
    operaciones.aprobar(operaciones.solicitar_aporte(cli, 200000, "equilibrio", None, None), usuario("op@x.com"))
    valor = _saldo(cli["id"])
    with pytest.raises(operaciones.ErrorNegocio, match="supera"):
        operaciones.solicitar_retiro(cli, valor + 1, None)
    opid = operaciones.solicitar_retiro(cli, 50000, None)
    with pytest.raises(operaciones.ErrorNegocio, match="supera"):                    # cuenta lo ya pedido
        operaciones.solicitar_retiro(cli, valor - 50000 + 1, None)
    operaciones.aprobar(opid, usuario("op@x.com"))
    assert db.uno("SELECT liquidado_cent FROM operaciones WHERE id = ?", (opid,))["liquidado_cent"] == 50000
    assert abs(_saldo(cli["id"]) - (valor - 50000)) <= 5
    assert db.uno("SELECT COUNT(*) n FROM ordenes WHERE operacion_id = ? AND lado = 'venta'", (opid,))["n"] == 4


def test_retiro_total(ctx):
    cli = cliente("laura@x.com")
    operaciones.aprobar(operaciones.solicitar_aporte(cli, 77777, "impulso", None, None, acepta_riesgo=True), usuario("op@x.com"))
    valor = _saldo(cli["id"])
    operaciones.aprobar(operaciones.solicitar_retiro(cli, valor, None), usuario("op@x.com"))
    assert _saldo(cli["id"]) <= 1


def test_rechazo_y_cancelacion(nav, ctx):
    cli = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(cli, 50000, "equilibrio", None, None)
    with pytest.raises(operaciones.ErrorNegocio, match="motivo"):
        operaciones.rechazar(opid, usuario("op@x.com"), "")
    operaciones.rechazar(opid, usuario("op@x.com"), "Transferencia no recibida")
    with pytest.raises(operaciones.ErrorNegocio, match="resuelta"):
        operaciones.aprobar(opid, usuario("op@x.com"))
    c = nav("laura@x.com")
    otra = operaciones.solicitar_aporte(cli, 50000, "equilibrio", None, None)
    c.post(f"/cliente/operaciones/{otra}/cancelar")
    assert db.uno("SELECT estado FROM operaciones WHERE id = ?", (otra,))["estado"] == "cancelada"


def test_un_cliente_no_toca_operaciones_ajenas(nav, ctx):
    opid = operaciones.solicitar_aporte(cliente("pedro@x.com"), 50000, "reserva", None, None)
    nav("laura@x.com").post(f"/cliente/operaciones/{opid}/cancelar")
    assert db.uno("SELECT estado FROM operaciones WHERE id = ?", (opid,))["estado"] == "pendiente"


def test_libro_y_bitacora_no_se_pueden_modificar(ctx):
    cli = cliente("laura@x.com")
    operaciones.aprobar(operaciones.solicitar_aporte(cli, 50000, "equilibrio", None, None), usuario("op@x.com"))
    c = db.conexion()
    for sql in ("UPDATE libro SET cantidad = 1", "DELETE FROM libro", "UPDATE ordenes SET precio = '1'",
                "DELETE FROM bitacora", "UPDATE bitacora SET actor = 'x'"):
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(sql)


def test_alteracion_de_bitacora_se_detecta(ctx):
    assert auditoria.verificar()["ok"]
    c = db.conexion()
    c.execute("DROP TRIGGER bitacora_no_modificable")              # alguien con acceso directo a la base
    c.execute("UPDATE bitacora SET detalle = '{}' WHERE id = 3")
    r = auditoria.verificar()
    assert not r["ok"] and r["fallo"] == 3


def test_reporte_csv_y_estado_de_cuenta(nav, ctx):
    cli = cliente("laura@x.com")
    operaciones.aprobar(operaciones.solicitar_aporte(cli, 50000, "equilibrio", "TRF-9", None), usuario("op@x.com"))
    r = nav("cum@x.com").get("/equipo/reportes/operaciones.csv?desde=2000-01-01&hasta=2999-12-31")
    texto = r.get_data(as_text=True)
    assert r.status_code == 200 and "Laura Cliente" in texto and "500,00" in texto and "TRF-9" in texto
    r = nav("laura@x.com").get("/cliente/estado-de-cuenta.csv")
    texto = r.get_data(as_text=True)
    assert "Depósito" in texto and "Compra" in texto and "BTC" in texto


def test_todas_las_pantallas_responden(nav, ctx):
    cli = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(cli, 50000, "equilibrio", None, None)
    c = nav("laura@x.com")
    for url in ("/cliente/", "/cliente/cartera", "/cliente/invertir", "/cliente/movimientos", "/cuenta/seguridad", "/cuenta/clave"):
        assert c.get(url).status_code == 200, url
    a = nav("admin@x.com")
    for url in ("/equipo/", "/equipo/?vista=cliente", "/equipo/?vista=modelo", "/equipo/operaciones",
                f"/equipo/operaciones/{opid}", "/equipo/clientes", f"/equipo/clientes/{cli['id']}", "/equipo/clientes/nuevo",
                "/equipo/cumplimiento", "/equipo/bitacora", "/admin/precios", "/admin/usuarios"):
        assert a.get(url).status_code == 200, url


def test_alta_de_cliente_por_pantalla(nav, ctx):
    e = nav("op@x.com")
    r = e.post("/equipo/clientes/nuevo", {"nombre": "Nuevo Cliente", "documento": "CI 99", "tipo": "persona",
                                          "email": "nuevo@x.com", "perfil_riesgo": "moderado", "modelo": "reserva"})
    assert r.status_code == 200 and "contraseña temporal" in r.get_data(as_text=True)
    u = usuario("nuevo@x.com")
    assert u["rol"] == "cliente" and u["debe_cambiar_clave"]
    r = e.post("/equipo/clientes/nuevo", {"nombre": "Otro", "documento": "CI 99", "tipo": "persona",
                                          "email": "otro@x.com", "perfil_riesgo": "moderado", "modelo": "reserva"})
    assert "Ya existe un cliente con ese documento" in r.get_data(as_text=True)
