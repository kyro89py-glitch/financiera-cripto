"""Financiera Cripto: plataforma de inversión en criptomonedas con portal de clientes y panel del equipo."""
import os
import secrets
from datetime import timedelta

from flask import Flask, g, redirect, render_template, url_for

from . import auditoria, cuentas, db, formato, precios, seguridad


def _env(nombre, defecto):
    return os.environ.get(nombre, defecto)


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    entorno = _env("FINANCIERA_ENTORNO", "produccion").strip().lower()
    prod = entorno == "produccion"
    app.config.update(
        ENTORNO=entorno,
        NOMBRE=_env("FINANCIERA_NOMBRE", "Financiera Cripto"),
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        DATABASE=_env("DATABASE", os.path.join(app.instance_path, "financiera.db")),
        SESSION_COOKIE_NAME="fc_sesion",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_env("COOKIE_SEGURA", "1" if prod else "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
        INACTIVIDAD_MIN=int(_env("INACTIVIDAD_MIN", "30")),
        INTENTOS_LOGIN=int(_env("INTENTOS_LOGIN", "5")),
        BLOQUEO_MIN=int(_env("BLOQUEO_MIN", "15")),
        EXIGIR_2FA_EQUIPO=_env("EXIGIR_2FA_EQUIPO", "1" if prod else "0") == "1",
        APORTE_MINIMO_USD=int(_env("APORTE_MINIMO_USD", "100")),
        UMBRAL_ORIGEN_FONDOS_USD=int(_env("UMBRAL_ORIGEN_FONDOS_USD", "10000")),
        UMBRAL_DOBLE_FIRMA_USD=int(_env("UMBRAL_DOBLE_FIRMA_USD", "25000")),
        PRECIO_MAX_MINUTOS=int(_env("PRECIO_MAX_MINUTOS", "60" if prod else "1440")),
        COINGECKO_API_KEY=_env("COINGECKO_API_KEY", ""),
        INSTRUCCIONES_DEPOSITO=_env(
            "INSTRUCCIONES_DEPOSITO",
            "Transfiere el monto a la cuenta bancaria de la empresa y escribe el número de comprobante. "
            "El equipo confirma la recepción del dinero antes de invertirlo."),
        ZONA_HORARIA=_env("ZONA_HORARIA", "America/Asuncion"),
        TRAS_PROXY=_env("TRAS_PROXY", "0") == "1",
        COMISION_ANUAL_PCT=_env("COMISION_ANUAL_PCT", "1.5"),
        DOCUMENTO_MAX_MB=int(_env("DOCUMENTO_MAX_MB", "8")),
        DOCUMENTOS_DIR=_env("DOCUMENTOS_DIR", ""),
        URL_PUBLICA=_env("URL_PUBLICA", "").rstrip("/"),
        SMTP_HOST=_env("SMTP_HOST", ""),
        SMTP_PUERTO=int(_env("SMTP_PUERTO", "587")),
        SMTP_USUARIO=_env("SMTP_USUARIO", ""),
        SMTP_CLAVE=_env("SMTP_CLAVE", ""),
        SMTP_REMITENTE=_env("SMTP_REMITENTE", ""),
        EJECUCION=_env("EJECUCION", "simulado").lower(),
        BINANCE_API_KEY=_env("BINANCE_API_KEY", ""),
        BINANCE_API_SECRET=_env("BINANCE_API_SECRET", ""),
        BINANCE_URL=_env("BINANCE_URL", "https://testnet.binance.vision").rstrip("/"),
        BINANCE_RECV_WINDOW=int(_env("BINANCE_RECV_WINDOW", "5000")),
        FUENTE_PRECIOS=_env("FUENTE_PRECIOS", "").lower(),
        ORDEN_PREFIJO=_env("ORDEN_PREFIJO", "fc"),
        SCRYPT_N=2 ** 14,
    )
    if config:
        app.config.update(config)

    if app.config["EJECUCION"] not in ("simulado", "binance"):
        raise RuntimeError("EJECUCION tiene que ser 'simulado' o 'binance'.")
    if not app.config["FUENTE_PRECIOS"]:
        app.config["FUENTE_PRECIOS"] = "binance" if app.config["EJECUCION"] == "binance" else "coingecko"
    if not app.config["SECRET_KEY"]:
        if app.config["ENTORNO"] == "produccion":
            raise RuntimeError("Falta SECRET_KEY. Defínela como variable de entorno antes de iniciar en producción.")
        app.config["SECRET_KEY"] = secrets.token_hex(32)

    carpeta = os.path.dirname(os.path.abspath(app.config["DATABASE"]))
    os.makedirs(carpeta, exist_ok=True)
    if not app.config["DOCUMENTOS_DIR"]:
        app.config["DOCUMENTOS_DIR"] = os.path.join(carpeta, "documentos")

    if app.config["TRAS_PROXY"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    seguridad.init_app(app)
    formato.init_app(app)

    from .rutas_admin import bp as bp_admin
    from .rutas_auth import bp as bp_auth
    from .rutas_cliente import bp as bp_cliente
    from .rutas_documentos import bp as bp_documentos
    from .rutas_equipo import bp as bp_equipo
    for bp in (bp_auth, bp_cliente, bp_equipo, bp_admin, bp_documentos):
        app.register_blueprint(bp)

    from . import comisiones, demo, notificaciones
    for cmd in (cuentas.cmd_crear_admin, precios.cmd_actualizar, auditoria.cmd_verificar, demo.cmd_sembrar,
                comisiones.cmd_cobrar, notificaciones.cmd_enviar):
        app.cli.add_command(cmd)

    with app.app_context():
        db.migrar()

    @app.get("/")
    def inicio():
        u = g.get("usuario")
        if not u:
            return redirect(url_for("auth.ingresar"))
        return redirect(url_for("cliente.inicio" if u["rol"] == "cliente" else "equipo.resumen"))

    @app.after_request
    def cabeceras(resp):
        h = resp.headers
        h.setdefault("Content-Security-Policy",
                     "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                     "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                     "frame-ancestors 'none'; form-action 'self'")
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "same-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if g.get("usuario"):
            h["Cache-Control"] = "no-store"
        if app.config["SESSION_COOKIE_SECURE"]:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp

    mensajes = {
        400: ("La solicitud no se pudo procesar", "Puede que la página haya quedado abierta mucho tiempo o que la sesión "
              "haya vencido. Vuelve atrás, recarga la página e intenta de nuevo."),
        403: ("No tienes permiso para ver esto", "Tu usuario no tiene acceso a esta sección. Si crees que es un error, "
              "habla con un administrador."),
        404: ("No encontramos esta página", "El enlace puede estar mal escrito o el registro ya no existe."),
        405: ("Acción no permitida", "Esta dirección no admite esa acción."),
        413: ("El envío es demasiado grande", "Reduce el tamaño de lo que estás enviando e intenta de nuevo."),
        500: ("Ocurrió un error inesperado", "El problema quedó registrado. Intenta de nuevo en unos minutos."),
    }

    def error(e):
        codigo = getattr(e, "code", 500) or 500
        titulo, texto = mensajes.get(codigo, mensajes[500])
        return render_template("error.html", codigo=codigo, titulo_error=titulo, texto_error=texto), codigo

    for codigo in (400, 403, 404, 405, 413, 500):
        app.register_error_handler(codigo, error)

    return app
