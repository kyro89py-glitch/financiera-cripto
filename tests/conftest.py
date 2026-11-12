from decimal import Decimal

import pytest

from financiera import create_app, cuentas, db, precios

CLAVE = "Prueba-2026!"


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "ENTORNO": "pruebas",
        "SECRET_KEY": "pruebas",
        "DATABASE": str(tmp_path / "prueba.db"),
        "SCRYPT_N": 2 ** 10,
        "EXIGIR_2FA_EQUIPO": False,
        "SESSION_COOKIE_SECURE": False,
        "PRECIO_MAX_MINUTOS": 60,
    })
    with app.app_context():
        for a, p in {"BTC": "70000", "ETH": "2000", "USDT": "1", "SOL": "100", "BNB": "600", "XRP": "1", "LINK": "10"}.items():
            precios.registrar(a, Decimal(p), Decimal("0"), "pruebas")
        for email, nombre, rol in [("admin@x.com", "Ana Admin", "admin"), ("op@x.com", "Oscar Operador", "operador"),
                                   ("op2@x.com", "Olga Operadora", "operador"), ("cum@x.com", "Carla Cumplimiento", "cumplimiento")]:
            cuentas.crear_usuario(email, nombre, rol, CLAVE, debe_cambiar=False)
        cid, _ = cuentas.crear_cliente({"nombre": "Laura Cliente", "documento": "CI 1", "tipo": "persona", "email": "laura@x.com",
                                        "perfil_riesgo": "moderado", "modelo": "equilibrio", "clave": CLAVE})
        cuentas.marcar_kyc(cid, "verificado", "ok", usuario("cum@x.com"))
        cid2, _ = cuentas.crear_cliente({"nombre": "Pedro Pendiente", "documento": "CI 2", "tipo": "persona", "email": "pedro@x.com",
                                         "perfil_riesgo": "moderado", "modelo": "reserva", "clave": CLAVE})
    yield app


def usuario(email):
    return db.uno("SELECT * FROM usuarios WHERE email = ?", (email,))


def cliente(email):
    return db.uno("SELECT c.* FROM clientes c JOIN usuarios u ON u.id = c.usuario_id WHERE u.email = ?", (email,))


@pytest.fixture
def ctx(app):
    with app.app_context():
        yield app


class Navegador:
    def __init__(self, app):
        self.c = app.test_client()

    def token(self):
        with self.c.session_transaction() as s:
            if "csrf" not in s:
                s["csrf"] = "t-" + str(id(self))
            return s["csrf"]

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, data=None, csrf=True, **kw):
        data = dict(data or {})
        if csrf:
            data["csrf"] = self.token()
        return self.c.post(url, data=data, **kw)

    def ingresar(self, email, clave=CLAVE):
        return self.post("/ingresar", {"email": email, "clave": clave})


@pytest.fixture
def nav(app):
    def crear(email=None):
        n = Navegador(app)
        if email:
            r = n.ingresar(email)
            assert r.status_code == 302, r.data
        return n
    return crear
