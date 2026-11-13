"""Portal del cliente."""
import csv
import io
from decimal import Decimal

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for

from . import cartera, cuentas, db, documentos, graficos, operaciones, precios, seguridad
from .dinero import fmt_num, leer_monto
from .formato import f_fecha

bp = Blueprint("cliente", __name__, url_prefix="/cliente")


@bp.before_request
def _guardia():
    r = seguridad.exigir_sesion()
    if r:
        return r
    if g.usuario["rol"] != "cliente":
        abort(403)
    g.cliente = db.uno("SELECT * FROM clientes WHERE usuario_id = ?", (g.usuario["id"],))
    if not g.cliente:
        abort(403)
    return None


def datos3d(filas, titulo):
    return {"titulo": titulo, "grupos": [{"label": f["activo"] if f["activo"] != "USD" else "Saldo USD",
                                         "value": f["valor"], "col": f["color"]} for f in filas if f["valor"] > 0]}


def _abiertas(cid):
    return db.todos("SELECT * FROM operaciones WHERE cliente_id = ? AND estado IN ('pendiente', 'primera_firma')"
                    " ORDER BY creado DESC", (cid,))


@bp.get("/")
def inicio():
    c = g.cliente
    pr = precios.vigentes()
    ten = cartera.tenencias(c["id"])
    filas, total = cartera.posiciones(c["id"], pr, ten)
    serie = cartera.serie_tenencias(ten)
    graf = graficos.linea(serie) if total else None
    var7 = (graf["fin_valor"] - graf["inicio_valor"]) if graf else 0
    aportado = cartera.aportado_neto(c["id"])
    modelo = db.uno("SELECT * FROM modelos WHERE codigo = ?", (c["modelo"],))
    faltan = documentos.faltantes(c) if c["kyc_estado"] != "verificado" else []
    return render_template("cliente/inicio.html", filas=filas, total=total, graf=graf, var7=var7, aportado=aportado,
                           modelo=modelo, abiertas=_abiertas(c["id"]), faltan=faltan)


@bp.get("/cartera", endpoint="cartera")
def ver_cartera():
    c = g.cliente
    filas, total = cartera.posiciones(c["id"])
    return render_template("cliente/cartera.html", filas=filas, total=total,
                           datos3d=datos3d(filas, f"Cartera de {c['nombre'].split()[0]}"))


@bp.route("/invertir", methods=["GET", "POST"])
def invertir():
    c = g.cliente
    error = None
    form = {"monto": "", "modelo": c["modelo"], "referencia": "", "acepta_riesgo": ""}
    if request.method == "POST":
        form = {k: (request.form.get(k) or "").strip() for k in form}
        try:
            monto = leer_monto(form["monto"])
            opid = operaciones.solicitar_aporte(c, monto, form["modelo"], form["referencia"], g.usuario,
                                                acepta_riesgo=form["acepta_riesgo"] == "si")
            flash(f"Solicitud de aporte #{opid} enviada. El equipo confirma la recepción del dinero y, al aprobarla, "
                  "se compra al precio de ese momento.", "ok")
            return redirect(url_for("cliente.movimientos"))
        except (ValueError, operaciones.ErrorNegocio) as e:
            error = str(e)
    pr = precios.vigentes()
    modelos = cartera.modelos()
    for m in modelos:
        m["fuera"] = operaciones.fuera_de_perfil(c, m)
    info = cartera.info_activos()
    _, total = cartera.posiciones(c["id"], pr)
    pend_retiro = sum(o["monto_cent"] for o in _abiertas(c["id"]) if o["tipo"] == "retiro")
    datos = {
        "minimo": current_app.config["APORTE_MINIMO_USD"] * 100,
        "precios": {a: str(p["precio"]) for a, p in pr.items()},
        "activos": {a: {"nombre": i["nombre"], "color": i["color"]} for a, i in info.items()},
        "modelos": {m["codigo"]: m["pesos"] for m in modelos},
        "fuera": [m["codigo"] for m in modelos if m["fuera"]],
    }
    return render_template("cliente/invertir.html", error=error, form=form, modelos=modelos, info=info,
                           datos=datos, disponible=max(total - pend_retiro, 0))


@bp.post("/retiro")
def retiro():
    c = g.cliente
    try:
        monto = leer_monto(request.form.get("monto"))
        opid = operaciones.solicitar_retiro(c, monto, g.usuario)
        flash(f"Solicitud de retiro #{opid} enviada. Te avisamos cuando el equipo la apruebe.", "ok")
        return redirect(url_for("cliente.movimientos"))
    except (ValueError, operaciones.ErrorNegocio) as e:
        flash(str(e), "error")
        return redirect(url_for("cliente.invertir") + "#retirar")


@bp.get("/movimientos")
def movimientos():
    c = g.cliente
    filtro = request.args.get("ver", "todos")
    sql = "SELECT * FROM operaciones WHERE cliente_id = ?"
    if filtro == "abiertos":
        sql += " AND estado IN ('pendiente', 'primera_firma')"
    ops = db.todos(sql + " ORDER BY creado DESC, id DESC LIMIT 200", (c["id"],))
    ordenes = {}
    for o in db.todos("SELECT * FROM ordenes WHERE cliente_id = ? ORDER BY id", (c["id"],)):
        ordenes.setdefault(o["operacion_id"], []).append(o)
    modelos = {m["codigo"]: m["nombre"] for m in db.todos("SELECT codigo, nombre FROM modelos")}
    return render_template("cliente/movimientos.html", ops=ops, ordenes=ordenes, filtro=filtro, modelos=modelos,
                           periodos=cartera.periodos_cliente(c))


@bp.post("/operaciones/<int:opid>/cancelar")
def cancelar(opid):
    try:
        operaciones.cancelar(opid, g.cliente, g.usuario)
        flash("Solicitud cancelada.", "ok")
    except operaciones.ErrorNegocio as e:
        flash(str(e), "error")
    return redirect(url_for("cliente.movimientos"))


@bp.get("/estado-de-cuenta/<periodo>", endpoint="estado_mensual")
def estado_mensual(periodo):
    c = g.cliente
    periodos = cartera.periodos_cliente(c)
    if periodo not in periodos:
        abort(404)
    return render_template("estado_cuenta.html", cli=c, ec=cartera.estado_cuenta(c, periodo), periodos=periodos,
                           url_periodo=lambda p: url_for("cliente.estado_mensual", periodo=p),
                           url_csv=url_for("cliente.estado_cuenta"), volver=url_for("cliente.movimientos"))


@bp.get("/estado-de-cuenta.csv")
def estado_cuenta():
    c = g.cliente
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Fecha", "Operación", "Concepto", "Activo", "Cantidad", "Precio USD", "Importe USD"])
    filas = db.todos("SELECT l.*, o.precio AS precio_orden FROM libro l LEFT JOIN ordenes o ON o.operacion_id = l.operacion_id"
                     " AND o.activo = l.activo WHERE l.cliente_id = ? ORDER BY l.ts, l.id", (c["id"],))
    nombres = {"deposito": "Depósito", "compra": "Compra", "venta": "Venta", "pago_retiro": "Pago de retiro",
               "comision": "Comisión de gestión"}
    for f in filas:
        if f["activo"] == "USD":
            w.writerow([f_fecha(f["ts"]), f["operacion_id"], nombres[f["concepto"]], "USD", "", "",
                        fmt_num(Decimal(f["cantidad"]) / 100, 2)])
        else:
            w.writerow([f_fecha(f["ts"]), f["operacion_id"], nombres[f["concepto"]], f["activo"],
                        fmt_num(Decimal(f["cantidad"]) / 10 ** 8, 8), f["precio_orden"] or "", ""])
    nombre = "estado-de-cuenta-" + "".join(ch for ch in c["documento"] if ch.isalnum()) + ".csv"
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@bp.route("/perfil", methods=["GET", "POST"])
def perfil():
    c = g.cliente
    if request.method == "POST":
        archivo = request.files.get("archivo")
        try:
            if not archivo or not archivo.filename:
                raise documentos.ErrorDocumento("Elige un archivo.")
            documentos.guardar(c, request.form.get("tipo"), archivo.filename, archivo.read(), g.usuario)
            flash("Documento recibido. El equipo de Cumplimiento lo revisa y te avisa.", "ok")
        except documentos.ErrorDocumento as e:
            flash(str(e), "error")
        return redirect(url_for("cliente.perfil") + "#legajo")
    modelo = db.uno("SELECT * FROM modelos WHERE codigo = ?", (c["modelo"],))
    return render_template("cliente/perfil.html", legajo=documentos.legajo(c), modelo=modelo,
                           tipos=documentos.TIPOS[c["tipo"]], estados_doc=documentos.ESTADOS,
                           riesgo_max=operaciones.RIESGO_MAX[c["perfil_riesgo"]])


@bp.route("/condiciones", methods=["GET", "POST"])
def condiciones():
    u = g.usuario
    vigente = (u["terminos_version"] or 0) >= seguridad.TERMINOS_VERSION
    error = None
    if request.method == "POST" and not vigente:
        if request.form.get("acepto") == "si":
            cuentas.aceptar_terminos(u)
            flash("Gracias. Ya puedes usar tu cuenta.", "ok")
            return redirect(url_for("cliente.inicio"))
        error = "Para continuar tienes que marcar que leíste y aceptas las condiciones."
    return render_template("cliente/condiciones.html", vigente=vigente, error=error, version=seguridad.TERMINOS_VERSION,
                           comision=current_app.config["COMISION_ANUAL_PCT"])
