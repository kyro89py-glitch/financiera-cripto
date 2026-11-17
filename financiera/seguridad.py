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
DESCRIPCION_PERMISOS = {
    "equipo.ver": "Entrar al área del equipo", "operaciones.aprobar": "Aprobar o rechazar depósitos y retiros",
    "clientes.crear": "Dar de alta clientes", "clientes.clave": "Entregar contraseñas temporales",
    "clientes.kyc": "Verificar identidad y debida diligencia", "clientes.origen": "Registrar origen de fondos",
    "cumplimiento.ver": "Ver alertas, bitácora y conciliación", "reportes.exportar": "Exportar reportes regulatorios",
    "documentos.subir": "Subir documentos de clientes", "documentos.revisar": "Aceptar o rechazar documentos",
    "conciliacion.registrar": "Registrar conciliaciones", "comisiones.cobrar": "Cobrar comisiones",
    "ejecucion.ver": "Ver el estado de la ejecución", "ejecucion.pausar": "Pausar la ejecución",
    "ejecucion.reanudar": "Reanudar la ejecución", "precios.editar": "Precios, monedas y ajustes",
    "usuarios.gestionar": "Gestionar usuarios del equipo", "antilavado.resolver": "Resolver alertas antilavado",
    "respaldos.gestionar": "Crear y probar respaldos", "limites.editar": "Cambiar límites de operación",
    "soporte.atender": "Responder consultas de clientes", "cuenta.solicitudes": "Resolver correcciones de datos y cierres de cuenta", "panel.ver": "Ver el panel de administración",
    "contenido.publicar": "Cargar, revisar y publicar noticias y acontecimientos",
    "autorizaciones.resolver": "Autorizar o rechazar acciones críticas pedidas por otra persona",
    "incidencias.gestionar": "Registrar y seguir incidencias", "clientes.datos_sensibles": "Ver datos personales completos de un cliente (queda registrado)",
}

PERMISOS = {
    "equipo.ver": {"operador", "cumplimiento", "admin"},
    "operaciones.aprobar": {"operador", "cumplimiento", "admin"},
    "clientes.crear": {"operador", "admin"},
    "clientes.clave": {"operador", "admin"},
    "clientes.kyc": {"cumplimiento", "admin"},
    "cuenta.solicitudes": {"cumplimiento", "admin"},
    "clientes.origen": {"cumplimiento", "admin"},
    "cumplimiento.ver": {"cumplimiento", "admin"},
    "reportes.exportar": {"cumplimiento", "admin"},
    "documentos.subir": {"operador", "cumplimiento", "admin"},
    "documentos.revisar": {"cumplimiento", "admin"},
    "conciliacion.registrar": {"cumplimiento", "admin"},
    "comisiones.cobrar": {"admin"},
    "ejecucion.ver": {"cumplimiento", "admin"},
    "ejecucion.pausar": {"cumplimiento", "admin"},
    "ejecucion.reanudar": {"admin"},
    "precios.editar": {"admin"},
    "usuarios.gestionar": {"admin"},
    "antilavado.resolver": {"cumplimiento", "admin"},
    "respaldos.gestionar": {"admin"},
    "limites.editar": {"admin"},
    "soporte.atender": {"operador", "cumplimiento", "admin"},
    "panel.ver": {"cumplimiento", "admin"},
    "contenido.publicar": {"cumplimiento", "admin"},
    "autorizaciones.resolver": {"cumplimiento", "admin"},
    "incidencias.gestionar": {"operador", "cumplimiento", "admin"},
    "clientes.datos_sensibles": {"cumplimiento", "admin"},
}

# Versión vigente de las condiciones y la información de riesgos que acepta cada cliente.
TERMINOS_VERSION = 1

# Rutas a las que se puede entrar aunque el usuario tenga un paso obligatorio pendiente.
SIN_FORZAR = {"auth.clave", "auth.seguridad", "auth.salir", "cliente.condiciones", "static", "auth.service_worker", "auth.sin_conexion"}


# ---------- contraseñas ----------
def hash_clave(clave):
    n, r, p = current_app.config["SCRYPT_N"], 8, current_app.config.get("SCRYPT_P", 1)
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


def necesita_rehash(guardado):
    """True si la contraseña se guardó con un costo menor al vigente (se actualiza al próximo ingreso)."""
    try:
        _, n, r, p, _, _ = guardado.split("$")
    except (ValueError, AttributeError):
        return True
    cfg = current_app.config
    return int(n) * int(p) < cfg["SCRYPT_N"] * cfg.get("SCRYPT_P", 1) or int(r) < 8


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
    from . import cifrado
    secreto = cifrado.descifrar_texto(secreto)
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


def describir_agente(ua):
    """«Chrome en Windows», «Safari en iPhone»… a partir del agente del navegador."""
    ua = ua or ""
    nav = ("Edge" if "Edg/" in ua else "Opera" if "OPR/" in ua else "Chrome" if ("Chrome/" in ua or "CriOS" in ua)
           else "Firefox" if ("Firefox/" in ua or "FxiOS" in ua) else "Safari" if "Safari/" in ua else "Navegador")
    so = ("Android" if "Android" in ua else "iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua
          else "Windows" if "Windows" in ua else "Mac" if ("Mac OS X" in ua or "Macintosh" in ua)
          else "Linux" if "Linux" in ua else "otro sistema")
    return f"{nav} en {so}"


def iniciar_sesion(usuario, motivo=None):
    """Abre una sesión nueva y la registra por dispositivo. Si el dispositivo es nuevo para el usuario, le avisa."""
    from .tiempo import ahora
    anterior = session.get("sid")
    session.clear()
    session.permanent = True
    session["uid"] = usuario["id"]
    session["ver"] = usuario["sesion_ver"]
    session["ult"] = time.time()
    session["csrf"] = secrets.token_urlsafe(32)
    agente = (request.headers.get("User-Agent") or "")[:300] if request else ""
    disp = describir_agente(agente)
    ts = ahora()
    sid = secrets.token_urlsafe(18)
    with db.transaccion() as c:
        if anterior:
            c.execute("UPDATE sesiones SET cerrada = ?, cierre = ? WHERE id = ? AND cerrada IS NULL", (ts, motivo or "renovada", anterior))
        conocido = c.execute("SELECT 1 FROM sesiones WHERE usuario_id = ? AND dispositivo = ? LIMIT 1", (usuario["id"], disp)).fetchone()
        previas = c.execute("SELECT 1 FROM sesiones WHERE usuario_id = ? LIMIT 1", (usuario["id"],)).fetchone()
        c.execute("INSERT INTO sesiones (id, usuario_id, creada, ultima, ip, agente, dispositivo) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (sid, usuario["id"], ts, ts, request.remote_addr if request else None, agente, disp))
    session["sid"] = sid
    session["sid_t"] = time.time()
    if previas and not motivo:
        from . import notificaciones, preferencias
        if not conocido:
            notificaciones.notificar(usuario["id"], f"Nuevo ingreso a tu cuenta desde {disp} (IP {request.remote_addr}). "
                                     "Si no fuiste tú, cambia tu contraseña y cierra esa sesión desde Seguridad.", "/cuenta/sesiones", ts=ts,
                                     categoria="seguridad")
        elif preferencias.leer(usuario["id"])["aviso_ingreso"] == "siempre":
            notificaciones.notificar(usuario["id"], f"Inicio de sesión desde {disp} (IP {request.remote_addr}).", "/cuenta/sesiones", ts=ts,
                                     categoria="seguridad")


def cerrar_sesiones(usuario_id, cierre, excepto=None):
    from .tiempo import ahora
    return db.ejecutar("UPDATE sesiones SET cerrada = ?, cierre = ? WHERE usuario_id = ? AND cerrada IS NULL AND id IS NOT ?",
                       (ahora(), cierre, usuario_id, excepto)).rowcount


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
            sid = session.get("sid")
            fila = db.uno("SELECT cerrada FROM sesiones WHERE id = ?", (sid,)) if sid else None
            cerrada = bool(sid) and (not fila or fila["cerrada"])
            if not u or not u["activo"] or u["sesion_ver"] != session.get("ver") or inactivo or cerrada:
                if sid and fila and not fila["cerrada"]:
                    from .tiempo import ahora
                    db.ejecutar("UPDATE sesiones SET cerrada = ?, cierre = ? WHERE id = ?", (ahora(), "vencida", sid))
                session.clear()
                g.sesion_vencida = True
            else:
                g.usuario = u
                session["ult"] = time.time()
                if sid and time.time() - session.get("sid_t", 0) > 60:
                    from .tiempo import ahora
                    db.ejecutar("UPDATE sesiones SET ultima = ? WHERE id = ?", (ahora(), sid))
                    session["sid_t"] = time.time()

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
            if u["rol"] == "cliente" and (u["terminos_version"] or 0) < TERMINOS_VERSION:
                return redirect(url_for("cliente.condiciones"))
        return None

    @app.context_processor
    def _contexto():
        return {"csrf_token": csrf_token, "usuario": g.get("usuario"), "puede": puede}
