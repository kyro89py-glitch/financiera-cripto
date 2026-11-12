"""Contraseñas, sesiones, protección CSRF, verificación en dos pasos y permisos por rol."""
import base64
import functools
import hashlib
import hmac
import os
import secrets
import struct
import time
from urllib.parse import quote

from flask import abort, current_app, g, redirect, request, session, url_for

from . import db

ROLES_EQUIPO = ("operador", "cumplimiento", "admin")

PERMISOS = {
    "equipo.ver": {"operador", "cumplimiento", "admin"},
    "operaciones.aprobar": {"operador", "cumplimiento", "admin"},
    "clientes.crear": {"operador", "admin"},
    "clientes.clave": {"operador", "admin"},
    "clientes.kyc": {"cumplimiento", "admin"},
    "clientes.origen": {"cumplimiento", "admin"},
    "cumplimiento.ver": {"cumplimiento", "admin"},
    "reportes.exportar": {"cumplimiento", "admin"},
    "precios.editar": {"admin"},
    "usuarios.gestionar": {"admin"},
}

# Rutas a las que se puede entrar aunque el usuario tenga un paso obligatorio pendiente.
SIN_FORZAR = {"auth.clave", "auth.seguridad", "auth.salir", "static"}


# ---------- contraseñas ----------
def hash_clave(clave):
    n, r, p = current_app.config["SCRYPT_N"], 8, 1
    sal = os.urandom(16)
    h = hashlib.scrypt(clave.encode("utf-8"), salt=sal, n=n, r=r, p=p, dklen=32, maxmem=64 * 1024 * 1024)
    return f"scrypt${n}${r}${p}${sal.hex()}${h.hex()}"


def verificar_clave(guardado, clave):
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calc = hashlib.scrypt(clave.encode("utf-8"), salt=bytes.fromhex(sal), n=int(n), r=int(r), p=int(p),
                              dklen=len(h) // 2, maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc.hex(), h)


_FICTICIO = {}


def hash_ficticio():
    """Hash de relleno para que un correo inexistente tarde lo mismo que uno real."""
    n = current_app.config["SCRYPT_N"]
    if n not in _FICTICIO:
        _FICTICIO[n] = hash_clave(secrets.token_hex(8))
    return _FICTICIO[n]


def validar_clave_nueva(clave, email=None):
    if len(clave) < 10:
        return "La contraseña tiene que tener al menos 10 caracteres."
    if clave.isdigit() or clave.isalpha():
        return "Usa letras y números en la contraseña."
    if email and clave.lower() == email.lower():
        return "La contraseña no puede ser igual al correo."
    return None


def clave_temporal():
    return secrets.token_urlsafe(9)


# ---------- verificación en dos pasos (TOTP, RFC 6238) ----------
def totp_secreto():
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def totp_codigo(secreto, contador):
    relleno = "=" * ((8 - len(secreto) % 8) % 8)
    clave = base64.b32decode(secreto + relleno, casefold=True)
    h = hmac.new(clave, struct.pack(">Q", contador), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def totp_verificar(secreto, codigo, ultimo=None, momento=None):
    """Devuelve el contador usado si el código es válido y no se usó antes; si no, None."""
    codigo = "".join(ch for ch in str(codigo or "") if ch.isdigit())
    if len(codigo) != 6 or not secreto:
        return None
    actual = int((momento or time.time()) // 30)
    for d in (0, -1, 1):
        c = actual + d
        if hmac.compare_digest(totp_codigo(secreto, c), codigo) and (ultimo is None or c > ultimo):
            return c
    return None


def totp_enlace(secreto, email):
    emisor = current_app.config["NOMBRE"]
    return f"otpauth://totp/{quote(emisor)}:{quote(email)}?secret={secreto}&issuer={quote(emisor)}&digits=6&period=30"


# ---------- sesión y permisos ----------
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def iniciar_sesion(usuario):
    session.clear()
    session.permanent = True
    session["uid"] = usuario["id"]
    session["ver"] = usuario["sesion_ver"]
    session["ult"] = time.time()
    session["csrf"] = secrets.token_urlsafe(32)


def puede(permiso, usuario=None):
    u = usuario if usuario is not None else g.get("usuario")
    return bool(u) and u["rol"] in PERMISOS[permiso]


def requiere(permiso):
    def deco(f):
        @functools.wraps(f)
        def envoltura(*args, **kwargs):
            if not puede(permiso):
                abort(403)
            return f(*args, **kwargs)
        return envoltura
    return deco


def exigir_sesion():
    if not g.get("usuario"):
        return redirect(url_for("auth.ingresar", siguiente=request.path))
    return None


def init_app(app):
    @app.before_request
    def _antes():
        g.usuario = None
        uid = session.get("uid")
        if uid is not None:
            u = db.uno("SELECT * FROM usuarios WHERE id = ?", (uid,))
            inactivo = time.time() - session.get("ult", 0) > app.config["INACTIVIDAD_MIN"] * 60
            if not u or not u["activo"] or u["sesion_ver"] != session.get("ver") or inactivo:
                session.clear()
                g.sesion_vencida = True
            else:
                g.usuario = u
                session["ult"] = time.time()

        if request.method not in ("GET", "HEAD", "OPTIONS"):
            enviado = request.form.get("csrf") or request.headers.get("X-CSRF-Token") or ""
            esperado = session.get("csrf") or ""
            if not esperado or not hmac.compare_digest(enviado, esperado):
                abort(400)

        u = g.usuario
        if u and request.endpoint not in SIN_FORZAR:
            if u["debe_cambiar_clave"]:
                return redirect(url_for("auth.clave"))
            if u["rol"] in ROLES_EQUIPO and app.config["EXIGIR_2FA_EQUIPO"] and not u["totp_secreto"]:
                return redirect(url_for("auth.seguridad"))
        return None

    @app.context_processor
    def _contexto():
        return {"csrf_token": csrf_token, "usuario": g.get("usuario"), "puede": puede}
