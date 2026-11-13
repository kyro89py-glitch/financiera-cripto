"""Avisos dentro del sistema y cola de correos salientes."""
import smtplib
import ssl
from email.message import EmailMessage

import click
from flask import current_app

from . import db
from .tiempo import ahora


def correo_activo():
    return bool(current_app.config.get("SMTP_HOST"))


def notificar(usuario_id, texto, enlace=None, asunto=None, ts=None):
    """Deja un aviso al usuario y, si hay correo configurado, encola un correo con el mismo texto."""
    ts = ts or ahora()
    with db.transaccion() as c:
        c.execute("INSERT INTO notificaciones (usuario_id, texto, enlace, ts) VALUES (?, ?, ?, ?)",
                  (usuario_id, texto, enlace, ts))
        if correo_activo():
            u = c.execute("SELECT email, nombre, activo FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
            if u and u["activo"]:
                nombre = current_app.config["NOMBRE"]
                url = current_app.config["URL_PUBLICA"]
                cuerpo = f"Hola {u['nombre'].split()[0]}:\n\n{texto}\n\n"
                if url and enlace:
                    cuerpo += f"Puedes verlo en {url}{enlace}\n\n"
                cuerpo += f"{nombre}\nEste es un mensaje automático; no respondas a este correo."
                c.execute("INSERT INTO correos (para, asunto, cuerpo, creado) VALUES (?, ?, ?, ?)",
                          (u["email"], asunto or f"Novedades en tu cuenta de {nombre}", cuerpo, ts))


def notificar_rol(roles, texto, enlace=None, excepto=None, ts=None):
    marcadores = ",".join("?" * len(roles))
    for u in db.todos(f"SELECT id FROM usuarios WHERE activo = 1 AND rol IN ({marcadores})", tuple(roles)):
        if u["id"] != excepto:
            notificar(u["id"], texto, enlace, ts=ts)


def no_leidas(usuario_id):
    return db.uno("SELECT COUNT(*) AS n FROM notificaciones WHERE usuario_id = ? AND leida = 0", (usuario_id,))["n"]


def listar(usuario_id, limite=60):
    return db.todos("SELECT * FROM notificaciones WHERE usuario_id = ? ORDER BY ts DESC, id DESC LIMIT ?", (usuario_id, limite))


def marcar_leidas(usuario_id):
    db.ejecutar("UPDATE notificaciones SET leida = 1 WHERE usuario_id = ? AND leida = 0", (usuario_id,))


def enviar_pendientes(limite=50):
    """Envía los correos en cola. Reintenta hasta 3 veces. Devuelve (enviados, con_error)."""
    if not correo_activo():
        return 0, 0
    cfg = current_app.config
    pendientes = db.todos("SELECT * FROM correos WHERE estado = 'pendiente' ORDER BY id LIMIT ?", (limite,))
    if not pendientes:
        return 0, 0
    enviados = errores = 0
    try:
        servidor = smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PUERTO"], timeout=20)
        servidor.starttls(context=ssl.create_default_context())
        if cfg["SMTP_USUARIO"]:
            servidor.login(cfg["SMTP_USUARIO"], cfg["SMTP_CLAVE"])
    except (OSError, smtplib.SMTPException) as e:
        for p in pendientes:
            _fallo(p, f"Conexión SMTP: {e.__class__.__name__}")
        return 0, len(pendientes)
    with servidor:
        for p in pendientes:
            msg = EmailMessage()
            msg["From"] = cfg["SMTP_REMITENTE"] or cfg["SMTP_USUARIO"]
            msg["To"] = p["para"]
            msg["Subject"] = p["asunto"]
            msg.set_content(p["cuerpo"])
            try:
                servidor.send_message(msg)
                db.ejecutar("UPDATE correos SET estado = 'enviado', enviado = ?, intentos = intentos + 1 WHERE id = ?",
                            (ahora(), p["id"]))
                enviados += 1
            except smtplib.SMTPException as e:
                _fallo(p, e.__class__.__name__)
                errores += 1
    return enviados, errores


def _fallo(p, error):
    estado = "error" if p["intentos"] + 1 >= 3 else "pendiente"
    db.ejecutar("UPDATE correos SET intentos = intentos + 1, error = ?, estado = ? WHERE id = ?", (error[:200], estado, p["id"]))


@click.command("enviar-correos")
def cmd_enviar():
    """Envía los correos pendientes (pensado para ejecutarse cada pocos minutos)."""
    if not correo_activo():
        click.echo("No hay servidor de correo configurado (SMTP_HOST). No se envió nada.")
        return
    enviados, errores = enviar_pendientes()
    click.echo(f"{enviados} correos enviados, {errores} con error.")
