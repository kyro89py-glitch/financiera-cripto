"""Ingreso, salida, cambio de contraseña y verificación en dos pasos."""
import time
from datetime import timedelta

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from . import auditoria, db, seguridad
from .tiempo import ahora, ahora_dt, iso, leer

bp = Blueprint("auth", __name__)


def _destino(u):
    return url_for("cliente.inicio") if u["rol"] == "cliente" else url_for("equipo.resumen")


def _seguro(destino):
    if destino and destino.startswith("/") and not destino.startswith("//") and "\\" not in destino:
        return destino
    return None


def _fallo(u, motivo):
    if not u:
        return
    fallos = u["fallos"] + 1
    bloqueo = None
    if fallos >= current_app.config["INTENTOS_LOGIN"]:
        bloqueo = iso(ahora_dt() + timedelta(minutes=current_app.config["BLOQUEO_MIN"]))
    db.ejecutar("UPDATE usuarios SET fallos = ?, bloqueado_hasta = ? WHERE id = ?", (fallos, bloqueo, u["id"]))
    texto = f"Ingreso fallido de {u['email']} ({motivo})." + (" Cuenta bloqueada temporalmente." if bloqueo else "")
    auditoria.registrar("ingreso.fallido", f"usuario:{u['id']}", {"texto": texto, "fallos": fallos},
                        usuario=None, actor=u["email"])


def _bloqueado(u):
    return bool(u and u["bloqueado_hasta"] and leer(u["bloqueado_hasta"]) > ahora_dt())


def _completar(u, siguiente):
    seguridad.iniciar_sesion(u)
    db.ejecutar("UPDATE usuarios SET fallos = 0, bloqueado_hasta = NULL, ultimo_ingreso = ? WHERE id = ?", (ahora(), u["id"]))
    auditoria.registrar("ingreso.ok", f"usuario:{u['id']}", {"texto": f"Ingresó {u['email']}."}, usuario=u)
    return redirect(_seguro(siguiente) or _destino(u))


@bp.route("/ingresar", methods=["GET", "POST"])
def ingresar():
    if g.usuario:
        return redirect(_destino(g.usuario))
    error, email = None, ""
    siguiente = request.values.get("siguiente", "")
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()[:200]
        clave = request.form.get("clave") or ""
        u = db.uno("SELECT * FROM usuarios WHERE email = ?", (email,))
        if _bloqueado(u):
            error = "La cuenta está bloqueada por varios intentos fallidos. Vuelve a intentar en unos minutos."
        else:
            valida = seguridad.verificar_clave(u["clave_hash"] if u else seguridad.hash_ficticio(), clave)
            if not (u and valida and u["activo"]):
                _fallo(u, "contraseña incorrecta" if u and not valida else "usuario inactivo" if u else "")
                if not u:
                    auditoria.registrar("ingreso.fallido", None, {"texto": "Intento de ingreso con un correo no registrado."},
                                        usuario=None, actor=email or "desconocido")
                error = "El correo o la contraseña no son correctos."
            elif u["totp_secreto"]:
                session.clear()
                session["pre"] = {"uid": u["id"], "t": time.time(), "sig": _seguro(siguiente) or ""}
                seguridad.csrf_token()
                return redirect(url_for("auth.codigo"))
            else:
                return _completar(u, siguiente)
    return render_template("auth/ingresar.html", error=error, email=email, siguiente=siguiente,
                           vencida=g.get("sesion_vencida"))


@bp.route("/ingresar/codigo", methods=["GET", "POST"])
def codigo():
    pre = session.get("pre")
    if not pre or time.time() - pre.get("t", 0) > 300:
        session.pop("pre", None)
        flash("Vuelve a escribir tu correo y contraseña.", "info")
        return redirect(url_for("auth.ingresar"))
    u = db.uno("SELECT * FROM usuarios WHERE id = ?", (pre["uid"],))
    if not u or not u["activo"]:
        session.clear()
        return redirect(url_for("auth.ingresar"))
    error = None
    if request.method == "POST":
        if _bloqueado(u):
            error = "La cuenta está bloqueada por varios intentos fallidos. Vuelve a intentar en unos minutos."
        else:
            contador = seguridad.totp_verificar(u["totp_secreto"], request.form.get("codigo"), u["totp_ultimo"])
            if contador is None:
                _fallo(u, "código de verificación incorrecto")
                error = "El código no es correcto o ya se usó. Escribe el código que muestra ahora tu aplicación."
            else:
                db.ejecutar("UPDATE usuarios SET totp_ultimo = ? WHERE id = ?", (contador, u["id"]))
                return _completar(u, pre.get("sig"))
    return render_template("auth/codigo.html", error=error)


@bp.post("/salir")
def salir():
    u = g.get("usuario")
    if u:
        auditoria.registrar("salida", f"usuario:{u['id']}", {"texto": f"Cerró sesión {u['email']}."}, usuario=u)
    session.clear()
    flash("Cerraste sesión.", "info")
    return redirect(url_for("auth.ingresar"))


@bp.route("/cuenta/clave", methods=["GET", "POST"])
def clave():
    r = seguridad.exigir_sesion()
    if r:
        return r
    u = g.usuario
    error = None
    if request.method == "POST":
        actual = request.form.get("actual") or ""
        nueva = request.form.get("nueva") or ""
        if not seguridad.verificar_clave(u["clave_hash"], actual):
            error = "La contraseña actual no es correcta."
        elif nueva != (request.form.get("repetir") or ""):
            error = "Las contraseñas nuevas no coinciden."
        elif nueva == actual:
            error = "La contraseña nueva tiene que ser distinta de la actual."
        else:
            error = seguridad.validar_clave_nueva(nueva, u["email"])
        if not error:
            db.ejecutar("UPDATE usuarios SET clave_hash = ?, debe_cambiar_clave = 0, sesion_ver = sesion_ver + 1 WHERE id = ?",
                        (seguridad.hash_clave(nueva), u["id"]))
            auditoria.registrar("clave.cambiada", f"usuario:{u['id']}", {"texto": f"{u['email']} cambió su contraseña."}, usuario=u)
            u = db.uno("SELECT * FROM usuarios WHERE id = ?", (u["id"],))
            seguridad.iniciar_sesion(u)
            flash("Contraseña actualizada. Se cerraron tus otras sesiones.", "ok")
            return redirect(_destino(u))
    return render_template("auth/clave.html", error=error, forzado=bool(u["debe_cambiar_clave"]))


@bp.route("/cuenta/seguridad", methods=["GET", "POST"], endpoint="seguridad")
def seguridad_cuenta():
    r = seguridad.exigir_sesion()
    if r:
        return r
    u = g.usuario
    error = None
    obligatorio = u["rol"] in seguridad.ROLES_EQUIPO and current_app.config["EXIGIR_2FA_EQUIPO"]
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "activar" and not u["totp_secreto"] and u["totp_pendiente"]:
            contador = seguridad.totp_verificar(u["totp_pendiente"], request.form.get("codigo"))
            if contador is None:
                error = "El código no coincide. Revisa que la hora del teléfono esté bien y vuelve a intentar."
            else:
                db.ejecutar("UPDATE usuarios SET totp_secreto = totp_pendiente, totp_pendiente = NULL, totp_ultimo = ?,"
                            " sesion_ver = sesion_ver + 1 WHERE id = ?", (contador, u["id"]))
                auditoria.registrar("2fa.activada", f"usuario:{u['id']}",
                                    {"texto": f"{u['email']} activó la verificación en dos pasos."}, usuario=u)
                seguridad.iniciar_sesion(db.uno("SELECT * FROM usuarios WHERE id = ?", (u["id"],)))
                flash("Verificación en dos pasos activada.", "ok")
                return redirect(url_for("auth.seguridad"))
        elif accion == "desactivar" and u["totp_secreto"]:
            if obligatorio:
                error = "Para el equipo la verificación en dos pasos es obligatoria."
            elif not seguridad.verificar_clave(u["clave_hash"], request.form.get("clave") or ""):
                error = "La contraseña no es correcta."
            elif seguridad.totp_verificar(u["totp_secreto"], request.form.get("codigo"), u["totp_ultimo"]) is None:
                error = "El código no es correcto."
            else:
                db.ejecutar("UPDATE usuarios SET totp_secreto = NULL, totp_ultimo = NULL WHERE id = ?", (u["id"],))
                auditoria.registrar("2fa.desactivada", f"usuario:{u['id']}",
                                    {"texto": f"{u['email']} desactivó la verificación en dos pasos."}, usuario=u)
                flash("Verificación en dos pasos desactivada.", "ok")
                return redirect(url_for("auth.seguridad"))
    u = db.uno("SELECT * FROM usuarios WHERE id = ?", (u["id"],))
    secreto = enlace = None
    if not u["totp_secreto"]:
        if not u["totp_pendiente"]:
            db.ejecutar("UPDATE usuarios SET totp_pendiente = ? WHERE id = ?", (seguridad.totp_secreto(), u["id"]))
            u = db.uno("SELECT * FROM usuarios WHERE id = ?", (u["id"],))
        secreto = u["totp_pendiente"]
        enlace = seguridad.totp_enlace(secreto, u["email"])
    grupos = " ".join(secreto[i:i + 4] for i in range(0, len(secreto), 4)) if secreto else None
    return render_template("auth/seguridad.html", error=error, activa=bool(u["totp_secreto"]), secreto=grupos,
                           enlace=enlace, obligatorio=obligatorio)



@bp.get("/cuenta/avisos")
def avisos():
    r = seguridad.exigir_sesion()
    if r:
        return r
    from . import notificaciones
    lista = notificaciones.listar(g.usuario["id"])
    notificaciones.marcar_leidas(g.usuario["id"])
    return render_template("auth/avisos.html", lista=lista)
