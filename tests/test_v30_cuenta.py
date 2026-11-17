"""v0.30 · Mi cuenta: fotografía, nombre de usuario, perfil público, correo, solicitudes, preferencias y actividad."""
import io
import re

from PIL import Image

from financiera import cuenta, db, preferencias
from tests.conftest import CLAVE, cliente, usuario


def imagen(fmt="PNG", lado=(900, 600), exif=False):
    b = io.BytesIO()
    im = Image.new("RGB", lado, (30, 90, 200))
    if exif:
        e = Image.Exif()
        e[0x010F] = "CamaraSecreta"
        im.save(b, "JPEG", exif=e)
    else:
        im.save(b, fmt)
    return b.getvalue()


def subir(n, datos, nombre="yo.png"):
    return n.post("/cuenta/foto", {"foto": (io.BytesIO(datos), nombre)}, content_type="multipart/form-data", follow_redirects=True)


def test_pantallas_de_cuenta_abren(nav):
    for email in ("laura@x.com", "pedro@x.com", "op@x.com", "admin@x.com"):
        n = nav(email)
        for url in ("/cuenta/", "/cuenta/datos", "/cuenta/personalizar", "/cuenta/actividad", "/cuenta/solicitudes"):
            assert n.get(url).status_code == 200, (email, url)
    assert nav().get("/cuenta/").status_code in (302, 401)


def test_foto_se_guarda_recodificada_y_persiste(nav, app):
    n = nav("laura@x.com")
    r = subir(n, imagen(exif=True), "foto.jpg")
    assert "Fotografía actualizada" in r.get_data(as_text=True)
    with app.app_context():
        u = usuario("laura@x.com")
        assert u["foto"] and re.fullmatch(r"[0-9a-f]+\.jpg", u["foto"])
        crudo = open(cuenta.ruta_foto(u), "rb").read()
    assert b"CamaraSecreta" not in crudo                      # sin metadatos del archivo original
    assert Image.open(io.BytesIO(crudo)).size == (512, 512)
    otro = nav("laura@x.com")                                 # otro dispositivo: la foto sigue ahí
    r = otro.get(f"/cuenta/foto/{u['id']}")
    assert r.status_code == 200 and r.mimetype == "image/jpeg" and r.headers.get("X-Content-Type-Options") == "nosniff"
    assert f"/cuenta/foto/{u['id']}" in otro.get("/cuenta/").get_data(as_text=True)


def test_foto_rechaza_archivos_que_no_son_imagen(nav, app):
    n = nav("laura@x.com")
    for datos, nombre in [(b"<?php system($_GET[1]); ?>", "a.php"), (b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", "a.svg"),
                          (b"\x89PNG\r\n\x1a\n" + b"x" * 200, "roto.png"), (b"%PDF-1.4 hola", "a.png"), (b"", "vacio.png"),
                          (imagen("GIF"), "a.gif"), (b"\xff\xd8\xff" + b"0" * (6 * 1024 * 1024 + 10), "grande.jpg")]:
        subir(n, datos, nombre)
        with app.app_context():
            assert usuario("laura@x.com")["foto"] is None, nombre


def test_foto_quitar_y_acceso(nav, app):
    n = nav("laura@x.com")
    subir(n, imagen())
    with app.app_context():
        uid = usuario("laura@x.com")["id"]
        ruta = cuenta.ruta_foto(usuario("laura@x.com"))
    pedro = nav("pedro@x.com")
    assert pedro.get(f"/cuenta/foto/{uid}").status_code == 404            # sin perfil público, otro cliente no la ve
    assert nav("op@x.com").get(f"/cuenta/foto/{uid}").status_code == 200  # el equipo sí
    assert nav().get(f"/cuenta/foto/{uid}").status_code in (302, 401, 404)
    n.post("/cuenta/datos", {"accion": "usuario", "usuario": "laura.c"})
    n.post("/cuenta/datos", {"accion": "publico", "activo": "si", "foto": "si"})
    assert pedro.get(f"/cuenta/foto/{uid}").status_code == 200
    n.post("/cuenta/foto", {"accion": "quitar"})
    import os
    with app.app_context():
        assert usuario("laura@x.com")["foto"] is None
    assert not os.path.exists(ruta)


def test_usuario_unico_y_disponibilidad(nav, app):
    n, p = nav("laura@x.com"), nav("pedro@x.com")
    assert n.get("/cuenta/usuario-disponible?u=laurita").get_json()["ok"] is True
    n.post("/cuenta/datos", {"accion": "usuario", "usuario": "Laurita"})
    with app.app_context():
        assert usuario("laura@x.com")["usuario"] == "laurita"
    assert p.get("/cuenta/usuario-disponible?u=LAURITA").get_json()["ok"] is False
    p.post("/cuenta/datos", {"accion": "usuario", "usuario": "LauRita"})
    with app.app_context():
        assert usuario("pedro@x.com")["usuario"] is None
        try:                                                    # la unicidad la garantiza la base, no solo la validación
            db.ejecutar("UPDATE usuarios SET usuario = 'LAURITA' WHERE email = 'pedro@x.com'")
            assert False, "debía fallar"
        except db.sqlite3.IntegrityError:
            pass
    for malo in ("ab", "1abc", "admin", "soporte1", "con espacio", "a..b", "x" * 21, "<script>"):
        assert p.get("/cuenta/usuario-disponible", query_string={"u": malo}).get_json()["ok"] is False, malo
    n.post("/cuenta/datos", {"accion": "usuario", "usuario": "otra"})  # cambio dentro de los 30 días
    with app.app_context():
        assert usuario("laura@x.com")["usuario"] == "laurita"


def test_identificador_de_cuenta(app):
    with app.app_context():
        u = usuario("laura@x.com")
        cod = cuenta.codigo(u["id"])
        assert re.fullmatch(r"FC\d{8}", cod) and cuenta.leer_codigo(cod) == u["id"] and cuenta.leer_codigo(cod.lower()) == u["id"]
        malo = cod[:-1] + str((int(cod[-1]) + 1) % 10)
        assert cuenta.leer_codigo(malo) is None


def test_perfil_publico_no_expone_finanzas_ni_contacto(nav, app):
    n = nav("laura@x.com")
    n.post("/cuenta/datos", {"accion": "usuario", "usuario": "laura.c"})
    n.post("/cuenta/datos", {"nombre_publico": "Lau", "bio": "Ahorro de a poco", "telefono": "0981 123456", "ciudad": "Asunción",
                             "pais": "Paraguay", "direccion": "Calle Falsa 123", "avatar": "2"})
    p = nav("pedro@x.com")
    n.post("/cuenta/datos", {"accion": "publico"})
    assert p.get("/u/laura.c").status_code == 404                       # la persona lo puede apagar
    n.post("/cuenta/datos", {"accion": "publico", "activo": "si", "bio": "si"})
    h = p.get("/u/laura.c").get_data(as_text=True)
    assert "Lau" in h and "Ahorro de a poco" in h
    for privado in ("laura@x.com", "0981", "Calle Falsa", "CI 1", "Laura Cliente", "Asunción", "US$"):
        assert privado not in h.split('<article class="tarjeta-publica">')[1].split("</article>")[0], privado
    n.post("/cuenta/datos", {"accion": "publico", "activo": "si", "ubicacion": "si"})
    assert "Asunción" in p.get("/u/laura.c").get_data(as_text=True)
    assert nav().get("/u/laura.c").status_code in (302, 401)           # sin sesión no se ve
    assert p.get("/u/noexiste").status_code == 404


def test_datos_validados_y_nacimiento_bloqueado(nav, app):
    n = nav("laura@x.com")
    n.post("/cuenta/datos", {"nombre_publico": "<b>Lau</b>", "nacimiento": "2015-01-01", "pais": "Narnia", "avatar": "99"})
    with app.app_context():
        u = usuario("laura@x.com")
        assert u["nacimiento"] is None and u["pais"] is None and (u["avatar"] or 0) < cuenta.AVATARES
    n.post("/cuenta/datos", {"nacimiento": "1990-05-04", "pais": "Paraguay"})
    n.post("/cuenta/datos", {"nacimiento": "1980-01-01"})
    with app.app_context():
        assert usuario("laura@x.com")["nacimiento"] == "1990-05-04"   # una vez cargada, solo por solicitud
    assert "&lt;b&gt;" in n.get("/cuenta/").get_data(as_text=True) or "<b>Lau</b>" not in n.get("/cuenta/").get_data(as_text=True)


def test_cambio_de_correo_con_verificacion(nav, app):
    n = nav("laura@x.com")
    n.post("/cuenta/correo", {"nuevo": "nueva@x.com", "clave": "mala"})
    with app.app_context():
        assert db.uno("SELECT COUNT(*) AS n FROM cambios_email")["n"] == 0
    n.post("/cuenta/correo", {"nuevo": "pedro@x.com", "clave": CLAVE})
    with app.app_context():
        assert db.uno("SELECT COUNT(*) AS n FROM cambios_email")["n"] == 0
    r = n.post("/cuenta/correo", {"nuevo": "nueva@x.com", "clave": CLAVE}, follow_redirects=True)
    token = re.search(r"/cuenta/correo/([A-Za-z0-9_\-]+)", r.get_data(as_text=True)).group(1)
    with app.app_context():
        assert usuario("laura@x.com") is not None                     # todavía no cambió
    assert nav().get(f"/cuenta/correo/{token}", follow_redirects=True).status_code == 200
    with app.app_context():
        assert usuario("laura@x.com") is None and usuario("nueva@x.com")["nombre"] == "Laura Cliente"
    assert n.get("/cuenta/").status_code in (302, 401)                # se cerraron las sesiones
    assert nav().ingresar("nueva@x.com").status_code == 302
    assert "ya fue usado" in nav().get(f"/cuenta/correo/{token}", follow_redirects=True).get_data(as_text=True) or \
        nav().get(f"/cuenta/correo/{token}").status_code in (302, 400, 404)


def test_correccion_de_dato_verificado_requiere_revision(nav, app):
    n = nav("laura@x.com")
    n.post("/cuenta/solicitudes", {"accion": "correccion", "nombre": "Laura Clienta", "motivo": "Mi apellido está mal escrito."})
    with app.app_context():
        assert usuario("laura@x.com")["nombre"] == "Laura Cliente"   # no cambia sola
        sid = db.uno("SELECT id FROM solicitudes_cuenta")["id"]
    assert nav("op@x.com").post("/equipo/solicitudes", {"id": sid, "decision": "aprobar", "nota": "Verificado"}).status_code == 403
    assert n.post("/equipo/solicitudes", {"id": sid, "decision": "aprobar", "nota": "Verificado"}).status_code in (302, 403)
    c = nav("cum@x.com")
    assert "Laura Clienta" in c.get("/equipo/solicitudes").get_data(as_text=True)
    c.post("/equipo/solicitudes", {"id": sid, "decision": "aprobar", "nota": "Coincide con la cédula."})
    with app.app_context():
        assert usuario("laura@x.com")["nombre"] == "Laura Clienta"
        assert cliente("laura@x.com")["kyc_estado"] == "pendiente"   # nueva verificación
        assert db.uno("SELECT COUNT(*) AS n FROM bitacora WHERE accion LIKE 'cuenta.%'")["n"] >= 2
    assert "Coincide con la cédula" in n.get("/cuenta/solicitudes").get_data(as_text=True)


def test_cierre_de_cuenta_con_revision(nav, app):
    n = nav("pedro@x.com")
    n.post("/cuenta/solicitudes", {"accion": "cierre", "motivo": "Ya no la uso", "clave": "mala"})
    with app.app_context():
        assert db.uno("SELECT COUNT(*) AS n FROM solicitudes_cuenta")["n"] == 0
    n.post("/cuenta/solicitudes", {"accion": "cierre", "motivo": "Ya no la uso", "clave": CLAVE})
    with app.app_context():
        s = db.uno("SELECT * FROM solicitudes_cuenta")
        assert s["tipo"] == "cierre" and usuario("pedro@x.com")["estado_cuenta"] == "cierre_solicitado" and usuario("pedro@x.com")["activo"] == 1
    nav("cum@x.com").post("/equipo/solicitudes", {"id": s["id"], "decision": "aprobar", "nota": "Sin saldo ni pendientes."})
    with app.app_context():
        u = usuario("pedro@x.com")
        assert u["activo"] == 0 and u["estado_cuenta"] == "cerrada"
        assert cliente("pedro@x.com") is not None                     # los registros se conservan
    assert n.get("/cuenta/").status_code in (302, 401)
    assert nav().ingresar("pedro@x.com").status_code != 302


def test_preferencias_se_guardan_en_la_cuenta(nav, app):
    n = nav("laura@x.com")
    n.post("/cuenta/personalizar", {"tema": "claro", "moneda": "PYG", "zona": "Europe/Madrid", "ocultar_saldos": "si"})
    otro = nav("laura@x.com")                                         # otro dispositivo
    h = otro.get("/cuenta/personalizar").get_data(as_text=True)
    assert 'data-tema="claro"' in h
    with app.app_context():
        u = usuario("laura@x.com")
        p = preferencias.leer(u["id"])
        assert p["tema"] == "claro" and p["moneda"] == "PYG" and p["zona"] == "Europe/Madrid" and u["ocultar_saldos"] == 1
    n.post("/cuenta/personalizar", {"tema": "rosa", "moneda": "EUR", "zona": "Marte/Olympus"})
    with app.app_context():
        p = preferencias.leer(usuario("laura@x.com")["id"])
        assert p["tema"] in ("claro", "oscuro") and p["moneda"] in ("USD", "PYG") and p["zona"] in ("", "Europe/Madrid")


def test_actividad_filtra_y_exporta(nav, app):
    n = nav("laura@x.com")
    n.post("/cuenta/datos", {"nombre_publico": "Lau"})
    n.post("/cuenta/personalizar", {"tema": "claro", "moneda": "USD"})
    h = n.get("/cuenta/actividad").get_data(as_text=True)
    assert "Inicios de sesión" in h and "Correcto" in h and "Guardado" in h
    solo = n.get("/cuenta/actividad?cat=sesiones").get_data(as_text=True)
    assert "act-ev cat-sesiones" in solo and "act-ev cat-perfil" not in solo
    assert "act-ev" not in n.get("/cuenta/actividad?desde=2001-01-01&hasta=2001-01-02").get_data(as_text=True)
    assert n.get("/cuenta/actividad?desde=<script>").status_code == 200
    r = n.get("/cuenta/actividad?formato=csv")
    assert r.mimetype == "text/csv" and "fecha;hora;categoria" in r.get_data(as_text=True)
    assert "Lau" not in nav("pedro@x.com").get("/cuenta/actividad").get_data(as_text=True)   # cada uno ve solo lo suyo


def test_envio_por_usuario_y_por_identificador(nav, app):
    from financiera import transferencias as tr
    nav("pedro@x.com").post("/cuenta/datos", {"accion": "usuario", "usuario": "pedrito"})
    with app.app_context():
        yo, el = cliente("laura@x.com"), cliente("pedro@x.com")
        cod = cuenta.codigo(usuario("pedro@x.com")["id"])
        for q in ("@pedrito", "pedrito", "PEDRITO", cod, cod.lower(), "pedro@x.com"):
            d = tr.buscar(q, yo["id"])
            assert d and d["id"] == el["id"], q
        assert tr.buscar("@nadie", yo["id"]) is None and tr.buscar("FC00000019", yo["id"]) is None
    assert 'value="@pedrito"' in nav("laura@x.com").get("/cliente/enviar?a=pedrito").get_data(as_text=True)
