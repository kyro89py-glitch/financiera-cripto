"""Mi cuenta: identidad, fotografía, nombre de usuario, perfil público, preferencias, solicitudes y cierre."""
import io

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for

from . import cuenta, db, limites, niveles, notificaciones, preferencias, seguridad

bp = Blueprint("cuenta", __name__)


@bp.before_request
def _guardia():
    if request.endpoint == "cuenta.correo_confirmar":
        return None  # el enlace del correo se abre sin sesión
    return seguridad.exigir_sesion()


def _cliente():
    return db.uno("SELECT * FROM clientes WHERE usuario_id = ?", (g.usuario["id"],)) if g.usuario["rol"] == "cliente" else None


def _contexto():
    """Lo que necesita la cabecera de Mi cuenta en todas sus pantallas."""
    u, cli = g.usuario, _cliente()
    return {"cli": cli, "codigo": cuenta.codigo(u["id"]), "proteccion": niveles.proteccion(cli, u),
            "nivel": niveles.nivel(cli, u) if cli else None, "pref": preferencias.leer(u["id"])}


@bp.get("/cuenta/")
def inicio():
    ctx = _contexto()
    u = g.usuario
    sol = cuenta.solicitudes_de(u["id"])
    sesiones = db.uno("SELECT COUNT(*) AS n FROM sesiones WHERE usuario_id = ? AND cerrada IS NULL", (u["id"],))["n"]
    completo = [("Fotografía", bool(u["foto"]), "cuenta.datos", "foto"), ("Nombre de usuario", bool(u["usuario"]), "cuenta.datos", "usuario"),
                ("Teléfono", bool(u["telefono"] or (ctx["cli"] and ctx["cli"]["telefono"])), "cuenta.datos", "contacto"),
                ("País y ciudad", bool(u["pais"] and u["ciudad"]), "cuenta.datos", "contacto"),
                ("Verificación en dos pasos", bool(u["totp_secreto"]), "auth.seguridad", "")]
    if ctx["cli"]:
        completo.insert(0, ("Identidad verificada", ctx["cli"]["kyc_estado"] == "verificado", "cliente.perfil", "legajo"))
    return render_template("cuenta/inicio.html", completo=completo, hechos=sum(1 for c in completo if c[1]),
                           abiertas=[s for s in sol if s["estado"] == "abierta"], sesiones=sesiones,
                           avisos=notificaciones.no_leidas(u["id"]), **ctx)


@bp.route("/cuenta/datos", methods=["GET", "POST"])
def datos():
    u = g.usuario
    if request.method == "POST":
        accion = request.form.get("accion")
        try:
            if accion == "usuario":
                t = cuenta.fijar_usuario(u, request.form.get("usuario"))
                flash(f"Tu nombre de usuario es @{t}.", "ok")
            elif accion == "publico":
                preferencias.guardar(u["id"], {"publico": {k: request.form.get(k) == "si" for k in preferencias.DEFECTO["publico"]}})
                flash("Guardamos qué muestra tu perfil público.", "ok")
            else:
                cambios = cuenta.actualizar_datos(u, request.form)
                flash("Datos guardados." if cambios else "No había cambios para guardar.", "ok" if cambios else "info")
        except cuenta.ErrorCuenta as e:
            flash(str(e), "error")
        return redirect(url_for("cuenta.datos") + "#" + {"usuario": "usuario", "publico": "publico"}.get(accion, "contacto"))
    pendiente = db.uno("SELECT nuevo, vence FROM cambios_email WHERE usuario_id = ? AND usada IS NULL AND vence > ? ORDER BY id DESC",
                       (u["id"], cuenta.ahora()))
    return render_template("cuenta/datos.html", paises=cuenta.PAISES, avatares=range(cuenta.AVATARES), correo_pendiente=pendiente,
                           enlace_prueba=request.args.get("enlace") if current_app.config["ENTORNO"] != "produccion" else None, **_contexto())


@bp.post("/cuenta/foto")
def foto_guardar():
    u = g.usuario
    limites.exigir(("foto", f"u{u['id']}"))
    try:
        if request.form.get("accion") == "quitar":
            cuenta.borrar_foto(u)
            flash("Quitamos tu fotografía. Se muestra tu avatar predeterminado.", "ok")
        else:
            archivo = request.files.get("foto")
            cuenta.guardar_foto(u, archivo.read(cuenta.FOTO_MAX_BYTES + 1) if archivo else b"")
            flash("Fotografía actualizada.", "ok")
    except cuenta.ErrorCuenta as e:
        flash(str(e), "error")
    return redirect(url_for("cuenta.datos") + "#foto")


@bp.get("/cuenta/foto/<int:uid>")
def foto(uid):
    """La foto la ve su dueño, el equipo y, si la persona la muestra en su perfil público, los demás usuarios con sesión."""
    u = db.uno("SELECT * FROM usuarios WHERE id = ?", (uid,))
    ruta = cuenta.ruta_foto(u) if u else None
    if not ruta:
        abort(404)
    yo = g.usuario
    if yo["id"] != uid and yo["rol"] == "cliente":
        p = preferencias.leer(uid)["publico"]
        if not (p["activo"] and p["foto"] and u["usuario"]):
            abort(404)
    with open(ruta, "rb") as f:
        resp = send_file(io.BytesIO(f.read()), mimetype="image/jpeg", max_age=0, conditional=False)
    resp.headers["Cache-Control"] = "private, max-age=86400, immutable" if request.args.get("v") else "private, no-cache"
    resp.headers["Content-Disposition"] = "inline"
    resp.set_etag(u["foto"])
    return resp


@bp.get("/cuenta/usuario-disponible")
def usuario_disponible():
    limites.exigir(("usuario_disp", f"u{g.usuario['id']}"))
    ok, msg = cuenta.disponible(request.args.get("u"), g.usuario["id"])
    return {"ok": ok, "texto": msg}


@bp.post("/cuenta/correo")
def correo_pedir():
    u = g.usuario
    limites.exigir(("correo", f"u{u['id']}"))
    try:
        base = current_app.config["URL_PUBLICA"] or request.host_url.rstrip("/")
        enlace = cuenta.pedir_cambio_email(u, request.form.get("nuevo"), request.form.get("clave"), base)
        flash("Te enviamos un enlace al correo nuevo. El cambio se aplica cuando lo abras (vale 1 hora).", "ok")
        if enlace and current_app.config["ENTORNO"] != "produccion" and not notificaciones.correo_activo():
            return redirect(url_for("cuenta.datos", enlace=enlace) + "#correo")
    except cuenta.ErrorCuenta as e:
        flash(str(e), "error")
    return redirect(url_for("cuenta.datos") + "#correo")


@bp.get("/cuenta/correo/<token>")
def correo_confirmar(token):
    try:
        u = cuenta.confirmar_email(token)
        flash(f"Listo: el correo de tu cuenta ahora es {u['email']}. Ingresa de nuevo.", "ok")
    except cuenta.ErrorCuenta as e:
        flash(str(e), "error")
    return redirect(url_for("auth.ingresar"))


@bp.route("/cuenta/personalizar", methods=["GET", "POST"])
def personalizar():
    u = g.usuario
    if request.method == "POST":
        f = request.form
        cambios = {"tema": f.get("tema"), "zona": f.get("zona", ""), "moneda": f.get("moneda")}
        preferencias.guardar(u["id"], cambios)
        db.ejecutar("UPDATE usuarios SET ocultar_saldos = ? WHERE id = ?", (1 if f.get("ocultar_saldos") == "si" else 0, u["id"]))
        if g.usuario["rol"] == "cliente":
            db.ejecutar("UPDATE clientes SET recibir_envios = ? WHERE usuario_id = ?", (1 if f.get("recibir_envios") == "si" else 0, u["id"]))
        from . import auditoria
        auditoria.registrar("preferencias.cambiadas", f"usuario:{u['id']}", {"texto": "Cambió sus preferencias de apariencia, región o privacidad."})
        flash("Preferencias guardadas en tu cuenta: las vas a ver igual en cualquier dispositivo.", "ok")
        resp = redirect(url_for("cuenta.personalizar"))
        if f.get("tema") in ("oscuro", "claro"):
            resp.set_cookie("tema", f.get("tema"), max_age=365 * 86400, samesite="Lax", httponly=True,
                            secure=current_app.config.get("SESSION_COOKIE_SECURE", False))
        return resp
    return render_template("cuenta/personalizar.html", zonas=preferencias.ZONAS, idiomas=preferencias.IDIOMAS,
                           zona_plataforma=current_app.config["ZONA_HORARIA"], categorias=preferencias.CATEGORIAS, **_contexto())


@bp.route("/cuenta/solicitudes", methods=["GET", "POST"])
def solicitudes():
    u = g.usuario
    if request.method == "POST":
        try:
            accion = request.form.get("accion")
            if accion == "cancelar":
                cuenta.cancelar_solicitud(request.form.get("id", type=int), u)
                flash("Solicitud cancelada.", "ok")
            elif accion == "cierre":
                cuenta.solicitar_cierre(u, _cliente(), request.form.get("motivo"), request.form.get("clave"))
                flash("Recibimos tu pedido de cierre. El equipo lo revisa y te avisa; mientras tanto puedes cancelarlo.", "ok")
            else:
                cuenta.solicitar_correccion(u, request.form)
                flash("Recibimos tu pedido de corrección. Cumplimiento lo revisa; puede pedirte un documento que lo respalde.", "ok")
        except cuenta.ErrorCuenta as e:
            flash(str(e), "error")
        return redirect(url_for("cuenta.solicitudes"))
    return render_template("cuenta/solicitudes.html", lista=cuenta.solicitudes_de(u["id"]), estados=cuenta.ESTADOS_SOLICITUD,
                           campos=cuenta.CAMPOS_VERIFICADOS, pendientes_cierre=cuenta.pendientes_para_cerrar(_cliente()), **_contexto())


@bp.get("/u/<nombre>")
def publico(nombre):
    u = db.uno("SELECT * FROM usuarios WHERE usuario = ? COLLATE NOCASE", (nombre.lstrip("@"),))
    p = cuenta.perfil_publico(u, preferencias.leer(u["id"])) if u else None
    if not p:
        abort(404)
    return render_template("cuenta/publico.html", p=p, propio=u["id"] == g.usuario["id"], puedo_enviar=g.usuario["rol"] == "cliente")


@bp.get("/cuenta/actividad")
def actividad():
    import re

    from . import actividad as act
    cat = request.args.get("cat") if request.args.get("cat") in act.CATEGORIAS else None
    fecha = lambda k: request.args.get(k) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", request.args.get(k) or "") else None  # noqa: E731
    desde, hasta = fecha("desde"), fecha("hasta")
    lista = act.eventos(g.usuario, _cliente(), cat, desde, hasta)
    if request.args.get("formato") == "csv":
        import csv

        from .formato import zona
        from .tiempo import leer
        limites.exigir(("datos", f"u{g.usuario['id']}"))
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["fecha", "hora", "categoria", "descripcion", "estado", "ip"])
        for e in lista:
            d = leer(e["ts"]).astimezone(zona())
            w.writerow([d.strftime("%Y-%m-%d"), d.strftime("%H:%M:%S"), act.CATEGORIAS[e["cat"]], e["texto"], e["estado"][1], e["ip"] or ""])
        resp = current_app.response_class("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8")
        resp.headers["Content-Disposition"] = 'attachment; filename="actividad.csv"'
        return resp
    conteo = {}
    for e in act.eventos(g.usuario, _cliente(), None, desde, hasta):
        conteo[e["cat"]] = conteo.get(e["cat"], 0) + 1
    return render_template("cuenta/actividad.html", grupos=act.por_dia(lista), total=len(lista), cat=cat, desde=desde, hasta=hasta,
                           categorias=act.CATEGORIAS, conteo=conteo, **_contexto())
