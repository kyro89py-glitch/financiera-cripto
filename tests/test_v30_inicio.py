"""v0.30 · Inicio personalizable: favoritos, accesos rápidos, período del gráfico y vistas guardadas en la cuenta."""
from financiera import db, preferencias
from financiera.tiempo import ahora
from tests.conftest import usuario


def test_accesos_rango_y_vistas(nav, app):
    n = nav("laura@x.com")
    base = {"accion": "panel", "orden": "patrimonio,favoritos,acciones", "visible": ["patrimonio", "favoritos", "acciones"]}
    n.post("/cuenta/preferencias", base | {"acceso": ["enviar", "mercados", "inventado", "enviar"], "rango": "3M", "vista_nombre": "  Simple  "})
    with app.app_context():
        uid = usuario("laura@x.com")["id"]
        p = preferencias.leer(uid)
        assert p["accesos"] == ["enviar", "mercados"] and p["rango"] == "3M" and p["orden"][:3] == ["patrimonio", "favoritos", "acciones"]
        assert [v["nombre"] for v in p["vistas"]] == ["Simple"] and p["vistas"][0]["accesos"] == ["enviar", "mercados"]
    h = nav("laura@x.com").get("/cliente/").get_data(as_text=True)     # otro dispositivo
    bloque = h.split('aria-label="Accesos rápidos"')[1].split("</nav>")[0]
    assert "Enviar" in bloque and "Mercados" in bloque and "Retirar" not in bloque
    # cambia la configuración y vuelve a la vista guardada
    n.post("/cuenta/preferencias", {"accion": "panel", "orden": "", "visible": ["patrimonio"], "acceso": ["retirar"], "rango": "Marte"})
    with app.app_context():
        p = preferencias.leer(uid)
        assert p["accesos"] == ["retirar"] and p["rango"] == "" and "acciones" in p["ocultos"]
    n.post("/cuenta/preferencias", {"accion": "vista", "i": "0"})
    with app.app_context():
        p = preferencias.leer(uid)
        assert p["accesos"] == ["enviar", "mercados"] and p["rango"] == "3M" and "acciones" not in p["ocultos"]
    for i in range(7):
        n.post("/cuenta/preferencias", base | {"acceso": ["enviar"], "vista_nombre": f"V{i}"})
    n.post("/cuenta/preferencias", {"accion": "vista", "i": "99"})
    n.post("/cuenta/preferencias", {"accion": "vista", "i": "0", "borrar": "1"})
    with app.app_context():
        assert len(preferencias.leer(uid)["vistas"]) == preferencias.MAX_VISTAS - 1
    n.post("/cuenta/preferencias", base | {"restablecer": "1"})
    with app.app_context():
        assert preferencias.leer(uid)["accesos"] == preferencias.ACCESOS_DEFECTO


def test_modulo_de_favoritos(nav, app):
    n = nav("laura@x.com")
    assert "Marca monedas con la estrella" in n.get("/cliente/").get_data(as_text=True)
    with app.app_context():
        db.ejecutar("INSERT INTO favoritos (usuario_id, activo, creado) VALUES (?, 'ETH', ?)", (usuario("laura@x.com")["id"], ahora()))
    h = n.get("/cliente/").get_data(as_text=True)
    assert 'class="fav"' in h and "/trading/ETH" in h
