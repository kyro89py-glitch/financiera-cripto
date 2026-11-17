"""v0.20 · Módulo 3: inicio personalizable, rendimiento por período, riesgo, sugerencias y centro de avisos."""
import re
from datetime import timedelta
from decimal import Decimal

from financiera import db, notificaciones, operaciones, panel, precios, preferencias
from financiera.tiempo import ahora_dt, iso

from .conftest import cliente, usuario


def _saldo(monto=500000, email="laura@x.com"):
    cli = cliente(email)
    opid = operaciones.solicitar_aporte(cli, monto, None, "T-saldo", None)
    operaciones.aprobar(opid, usuario("op@x.com"))
    return cli


def test_preferencias_validadas_en_el_servidor(ctx):
    uid = usuario("laura@x.com")["id"]
    p = preferencias.guardar(uid, {"orden": ["mercado", "inventado", "activos", "mercado"], "ocultos": ["patrimonio", "riesgo", "x"],
                                   "moneda": "EUR", "correo": {"precios": False, "seguridad": False}})
    assert p["orden"][:2] == ["mercado", "activos"] and set(p["orden"]) == set(preferencias.MODULOS)
    assert p["ocultos"] == ["riesgo"]                # el patrimonio no se puede ocultar y lo desconocido se ignora
    assert p["moneda"] == "USD"                      # moneda inválida: queda la anterior
    assert p["correo"]["precios"] is False and p["correo"]["seguridad"] is True  # seguridad siempre llega


def test_inicio_respeta_orden_y_modulos_ocultos(nav, ctx):
    _saldo()
    n = nav("laura@x.com")
    orden = ",".join(["actividad", "patrimonio"] + [m for m in preferencias.MODULOS if m not in ("actividad", "patrimonio")])
    visibles = [m for m in preferencias.MODULOS if m != "ranking"]
    r = n.post("/cuenta/preferencias", {"accion": "panel", "orden": orden, "visible": visibles, "volver": "/cliente/"})
    assert r.status_code == 302
    html = n.get("/cliente/").data.decode()
    mods = re.findall(r'data-modulo="(\w+)"', html)
    assert mods[:2] == ["actividad", "patrimonio"] and "ranking" not in mods
    for texto in ("Rendimiento por período", "Riesgo de tu cartera", "Alertas importantes", "Para considerar", "Personalizar"):
        assert texto in html


def test_rendimiento_por_periodo_descuenta_depositos(ctx):
    cli = cliente("laura@x.com")
    hace = iso(ahora_dt() - timedelta(days=10))
    opid = operaciones.solicitar_aporte(cli, 100000, None, "T-viejo", None, ts=hace)
    operaciones.aprobar(opid, usuario("op@x.com"), ts=hace)
    _saldo(400000)  # depósito de hoy: el patrimonio sube, pero no es rendimiento
    precios.registrar("BTC", Decimal("70000"), Decimal("0"), "pruebas", ts=iso(ahora_dt() - timedelta(days=8)), historial_min=0)
    precios.registrar("BTC", Decimal("77000"), Decimal("0"), "pruebas")
    filas = {r["etiqueta"]: r for r in panel.rendimientos(cli["id"], 500000, precios.mercado())}
    r = filas["30 días"]
    assert r["parcial"] and r["cambio"] == 400000 and abs(r["twr"]) < 0.01   # todo en dólares: 0 % aunque entraron US$ 4.000
    assert abs(filas["7 días"]["btc"] - 10.0) < 0.01


def test_sugerencias_y_alertas_informativas(ctx):
    cli = _saldo()
    operaciones.operar(cli, "BTC", "compra", 400000, usuario("laura@x.com"))
    from financiera import cartera
    filas, total = cartera.posiciones(cli["id"])
    ind = cartera.indicadores(cli["id"], filas, total)
    r = panel.riesgo(cli, filas, ind)
    titulos = [s["titulo"] for s in panel.sugerencias(cli, usuario("laura@x.com"), filas, total, 0, r, None)]
    assert "Protege tu acceso" in titulos and any("Concentración en BTC" in t for t in titulos)
    textos = [t for _, t, _ in panel.alertas(cli, usuario("laura@x.com"), filas, total, [], ind)]
    assert any("verificación en dos pasos" in t for t in textos) and any("BTC" in t for t in textos)
    assert panel.ranking(filas, cartera.costos(cli["id"]))["mejores"] or panel.ranking(filas, cartera.costos(cli["id"]))["peores"]
    frases = panel.resumen_mercado(precios.mercado())
    assert frases and any("monedas suben" in t for t, _ in frases)
    assert not any("mayor suba" in t for t, _ in frases)  # si nada se movió, no se inventa una «mayor suba»


def test_avisos_por_categoria_y_correo_segun_preferencia(nav, ctx):
    ctx.config["SMTP_HOST"] = "smtp.prueba.local"
    uid = usuario("laura@x.com")["id"]
    preferencias.guardar(uid, {"correo": {"precios": False}})
    db.ejecutar("DELETE FROM correos")
    notificaciones.notificar(uid, "Tu alerta de precio de BTC se activó.", "/mercado/BTC")
    notificaciones.notificar(uid, "Nuevo ingreso a tu cuenta desde Chrome en Android.", "/cuenta/sesiones")
    cats = {n["texto"][:10]: n["categoria"] for n in notificaciones.listar(uid)}
    assert set(cats.values()) >= {"precios", "seguridad"}
    assert db.uno("SELECT COUNT(*) AS n FROM correos")["n"] == 1  # solo el de seguridad
    n = nav("laura@x.com")
    html = n.get("/cuenta/avisos?cat=precios").data.decode()
    assert "alerta de precio" in html and "Nuevo ingreso" not in html
    n.post("/cuenta/avisos", {"accion": "leer_todo", "cat": "precios"})   # 0.30: se marcan a pedido, por categoría
    assert db.uno("SELECT leida FROM notificaciones WHERE usuario_id = ? AND categoria = 'precios'", (uid,))["leida"] == 1
    assert db.uno("SELECT leida FROM notificaciones WHERE usuario_id = ? AND categoria = 'seguridad' ORDER BY id DESC", (uid,))["leida"] == 0
