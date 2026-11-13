"""Panel del equipo: resumen, operaciones, clientes y cumplimiento."""
import csv
import io
from decimal import Decimal

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for

from datetime import timedelta

from . import (auditoria, cartera, comisiones, conciliacion, cuentas, db, documentos, ejecucion, exchange, graficos, operaciones,
               precios, seguridad)
from .dinero import fmt_num
from .formato import ESTADOS, TIPOS_OP, f_fecha, zona
from .tiempo import ahora_dt, iso, leer

bp = Blueprint("equipo", __name__, url_prefix="/equipo")

PALETA = ["#1D3FE0", "#F5A524", "#22B8A0", "#A66BFA", "#E3567A", "#7F93B0", "#E3B81F", "#3CA0E8", "#5BBF6A", "#C9423A"]


@bp.before_request
def _guardia():
    r = seguridad.exigir_sesion()
    if r:
        return r
    if not seguridad.puede("equipo.ver"):
        abort(403)
    return None


def _cliente_o_404(cid):
    c = db.uno("SELECT c.*, u.email, u.activo AS usuario_activo FROM clientes c LEFT JOIN usuarios u ON u.id = c.usuario_id"
               " WHERE c.id = ?", (cid,))
    if not c:
        abort(404)
    return c


@bp.get("/")
def resumen():
    pr = precios.vigentes()
    casa = cartera.resumen_casa(pr)
    vista = request.args.get("vista", "activo")
    clientes = db.todos("SELECT id, nombre, modelo, kyc_estado FROM clientes ORDER BY nombre")
    modelos = {m["codigo"]: m for m in db.todos("SELECT * FROM modelos")}
    abiertas = db.todos("SELECT * FROM operaciones WHERE estado IN ('pendiente', 'primera_firma', 'ejecutando')")
    neto = sum(o["monto_cent"] if o["tipo"] == "aporte" else -o["monto_cent"] for o in abiertas)
    if vista == "modelo":
        grupos = [{"label": modelos[k]["nombre"], "value": v, "col": modelos[k]["color"]} for k, v in casa["por_modelo"].items()]
    elif vista == "cliente":
        nombres = {c["id"]: c["nombre"] for c in clientes}
        grupos = [{"label": nombres[k], "value": v, "col": PALETA[i % len(PALETA)]}
                  for i, (k, v) in enumerate(sorted(casa["por_cliente"].items(), key=lambda x: -x[1]))]
    else:
        vista = "activo"
        grupos = [{"label": a["activo"] if a["activo"] != "USD" else "Saldo USD", "value": a["valor"], "col": a["color"]}
                  for a in casa["activos"]]
    top = sorted(((casa["por_cliente"].get(c["id"], 0), c) for c in clientes), key=lambda x: -x[0])[:6]
    serie = cartera.serie_casa()
    graf = graficos.linea(serie) if casa["total"] else None
    hoy = ahora_dt().astimezone(zona()).date()
    dias = [hoy - timedelta(days=13 - i) for i in range(14)]
    flujo = {d: [0, 0] for d in dias}
    for o in db.todos("SELECT tipo, liquidado_cent, resuelto_ts FROM operaciones WHERE estado = 'liquidada' AND tipo IN ('aporte', 'retiro')"
                      " AND resuelto_ts >= ?", (iso(ahora_dt() - timedelta(days=15)),)):
        d = leer(o["resuelto_ts"]).astimezone(zona()).date()
        if d in flujo:
            flujo[d][0 if o["tipo"] == "aporte" else 1] += o["liquidado_cent"]
    barras = graficos.barras([(f"{d.isoformat()}T12:00:00Z", a, r) for d, (a, r) in flujo.items()])
    entradas = sum(a for a, _ in flujo.values())
    salidas = sum(r for _, r in flujo.values())
    mas_antigua = min((o["creado"] for o in abiertas), default=None)
    ult_comision = (comisiones.resumen_periodos(1) or [None])[0]
    return render_template("equipo/resumen.html", casa=casa, vista=vista, datos3d={"titulo": "Activos bajo gestión", "grupos": grupos},
                           clientes=clientes, abiertas=abiertas, neto=neto, top=top, alertas=operaciones.alertas()[:6],
                           con_saldo=sum(1 for v in casa["por_cliente"].values() if v > 0), graf=graf, barras=barras,
                           entradas=entradas, salidas=salidas, mas_antigua=mas_antigua, ult_comision=ult_comision,
                           conc=conciliacion.estado())


@bp.get("/operaciones", endpoint="operaciones")
def operaciones_lista():
    filtro = request.args.get("ver", "abiertas")
    condiciones = {"abiertas": "o.estado IN ('pendiente', 'primera_firma', 'ejecutando')", "liquidadas": "o.estado = 'liquidada'",
                   "rechazadas": "o.estado IN ('rechazada', 'cancelada')", "todas": "1 = 1"}
    if filtro not in condiciones:
        filtro = "abiertas"
    orden = "o.creado ASC" if filtro == "abiertas" else "o.creado DESC"
    ops = db.todos(
        "SELECT o.*, c.nombre, c.documento, c.kyc_estado, c.origen_fondos FROM operaciones o JOIN clientes c ON c.id = o.cliente_id"
        f" WHERE {condiciones[filtro]} ORDER BY {orden}, o.id LIMIT 300")
    return render_template("equipo/operaciones.html", ops=ops, filtro=filtro,
                           requiere_origen=operaciones.requiere_origen, requiere_doble=operaciones.requiere_doble_firma)



@bp.route("/operaciones/<int:opid>", methods=["GET"])
def operacion(opid):
    op = db.uno("SELECT * FROM operaciones WHERE id = ?", (opid,))
    if not op:
        abort(404)
    cli = _cliente_o_404(op["cliente_id"])
    usuarios = {u["id"]: u for u in db.todos("SELECT id, nombre, rol FROM usuarios")}
    ordenes = db.todos("SELECT * FROM ordenes WHERE operacion_id = ? ORDER BY id", (opid,))
    asientos = db.todos("SELECT * FROM libro WHERE operacion_id = ? ORDER BY id", (opid,))
    pr = precios.vigentes()
    plan = []
    if op["estado"] in operaciones.ESTADOS_ABIERTOS and op["tipo"] == "aporte":
        for a, pb in cartera.pesos_modelo(op["modelo"]):
            usd = op["monto_cent"] * pb // 10000
            p = pr.get(a)
            plan.append({"activo": a, "pb": pb, "usd": usd, "precio": p["precio"] if p else None,
                         "unidades": (Decimal(usd) / 100 / p["precio"]) if p else None})
    _, valor = cartera.posiciones(cli["id"], pr)
    modelo = db.uno("SELECT * FROM modelos WHERE codigo = ?", (op["modelo"],)) if op["modelo"] else None
    return render_template("equipo/operacion.html", op=op, cli=cli, usuarios=usuarios, ordenes=ordenes, asientos=asientos,
                           requisitos=operaciones.requisitos(op, cli, g.usuario), plan=plan, valor=valor, modelo=modelo,
                           doble=operaciones.requiere_doble_firma(op), tramos=ejecucion.tramos(opid),
                           estados_tramo=ejecucion.ESTADOS_TRAMO, pausada=ejecucion.pausada(), modo=exchange.modo())


@bp.post("/operaciones/<int:opid>/reintentar", endpoint="reintentar")
@seguridad.requiere("operaciones.aprobar")
def reintentar(opid):
    try:
        r = ejecucion.reintentar(opid, g.usuario)
        flash("Ejecución completada y operación liquidada." if r == "liquidada" else
              "La ejecución sigue incompleta. Revisa la nota de cada tramo.", "ok" if r == "liquidada" else "error")
    except ejecucion.ErrorEjecucion as e:
        flash(str(e), "error")
    return redirect(url_for("equipo.operacion", opid=opid))


@bp.post("/operaciones/<int:opid>/aprobar")
@seguridad.requiere("operaciones.aprobar")
def aprobar(opid):
    try:
        r = operaciones.aprobar(opid, g.usuario)
        if r == "incompleta":
            flash(f"Operación #{opid} aprobada, pero la ejecución quedó incompleta. Revisa los tramos y reintenta.", "error")
        else:
            flash("Primera firma registrada. Falta la segunda firma de Cumplimiento." if r == "primera_firma"
                  else f"Operación #{opid} aprobada y liquidada.", "ok")
    except operaciones.ErrorNegocio as e:
        flash(str(e), "error")
    return redirect(url_for("equipo.operacion", opid=opid))


@bp.post("/operaciones/<int:opid>/rechazar")
@seguridad.requiere("operaciones.aprobar")
def rechazar(opid):
    try:
        operaciones.rechazar(opid, g.usuario, request.form.get("motivo"))
        flash(f"Operación #{opid} rechazada.", "ok")
    except operaciones.ErrorNegocio as e:
        flash(str(e), "error")
    return redirect(url_for("equipo.operacion", opid=opid))


@bp.get("/clientes")
def clientes():
    q = (request.args.get("q") or "").strip()
    sql = ("SELECT c.*, u.email FROM clientes c LEFT JOIN usuarios u ON u.id = c.usuario_id")
    args = ()
    if q:
        sql += " WHERE c.nombre LIKE ? OR c.documento LIKE ? OR u.email LIKE ?"
        args = (f"%{q}%",) * 3
    filas = db.todos(sql + " ORDER BY c.nombre LIMIT 500", args)
    casa = cartera.resumen_casa()
    modelos = {m["codigo"]: m["nombre"] for m in db.todos("SELECT codigo, nombre FROM modelos")}
    return render_template("equipo/clientes.html", filas=filas, q=q, valores=casa["por_cliente"], modelos=modelos)


@bp.route("/clientes/nuevo", methods=["GET", "POST"])
@seguridad.requiere("clientes.crear")
def cliente_nuevo():
    error = None
    form = {k: "" for k in ("nombre", "documento", "tipo", "telefono", "email", "perfil_riesgo", "modelo")}
    form.update(tipo="persona", perfil_riesgo="moderado", modelo="equilibrio")
    if request.method == "POST":
        form = {k: (request.form.get(k) or "").strip() for k in form}
        try:
            cid, clave = cuentas.crear_cliente(form, creador=g.usuario)
            cli = _cliente_o_404(cid)
            return render_template("equipo/clave_temporal.html", cli=cli, clave=clave, nuevo=True)
        except cuentas.ErrorDatos as e:
            error = str(e)
    return render_template("equipo/cliente_nuevo.html", form=form, error=error, modelos=cartera.modelos())


@bp.get("/clientes/<int:cid>")
def cliente(cid):
    cli = _cliente_o_404(cid)
    filas, total = cartera.posiciones(cid)
    ops = db.todos("SELECT * FROM operaciones WHERE cliente_id = ? ORDER BY creado DESC LIMIT 50", (cid,))
    usuarios = {u["id"]: u for u in db.todos("SELECT id, nombre FROM usuarios")}
    modelo = db.uno("SELECT * FROM modelos WHERE codigo = ?", (cli["modelo"],))
    acepto = db.uno("SELECT terminos_version, terminos_ts FROM usuarios WHERE id = ?", (cli["usuario_id"],)) if cli["usuario_id"] else None
    return render_template("equipo/cliente.html", cli=cli, filas=filas, total=total, ops=ops, usuarios=usuarios,
                           modelo=modelo, aportado=cartera.aportado_neto(cid), legajo=documentos.legajo(cli),
                           tipos=documentos.TIPOS[cli["tipo"]], estados_doc=documentos.ESTADOS, acepto=acepto,
                           faltan=documentos.faltantes(cli), periodos=cartera.periodos_cliente(cli))


@bp.post("/clientes/<int:cid>/kyc")
@seguridad.requiere("clientes.kyc")
def cliente_kyc(cid):
    _cliente_o_404(cid)
    try:
        cuentas.marcar_kyc(cid, request.form.get("estado"), request.form.get("nota"), g.usuario)
        flash("Verificación actualizada.", "ok")
    except cuentas.ErrorDatos as e:
        flash(str(e), "error")
    return redirect(url_for("equipo.cliente", cid=cid))


@bp.post("/clientes/<int:cid>/origen-fondos")
@seguridad.requiere("clientes.origen")
def cliente_origen(cid):
    _cliente_o_404(cid)
    try:
        cuentas.registrar_origen(cid, request.form.get("origen"), g.usuario)
        flash("Origen de fondos registrado.", "ok")
    except cuentas.ErrorDatos as e:
        flash(str(e), "error")
    return redirect(url_for("equipo.cliente", cid=cid))


@bp.post("/clientes/<int:cid>/clave")
@seguridad.requiere("clientes.clave")
def cliente_clave(cid):
    cli = _cliente_o_404(cid)
    if not cli["usuario_id"]:
        abort(400)
    clave = seguridad.clave_temporal()
    with db.transaccion() as c:
        c.execute("UPDATE usuarios SET clave_hash = ?, debe_cambiar_clave = 1, sesion_ver = sesion_ver + 1, fallos = 0,"
                  " bloqueado_hasta = NULL WHERE id = ?", (seguridad.hash_clave(clave), cli["usuario_id"]))
        auditoria.registrar("cliente.clave", f"cliente:{cid}",
                            {"texto": f"Generó una contraseña temporal para {cli['nombre']}."})
    return render_template("equipo/clave_temporal.html", cli=cli, clave=clave, nuevo=False)


@bp.get("/cumplimiento")
@seguridad.requiere("cumplimiento.ver")
def cumplimiento():
    pendientes = db.todos("SELECT * FROM clientes WHERE kyc_estado != 'verificado' ORDER BY creado")
    return render_template("equipo/cumplimiento.html", alertas=operaciones.alertas(), cadena=auditoria.verificar(),
                           pendientes=pendientes)


@bp.get("/bitacora")
@seguridad.requiere("cumplimiento.ver")
def bitacora():
    q = (request.args.get("q") or "").strip()
    pagina = max(1, request.args.get("p", 1, type=int))
    sql, args = "SELECT * FROM bitacora", ()
    if q:
        sql += " WHERE actor LIKE ? OR accion LIKE ? OR detalle LIKE ?"
        args = (f"%{q}%",) * 3
    filas = db.todos(sql + " ORDER BY id DESC LIMIT 51 OFFSET ?", args + ((pagina - 1) * 50,))
    return render_template("equipo/bitacora.html", filas=filas[:50], hay_mas=len(filas) > 50, pagina=pagina, q=q,
                           texto=auditoria.texto)


@bp.get("/reportes/operaciones.csv")
@seguridad.requiere("reportes.exportar")
def reporte_operaciones():
    desde = request.args.get("desde") or "2000-01-01"
    hasta = request.args.get("hasta") or "2999-12-31"
    filas = db.todos(
        "SELECT o.*, c.nombre, c.documento, c.tipo AS tipo_cliente FROM operaciones o JOIN clientes c ON c.id = o.cliente_id"
        " WHERE substr(o.creado, 1, 10) BETWEEN ? AND ? ORDER BY o.creado", (desde, hasta))
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Operación", "Fecha", "Cliente", "Documento", "Tipo de cliente", "Tipo", "Estado", "Monto USD",
                "Liquidado USD", "Referencia", "Motivo"])
    for o in filas:
        w.writerow([o["id"], f_fecha(o["creado"]), o["nombre"], o["documento"], o["tipo_cliente"], TIPOS_OP[o["tipo"]],
                    ESTADOS[o["estado"]][1], fmt_num(Decimal(o["monto_cent"]) / 100),
                    fmt_num(Decimal(o["liquidado_cent"]) / 100) if o["liquidado_cent"] is not None else "",
                    o["referencia"] or "", o["motivo"] or ""])
    auditoria.registrar("reporte.exportado", "operaciones",
                        {"texto": f"Exportó el reporte de operaciones del {desde} al {hasta} ({len(filas)} filas)."})
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="operaciones-{desde}-{hasta}.csv"'})


@bp.post("/clientes/<int:cid>/documentos")
@seguridad.requiere("documentos.subir")
def cliente_documento(cid):
    cli = _cliente_o_404(cid)
    archivo = request.files.get("archivo")
    try:
        if not archivo or not archivo.filename:
            raise documentos.ErrorDocumento("Elige un archivo.")
        documentos.guardar(cli, request.form.get("tipo"), archivo.filename, archivo.read(), g.usuario)
        flash("Documento agregado al legajo.", "ok")
    except documentos.ErrorDocumento as e:
        flash(str(e), "error")
    return redirect(url_for("equipo.cliente", cid=cid) + "#legajo")


@bp.post("/documentos/<int:did>/revisar")
@seguridad.requiere("documentos.revisar")
def documento_revisar(did):
    d = db.uno("SELECT cliente_id FROM documentos WHERE id = ?", (did,))
    if not d:
        abort(404)
    try:
        documentos.revisar(did, request.form.get("estado"), request.form.get("nota"), g.usuario)
        flash("Revisión guardada.", "ok")
    except documentos.ErrorDocumento as e:
        flash(str(e), "error")
    destino = request.form.get("volver")
    if destino == "cola":
        return redirect(url_for("equipo.documentos"))
    return redirect(url_for("equipo.cliente", cid=d["cliente_id"]) + "#legajo")


@bp.get("/documentos", endpoint="documentos")
@seguridad.requiere("cumplimiento.ver")
def documentos_cola():
    return render_template("equipo/documentos.html", pendientes=documentos.pendientes_revision(),
                           nombre_tipo=documentos.nombre_tipo)



@bp.route("/conciliacion", methods=["GET", "POST"], endpoint="conciliacion")
@seguridad.requiere("cumplimiento.ver")
def conciliacion_ver():
    error = None
    valores = {}
    if request.method == "POST":
        if not seguridad.puede("conciliacion.registrar"):
            abort(403)
        valores = {a: request.form.get(f"real_{a}", "") for a in conciliacion.activos_a_conciliar()}
        try:
            conciliacion.registrar(valores, request.form.get("nota"), g.usuario)
            flash("Conciliación registrada.", "ok")
            return redirect(url_for("equipo.conciliacion"))
        except conciliacion.ErrorConciliacion as e:
            error = str(e)
    elif request.args.get("desde") == "exchange" and exchange.modo() == "binance":
        try:
            valores = conciliacion.valores_exchange()
            flash("Saldos de Binance cargados en el formulario. Completa el saldo bancario en dólares, revisa y registra.", "ok")
        except exchange.ErrorExchange as e:
            error = f"No se pudieron traer los saldos de Binance: {e}"
    info = cartera.info_activos()
    return render_template("equipo/conciliacion.html", libro=conciliacion.saldos_libro(), activos=conciliacion.activos_a_conciliar(),
                           info=info, historial=conciliacion.historial(), estado=conciliacion.estado(), error=error, valores=valores,
                           modo=exchange.modo())



@bp.get("/clientes/<int:cid>/estado-de-cuenta/<periodo>", endpoint="estado_mensual")
def estado_mensual(cid, periodo):
    cli = _cliente_o_404(cid)
    periodos = cartera.periodos_cliente(cli)
    if periodo not in periodos:
        abort(404)
    return render_template("estado_cuenta.html", cli=cli, ec=cartera.estado_cuenta(cli, periodo), periodos=periodos,
                           url_periodo=lambda p: url_for("equipo.estado_mensual", cid=cid, periodo=p),
                           url_csv=None, volver=url_for("equipo.cliente", cid=cid))
