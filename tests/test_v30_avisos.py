"""v0.30 · Notificaciones: leer, eliminar, filtrar y preferencias por tipo y canal, guardadas en la cuenta."""
from financiera import db, notificaciones, preferencias
from tests.conftest import usuario


def _ids(uid):
    return [r["id"] for r in db.todos("SELECT id FROM notificaciones WHERE usuario_id = ? ORDER BY id", (uid,))]


def test_marcar_eliminar_y_abrir(nav, app):
    with app.app_context():
        uid, otro = usuario("laura@x.com")["id"], usuario("pedro@x.com")["id"]
        db.ejecutar("DELETE FROM notificaciones")
        notificaciones.notificar(uid, "Se ejecutó tu compra.", "/cliente/movimientos", categoria="operaciones")
        notificaciones.notificar(uid, "Subió BTC.", None, categoria="mercado")
        notificaciones.notificar(otro, "Aviso de Pedro.", "/cliente/", categoria="cuenta")
        a, b = _ids(uid)
        ajeno = _ids(otro)[0]
    n = nav("laura@x.com")
    h = n.get("/cuenta/avisos").get_data(as_text=True)
    assert "Se ejecutó tu compra" in h and "Aviso de Pedro" not in h
    with app.app_context():
        assert notificaciones.no_leidas(uid) == 2                      # ver la lista no marca nada
    r = n.get(f"/cuenta/avisos/{a}")
    assert r.status_code == 302 and r.headers["Location"].endswith("/cliente/movimientos")
    n.post("/cuenta/avisos", {"accion": "leer", "id": b})
    with app.app_context():
        assert notificaciones.no_leidas(uid) == 0
    n.post("/cuenta/avisos", {"accion": "no_leer", "id": b})
    assert "Subió BTC" in n.get("/cuenta/avisos?ver=nuevas").get_data(as_text=True)
    assert "Se ejecutó tu compra" not in n.get("/cuenta/avisos?ver=nuevas").get_data(as_text=True)
    # no puede tocar avisos ajenos
    assert n.get(f"/cuenta/avisos/{ajeno}").status_code == 404
    n.post("/cuenta/avisos", {"accion": "eliminar", "id": ajeno})
    n.post("/cuenta/avisos", {"accion": "leer", "id": ajeno})
    with app.app_context():
        assert _ids(otro) == [ajeno] and notificaciones.no_leidas(otro) == 1
    n.post("/cuenta/avisos", {"accion": "eliminar_leidas"})
    with app.app_context():
        assert _ids(uid) == [b]
    n.post("/cuenta/avisos", {"accion": "eliminar", "id": b})
    with app.app_context():
        assert _ids(uid) == []
    assert n.post("/cuenta/avisos", {"accion": "leer_todo"}, csrf=False).status_code in (400, 403)


def test_preferencias_por_tipo_y_canal(nav, app):
    n = nav("laura@x.com")
    n.post("/cuenta/avisos", {"accion": "preferencias", "app_operaciones": "si", "correo_operaciones": "si", "push_precios": "si",
                              "aviso_ingreso": "siempre"})
    with app.app_context():
        uid = usuario("laura@x.com")["id"]
        db.ejecutar("DELETE FROM notificaciones")
        p = preferencias.leer(uid)
        assert p["app"]["operaciones"] and not p["app"]["mercado"] and p["push"]["precios"] and not p["correo"]["mercado"]
        assert p["app"]["seguridad"] and p["correo"]["seguridad"]      # seguridad no se puede apagar
        assert p["aviso_ingreso"] == "siempre"
        notificaciones.notificar(uid, "Mercado movido.", None, categoria="mercado")
        notificaciones.notificar(uid, "Compra hecha.", None, categoria="operaciones")
        filas = {r["categoria"]: r["leida"] for r in db.todos("SELECT categoria, leida FROM notificaciones WHERE usuario_id = ?", (uid,))}
        assert filas["mercado"] == 1 and filas["operaciones"] == 0     # silenciada: en el historial, sin sumar al contador
    otro = nav("laura@x.com")                                          # otro dispositivo ve la misma configuración y recibe el aviso de ingreso
    h = otro.get("/cuenta/avisos").get_data(as_text=True)
    assert 'value="siempre" selected' in h and "Inicio de sesión desde" in h and "pendiente de integración" in h


def test_comunicado_llega_a_clientes(app):
    with app.app_context():
        db.ejecutar("DELETE FROM notificaciones")
        assert notificaciones.comunicado("Mantenimiento el domingo.") == 2
        assert db.uno("SELECT COUNT(*) AS n FROM notificaciones WHERE categoria = 'comunicaciones'")["n"] == 2
        assert db.uno("SELECT COUNT(*) AS n FROM notificaciones WHERE usuario_id = ?", (usuario("op@x.com")["id"],))["n"] == 0
