import time

from financiera import auditoria, db, seguridad

from .conftest import CLAVE, usuario


def test_ingreso_correcto_y_salida(nav):
    n = nav()
    r = n.ingresar("laura@x.com")
    assert r.status_code == 302 and r.headers["Location"].endswith("/cliente/")
    assert n.get("/cliente/").status_code == 200
    n.post("/salir")
    assert n.get("/cliente/").status_code == 302


def test_clave_incorrecta_no_revela_si_existe_el_correo(nav):
    n = nav()
    r1 = n.ingresar("laura@x.com", "otra-clave-1")
    r2 = n.ingresar("nadie@x.com", "otra-clave-1")
    assert r1.status_code == r2.status_code == 200
    assert "El correo o la contraseña no son correctos" in r1.get_data(as_text=True)
    assert "El correo o la contraseña no son correctos" in r2.get_data(as_text=True)


def test_bloqueo_tras_intentos_fallidos(nav, ctx):
    n = nav()
    for _ in range(5):
        n.ingresar("laura@x.com", "mala-clave-9")
    r = n.ingresar("laura@x.com")   # aun con la clave correcta
    assert r.status_code == 200 and "bloqueada" in r.get_data(as_text=True)
    assert usuario("laura@x.com")["bloqueado_hasta"]


def test_post_sin_token_csrf_se_rechaza(nav):
    n = nav("laura@x.com")
    r = n.post("/cliente/retiro", {"monto": "10"}, csrf=False)
    assert r.status_code == 400


def test_cabeceras_de_seguridad(nav):
    r = nav().get("/ingresar")
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_contrasena_temporal_obliga_a_cambiarla(nav, ctx):
    db.ejecutar("UPDATE usuarios SET debe_cambiar_clave = 1 WHERE email = 'laura@x.com'")
    n = nav("laura@x.com")
    r = n.get("/cliente/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/cuenta/clave")
    r = n.post("/cuenta/clave", {"actual": CLAVE, "nueva": "Nueva-clave-2027", "repetir": "Nueva-clave-2027"})
    assert r.status_code == 302
    assert n.get("/cliente/").status_code == 200
    assert not usuario("laura@x.com")["debe_cambiar_clave"]


def test_cambio_de_clave_cierra_otras_sesiones(nav):
    a, b = nav("laura@x.com"), nav("laura@x.com")
    a.post("/cuenta/clave", {"actual": CLAVE, "nueva": "Nueva-clave-2027", "repetir": "Nueva-clave-2027"})
    assert a.get("/cliente/").status_code == 200
    assert b.get("/cliente/").status_code == 302


def test_verificacion_en_dos_pasos(nav, ctx):
    n = nav("op@x.com")
    n.get("/cuenta/seguridad")
    secreto = usuario("op@x.com")["totp_pendiente"]
    codigo = seguridad.totp_codigo(secreto, int(time.time() // 30))
    r = n.post("/cuenta/seguridad", {"accion": "activar", "codigo": codigo})
    assert r.status_code == 302 and usuario("op@x.com")["totp_secreto"] == secreto

    m = nav()
    r = m.ingresar("op@x.com")
    assert r.headers["Location"].endswith("/ingresar/codigo")
    assert m.get("/equipo/").status_code == 302                    # sin código no entra
    r = m.post("/ingresar/codigo", {"codigo": codigo})             # el mismo código no sirve dos veces
    assert r.status_code == 200
    siguiente = seguridad.totp_codigo(secreto, int(time.time() // 30) + 1)
    r = m.post("/ingresar/codigo", {"codigo": siguiente})
    assert r.status_code == 302 and m.get("/equipo/").status_code == 200


def test_equipo_obligado_a_activar_dos_pasos(app, nav):
    app.config["EXIGIR_2FA_EQUIPO"] = True
    n = nav("op@x.com")
    r = n.get("/equipo/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/cuenta/seguridad")
    assert nav("laura@x.com").get("/cliente/").status_code == 200   # a los clientes no se les exige


def test_permisos_por_rol(nav):
    cli = nav("laura@x.com")
    assert cli.get("/equipo/").status_code == 403
    assert cli.get("/admin/precios").status_code == 403
    op = nav("op@x.com")
    assert op.get("/equipo/").status_code == 200
    assert op.get("/equipo/bitacora").status_code == 403
    assert op.get("/admin/usuarios").status_code == 403
    assert op.post("/equipo/clientes/1/kyc", {"estado": "verificado"}).status_code == 403
    assert op.get("/cliente/").status_code == 403
    cum = nav("cum@x.com")
    assert cum.get("/equipo/bitacora").status_code == 200
    assert cum.post("/equipo/clientes/nuevo", {}).status_code == 403


def test_ingreso_queda_en_la_bitacora(nav, ctx):
    nav("laura@x.com")
    acciones = [f["accion"] for f in db.todos("SELECT accion FROM bitacora")]
    assert "ingreso.ok" in acciones
    assert auditoria.verificar()["ok"]
