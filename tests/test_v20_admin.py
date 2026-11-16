"""v0.20 · Módulo 8: panel de administración, límites y permisos por rol."""
from financiera import db, niveles, operaciones, seguridad

from .conftest import cliente, usuario


def test_panel_con_estadisticas_y_riesgos(nav, ctx):
    cli = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(cli, 300000, None, "T", None)
    operaciones.aprobar(opid, usuario("op@x.com"))
    operaciones.operar(cli, "BTC", "compra", 100000, usuario("laura@x.com"))
    html = nav("admin@x.com").get("/admin/panel").data.decode()
    for t in ("Clientes", "Volumen operado 30 días", "Activos más utilizados", "Alertas de riesgo", "Acciones del equipo",
              "Supervisión: mayores órdenes", "US$ 1.000"):
        assert t in html, t


def test_permisos_diferenciados_por_rol(nav, ctx):
    assert nav("cum@x.com").get("/admin/panel").status_code == 200       # Cumplimiento ve el panel
    assert nav("cum@x.com").get("/admin/limites").status_code == 403     # pero no cambia límites
    assert nav("op@x.com").get("/admin/panel").status_code == 403        # Operaciones no
    assert nav("laura@x.com").get("/admin/panel").status_code in (302, 403)
    html = nav("admin@x.com").get("/admin/permisos").data.decode()
    assert "Matriz de permisos" in html and all(seguridad.DESCRIPCION_PERMISOS[p] in html for p in seguridad.PERMISOS)


def test_admin_cambia_limites_desde_la_pantalla(nav, ctx):
    n = nav("admin@x.com")
    assert n.post("/admin/limites", {"ORDEN_MAXIMA_USD": "10.000", "ENVIO_MAX_DIA_USD": "abc"}).status_code == 302
    assert niveles.valor("ORDEN_MAXIMA_USD") == 10000
    assert niveles.valor("ENVIO_MAX_DIA_USD") == ctx.config["ENVIO_MAX_DIA_USD"]
    assert db.uno("SELECT COUNT(*) AS n FROM bitacora WHERE accion = 'limite.cambiado'")["n"] == 1
