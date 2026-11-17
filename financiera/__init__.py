"""Financiera Cripto: plataforma de inversión en criptomonedas con portal de clientes y panel del equipo."""
import os
import secrets
from datetime import timedelta

from flask import Flask, g, redirect, render_template, url_for

from . import auditoria, cuentas, db, formato, precios, seguridad


def _env(nombre, defecto):
    return os.environ.get(nombre, defecto)


def _secreto(nombre, defecto=""):
    """Lee un secreto de NOMBRE o, mejor, de un archivo indicado en NOMBRE_FILE (secretos de Docker, gestores de
    secretos montados como archivo). Así las claves no quedan en el entorno del proceso ni en docker-compose.yml."""
    ruta = os.environ.get(nombre + "_FILE")
    if ruta:
        with open(ruta, encoding="utf-8") as f:
            return f.read().strip()
    return os.environ.get(nombre, defecto)


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    entorno = _env("FINANCIERA_ENTORNO", "produccion").strip().lower()
    prod = entorno == "produccion"
    app.config.update(
        ENTORNO=entorno,
        NOMBRE=_env("FINANCIERA_NOMBRE", "Financiera Cripto"),
        SECRET_KEY=_secreto("SECRET_KEY") or None,
        CLAVE_CIFRADO=_secreto("CLAVE_CIFRADO"),
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
        ORDEN_MAXIMA_USD=int(_env("ORDEN_MAXIMA_USD", "25000")),
        PYG_MARGEN_MAX_PCT=int(_env("PYG_MARGEN_MAX_PCT", "5")),
        ENVIO_MAX_DIA_USD=int(_env("ENVIO_MAX_DIA_USD", "5000")),
        # Transferencias a otras entidades: solo con un proveedor autorizado. Mientras tanto el flujo externo es una demostración.
        TRANSFERENCIAS_REALES=_env("TRANSFERENCIAS_REALES", "0") == "1",
        RETIRO_MAX_DIA_USD=int(_env("RETIRO_MAX_DIA_USD", "50000")),
        OFICINA_DIRECCION=_env("OFICINA_DIRECCION", ""),
        DEPOSITO_USDT_DIRECCION=_env("DEPOSITO_USDT_DIRECCION", ""),
        DEPOSITO_USDT_RED=_env("DEPOSITO_USDT_RED", "TRON (TRC-20)"),
        COMISION_EXCHANGE_PCT=_env("COMISION_EXCHANGE_PCT", "0.1"),
        ENVIO_AVISO_USD=int(_env("ENVIO_AVISO_USD", "2000")),
        PRECIO_MAX_MINUTOS=int(_env("PRECIO_MAX_MINUTOS", "2" if prod else "1440")),
        COINGECKO_API_KEY=_secreto("COINGECKO_API_KEY"),
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
        SMTP_CLAVE=_secreto("SMTP_CLAVE"),
        SMTP_REMITENTE=_env("SMTP_REMITENTE", ""),
        EJECUCION=_env("EJECUCION", "simulado").lower(),
        BINANCE_API_KEY=_secreto("BINANCE_API_KEY"),
        BINANCE_API_SECRET=_secreto("BINANCE_API_SECRET"),
        BINANCE_URL=_env("BINANCE_URL", "https://testnet.binance.vision").rstrip("/"),
        BINANCE_RECV_WINDOW=int(_env("BINANCE_RECV_WINDOW", "5000")),
        FUENTE_PRECIOS=_env("FUENTE_PRECIOS", "").lower(),
        VIVO_SEGUNDOS=float(_env("VIVO_SEGUNDOS", "3")),
        ORDEN_PREFIJO=_env("ORDEN_PREFIJO", "fc"),
        # S-08: costo equivalente al mínimo que recomienda OWASP para scrypt (N=2^15, r=8, p=3; 32 MiB por cálculo).
        SCRYPT_N=2 ** 15,
        SCRYPT_P=3,
        LIMITES_DESACTIVADOS=False,
        RECUPERACION_MINUTOS=30,
        RESPALDOS_DIR=_env("RESPALDOS_DIR", ""),
        RESPALDOS_CONSERVAR=int(_env("RESPALDOS_CONSERVAR", "14")),
        RESPALDO_COMANDO=_env("RESPALDO_COMANDO", ""),
        METRICAS_TOKEN=_secreto("METRICAS_TOKEN"),
        UMBRAL_AML_USD=int(_env("UMBRAL_AML_USD", "10000")),
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
    if app.config["ENTORNO"] == "produccion":
        if len(app.config["SECRET_KEY"]) < 32:
            raise RuntimeError("SECRET_KEY es demasiado corta: usa al menos 32 caracteres al azar.")
        if not app.config["CLAVE_CIFRADO"]:
            raise RuntimeError("Falta CLAVE_CIFRADO (cifrado de datos sensibles). Genérala con `flask cifrado generar-clave`.")

    carpeta = os.path.dirname(os.path.abspath(app.config["DATABASE"]))
    os.makedirs(carpeta, exist_ok=True)
    if not app.config["DOCUMENTOS_DIR"]:
        app.config["DOCUMENTOS_DIR"] = os.path.join(carpeta, "documentos")
    app.config.setdefault("FOTOS_DIR", os.environ.get("FOTOS_DIR") or os.path.join(carpeta, "fotos"))
    if not app.config["RESPALDOS_DIR"]:
        app.config["RESPALDOS_DIR"] = os.path.join(carpeta, "respaldos")

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
    from .rutas_cuenta import bp as bp_cuenta
    for bp in (bp_auth, bp_cliente, bp_equipo, bp_admin, bp_documentos, bp_cuenta):
        app.register_blueprint(bp)

    from . import antilavado, cifrado, comisiones, demo, noticias, notificaciones, observabilidad, planes, respaldos
    observabilidad.init_app(app)
    for cmd in (cuentas.cmd_crear_admin, precios.cmd_actualizar, precios.cmd_vivo, auditoria.cmd_verificar, demo.cmd_sembrar,
                comisiones.cmd_cobrar, notificaciones.cmd_enviar, planes.cmd_ejecutar, cifrado.cmd_cifrado,
                respaldos.cmd_respaldo, antilavado.cmd_antilavado, observabilidad.cmd_recuperar, noticias.cmd_importar):
        app.cli.add_command(cmd)

    with app.app_context():
        db.migrar()

    @app.get("/")
    def inicio():
        u = g.get("usuario")
        if not u:
            from . import graficos
            todas = [m for m in precios.mercado(dias=7) if m["habilitado"]]
            filas = todas[:8]
            for m in filas:
                m["chispa"] = graficos.chispa(m["serie"], 150, 40)
            grupos = [{"label": m["codigo"], "value": int(1000000 / (i + 1.4)), "col": m["color"]} for i, m in enumerate(filas)]
            return render_template("inicio.html", filas=filas, total_monedas=len(todas), datos3d={"titulo": "", "grupos": grupos})
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
        if g.get("usuario") and not h.get("ETag"):
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
        429: ("Demasiados intentos seguidos", "Por seguridad pausamos esta acción un momento. Espera unos minutos y vuelve a intentar."),
        500: ("Ocurrió un error inesperado", "El problema quedó registrado. Intenta de nuevo en unos minutos."),
    }

    def error(e):
        codigo = getattr(e, "code", 500) or 500
        titulo, texto = mensajes.get(codigo, mensajes[500])
        espera = g.get("reintentar")
        if codigo == 429 and espera:
            texto = f"Por seguridad pausamos esta acción. Vuelve a intentar en {max(1, round(espera / 60))} min."
        from flask import request as rq
        if rq.accept_mimetypes.best == "application/json" or rq.path.endswith(".json") or rq.endpoint == "cliente.destinatario":
            resp = {"ok": False, "error": titulo, "texto": texto, "referencia": g.get("rid")}, codigo
        else:
            resp = render_template("error.html", codigo=codigo, titulo_error=titulo, texto_error=texto, referencia=g.get("rid")), codigo
        if codigo == 429 and espera:
            return resp[0], codigo, {"Retry-After": str(int(espera))}
        return resp

    for codigo in (400, 403, 404, 405, 413, 429, 500):
        app.register_error_handler(codigo, error)

    return app
