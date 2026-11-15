"""Envíos entre clientes, apertura de cuenta en línea, resultado por moneda y app instalable."""
from datetime import timedelta

import pytest

from financiera import auditoria, cartera, cuentas, db, notificaciones, operaciones, seguridad, transferencias
from financiera.tiempo import ahora_dt, iso

from .conftest import CLAVE, cliente, legajo_completo, usuario


class _Web:
    """Cliente web anónimo que manda el token CSRF de su sesión, como hace el navegador."""

    def __init__(self):
        from flask import current_app
        self.c = current_app.test_client()
        self.c.get("/abrir-cuenta")
        with self.c.session_transaction() as ses:
            self.tok = ses["csrf"]

    def get(self, *a, **k):
        return self.c.get(*a, **k)

    def post(self, url, data, **k):
        return self.c.post(url, data=dict(data, csrf=self.tok), **k)


def _verificar_pedro():
    legajo_completo(cliente("pedro@x.com")["id"])
    cuentas.marcar_kyc(cliente("pedro@x.com")["id"], "verificado", "", usuario("cum@x.com"))


def _saldo(monto=100000):
    laura = cliente("laura@x.com")
    operaciones.aprobar(operaciones.solicitar_aporte(laura, monto, "saldo", "T", None), usuario("op@x.com"))
    return laura, usuario("laura@x.com")


def test_envio_de_dolares_y_de_monedas(ctx):
    laura, u = _saldo()
    with pytest.raises(transferencias.ErrorEnvio, match="contraseña"):
        transferencias.enviar(laura, "pedro@x.com", "USD", 1000, u, "mala")
    with pytest.raises(transferencias.ErrorEnvio, match="no tiene la identidad"):
        transferencias.enviar(laura, "pedro@x.com", "USD", 1000, u, CLAVE)
    _verificar_pedro()
    with pytest.raises(transferencias.ErrorEnvio, match="No encontramos"):
        transferencias.enviar(laura, "laura@x.com", "USD", 1000, u, CLAVE)        # a sí misma
    with pytest.raises(transferencias.ErrorEnvio, match="mínimo"):
        transferencias.enviar(laura, "pedro@x.com", "USD", 50, u, CLAVE)
    pedro = cliente("pedro@x.com")
    antes = notificaciones.no_leidas(pedro["usuario_id"])
    tid = transferencias.enviar(laura, "PEDRO@x.com", "USD", 12345, u, CLAVE, nota="almuerzo")
    assert cartera.tenencias(laura["id"]) == {"USD": 100000 - 12345} and cartera.tenencias(pedro["id"]) == {"USD": 12345}
    assert notificaciones.no_leidas(pedro["usuario_id"]) == antes + 1
    assert "Laura" in notificaciones.listar(pedro["usuario_id"])[0]["texto"]
    assert db.uno("SELECT COUNT(*) AS n FROM libro WHERE transferencia_id = ?", (tid,))["n"] == 2
    # por número de documento, enviando monedas
    operaciones.operar(laura, "BTC", "compra", 35000, u)
    with pytest.raises(transferencias.ErrorEnvio, match="No encontramos"):
        transferencias.enviar(laura, "2", "BTC", 7000, u, CLAVE)                       # documento demasiado corto
    transferencias.enviar(laura, "pedro@x.com", "BTC", 7000, u, CLAVE)
    assert cartera.tenencias(pedro["id"])["BTC"] == 100000                            # US$ 70 a 70.000 = 0,001 BTC
    with pytest.raises(Exception):
        db.ejecutar("UPDATE transferencias SET valor_cent = 1")
    assert auditoria.verificar()["ok"]


def test_envio_por_documento_limite_diario_y_dos_pasos(ctx):
    laura, u = _saldo(900000)
    _verificar_pedro()
    db.ejecutar("UPDATE clientes SET documento = 'CI 4.567.890' WHERE id = ?", (cliente("pedro@x.com")["id"],))
    assert transferencias.buscar("4567890")["id"] == cliente("pedro@x.com")["id"]
    assert transferencias.buscar("456") is None
    ctx.config["ENVIO_MAX_DIA_USD"] = 1000
    transferencias.enviar(laura, "4.567.890", "USD", 60000, u, CLAVE)
    with pytest.raises(transferencias.ErrorEnvio, match="límite diario"):
        transferencias.enviar(laura, "4.567.890", "USD", 50000, u, CLAVE)
    # con dos pasos activo, el código es obligatorio y no se puede reutilizar
    secreto = seguridad.totp_secreto()
    db.ejecutar("UPDATE usuarios SET totp_secreto = ? WHERE id = ?", (secreto, u["id"]))
    with pytest.raises(transferencias.ErrorEnvio, match="código"):
        transferencias.enviar(laura, "4.567.890", "USD", 1000, u, CLAVE, codigo="000000")
    import time
    cod = seguridad.totp_codigo(secreto, int(time.time() // 30))
    transferencias.enviar(laura, "4.567.890", "USD", 1000, u, CLAVE, codigo=cod)
    with pytest.raises(transferencias.ErrorEnvio, match="código"):
        transferencias.enviar(laura, "4.567.890", "USD", 1000, u, CLAVE, codigo=cod)
    assert transferencias.ocultar("Laura Giménez Benítez Ruiz") == "Laura G. B."


def test_envios_cuentan_en_aportado_rendimiento_y_estado_de_cuenta(nav, ctx):
    laura, u = _saldo()
    _verificar_pedro()
    transferencias.enviar(laura, "pedro@x.com", "USD", 30000, u, CLAVE)
    pedro = cliente("pedro@x.com")
    assert cartera.aportado_neto(laura["id"]) == 70000 and cartera.aportado_neto(pedro["id"]) == 30000
    assert abs(cartera.rendimiento(laura["id"])["twr"]) < 0.01 and abs(cartera.rendimiento(pedro["id"])["twr"]) < 0.01
    periodo = cartera.periodos_cliente(laura)[0]
    ec = cartera.estado_cuenta(laura, periodo)
    assert ec["enviado"] == 30000 and ec["mercado"] == 0 and len(ec["transferencias"]) == 1
    n = nav("laura@x.com")
    assert "Envío a Pedro".encode() in n.get(f"/cliente/estado-de-cuenta/{periodo}").data
    # pantallas
    assert n.get("/cliente/enviar").status_code == 200
    assert n.get("/cliente/enviar/destinatario?q=pedro@x.com").get_json() == {"ok": True, "texto": "Vas a enviar a Pedro P."}
    assert n.get("/cliente/enviar/destinatario?q=nadie@x.com").get_json()["ok"] is False
    r = n.post("/cliente/enviar", {"destino": "pedro@x.com", "activo": "USD", "monto": "10", "clave": CLAVE})
    assert r.status_code == 302 and cartera.tenencias(pedro["id"])["USD"] == 31000
    r = n.post("/cliente/enviar", {"destino": "pedro@x.com", "activo": "USD", "monto": "10", "clave": "mala"})
    assert r.status_code == 200 and "contraseña no es correcta".encode() in r.data and b'value="mala"' not in r.data
    assert nav("op@x.com").get(f"/equipo/clientes/{laura['id']}").status_code == 200
    assert b"Recibiste de" in nav("pedro@x.com").get("/cliente/movimientos").data
    csv_ = nav("pedro@x.com").get("/cliente/estado-de-cuenta.csv").data.decode("utf-8-sig")
    assert "Recibido de otro cliente" in csv_ and ";E1;" in csv_


def test_resultado_por_moneda(ctx):
    laura, u = _saldo()
    operaciones.operar(laura, "BTC", "compra", 70000, u)                  # 0,01 BTC a 70.000
    from decimal import Decimal
    from financiera import precios
    precios.actualizar_manual("BTC", Decimal("80000"), usuario("admin@x.com"))
    operaciones.operar(laura, "BTC", "venta", 40000, u)                   # vende la mitad a 80.000
    k = cartera.costos(laura["id"])["BTC"]
    assert k["cantidad"] == 500000 and k["costo"] == 35000 and k["realizado"] == 5000


def test_apertura_de_cuenta_en_linea(nav, ctx):
    web = _Web()
    assert web.get("/abrir-cuenta").status_code == 200
    datos = {"tipo": "persona", "nombre": "Nora Núñez", "documento": "CI 7.000.001", "email": "nora@x.com", "telefono": "0981",
             "clave": CLAVE, "clave2": CLAVE, "acepto": "si", "plazo": "3", "caida": "3", "experiencia": "3", "parte": "3"}
    r = web.post("/abrir-cuenta", dict(datos, clave2="otra"))
    assert r.status_code == 200 and "no coinciden".encode() in r.data and CLAVE.encode() not in r.data
    r = web.post("/abrir-cuenta", dict(datos, caida=""))
    assert "Responde todas".encode() in r.data
    r = web.post("/abrir-cuenta", dict(datos, web="soy-un-robot"))
    assert r.status_code == 200 and not db.uno("SELECT 1 FROM usuarios WHERE email = 'nora@x.com'")
    r = web.post("/abrir-cuenta", datos)
    assert r.status_code == 302 and r.headers["Location"].endswith("/ingresar")
    nora = db.uno("SELECT c.*, u.terminos_version, u.debe_cambiar_clave FROM clientes c JOIN usuarios u ON u.id = c.usuario_id"
                  " WHERE u.email = 'nora@x.com'")
    assert (nora["perfil_riesgo"], nora["modelo"], nora["origen"], nora["kyc_estado"]) == ("arriesgado", "impulso", "web", "pendiente")
    assert nora["terminos_version"] == seguridad.TERMINOS_VERSION and nora["debe_cambiar_clave"] == 0
    assert db.uno("SELECT 1 FROM bitacora WHERE accion = 'cliente.registro_web'")
    assert "Nueva cuenta abierta en línea" in notificaciones.listar(usuario("cum@x.com")["id"])[0]["texto"]
    assert web.post("/abrir-cuenta", dict(datos, email="otra@x.com")).status_code == 200      # documento repetido
    assert cuentas.perfil_de({"plazo": "1", "caida": "1", "experiencia": "1", "parte": "1"}) == "conservador"
    assert cuentas.perfil_de({"plazo": "2", "caida": "2", "experiencia": "2", "parte": "2"}) == "moderado"
    # el cliente nuevo entra directo, sin cambio de clave ni condiciones pendientes, pero no puede operar
    n = nav("nora@x.com")
    assert n.get("/cliente/").status_code == 200
    with pytest.raises(operaciones.ErrorNegocio, match="verificar tu identidad"):
        operaciones.operar(cliente("nora@x.com"), "BTC", "compra", 1000, usuario("nora@x.com"))
    assert web.get("/condiciones").status_code == 200


def test_limite_de_registros_por_conexion(ctx):
    datos = {"tipo": "persona", "nombre": "A B", "documento": "CI 9{}", "email": "a{}@x.com", "clave": "Segura-2026x",
             "clave2": "Segura-2026x", "acepto": "si", "plazo": "1", "caida": "1", "experiencia": "1", "parte": "1"}
    web = _Web()
    for i in range(5):
        d = {k: (v.format(i) if "{}" in v else v) for k, v in datos.items()}
        assert web.post("/abrir-cuenta", d, environ_base={"REMOTE_ADDR": "10.0.0.7"}).status_code == 302
    d = {k: (v.format(9) if "{}" in v else v) for k, v in datos.items()}
    r = web.post("/abrir-cuenta", d, environ_base={"REMOTE_ADDR": "10.0.0.7"})
    assert r.status_code == 200 and "demasiadas cuentas".encode() in r.data
    assert web.post("/abrir-cuenta", d, environ_base={"REMOTE_ADDR": "10.0.0.8"}).status_code == 302


def test_app_instalable(ctx):
    from flask import current_app
    web = current_app.test_client()
    r = web.get("/sw.js")
    assert r.status_code == 200 and r.headers["Service-Worker-Allowed"] == "/" and b"sin-conexion" in r.data
    assert web.get("/sin-conexion").status_code == 200
    m = web.get("/static/manifest.webmanifest")
    assert m.status_code == 200 and b'"display": "standalone"' in m.data
    assert b'rel="manifest"' in web.get("/").data
    assert web.get("/static/img/icono-512.png").status_code == 200
