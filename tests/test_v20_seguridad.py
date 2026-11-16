"""v0.20 · Módulo 1: hallazgos S-03 a S-10 de la auditoría, idempotencia y observabilidad. Cada prueba falla sin su corrección."""
import os
import re

import pytest
from cryptography.fernet import Fernet

from financiera import antilavado, cifrado, create_app, db, documentos, limites, observabilidad, operaciones, respaldos, seguridad
from financiera import transferencias as tr

from .conftest import CLAVE, cliente, usuario
from .test_ejecucion import _aporte, bx  # noqa: F401  (fixture del Binance imitado)


def _saldo(n, email="laura@x.com", monto=500000):
    """Deja saldo en dólares a un cliente con un aporte aprobado."""
    cli = cliente(email)
    opid = operaciones.solicitar_aporte(cli, monto, None, "T-saldo", None)
    operaciones.aprobar(opid, usuario("op@x.com"))
    return cli


# ---------- S-03: límites de tasa ----------
def test_s03_busqueda_de_destinatarios_tiene_limite(nav, ctx):
    n = nav("laura@x.com")
    for i in range(20):
        assert n.get(f"/cliente/enviar/destinatario?q=nadie{i}@x.com").status_code == 200
    r = n.get("/cliente/enviar/destinatario?q=pedro@x.com")
    assert r.status_code == 429 and r.get_json()["ok"] is False and r.headers.get("Retry-After")


def test_s03_ingreso_limitado_por_ip_y_por_correo(nav, ctx):
    n = nav()
    for _ in range(10):
        assert n.post("/ingresar", {"email": "laura@x.com", "clave": "mala-clave-1"}).status_code == 200
    # El undécimo intento contra el mismo correo se corta antes de verificar la contraseña, aunque sea la correcta.
    assert n.post("/ingresar", {"email": "laura@x.com", "clave": CLAVE}).status_code == 429
    for i in range(10):
        n.post("/ingresar", {"email": f"otro{i}@x.com", "clave": "x"})
    assert n.post("/ingresar", {"email": "pedro@x.com", "clave": CLAVE}).status_code == 429  # 20 por IP


def test_s03_consultas_de_mercado_limitadas_en_memoria(nav, ctx, monkeypatch):
    monkeypatch.setattr(limites, "API_POR_MINUTO", 5)
    n = nav("laura@x.com")
    codigos = [n.get("/mercado/precios.json").status_code for _ in range(7)]
    assert codigos[:5] == [200] * 5 and codigos[-1] == 429


# ---------- S-04: cifrado en reposo ----------
def test_s04_documentos_cifrados_en_disco_y_legibles_al_descargar(nav, ctx):
    d = db.uno("SELECT * FROM documentos ORDER BY id LIMIT 1")
    with open(documentos.ruta(d), "rb") as f:
        crudo = f.read()
    assert crudo.startswith(cifrado.MAGIA) and b"%PDF" not in crudo
    r = nav("op@x.com").get(f"/documentos/{d['id']}")
    assert r.status_code == 200 and r.data.startswith(b"%PDF")


def test_s04_migrar_y_rotar_claves(ctx):
    k1, k2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    ctx.config["CLAVE_CIFRADO"] = k1
    uid = usuario("op@x.com")["id"]
    db.ejecutar("UPDATE usuarios SET totp_secreto = 'JBSWY3DPEHPK3PXP' WHERE id = ?", (uid,))  # dato viejo en claro
    d = db.uno("SELECT * FROM documentos ORDER BY id LIMIT 1")
    with open(documentos.ruta(d), "wb") as f:
        f.write(b"%PDF-1.4 viejo en claro")
    cifrado._recifrar(rotar=False)
    assert cifrado.esta_cifrado(usuario("op@x.com")["totp_secreto"])
    assert documentos.leer(d) == b"%PDF-1.4 viejo en claro"
    ctx.config["CLAVE_CIFRADO"] = f"{k2},{k1}"
    cifrado._recifrar(rotar=True)
    ctx.config["CLAVE_CIFRADO"] = k2  # la clave vieja ya no hace falta
    assert cifrado.descifrar_texto(usuario("op@x.com")["totp_secreto"]) == "JBSWY3DPEHPK3PXP"
    assert documentos.leer(d) == b"%PDF-1.4 viejo en claro"
    ctx.config["CLAVE_CIFRADO"] = k1
    with pytest.raises(cifrado.ErrorCifrado):
        documentos.leer(d)


# ---------- S-05: respaldos cifrados con prueba de restauración ----------
def test_s05_respaldo_cifrado_verificado_y_restaurable(ctx, tmp_path):
    _saldo(1)
    ruta = respaldos.crear(str(tmp_path / "resp"))
    with open(ruta, "rb") as f:
        crudo = f.read()
    assert crudo.startswith(cifrado.MAGIA) and b"SQLite format" not in crudo
    r = respaldos.probar(ruta)
    assert r["ok"], r["controles"]
    assert {c["control"] for c in r["controles"]} >= {"integridad de SQLite", "cadena de la bitácora", "saldos del libro", "documentos"}
    assert db.uno("SELECT prueba_ok FROM respaldos ORDER BY id DESC LIMIT 1")["prueba_ok"] == 1
    destino = str(tmp_path / "restaurada" / "base.db")
    respaldos.restaurar(ruta, destino)
    assert os.path.exists(destino)
    with pytest.raises(respaldos.ErrorRespaldo):
        respaldos.restaurar(ruta, destino)  # nunca pisa una base existente
    # Un respaldo alterado no pasa la prueba.
    with open(ruta, "r+b") as f:
        f.seek(len(crudo) // 2)
        f.write(b"XXXX")
    assert respaldos.probar(ruta)["ok"] is False


def test_s05_rotacion_conserva_los_ultimos(ctx, tmp_path):
    ctx.config["RESPALDOS_CONSERVAR"] = 2
    carpeta = str(tmp_path / "rot")
    os.makedirs(carpeta)
    for i in range(3):
        open(os.path.join(carpeta, f"respaldo-2026010{i}-000000.fcbak"), "wb").close()
    respaldos._rotar(carpeta)
    assert sorted(os.listdir(carpeta)) == ["respaldo-20260101-000000.fcbak", "respaldo-20260102-000000.fcbak"]


# ---------- S-06: antilavado ----------
def test_s06_monto_alto_y_fraccionamiento(ctx):
    laura = cliente("laura@x.com")
    operaciones.solicitar_aporte(laura, 1_000_000, None, "T-alto", None)  # US$ 10.000 = umbral
    assert db.uno("SELECT * FROM alertas_aml WHERE regla = 'monto_alto'")
    pedro = cliente("pedro@x.com")
    for i in range(3):
        operaciones.solicitar_aporte(pedro, 400_000, None, f"T-{i}", None)
    a = db.uno("SELECT * FROM alertas_aml WHERE regla = 'fraccionamiento' AND cliente_id = ?", (pedro["id"],))
    assert a and "3 depósitos" in a["detalle"]
    antilavado.evaluar(pedro["id"])  # volver a evaluar no duplica
    assert db.uno("SELECT COUNT(*) AS n FROM alertas_aml WHERE cliente_id = ?", (pedro["id"],))["n"] == 1


def test_s06_lista_de_sanciones_bloquea_hasta_que_cumplimiento_resuelve(ctx, tmp_path):
    cli = _saldo(1)
    lista = tmp_path / "onu.csv"
    lista.write_text("nombre,documento,pais,referencia\nCLIENTE Laura,,PY,QDi.999\nOtra Persona,X99,XX,QDi.1\n", encoding="utf-8")
    assert antilavado.importar_lista(str(lista), "ONU") == 2
    assert antilavado.revisar_todos() >= 1
    alerta = db.uno("SELECT * FROM alertas_aml WHERE regla = 'sancion'")
    assert alerta["nivel"] == "critica" and alerta["cliente_id"] == cli["id"]
    assert db.uno("SELECT riesgo_aml FROM clientes WHERE id = ?", (cli["id"],))["riesgo_aml"] == "alto"
    with pytest.raises(operaciones.ErrorNegocio, match="revisión de cumplimiento"):
        operaciones.operar(cli, "BTC", "compra", 10000, usuario("laura@x.com"))
    opid = operaciones.solicitar_retiro(cli, 10000, usuario("laura@x.com"))
    with pytest.raises(operaciones.ErrorNegocio, match="lista de sanciones"):
        operaciones.aprobar(opid, usuario("op@x.com"))
    with pytest.raises(ValueError):
        antilavado.resolver(alerta["id"], "descartada", "", usuario("cum@x.com"))  # sin justificación no se puede
    antilavado.resolver(alerta["id"], "descartada", "Homónimo: fecha de nacimiento y documento distintos.", usuario("cum@x.com"))
    assert operaciones.aprobar(opid, usuario("op@x.com")) in ("liquidada", "primera_firma")
    assert db.uno("SELECT 1 FROM bitacora WHERE accion = 'aml.descartada'")


def test_s06_pantalla_de_antilavado_por_roles(nav, ctx):
    assert nav("cum@x.com").get("/equipo/antilavado").status_code == 200
    assert nav("op@x.com").get("/equipo/antilavado").status_code == 403
    r = nav("cum@x.com").post(f"/equipo/clientes/{cliente('pedro@x.com')['id']}/diligencia",
                              {"pep": "si", "pep_cargo": "Concejal", "nacionalidad": "Paraguaya", "domicilio_fiscal": "Asunción"})
    assert r.status_code == 302
    assert db.uno("SELECT * FROM alertas_aml WHERE regla = 'pep'")
    assert db.uno("SELECT nacionalidad FROM clientes WHERE id = ?", (cliente("pedro@x.com")["id"],))["nacionalidad"] == "Paraguaya"


# ---------- S-07: recuperación de contraseña ----------
def _enlace(n, email):
    r = n.post("/recuperar", {"email": email})
    m = re.search(rb'href="(http://localhost/recuperar/[^"]+)"', r.data)
    return r, (m.group(1).decode().replace("http://localhost", "") if m else None)


def test_s07_recuperar_contrasena_con_enlace_de_un_solo_uso(nav, ctx):
    n = nav()
    r, ruta = _enlace(n, "laura@x.com")
    assert r.status_code == 200 and ruta
    r2, nada = _enlace(n, "noexiste@x.com")
    assert nada is None and "Si el correo corresponde".encode() in r2.data  # misma respuesta: no revela quién es cliente
    assert n.post(ruta, {"nueva": "Nueva-clave-2027", "repetir": "Nueva-clave-2027"}).status_code == 302
    assert n.post(ruta, {"nueva": "Otra-clave-2028", "repetir": "Otra-clave-2028"}).status_code == 410  # un solo uso
    assert nav().ingresar("laura@x.com", "Nueva-clave-2027").status_code == 302
    assert nav().ingresar("laura@x.com", CLAVE).status_code == 200
    assert db.uno("SELECT 1 FROM bitacora WHERE accion = 'clave.recuperada'")


def test_s07_enlace_vencido_y_dos_pasos_obligatorio(nav, ctx):
    n = nav()
    _, ruta = _enlace(n, "laura@x.com")
    db.ejecutar("UPDATE recuperaciones SET vence = '2000-01-01T00:00:00Z'")
    assert n.get(ruta).status_code == 410
    from financiera import seguridad as seg
    db.ejecutar("UPDATE usuarios SET totp_secreto = ? WHERE email = 'laura@x.com'", (cifrado.cifrar_texto("JBSWY3DPEHPK3PXP"),))
    _, ruta = _enlace(nav(), "laura@x.com")
    r = n.post(ruta, {"nueva": "Nueva-clave-2027", "repetir": "Nueva-clave-2027", "codigo": "000000"})
    assert r.status_code == 200 and "código".encode() in r.data
    import time
    codigo = seg.totp_codigo("JBSWY3DPEHPK3PXP", int(time.time() // 30))
    assert n.post(ruta, {"nueva": "Nueva-clave-2027", "repetir": "Nueva-clave-2027", "codigo": codigo}).status_code == 302


# ---------- S-08: costo de las contraseñas ----------
def test_s08_contrasenas_viejas_se_refuerzan_al_ingresar(nav, ctx):
    ctx.config["SCRYPT_P"] = 1
    viejo = seguridad.hash_clave(CLAVE)
    db.ejecutar("UPDATE usuarios SET clave_hash = ? WHERE email = 'laura@x.com'", (viejo,))
    ctx.config["SCRYPT_P"] = 3
    assert seguridad.necesita_rehash(viejo)
    assert nav().ingresar("laura@x.com").status_code == 302
    nuevo = usuario("laura@x.com")["clave_hash"]
    assert nuevo != viejo and nuevo.split("$")[3] == "3" and not seguridad.necesita_rehash(nuevo)
    app = create_app({"ENTORNO": "pruebas", "SECRET_KEY": "x", "DATABASE": ctx.config["DATABASE"]})
    assert app.config["SCRYPT_N"] * app.config["SCRYPT_P"] >= 2 ** 15 * 3


# ---------- S-09: secretos ----------
def test_s09_secretos_desde_archivo_y_controles_de_produccion(tmp_path, monkeypatch):
    clave = tmp_path / "secret_key"
    clave.write_text("s" * 48 + "\n")
    cc = tmp_path / "cifrado"
    cc.write_text(Fernet.generate_key().decode())
    monkeypatch.setenv("SECRET_KEY_FILE", str(clave))
    monkeypatch.setenv("CLAVE_CIFRADO_FILE", str(cc))
    monkeypatch.setenv("FINANCIERA_ENTORNO", "produccion")
    app = create_app({"DATABASE": str(tmp_path / "p.db")})
    assert app.config["SECRET_KEY"] == "s" * 48 and app.config["CLAVE_CIFRADO"]
    clave.write_text("corta")
    with pytest.raises(RuntimeError, match="demasiado corta"):
        create_app({"DATABASE": str(tmp_path / "p2.db")})
    clave.write_text("s" * 48)
    monkeypatch.delenv("CLAVE_CIFRADO_FILE")
    with pytest.raises(RuntimeError, match="CLAVE_CIFRADO"):
        create_app({"DATABASE": str(tmp_path / "p3.db")})


# ---------- idempotencia ----------
def test_formulario_reenviado_no_duplica_la_operacion(nav, ctx):
    _saldo(1)
    n = nav("laura@x.com")
    datos = {"de": "USD", "a": "BTC", "monto": "100", "idem": "clave-idem-prueba-001"}
    antes = db.uno("SELECT COUNT(*) AS n FROM operaciones")["n"]
    assert n.post("/cliente/convertir", datos).status_code == 302
    r = n.post("/cliente/convertir", datos)  # doble clic o reenvío del navegador
    assert r.status_code == 302
    assert db.uno("SELECT COUNT(*) AS n FROM operaciones")["n"] == antes + 1
    # Un formulario con error libera la clave para poder corregir y reenviar.
    malo = {"de": "USD", "a": "BTC", "monto": "999999", "idem": "clave-idem-prueba-002"}
    n.post("/cliente/convertir", malo)
    assert not db.uno("SELECT 1 FROM idempotencia WHERE clave = 'clave-idem-prueba-002'")


# ---------- S-10 y observabilidad ----------
def test_precios_responden_304_si_no_cambiaron(nav, ctx):
    n = nav("laura@x.com")
    r = n.get("/mercado/precios.json")
    etag = r.headers["ETag"]
    assert "no-store" not in r.headers["Cache-Control"]
    assert n.get("/mercado/precios.json", headers={"If-None-Match": etag}).status_code == 304
    from decimal import Decimal

    from financiera import precios
    precios.registrar("BTC", Decimal("71000"), Decimal("1"), "pruebas", ts="2099-01-01T00:00:00Z")
    assert n.get("/mercado/precios.json", headers={"If-None-Match": etag}).status_code == 200


def test_salud_metricas_e_identificador_de_solicitud(ctx):
    web = ctx.test_client()
    r = web.get("/salud")
    assert r.status_code == 200 and r.get_json()["estado"] in ("ok", "degradado") and r.get_json()["base"] == "ok"
    assert re.fullmatch(r"[0-9a-f]{16}", r.headers["X-Request-ID"])
    assert web.get("/salud", headers={"X-Request-ID": "mi-id-12345"}).headers["X-Request-ID"] == "mi-id-12345"
    assert web.get("/metricas").status_code == 404
    ctx.config["METRICAS_TOKEN"] = "tok-123"
    assert web.get("/metricas", headers={"Authorization": "Bearer otro"}).status_code == 404
    m = web.get("/metricas", headers={"Authorization": "Bearer tok-123"})
    assert m.status_code == 200 and b"fc_solicitudes_total" in m.data and b"fc_salud" in m.data


def test_recuperar_ejecuciones_a_medias(bx):  # noqa: F811
    bx.fallas["BTCUSDT"] = ["error_500"]
    opid, r = _aporte()
    assert r == "incompleta"
    assert observabilidad.recuperar(antiguedad_seg=0) == [(opid, "liquidada")]
    assert db.uno("SELECT estado FROM operaciones WHERE id = ?", (opid,))["estado"] == "liquidada"


def test_envio_bloqueado_por_sancion(ctx, tmp_path):
    cli = _saldo(1)
    lista = tmp_path / "l.csv"
    lista.write_text("nombre,documento\nX,CI1\n", encoding="utf-8")
    antilavado.importar_lista(str(lista), "OFAC")
    antilavado.evaluar(cli["id"])
    with pytest.raises(tr.ErrorEnvio, match="revisión de cumplimiento"):
        tr.enviar(cli, "pedro@x.com", "USD", 1000, usuario("laura@x.com"), CLAVE)
