"""v0.20 · Módulos 6 y 7: perfil, límites, centro de seguridad, ayuda con consultas, academia, Earn informativo y análisis."""
import pytest

from financiera import db, niveles, operaciones, preferencias, soporte

from .conftest import cliente, usuario


def _saldo(monto=500000):
    cli = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(cli, monto, None, "T-saldo", None)
    operaciones.aprobar(opid, usuario("op@x.com"))
    return cli


def test_limites_editables_y_auditados(ctx):
    admin = usuario("admin@x.com")
    assert niveles.valor("ORDEN_MAXIMA_USD") == ctx.config["ORDEN_MAXIMA_USD"]
    assert niveles.fijar("ORDEN_MAXIMA_USD", 500, admin) is True
    cli = _saldo()
    with pytest.raises(operaciones.ErrorNegocio, match="máximo"):
        operaciones.operar(cli, "BTC", "compra", 60000, usuario("laura@x.com"))
    with pytest.raises(ValueError):
        niveles.fijar("ORDEN_MAXIMA_USD", 5, admin)
    assert db.uno("SELECT 1 FROM bitacora WHERE accion = 'limite.cambiado'")


def test_limite_de_retiros_por_dia(ctx):
    cli = _saldo(500000)
    niveles.fijar("RETIRO_MAX_DIA_USD", 1000, usuario("admin@x.com"))
    operaciones.solicitar_retiro(cli, 80000, usuario("laura@x.com"))
    with pytest.raises(operaciones.ErrorNegocio, match="retiros por día"):
        operaciones.solicitar_retiro(cli, 30000, usuario("laura@x.com"))


def test_nivel_y_proteccion_de_la_cuenta(nav, ctx):
    cli, u = cliente("laura@x.com"), usuario("laura@x.com")
    assert niveles.nivel(cli, u)["n"] == 1 and "dos pasos" in niveles.nivel(cli, u)["falta"]
    assert niveles.nivel(cliente("pedro@x.com"), usuario("pedro@x.com"))["n"] == 0
    p = niveles.proteccion(cli, u)
    assert 0 < p["puntos"] < 100 and not next(c for c in p["controles"] if c["titulo"] == "Verificación en dos pasos")["ok"]
    n = nav("laura@x.com")
    html = n.get("/cliente/perfil").data.decode()
    for t in ("Límites de operación", "Identidad verificada", "Preferencias", "Historial de actividad", "Centro de seguridad", "Acceso por API"):
        assert t in html, t
    seg = n.get("/cuenta/centro-seguridad").data.decode()
    assert "Controles" in seg and "Dispositivos con sesión" in seg
    assert nav("op@x.com").get("/cuenta/centro-seguridad").status_code == 200  # también para el equipo


def test_consulta_con_seguimiento_entre_cliente_y_equipo(nav, ctx):
    n = nav("laura@x.com")
    r = n.post("/cliente/ayuda", {"categoria": "depositos", "asunto": "No veo mi depósito", "texto": "Transferí ayer y todavía no aparece."})
    assert r.status_code == 302
    q = db.uno("SELECT * FROM consultas")
    assert q["estado"] == "abierta"
    assert nav("pedro@x.com").get(f"/cliente/ayuda/{q['id']}").status_code == 404  # no es suya
    eq = nav("op@x.com")
    assert "No veo mi depósito" in eq.get("/equipo/soporte").data.decode()
    assert eq.post(f"/equipo/soporte/{q['id']}", {"texto": "Ya lo acreditamos, revisa tu billetera."}).status_code == 302
    assert db.uno("SELECT estado FROM consultas")["estado"] == "respondida"
    aviso = db.uno("SELECT texto FROM notificaciones WHERE usuario_id = ? ORDER BY id DESC", (usuario("laura@x.com")["id"],))
    assert "Respondimos tu consulta" in aviso["texto"]
    hilo = n.get(f"/cliente/ayuda/{q['id']}").data.decode()
    assert "Ya lo acreditamos" in hilo and "Equipo de soporte" in hilo
    n.post(f"/cliente/ayuda/{q['id']}", {"accion": "cerrar"})
    with pytest.raises(soporte.ErrorSoporte, match="cerrada"):
        soporte.responder(q["id"], usuario("laura@x.com"), "otra cosa", False)
    assert n.get("/equipo/soporte").status_code == 403
    assert "verifico mi identidad" in n.get("/cliente/ayuda?q=identidad").data.decode()


def test_academia_con_progreso(nav, ctx):
    n = nav("laura@x.com")
    assert "0 de 10 leídas" in n.get("/academia").data.decode()
    r = n.post("/academia/que-es-una-criptomoneda")
    assert r.status_code == 302 and "/academia/como-leer-un-precio" in r.headers["Location"]
    assert preferencias.leer(usuario("laura@x.com")["id"])["lecciones"] == ["que-es-una-criptomoneda"]
    assert "1 de 10 leídas" in n.get("/academia").data.decode()
    assert n.get("/academia/no-existe").status_code == 404
    assert "Para recordar" in n.get("/academia/tipos-de-ordenes").data.decode()


def test_earn_es_solo_informativo(nav, ctx):
    n = nav("laura@x.com")
    html = n.get("/cliente/earn").data.decode()
    assert "No disponible" in html and "no promete ninguna ganancia" in html and "Riesgos" in html
    antes = db.uno("SELECT COUNT(*) AS n FROM libro")["n"]
    n.post("/cliente/earn", {"producto": "staking"})
    n.post("/cliente/earn", {"producto": "inventado"})
    assert preferencias.leer(usuario("laura@x.com")["id"])["earn_interes"] == ["staking"]
    assert db.uno("SELECT COUNT(*) AS n FROM libro")["n"] == antes  # marcar interés no mueve dinero


def test_analisis_de_cartera(nav, ctx):
    cli = _saldo()
    operaciones.operar(cli, "BTC", "compra", 200000, usuario("laura@x.com"))
    html = nav("laura@x.com").get("/cliente/analisis").data.decode()
    for t in ("Activo por activo", "Aporte al riesgo", "Diversificación efectiva", "Rendimiento por período"):
        assert t in html, t
