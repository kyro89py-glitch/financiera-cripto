"""v0.30 · Administración: control dual de acciones críticas, incidencias, perfil completo del cliente y reporte agregado."""
import csv
import io

from financiera import autorizaciones as aut
from financiera import db, niveles

from .conftest import cliente, usuario


def _ultima():
    return db.uno("SELECT * FROM autorizaciones ORDER BY id DESC LIMIT 1")


def test_control_dual_en_limites(nav, ctx):
    a = nav("admin@x.com")
    a.post("/admin/limites", {"ORDEN_MAXIMA_USD": "12000", "motivo": "x"})            # sin motivo suficiente
    assert db.uno("SELECT COUNT(*) AS n FROM autorizaciones")["n"] == 0
    a.post("/admin/limites", {"ORDEN_MAXIMA_USD": "12000", "motivo": "Campaña de diciembre"})
    p = _ultima()
    assert p["estado"] == "pendiente" and "12.000" in p["resumen"] and niveles.valor("ORDEN_MAXIMA_USD") != 12000
    a.post("/admin/limites", {"ORDEN_MAXIMA_USD": "12000", "motivo": "Otra vez"})      # duplicado
    assert db.uno("SELECT COUNT(*) AS n FROM autorizaciones")["n"] == 1
    a.post("/equipo/autorizaciones", {"id": p["id"], "decision": "aprobar"})            # quien pide no aprueba
    assert _ultima()["estado"] == "pendiente"
    assert nav("op@x.com").post("/equipo/autorizaciones", {"id": p["id"], "decision": "aprobar"}).status_code in (302, 403)
    assert _ultima()["estado"] == "pendiente"
    c = nav("cum@x.com")
    assert "Campaña de diciembre" in c.get("/equipo/autorizaciones").get_data(as_text=True)
    c.post("/equipo/autorizaciones", {"id": p["id"], "decision": "rechazar", "nota": ""})  # rechazar exige nota
    assert _ultima()["estado"] == "pendiente"
    c.post("/equipo/autorizaciones", {"id": p["id"], "decision": "aprobar", "nota": "Ok"})
    p = _ultima()
    assert p["estado"] == "ejecutada" and p["resultado"].startswith("1 límite") and niveles.valor("ORDEN_MAXIMA_USD") == 12000
    c.post("/equipo/autorizaciones", {"id": p["id"], "decision": "aprobar"})            # no se ejecuta dos veces
    acciones = [r["accion"] for r in db.todos("SELECT accion FROM bitacora WHERE accion LIKE 'autorizacion.%' OR accion = 'limite.cambiado'")]
    assert acciones.count("autorizacion.pedida") == 1 and acciones.count("autorizacion.aprobada") == 1 and acciones.count("limite.cambiado") == 1


def test_baja_de_usuario_y_cancelacion_y_vencimiento(nav, ctx):
    a = nav("admin@x.com")
    op = usuario("op@x.com")
    a.post(f"/admin/usuarios/{op['id']}/estado", {"motivo": "Dejó la empresa"})
    p = _ultima()
    assert usuario("op@x.com")["activo"] == 1 and "Desactivar" in p["resumen"]
    a.post("/equipo/autorizaciones", {"id": p["id"], "decision": "cancelar"})
    assert _ultima()["estado"] == "cancelada"
    a.post(f"/admin/usuarios/{op['id']}/estado", {"motivo": "Dejó la empresa"})
    p = _ultima()
    db.ejecutar("UPDATE autorizaciones SET vence = '2000-01-01T00:00:00Z' WHERE id = ?", (p["id"],))
    nav("cum@x.com").post("/equipo/autorizaciones", {"id": p["id"], "decision": "aprobar"})
    assert _ultima()["estado"] == "vencida" and usuario("op@x.com")["activo"] == 1
    a.post(f"/admin/usuarios/{op['id']}/estado", {"motivo": "Dejó la empresa"})
    nav("cum@x.com").post("/equipo/autorizaciones", {"id": _ultima()["id"], "decision": "aprobar"})
    assert usuario("op@x.com")["activo"] == 0
    a.post(f"/admin/usuarios/{usuario('admin@x.com')['id']}/estado", {"motivo": "Probar autodesactivar"})
    assert _ultima()["accion"] == "usuario_estado" and _ultima()["estado"] == "ejecutada"   # no se creó un pedido nuevo


def test_cobro_de_comision_pasa_por_autorizacion(nav, ctx):
    a = nav("admin@x.com")
    a.post("/admin/comisiones", {"periodo": "2026-10", "motivo": "Cobro mensual"})
    p = _ultima()
    assert p["accion"] == "comision" and p["estado"] == "pendiente"
    assert db.uno("SELECT COUNT(*) AS n FROM operaciones WHERE tipo = 'comision'")["n"] == 0
    nav("cum@x.com").post("/equipo/autorizaciones", {"id": p["id"], "decision": "aprobar"})
    assert _ultima()["estado"] in ("ejecutada", "fallida") and _ultima()["resultado"]


def test_sin_control_dual_se_aplica_directo(nav, ctx):
    ctx.config["CONTROL_DUAL"] = False
    nav("admin@x.com").post("/admin/limites", {"ORDEN_MAXIMA_USD": "9000"})
    assert niveles.valor("ORDEN_MAXIMA_USD") == 9000 and db.uno("SELECT COUNT(*) AS n FROM autorizaciones")["n"] == 0


def test_incidencias(nav, ctx):
    o = nav("op@x.com")
    o.post("/equipo/incidencias", {"titulo": "Caída", "descripcion": "corto", "categoria": "tecnica", "severidad": "alta"})
    assert db.uno("SELECT COUNT(*) AS n FROM incidencias")["n"] == 0
    r = o.post("/equipo/incidencias", {"titulo": "Depósito sin acreditar", "descripcion": "El cliente reporta un depósito de ayer que no ve.",
                                       "categoria": "cliente", "severidad": "critica", "cliente": "laura@x.com",
                                       "asignada_a": str(usuario("cum@x.com")["id"])})
    iid = int(r.headers["Location"].rsplit("/", 1)[1])
    i = db.uno("SELECT * FROM incidencias WHERE id = ?", (iid,))
    assert i["cliente_id"] == cliente("laura@x.com")["id"] and i["asignada_a"] == usuario("cum@x.com")["id"]
    assert db.uno("SELECT COUNT(*) AS n FROM notificaciones WHERE usuario_id = ? AND texto LIKE '%Depósito sin acreditar%'",
                  (usuario("admin@x.com")["id"],))["n"] >= 1
    o.post(f"/equipo/incidencias/{iid}", {"estado": "resuelta"})                     # resolver sin nota: no
    assert db.uno("SELECT estado FROM incidencias WHERE id = ?", (iid,))["estado"] == "abierta"
    o.post(f"/equipo/incidencias/{iid}", {"estado": "en_curso", "nota": "Revisando el extracto bancario."})
    o.post(f"/equipo/incidencias/{iid}", {"estado": "resuelta", "nota": "Acreditado tras conciliar."})
    i = db.uno("SELECT * FROM incidencias WHERE id = ?", (iid,))
    assert i["estado"] == "resuelta" and i["resuelta"]
    h = o.get(f"/equipo/incidencias/{iid}").get_data(as_text=True)
    assert "Revisando el extracto" in h and "Abierta → En curso" in h
    assert "Depósito sin acreditar" in o.get("/equipo/incidencias?estado=resuelta").get_data(as_text=True)
    assert "Depósito sin acreditar" not in o.get("/equipo/incidencias").get_data(as_text=True)    # activas
    assert nav("laura@x.com").get("/equipo/incidencias").status_code in (302, 403)
    assert db.uno("SELECT COUNT(*) AS n FROM bitacora WHERE accion LIKE 'incidencia.%'")["n"] == 3


def test_perfil_del_cliente_enmascara_y_registra(nav, ctx):
    nav("laura@x.com").post("/cuenta/datos", {"telefono": "0981 555 123", "direccion": "Av. España 1234", "ciudad": "Asunción", "pais": "Paraguay"})
    cid = cliente("laura@x.com")["id"]
    o = nav("op@x.com").get(f"/equipo/clientes/{cid}").get_data(as_text=True)
    assert "Identidad y cuenta" in o and "FC" in o and "0981 555 123" not in o and "Av. España 1234" not in o
    assert "Ver datos completos" not in o                                              # Operaciones no puede
    assert nav("op@x.com").post(f"/equipo/clientes/{cid}/datos-sensibles", {"motivo": "Curiosidad"}).status_code == 403
    c = nav("cum@x.com")
    assert "Ver datos completos" in c.get(f"/equipo/clientes/{cid}").get_data(as_text=True)
    c.post(f"/equipo/clientes/{cid}/datos-sensibles", {"motivo": ""})
    assert db.uno("SELECT COUNT(*) AS n FROM bitacora WHERE accion = 'cliente.datos_vistos'")["n"] == 0
    h = c.post(f"/equipo/clientes/{cid}/datos-sensibles", {"motivo": "Verificar dirección para el legajo"}).get_data(as_text=True)
    assert "0981 555 123" in h and "Av. España 1234" in h
    b = db.uno("SELECT * FROM bitacora WHERE accion = 'cliente.datos_vistos'")
    assert b and "Verificar dirección" in b["detalle"] and b["usuario_id"] == usuario("cum@x.com")["id"]
    assert "Actividad de la cuenta" in h


def test_reporte_agregado(nav, ctx):
    r = nav("cum@x.com").get("/admin/panel/reporte.csv?dias=7")
    filas = list(csv.reader(io.StringIO(r.data.decode("utf-8-sig")), delimiter=";"))
    assert r.mimetype == "text/csv" and filas[0] == ["indicador", "valor", "nota"] and any("simulador" in f[0] for f in filas)
    assert "laura" not in r.data.decode().lower()
    assert nav("op@x.com").get("/admin/panel/reporte.csv").status_code == 403
    assert db.uno("SELECT COUNT(*) AS n FROM bitacora WHERE accion = 'reporte.exportado'")["n"] == 1
    assert aut.pendientes() == 0
