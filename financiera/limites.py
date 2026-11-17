"""Límites de tasa (hallazgo S-03) e idempotencia de formularios.

Las reglas sensibles (ingreso, registro, búsqueda de destinatarios, recuperación de contraseña, descargas de datos)
se cuentan en la base, así valen aunque haya varios procesos. Las consultas de precios, que son muchas y baratas,
se limitan en memoria por proceso para no escribir en la base en cada pedido.
"""
import hashlib
import secrets
import threading
import time
from contextlib import contextmanager

from flask import abort, current_app, g, request

from . import db
from .tiempo import ahora

# regla: (máximo de intentos, ventana en segundos)
REGLAS = {
    "ingreso_ip": (20, 600),
    "ingreso_email": (10, 600),
    "registro_ip": (20, 3600),
    "destinatario": (20, 600),
    "destinatario_ip": (60, 600),
    "recuperar_ip": (5, 3600),
    "recuperar_email": (3, 3600),
    "datos": (15, 3600),
    "consulta": (30, 600),
    "usuario_disp": (60, 600),
    "foto": (12, 3600),
    "correo": (5, 3600),
}
API_POR_MINUTO = 240


class Excedido(Exception):
    def __init__(self, espera):
        super().__init__(espera)
        self.espera = max(1, int(espera))


def _clave(texto):
    secreto = current_app.config["SECRET_KEY"]
    return hashlib.sha256(f"{secreto}|{texto}".encode()).hexdigest()[:32]


def ip():
    return request.remote_addr or "sin-ip"


def contar(regla, quien, registrar=True):
    """Suma un intento. Si se pasó del máximo lanza Excedido con los segundos que faltan."""
    maximo, ventana = REGLAS[regla]
    if current_app.config.get("LIMITES_DESACTIVADOS"):
        return
    clave, t = _clave(quien), time.time()
    with db.transaccion() as c:
        filas = c.execute("SELECT ts FROM limites WHERE regla = ? AND clave = ? AND ts > ? ORDER BY ts",
                          (regla, clave, t - ventana)).fetchall()
        if len(filas) >= maximo:
            raise Excedido(filas[0]["ts"] + ventana - t)
        if registrar:
            c.execute("INSERT INTO limites (regla, clave, ts) VALUES (?, ?, ?)", (regla, clave, t))
        if secrets.randbelow(50) == 0:
            c.execute("DELETE FROM limites WHERE ts < ?", (t - 86400,))


def limpiar(regla, quien):
    """Olvida los intentos de una regla (por ejemplo, al ingresar bien)."""
    db.ejecutar("DELETE FROM limites WHERE regla = ? AND clave = ?", (regla, _clave(quien)))


def exigir(*pares):
    """Cuenta cada (regla, quién) y corta la solicitud con 429 si alguna se excede."""
    try:
        for regla, quien in pares:
            contar(regla, quien)
    except Excedido as e:
        g.reintentar = e.espera
        abort(429)


# ---------- consultas de mercado: ventana fija por minuto en memoria ----------
_api_lock = threading.Lock()


def api():
    if current_app.config.get("LIMITES_DESACTIVADOS"):
        return
    minuto, quien = int(time.time() // 60), ip()
    _api = current_app.extensions.setdefault("limite_api", {})
    with _api_lock:
        if len(_api) > 20000:
            _api.clear()
        k = (quien, minuto)
        _api[k] = _api.get(k, 0) + 1
        n = _api[k]
    if n > API_POR_MINUTO:
        g.reintentar = 60 - int(time.time() % 60)
        abort(429)


# ---------- idempotencia ----------
def nueva_clave():
    return secrets.token_urlsafe(18)


@contextmanager
def una_vez(ruta):
    """Envuelve el proceso de un formulario que mueve dinero.

    Si el formulario trae `idem` y esa clave ya se usó, entrega el resultado anterior (una dirección) en lugar de
    procesarlo de nuevo. Si el proceso falla, la clave se libera para que la persona pueda corregir y reenviar.
    """
    clave = (request.form.get("idem") or "").strip()[:64]
    estado = {"repetida": None, "resultado": None}
    if not clave or not g.get("usuario"):
        yield estado
        return
    with db.transaccion() as c:
        previa = c.execute("SELECT * FROM idempotencia WHERE clave = ?", (clave,)).fetchone()
        if previa is None:
            c.execute("INSERT INTO idempotencia (clave, usuario_id, ruta, creada) VALUES (?, ?, ?, ?)",
                      (clave, g.usuario["id"], ruta, ahora()))
    if previa is not None:
        estado["repetida"] = previa["resultado"] or ""
        yield estado
        return
    try:
        yield estado
    except BaseException:
        db.ejecutar("DELETE FROM idempotencia WHERE clave = ? AND resultado IS NULL", (clave,))
        raise
    if estado["resultado"]:
        db.ejecutar("UPDATE idempotencia SET resultado = ? WHERE clave = ?", (estado["resultado"], clave))
    else:
        db.ejecutar("DELETE FROM idempotencia WHERE clave = ? AND resultado IS NULL", (clave,))


def idempotente(ruta, aviso="Esa solicitud ya se había enviado: no la repetimos."):
    """Decorador para rutas POST que mueven dinero. Se considera procesada si redirige con un mensaje 'ok' o 'warn';
    si terminó en error, la clave se libera para que la persona corrija y vuelva a enviar."""
    import functools

    from flask import flash, redirect, session

    def deco(f):
        @functools.wraps(f)
        def envoltura(*args, **kwargs):
            if request.method != "POST":
                return f(*args, **kwargs)
            with una_vez(ruta) as estado:
                if estado["repetida"] is not None:
                    flash(aviso, "info")
                    return redirect(estado["repetida"] or request.path)
                resp = f(*args, **kwargs)
                avisos = session.get("_flashes") or []
                if getattr(resp, "status_code", 200) in (302, 303) and avisos and avisos[-1][0] in ("ok", "warn"):
                    estado["resultado"] = resp.headers.get("Location")
                return resp
        return envoltura
    return deco
