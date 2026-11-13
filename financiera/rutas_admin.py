"""Administración: precios, comisiones, ejecución en el exchange y usuarios del equipo."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from . import auditoria, cartera, comisiones, conciliacion, cuentas, db, ejecucion, exchange, precios, seguridad
from .dinero import leer_precio

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
def _guardia():
    r = seguridad.exigir_sesion()
    if r:
        return r
    if request.endpoint == "admin.ejecucion" and seguridad.puede("ejecucion.ver"):
        return None  # Cumplimiento también puede ver la ejecución y activar la pausa de emergencia
    if g.usuario["rol"] != "admin":
        abort(403)
    return None


@bp.get("/precios", endpoint="precios")
def precios_ver():
    return render_template("admin/precios.html", fuente=precios.fuente(), activos=precios.activos(), vig=precios.vigentes(),
                           viejos=dict(precios.antiguos()))



@bp.post("/precios/manual")
def precio_manual():
    activo = request.form.get("activo") or ""
    try:
        precios.actualizar_manual(activo, leer_precio(request.form.get("precio")), g.usuario)
        flash(f"Precio de {activo} actualizado.", "ok")
    except (ValueError, precios.ErrorPrecio) as e:
        flash(str(e), "error")
    return redirect(url_for("admin.precios"))


@bp.post("/precios/coingecko")
def precio_coingecko():
    try:
        n = precios.actualizar(g.usuario)
        flash(f"{n} precios actualizados desde {precios.fuente()}.", "ok")
    except precios.ErrorPrecio as e:
        flash(str(e) + " Puedes cargar los precios a mano.", "error")
    return redirect(url_for("admin.precios"))


@bp.route("/usuarios", methods=["GET", "POST"])
def usuarios():
    error = None
    form = {"nombre": "", "email": "", "rol": "operador"}
    if request.method == "POST":
        form = {k: (request.form.get(k) or "").strip() for k in form}
        if form["rol"] not in seguridad.ROLES_EQUIPO:
            error = "Elige un rol del equipo."
        else:
            clave = seguridad.clave_temporal()
            try:
                uid = cuentas.crear_usuario(form["email"], form["nombre"], form["rol"], clave, creador=g.usuario)
                u = db.uno("SELECT * FROM usuarios WHERE id = ?", (uid,))
                return render_template("admin/clave_equipo.html", u=u, clave=clave)
            except cuentas.ErrorDatos as e:
                error = str(e)
    lista = db.todos("SELECT * FROM usuarios WHERE rol != 'cliente' ORDER BY activo DESC, nombre")
    return render_template("admin/usuarios.html", lista=lista, form=form, error=error)


@bp.post("/usuarios/<int:uid>/estado")
def usuario_estado(uid):
    u = db.uno("SELECT * FROM usuarios WHERE id = ? AND rol != 'cliente'", (uid,))
    if not u:
        abort(404)
    if u["id"] == g.usuario["id"]:
        flash("No puedes desactivar tu propio usuario.", "error")
        return redirect(url_for("admin.usuarios"))
    nuevo = 0 if u["activo"] else 1
    with db.transaccion() as c:
        c.execute("UPDATE usuarios SET activo = ?, sesion_ver = sesion_ver + 1 WHERE id = ?", (nuevo, uid))
        auditoria.registrar("usuario.estado", f"usuario:{uid}",
                            {"texto": f"{'Reactivó' if nuevo else 'Desactivó'} al usuario {u['email']}."})
    flash("Usuario " + ("reactivado." if nuevo else "desactivado. Sus sesiones abiertas se cerraron."), "ok")
    return redirect(url_for("admin.usuarios"))


@bp.post("/usuarios/<int:uid>/clave")
def usuario_clave(uid):
    u = db.uno("SELECT * FROM usuarios WHERE id = ? AND rol != 'cliente'", (uid,))
    if not u:
        abort(404)
    clave = seguridad.clave_temporal()
    with db.transaccion() as c:
        c.execute("UPDATE usuarios SET clave_hash = ?, debe_cambiar_clave = 1, sesion_ver = sesion_ver + 1, fallos = 0,"
                  " bloqueado_hasta = NULL, totp_secreto = NULL, totp_pendiente = NULL WHERE id = ?",
                  (seguridad.hash_clave(clave), uid))
        auditoria.registrar("usuario.clave", f"usuario:{uid}",
                            {"texto": f"Restableció el acceso de {u['email']} (contraseña temporal y nueva verificación en dos pasos)."})
    u = db.uno("SELECT * FROM usuarios WHERE id = ?", (uid,))
    return render_template("admin/clave_equipo.html", u=u, clave=clave, restablecida=True)


@bp.route("/comisiones", methods=["GET", "POST"], endpoint="comisiones")
def comisiones_ver():
    sugerido = comisiones.periodo_anterior()
    if request.method == "POST":
        periodo = (request.form.get("periodo") or sugerido).strip()
        try:
            r = comisiones.cobrar(periodo, g.usuario)
            flash(f"Comisión de {comisiones.nombre_periodo(periodo)}: se cobró a {r['cobradas']} clientes"
                  + (f"; {r['ya_cobradas']} ya estaban cobrados." if r["ya_cobradas"] else "."), "ok")
            if r.get("incompletas"):
                flash(f"{r['incompletas']} cobros quedaron con la ejecución incompleta: revísalos en Operaciones.", "error")
            for e in r.get("errores", []):
                flash(f"No se cobró a {e}", "error")
        except comisiones.ErrorComision as e:
            flash(str(e), "error")
        return redirect(url_for("admin.comisiones"))
    return render_template("admin/comisiones.html", periodos=comisiones.resumen_periodos(), sugerido=sugerido,
                           tasa=comisiones.tasa(), nombre_periodo=comisiones.nombre_periodo)



@bp.route("/ejecucion", methods=["GET", "POST"], endpoint="ejecucion")
def ejecucion_ver():
    brk = exchange.broker()
    controles = saldos = None
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion in ("pausar", "reanudar"):
            if not seguridad.puede("ejecucion." + accion):
                abort(403)
            ejecucion.pausar(accion == "pausar", g.usuario, (request.form.get("motivo") or "").strip()[:200])
            flash("Ejecución en pausa: no se enviarán órdenes hasta reanudarla." if accion == "pausar"
                  else "Ejecución reanudada.", "ok")
            return redirect(url_for("admin.ejecucion"))
        try:
            if accion == "probar":
                controles = brk.verificar()
            elif accion == "saldos":
                saldos = brk.saldos()
        except exchange.ErrorExchange as e:
            flash(f"{brk.etiqueta}: {e}", "error")
    pausa = db.uno("SELECT a.*, u.nombre FROM ajustes a LEFT JOIN usuarios u ON u.id = a.por WHERE a.clave = ?", (ejecucion.PAUSA,))
    recientes = db.todos(
        "SELECT e.*, o.tipo, o.cliente_id, c.nombre FROM ejecuciones e JOIN operaciones o ON o.id = e.operacion_id"
        " JOIN clientes c ON c.id = o.cliente_id ORDER BY e.actualizado DESC, e.id DESC LIMIT 25")
    return render_template("admin/ejecucion.html", brk=brk, modo=exchange.modo(), pausada=ejecucion.pausada(), pausa=pausa,
                           controles=controles, saldos=saldos, libro=conciliacion.saldos_libro(), info=cartera.info_activos(),
                           incompletas=ejecucion.incompletas(), recientes=recientes, estados_tramo=ejecucion.ESTADOS_TRAMO,
                           fuente=precios.fuente())
