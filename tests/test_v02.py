"""Legajo documental, condiciones, idoneidad, comisiones, conciliación, estados de cuenta, avisos y migraciones."""
import io
from decimal import Decimal

import pytest

from financiera import cartera, comisiones, conciliacion, cuentas, db, documentos, notificaciones, operaciones, precios
from financiera.formato import zona
from financiera.tiempo import ahora, ahora_dt

from .conftest import CLAVE, cliente, legajo_completo, usuario

PDF = documentos.pdf_ejemplo("prueba")


def _aporte_aprobado(email, monto=120000, modelo=None):
    cli = cliente(email)
    opid = operaciones.solicitar_aporte(cli, monto, modelo or cli["modelo"], "ref", None)
    assert operaciones.aprobar(opid, usuario("op@x.com")) == "liquidada"
    return opid


def _texto_cantidad(unidades, activo):
    return str(Decimal(unidades) / (100 if activo == "USD" else 10 ** 8))


# ---------- legajo documental ----------

def test_solo_se_aceptan_pdf_jpg_o_png_reales(ctx):
    cli = cliente("pedro@x.com")
    with pytest.raises(documentos.ErrorDocumento, match="Solo se aceptan"):
        documentos.guardar(cli, "identidad", "cedula.pdf", b"esto no es un pdf", usuario("op@x.com"))
    with pytest.raises(documentos.ErrorDocumento, match="vacío"):
        documentos.guardar(cli, "identidad", "cedula.pdf", b"", usuario("op@x.com"))
    with pytest.raises(documentos.ErrorDocumento, match="Elige"):
        documentos.guardar(cli, "inventado", "cedula.pdf", PDF, usuario("op@x.com"))
    ctx.config["DOCUMENTO_MAX_MB"] = 1
    with pytest.raises(documentos.ErrorDocumento, match="supera"):
        documentos.guardar(cli, "identidad", "cedula.pdf", PDF + b"0" * (1024 * 1024), usuario("op@x.com"))
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    did = documentos.guardar(cli, "identidad", "../../etc/cedula.png", png, usuario("op@x.com"))
    d = db.uno("SELECT * FROM documentos WHERE id = ?", (did,))
    assert d["mime"] == "image/png" and d["estado"] == "pendiente" and "/" not in d["nombre_original"]


def test_la_identidad_no_se_verifica_sin_documentos_aceptados(ctx):
    pedro = cliente("pedro@x.com")
    with pytest.raises(cuentas.ErrorDatos, match="faltan documentos"):
        cuentas.marcar_kyc(pedro["id"], "verificado", "", usuario("cum@x.com"))
    assert len(documentos.faltantes(pedro)) == 2
    legajo_completo(pedro["id"])
    assert documentos.faltantes(pedro) == []
    cuentas.marcar_kyc(pedro["id"], "verificado", "", usuario("cum@x.com"))
    assert cliente("pedro@x.com")["kyc_estado"] == "verificado"


def test_rechazo_de_documento_exige_motivo_y_avisa(ctx):
    pedro = cliente("pedro@x.com")
    did = documentos.guardar(pedro, "identidad", "cedula.pdf", PDF, usuario("pedro@x.com"))
    with pytest.raises(documentos.ErrorDocumento, match="por qué"):
        documentos.revisar(did, "rechazado", "", usuario("cum@x.com"))
    antes = notificaciones.no_leidas(pedro["usuario_id"])
    documentos.revisar(did, "rechazado", "La foto está borrosa", usuario("cum@x.com"))
    assert notificaciones.no_leidas(pedro["usuario_id"]) == antes + 1
    assert "borrosa" in notificaciones.listar(pedro["usuario_id"])[0]["texto"]


def test_cliente_sube_documento_y_solo_lo_ven_el_y_el_equipo(nav, ctx):
    pedro = nav("pedro@x.com")
    r = pedro.post("/cliente/perfil", {"tipo": "identidad", "archivo": (io.BytesIO(PDF), "cedula.pdf")},
                   content_type="multipart/form-data")
    assert r.status_code == 302
    d = db.uno("SELECT * FROM documentos WHERE cliente_id = ?", (cliente("pedro@x.com")["id"],))
    assert d and d["subido_por"] == usuario("pedro@x.com")["id"]
    r = pedro.get(f"/documentos/{d['id']}")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert nav("laura@x.com").get(f"/documentos/{d['id']}").status_code == 404
    cum = nav("cum@x.com")
    assert cum.get(f"/documentos/{d['id']}").status_code == 200
    assert db.uno("SELECT 1 FROM bitacora WHERE accion = 'documento.consultado'")
    assert b"cedula.pdf" in cum.get("/equipo/documentos").data
    r = cum.post(f"/equipo/documentos/{d['id']}/revisar", {"estado": "aceptado", "nota": "", "volver": "cola"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/equipo/documentos")
    assert db.uno("SELECT estado FROM documentos WHERE id = ?", (d["id"],))["estado"] == "aceptado"
    # Operaciones puede subir al legajo pero no revisar.
    op = nav("op@x.com")
    assert op.post(f"/equipo/documentos/{d['id']}/revisar", {"estado": "rechazado", "nota": "no corresponde"}).status_code == 403


# ---------- condiciones e idoneidad ----------

def test_cliente_nuevo_debe_aceptar_las_condiciones(nav, ctx):
    cuentas.crear_cliente({"nombre": "Nora Nueva", "documento": "CI 9", "tipo": "persona", "email": "nora@x.com",
                           "perfil_riesgo": "conservador", "modelo": "reserva", "clave": CLAVE})
    n = nav("nora@x.com")
    r = n.get("/cliente/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/cliente/condiciones")
    assert n.get("/cliente/movimientos").status_code == 302
    r = n.post("/cliente/condiciones", {})
    assert r.status_code == 200 and "tienes que marcar".encode() in r.data
    r = n.post("/cliente/condiciones", {"acepto": "si"})
    assert r.status_code == 302
    assert n.get("/cliente/").status_code == 200
    u = usuario("nora@x.com")
    assert u["terminos_version"] == 1 and u["terminos_ts"]
    assert db.uno("SELECT 1 FROM bitacora WHERE accion = 'terminos.aceptados'")


def test_cartera_con_mas_riesgo_que_el_perfil_requiere_confirmacion(nav, ctx):
    laura = nav("laura@x.com")  # perfil moderado: hasta riesgo 3
    r = laura.post("/cliente/invertir", {"monto": "500", "modelo": "impulso", "referencia": "T-1"})
    assert r.status_code == 200 and "más riesgo".encode() in r.data
    assert not db.uno("SELECT 1 FROM operaciones WHERE tipo = 'aporte'")
    r = laura.post("/cliente/invertir", {"monto": "500", "modelo": "impulso", "referencia": "T-1", "acepta_riesgo": "si"})
    assert r.status_code == 302
    op = db.uno("SELECT * FROM operaciones WHERE tipo = 'aporte'")
    assert op["fuera_perfil"] == 1
    textos = [t for _, t in operaciones.requisitos(op, cliente("laura@x.com"), usuario("op@x.com"))]
    assert any("más riesgo que el perfil" in t for t in textos)
    # Dentro del perfil no hace falta confirmar.
    opid = operaciones.solicitar_aporte(cliente("laura@x.com"), 50000, "equilibrio", None, None)
    assert db.uno("SELECT fuera_perfil FROM operaciones WHERE id = ?", (opid,))["fuera_perfil"] == 0


# ---------- comisión de gestión ----------

def test_comision_mensual_sobre_el_cierre_y_proporcional(ctx):
    laura = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(laura, 900000, laura["modelo"], "ref", None, ts="2026-10-16T15:00:00Z")
    operaciones.aprobar(opid, usuario("op@x.com"), ts="2026-10-16T15:00:00Z")
    pedro = cliente("pedro@x.com")  # invierte recién en noviembre: no paga octubre
    legajo_completo(pedro["id"])
    cuentas.marcar_kyc(pedro["id"], "verificado", "", usuario("cum@x.com"))
    operaciones.aprobar(operaciones.solicitar_aporte(cliente("pedro@x.com"), 50000, "reserva", None, None,
                                                     ts="2026-11-02T12:00:00Z"), usuario("op@x.com"), ts="2026-11-02T12:00:00Z")
    valor, fraccion, dias = comisiones.base(cliente("laura@x.com"), "2026-10")
    assert valor > 0 and fraccion == Decimal(1) / 2 and dias == 16  # 15,5 de 31 días
    assert comisiones.base(cliente("pedro@x.com"), "2026-10")[0] == 0
    _, antes = cartera.posiciones(laura["id"])
    r = comisiones.cobrar("2026-10", usuario("admin@x.com"))
    esperado = comisiones.calcular(valor, fraccion)
    assert abs(esperado - valor * 0.015 / 12 / 2) <= 0.5
    assert r == {"cobradas": 1, "total": esperado, "ya_cobradas": 0}
    op = db.uno("SELECT * FROM operaciones WHERE tipo = 'comision'")
    assert op["estado"] == "liquidada" and op["periodo"] == "2026-10" and op["liquidado_cent"] == esperado
    _, despues = cartera.posiciones(laura["id"])
    assert abs(antes - despues - esperado) <= 2
    assert "16 días" in notificaciones.listar(laura["usuario_id"])[0]["texto"]
    # Idempotente, y la base de datos impide duplicar el mes.
    assert comisiones.cobrar("2026-10", usuario("admin@x.com")) == {"cobradas": 0, "total": 0, "ya_cobradas": 1}
    with pytest.raises(Exception):
        db.ejecutar("INSERT INTO operaciones (cliente_id, tipo, monto_cent, periodo, estado, creado) "
                    "VALUES (?, 'comision', 1, '2026-10', 'liquidada', ?)", (laura["id"], ahora()))
    with pytest.raises(comisiones.ErrorComision, match="formato"):
        comisiones.cobrar("octubre")
    with pytest.raises(comisiones.ErrorComision, match="meses cerrados"):
        comisiones.cobrar(ahora_dt().astimezone(zona()).strftime("%Y-%m"))


def test_comision_con_precios_viejos_no_se_cobra(ctx):
    _aporte_aprobado("laura@x.com")
    db.ejecutar("UPDATE precios SET ts = '2020-01-01T00:00:00Z'")
    with pytest.raises(comisiones.ErrorComision, match="(?i)precio"):
        comisiones.cobrar("2026-10")


# ---------- conciliación de custodia ----------

def test_conciliacion_sin_y_con_diferencias(nav, ctx):
    _aporte_aprobado("laura@x.com")
    assert conciliacion.estado()[0] == "nunca"
    libro = conciliacion.saldos_libro()
    reales = {a: _texto_cantidad(libro.get(a, 0), a) for a in conciliacion.activos_a_conciliar()}
    conciliacion.registrar(reales, "cierre", usuario("cum@x.com"))
    assert conciliacion.estado()[0] == "ok"
    reales["BTC"] = _texto_cantidad(libro["BTC"] + 1, "BTC")
    conciliacion.registrar(reales, "", usuario("cum@x.com"))
    est, ult = conciliacion.estado()
    assert est == "diferencias" and ult["diferencias"] == 1
    assert any(e == ("conciliacion", None) and n == "alta" for n, _, e in operaciones.alertas())
    with pytest.raises(conciliacion.ErrorConciliacion):
        conciliacion.registrar(dict(reales, ETH="abc"), "", usuario("cum@x.com"))
    with pytest.raises(Exception):
        db.ejecutar("UPDATE conciliaciones SET diferencias = 0")
    # Por pantalla: Operaciones no puede registrar.
    assert nav("op@x.com").post("/equipo/conciliacion", {f"real_{a}": v for a, v in reales.items()}).status_code == 403
    r = nav("cum@x.com").post("/equipo/conciliacion", dict({f"real_{a}": v for a, v in reales.items()}, real_BTC=_texto_cantidad(libro["BTC"], "BTC")))
    assert r.status_code == 302 and conciliacion.estado()[0] == "ok"


# ---------- estados de cuenta ----------

def test_estado_de_cuenta_mensual_cuadra(nav, ctx):
    _aporte_aprobado("laura@x.com", 300000)
    precios.registrar("BTC", Decimal("84000"), Decimal("20"), "pruebas")
    laura = cliente("laura@x.com")
    periodo = cartera.periodos_cliente(laura)[0]
    ec = cartera.estado_cuenta(laura, periodo)
    assert ec["en_curso"] and ec["valor_inicial"] == 0 and ec["aportes"] == 300000
    assert ec["mercado"] > 0
    assert ec["valor_final"] == ec["valor_inicial"] + ec["aportes"] - ec["retiros"] - ec["comisiones"] + ec["mercado"]
    _, total = cartera.posiciones(laura["id"])
    assert ec["valor_final"] == total
    n = nav("laura@x.com")
    r = n.get(f"/cliente/estado-de-cuenta/{periodo}")
    assert r.status_code == 200 and b"Estado de cuenta" in r.data and b"Resultado de mercado" in r.data
    assert n.get("/cliente/estado-de-cuenta/1999-01").status_code == 404
    assert nav("op@x.com").get(f"/equipo/clientes/{laura['id']}/estado-de-cuenta/{periodo}").status_code == 200


# ---------- avisos ----------

def test_avisos_de_aprobacion_y_correo(nav, ctx):
    ctx.config.update(SMTP_HOST="smtp.ejemplo.com", URL_PUBLICA="https://app.ejemplo.com")
    _aporte_aprobado("laura@x.com")
    laura = usuario("laura@x.com")
    assert notificaciones.no_leidas(laura["id"]) >= 1
    correo = db.uno("SELECT * FROM correos WHERE para = ?", ("laura@x.com",))
    assert correo and "https://app.ejemplo.com/cliente/movimientos" in correo["cuerpo"]
    n = nav("laura@x.com")
    assert n.get("/cuenta/avisos").status_code == 200
    assert notificaciones.no_leidas(laura["id"]) == 0


def test_solicitud_avisa_al_equipo(ctx):
    antes = notificaciones.no_leidas(usuario("op@x.com")["id"])
    operaciones.solicitar_aporte(cliente("laura@x.com"), 50000, "equilibrio", None, usuario("laura@x.com"))
    assert notificaciones.no_leidas(usuario("op@x.com")["id"]) == antes + 1


# ---------- migraciones ----------

def test_migraciones_se_aplican_una_sola_vez(ctx):
    n = len(db._migraciones())
    assert n >= 1 and db.version() == n
    assert db.migrar() == []
    assert db.version() == n


def test_pantallas_nuevas_responden(nav, ctx):
    _aporte_aprobado("laura@x.com")
    cum = nav("cum@x.com")
    for url in ("/equipo/cumplimiento", "/equipo/documentos", "/equipo/conciliacion", "/equipo/bitacora", "/cuenta/avisos"):
        assert cum.get(url).status_code == 200, url
    adm = nav("admin@x.com")
    for url in ("/admin/comisiones", "/admin/precios", "/admin/usuarios"):
        assert adm.get(url).status_code == 200, url
    assert nav("op@x.com").get("/admin/comisiones").status_code == 403
    laura = nav("laura@x.com")
    for url in ("/cliente/perfil", "/cliente/condiciones", "/cliente/movimientos", "/cliente/invertir"):
        assert laura.get(url).status_code == 200, url
