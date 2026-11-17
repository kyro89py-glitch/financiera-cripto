"""Administración: precios, comisiones, ejecución en el exchange y usuarios del equipo."""
import csv
import io

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for

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
    if request.endpoint in ("admin.panel", "admin.permisos", "admin.reporte") and seguridad.puede("panel.ver"):
        return None  # Cumplimiento ve el panel y la matriz de permisos, sin poder cambiar ajustes
    if g.usuario["rol"] != "admin":
        abort(403)
    return None


@bp.get("/precios", endpoint="precios")
def precios_ver():
    en_vivo, seg, fuente_vivo = precios.vivo()
    return render_template("admin/precios.html", fuente=precios.fuente(), activos=precios.activos(), vig=precios.vigentes(),
                           viejos=dict(precios.antiguos()), en_vivo=en_vivo, seg=seg, categorias=precios.CATEGORIAS,
                           custodia=set(cartera.activos_en_custodia()))


@bp.post("/precios/<codigo>/habilitar")
def moneda_habilitar(codigo):
    a = db.uno("SELECT * FROM activos WHERE codigo = ?", (codigo,))
    if a:
        nuevo = 0 if a["habilitado"] else 1
        with db.transaccion():
            db.ejecutar("UPDATE activos SET habilitado = ? WHERE codigo = ?", (nuevo, codigo))
            auditoria.registrar("activo.habilitado" if nuevo else "activo.suspendido", f"activo:{codigo}",
                                {"texto": f"{'Habilitó' if nuevo else 'Suspendió'} las compras de {codigo}."
                                          + ("" if nuevo else " Quien la tiene la puede seguir vendiendo.")}, usuario=g.usuario)
        flash(f"{codigo}: " + ("se puede comprar de nuevo." if nuevo else "compras suspendidas; las ventas siguen habilitadas."), "ok")
    return redirect(url_for("admin.precios"))



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
    from . import autorizaciones as aut
    if aut.activo():
        try:
            aut.solicitar("usuario_estado", {"uid": uid}, request.form.get("motivo"), g.usuario)
            flash("Pedido registrado: lo tiene que autorizar otra persona del equipo (Administración o Cumplimiento).", "ok")
        except aut.ErrorAutorizacion as e:
            flash(str(e), "error")
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
        from . import autorizaciones as aut
        if aut.activo():
            try:
                aut.solicitar("comision", {"periodo": periodo}, request.form.get("motivo"), g.usuario)
                flash("Pedido registrado: el cobro se hace cuando otra persona lo autorice.", "ok")
            except aut.ErrorAutorizacion as e:
                flash(str(e), "error")
            return redirect(url_for("admin.comisiones"))
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


@bp.route("/guaranies", methods=["GET", "POST"], endpoint="guaranies")
def guaranies():
    from . import guarani
    if request.method == "POST":
        try:
            guarani.fijar(guarani.leer(request.form.get("deposito")), guarani.leer(request.form.get("retiro")), g.usuario)
            flash("Tipo de cambio actualizado.", "ok")
            return redirect(url_for("admin.guaranies"))
        except (ValueError, guarani.ErrorCambio) as e:
            flash(str(e), "error")
    recientes = db.todos("SELECT o.*, c.nombre FROM operaciones o JOIN clientes c ON c.id = o.cliente_id WHERE o.cambio_pyg IS NOT NULL"
                         " ORDER BY o.id DESC LIMIT 15")
    return render_template("admin/guaranies.html", cambios=guarani.cambios(), recientes=recientes)


@bp.route("/respaldos", methods=["GET", "POST"])
@seguridad.requiere("respaldos.gestionar")
def respaldos():
    import os

    from . import respaldos as resp_mod
    if request.method == "POST":
        try:
            ruta = resp_mod.crear()
            r = resp_mod.probar(ruta)
            flash(f"Respaldo creado y verificado ({os.path.basename(ruta)})." if r["ok"]
                  else "El respaldo se creó pero la prueba de restauración falló: revisa el detalle.", "ok" if r["ok"] else "error")
        except Exception as e:  # noqa: BLE001 - se informa a la persona y queda en el registro
            current_app.logger.exception("respaldo")
            flash(f"No se pudo crear el respaldo: {e.__class__.__name__}.", "error")
        return redirect(url_for("admin.respaldos"))
    filas = db.todos("SELECT * FROM respaldos ORDER BY id DESC LIMIT 30")
    return render_template("admin/respaldos.html", filas=filas, carpeta=current_app.config["RESPALDOS_DIR"],
                           conservar=current_app.config["RESPALDOS_CONSERVAR"], externo=bool(current_app.config["RESPALDO_COMANDO"]))


# ---------- v0.20: panel de administración, límites y permisos ----------
@bp.get("/panel")
@seguridad.requiere("panel.ver")
def panel():
    from datetime import timedelta

    from . import antilavado, ejecucion, observabilidad
    from .tiempo import ahora_dt, iso
    d1, d7, d30 = (iso(ahora_dt() - timedelta(days=n)) for n in (1, 7, 30))
    uno = lambda sql, *a: db.uno(sql, a)["n"]  # noqa: E731
    clientes = uno("SELECT COUNT(*) AS n FROM clientes")
    usuarios = {
        "clientes": clientes, "nuevos7": uno("SELECT COUNT(*) AS n FROM clientes WHERE creado >= ?", d7),
        "nuevos30": uno("SELECT COUNT(*) AS n FROM clientes WHERE creado >= ?", d30),
        "verificados": uno("SELECT COUNT(*) AS n FROM clientes WHERE kyc_estado = 'verificado'"),
        "pendientes_kyc": uno("SELECT COUNT(*) AS n FROM clientes WHERE kyc_estado != 'verificado'"),
        "con_2fa": uno("SELECT COUNT(*) AS n FROM usuarios WHERE rol = 'cliente' AND totp_secreto IS NOT NULL"),
        "activos7": uno("SELECT COUNT(DISTINCT usuario_id) AS n FROM sesiones WHERE ultima >= ?", d7),
        "equipo": uno("SELECT COUNT(*) AS n FROM usuarios WHERE rol != 'cliente' AND activo = 1"),
    }
    vol = {k: db.uno("SELECT COALESCE(SUM(importe_cent), 0) AS v, COUNT(*) AS n FROM ordenes WHERE ts >= ?", (d,))
           for k, d in (("24 h", d1), ("7 días", d7), ("30 días", d30))}
    flujos = {t: db.uno("SELECT COALESCE(SUM(liquidado_cent), 0) AS v, COUNT(*) AS n FROM operaciones WHERE tipo = ? AND estado = 'liquidada'"
                        " AND resuelto_ts >= ?", (t, d30)) for t in ("aporte", "retiro")}
    envios = db.uno("SELECT COALESCE(SUM(valor_cent), 0) AS v, COUNT(*) AS n FROM transferencias WHERE ts >= ?", (d30,))
    activos_top = db.todos("SELECT o.activo, a.color, SUM(o.importe_cent) AS v, COUNT(*) AS n, COUNT(DISTINCT o.cliente_id) AS clientes"
                           " FROM ordenes o JOIN activos a ON a.codigo = o.activo WHERE o.ts >= ? GROUP BY o.activo ORDER BY v DESC LIMIT 8", (d30,))
    estado_salud, salud = observabilidad.chequeos()
    aml = {r["nivel"]: r["n"] for r in db.todos("SELECT nivel, COUNT(*) AS n FROM alertas_aml WHERE estado = 'abierta' GROUP BY nivel")}
    riesgos = []
    if aml.get("critica"):
        riesgos.append(("bad", f"{aml['critica']} coincidencia(s) con listas de sanciones sin resolver.", url_for("equipo.antilavado")))
    if aml.get("alta") or aml.get("media"):
        riesgos.append(("warn", f"{aml.get('alta', 0) + aml.get('media', 0)} alerta(s) antilavado abiertas.", url_for("equipo.antilavado")))
    if ejecucion.pausada():
        riesgos.append(("bad", "La ejecución de operaciones está en pausa.", url_for("admin.ejecucion")))
    if salud.get("ejecuciones_incompletas"):
        riesgos.append(("bad", f"{salud['ejecuciones_incompletas']} ejecución(es) a medias.", url_for("admin.ejecucion")))
    if salud.get("precios"):
        riesgos.append(("warn", "Precios desactualizados: no se ejecutan operaciones.", url_for("admin.precios")))
    if salud.get("ultimo_respaldo_h") is None or salud["ultimo_respaldo_h"] > 26:
        riesgos.append(("warn", "No hay un respaldo de las últimas 26 horas.", url_for("admin.respaldos") if seguridad.puede("respaldos.gestionar") else None))
    bloqueadas = uno("SELECT COUNT(*) AS n FROM usuarios WHERE bloqueado_hasta IS NOT NULL AND bloqueado_hasta > ?", iso(ahora_dt()))
    if bloqueadas:
        riesgos.append(("warn", f"{bloqueadas} cuenta(s) bloqueadas por intentos fallidos.", None))
    from . import autorizaciones
    pend = autorizaciones.pendientes()
    if pend:
        riesgos.append(("warn", f"{pend} acción(es) crítica(s) esperando autorización.", url_for("equipo.autorizaciones")))
    inc = uno("SELECT COUNT(*) AS n FROM incidencias WHERE estado IN ('abierta', 'en_curso') AND severidad IN ('alta', 'critica')")
    if inc:
        riesgos.append(("bad", f"{inc} incidencia(s) alta(s) o crítica(s) sin resolver.", url_for("equipo.incidencias")))
    consultas = uno("SELECT COUNT(*) AS n FROM consultas WHERE estado = 'abierta'")
    if consultas:
        riesgos.append(("info", f"{consultas} consulta(s) de clientes esperando respuesta.", url_for("equipo.soporte")))
    grandes = db.todos("SELECT o.*, c.nombre FROM ordenes o JOIN clientes c ON c.id = o.cliente_id WHERE o.ts >= ? ORDER BY o.importe_cent DESC LIMIT 8", (d7,))
    acciones = db.todos("SELECT b.ts, b.accion, b.detalle, u.nombre, u.rol FROM bitacora b JOIN usuarios u ON u.id = b.usuario_id"
                        " WHERE u.rol != 'cliente' ORDER BY b.id DESC LIMIT 15")
    return render_template("admin/panel.html", usuarios=usuarios, vol=vol, flujos=flujos, envios=envios, activos_top=activos_top,
                           riesgos=riesgos, grandes=grandes, acciones=acciones, salud=salud, estado_salud=estado_salud,
                           aml_total=sum(aml.values()), antilavado=antilavado)


@bp.route("/limites", methods=["GET", "POST"])
@seguridad.requiere("limites.editar")
def limites():
    from . import niveles
    from . import autorizaciones as aut
    if request.method == "POST" and aut.activo():
        pedido, malos = {}, []
        for clave in niveles.LIMITES:
            texto = (request.form.get(clave) or "").replace(".", "").replace(",", "").strip()
            if texto:
                if texto.isdigit():
                    pedido[clave] = int(texto)
                else:
                    malos.append(f"{niveles.LIMITES[clave][0]}: escribe un número entero de dólares.")
        for e in malos:
            flash(e, "error")
        try:
            aut.solicitar("limites", {"cambios": pedido}, request.form.get("motivo"), g.usuario)
            flash("Pedido registrado: los límites cambian cuando otra persona lo autorice.", "ok")
        except aut.ErrorAutorizacion as e:
            flash(str(e), "error")
        return redirect(url_for("admin.limites"))
    if request.method == "POST":
        cambios, errores = 0, []
        for clave in niveles.LIMITES:
            texto = (request.form.get(clave) or "").replace(".", "").replace(",", "").strip()
            if not texto:
                continue
            try:
                cambios += niveles.fijar(clave, int(texto), g.usuario)
            except ValueError as e:
                errores.append(str(e) if "elige" in str(e) else f"{niveles.LIMITES[clave][0]}: escribe un número entero de dólares.")
        for e in errores:
            flash(e, "error")
        if cambios:
            flash(f"{cambios} límite(s) actualizados. El cambio quedó en la bitácora.", "ok")
        return redirect(url_for("admin.limites"))
    filas = [(k, t, d, niveles.valor(k), current_app.config[k], mn, mx) for k, (t, d, mn, mx) in niveles.LIMITES.items()]
    return render_template("admin/limites.html", filas=filas, dual=aut.activo(),
                           pendientes=db.todos("SELECT * FROM autorizaciones WHERE accion = 'limites' AND estado = 'pendiente'"))


@bp.get("/permisos")
@seguridad.requiere("panel.ver")
def permisos():
    equipo = db.todos("SELECT nombre, email, rol, activo, totp_secreto IS NOT NULL AS dos_pasos, ultimo_ingreso FROM usuarios"
                      " WHERE rol != 'cliente' ORDER BY rol, nombre")
    return render_template("admin/permisos.html", permisos=seguridad.PERMISOS, descripcion=seguridad.DESCRIPCION_PERMISOS,
                           roles=seguridad.ROLES_EQUIPO, equipo=equipo)


@bp.get("/panel/reporte.csv", endpoint="reporte")
@seguridad.requiere("reportes.exportar")
def reporte():
    """Indicadores agregados de un período (sin datos personales) para reportes internos o regulatorios."""
    from datetime import timedelta

    from .tiempo import ahora_dt, iso
    try:
        dias = max(1, min(366, int(request.args.get("dias") or 30)))
    except ValueError:
        dias = 30
    desde = iso(ahora_dt() - timedelta(days=dias))
    uno = lambda sql, *a: db.uno(sql, a)  # noqa: E731
    filas = [
        ("Clientes nuevos", uno("SELECT COUNT(*) AS n FROM clientes WHERE creado >= ?", desde)["n"], ""),
        ("Identidades verificadas (total)", uno("SELECT COUNT(*) AS n FROM clientes WHERE kyc_estado = 'verificado'")["n"], ""),
        ("Órdenes de compra y venta", uno("SELECT COUNT(*) AS n FROM ordenes WHERE ts >= ?", desde)["n"], ""),
        ("Volumen operado (USD)", uno("SELECT COALESCE(SUM(importe_cent), 0) AS n FROM ordenes WHERE ts >= ?", desde)["n"] / 100, ""),
        ("Órdenes ejecutadas en el simulador", uno("SELECT COUNT(*) AS n FROM ordenes WHERE ts >= ? AND venue != 'binance'", desde)["n"], "no son operaciones reales"),
        ("Depósitos acreditados (USD)", uno("SELECT COALESCE(SUM(liquidado_cent), 0) AS n FROM operaciones WHERE tipo = 'aporte' AND estado = 'liquidada' AND resuelto_ts >= ?", desde)["n"] / 100, ""),
        ("Retiros pagados (USD)", uno("SELECT COALESCE(SUM(liquidado_cent), 0) AS n FROM operaciones WHERE tipo = 'retiro' AND estado = 'liquidada' AND resuelto_ts >= ?", desde)["n"] / 100, ""),
        ("Transferencias internas", uno("SELECT COUNT(*) AS n FROM transferencias WHERE ts >= ?", desde)["n"], ""),
        ("Valor transferido internamente (USD)", uno("SELECT COALESCE(SUM(valor_cent), 0) AS n FROM transferencias WHERE ts >= ?", desde)["n"] / 100, ""),
        ("Comisiones de gestión cobradas (USD)", uno("SELECT COALESCE(SUM(liquidado_cent), 0) AS n FROM operaciones WHERE tipo = 'comision' AND estado = 'liquidada' AND resuelto_ts >= ?", desde)["n"] / 100, ""),
        ("Alertas antilavado generadas", uno("SELECT COUNT(*) AS n FROM alertas_aml WHERE creada >= ?", desde)["n"], ""),
        ("Incidencias registradas", uno("SELECT COUNT(*) AS n FROM incidencias WHERE creada >= ?", desde)["n"], ""),
        ("Acciones críticas autorizadas", uno("SELECT COUNT(*) AS n FROM autorizaciones WHERE estado = 'ejecutada' AND resuelta >= ?", desde)["n"], ""),
    ]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["indicador", "valor", "nota"])
    w.writerow(["periodo", f"últimos {dias} días hasta {iso(ahora_dt())}", ""])
    for f in filas:
        w.writerow([f[0], str(f[1]).replace(".", ","), f[2]])
    auditoria.registrar("reporte.exportado", None, {"texto": f"Exportó el resumen de indicadores de los últimos {dias} días."})
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="indicadores-{dias}d.csv"'})
