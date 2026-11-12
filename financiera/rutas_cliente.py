"""Portal del cliente."""
import csv
import io
from decimal import Decimal

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for

from . import cartera, db, operaciones, precios, seguridad
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


def _datos3d(filas, titulo):
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
    graf = cartera.grafico(serie) if total else None
    var7 = (graf["fin"] - graf["inicio"]) if graf else 0
    aportado = cartera.aportado_neto(c["id"])
    modelo = db.uno("SELECT * FROM modelos WHERE codigo = ?", (c["modelo"],))
    return render_template("cliente/inicio.html", filas=filas, total=total, graf=graf, var7=var7, aportado=aportado,
                           modelo=modelo, abiertas=_abiertas(c["id"]))


@bp.get("/cartera", endpoint="cartera")
def ver_cartera():
    c = g.cliente
    filas, total = cartera.posiciones(c["id"])
    primer = c["nombre"].split()[0]
    return render_template("cliente/cartera.html", filas=filas, total=total,
                           datos3d=_datos3d(filas, f"Cartera de {primer}"))



@bp.route("/invertir", methods=["GET", "POST"])
def invertir():
    c = g.cliente
    error = None
    form = {"monto": "", "modelo": c["modelo"], "referencia": ""}
    if request.method == "POST":
        form = {k: (request.form.get(k) or "").strip() for k in form}
        try:
            monto = leer_monto(form["monto"])
            opid = operaciones.solicitar_aporte(c, monto, form["modelo"], form["referencia"], g.usuario)
            flash(f"Solicitud de aporte #{opid} enviada. El equipo confirma la recepción del dinero y, al aprobarla, "
                  "se compra al precio de ese momento.", "ok")
            return redirect(url_for("cliente.movimientos"))
        except (ValueError, operaciones.ErrorNegocio) as e:
            error = str(e)
    pr = precios.vigentes()
    modelos = cartera.modelos()
    info = cartera.info_activos()
    _, total = cartera.posiciones(c["id"], pr)
    pend_retiro = sum(o["monto_cent"] for o in _abiertas(c["id"]) if o["tipo"] == "retiro")
    datos = {
        "minimo": current_app.config["APORTE_MINIMO_USD"] * 100,
        "precios": {a: str(p["precio"]) for a, p in pr.items()},
        "activos": {a: {"nombre": i["nombre"], "color": i["color"]} for a, i in info.items()},
        "modelos": {m["codigo"]: m["pesos"] for m in modelos},
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
    return render_template("cliente/movimientos.html", ops=ops, ordenes=ordenes, filtro=filtro, modelos=modelos)


@bp.post("/operaciones/<int:opid>/cancelar")
def cancelar(opid):
    try:
        operaciones.cancelar(opid, g.cliente, g.usuario)
        flash("Solicitud cancelada.", "ok")
    except operaciones.ErrorNegocio as e:
        flash(str(e), "error")
    return redirect(url_for("cliente.movimientos"))


@bp.get("/estado-de-cuenta.csv")
def estado_cuenta():
    c = g.cliente
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Fecha", "Operación", "Concepto", "Activo", "Cantidad", "Precio USD", "Importe USD"])
    filas = db.todos("SELECT l.*, o.precio AS precio_orden FROM libro l LEFT JOIN ordenes o ON o.operacion_id = l.operacion_id"
                     " AND o.activo = l.activo WHERE l.cliente_id = ? ORDER BY l.ts, l.id", (c["id"],))
    nombres = {"deposito": "Depósito", "compra": "Compra", "venta": "Venta", "pago_retiro": "Pago de retiro"}
    for f in filas:
        if f["activo"] == "USD":
            w.writerow([f_fecha(f["ts"]), f["operacion_id"], nombres[f["concepto"]], "USD", "", "", fmt_num(Decimal(f["cantidad"]) / 100, 2)])
        else:
            w.writerow([f_fecha(f["ts"]), f["operacion_id"], nombres[f["concepto"]], f["activo"],
                        fmt_num(Decimal(f["cantidad"]) / 10 ** 8, 8), f["precio_orden"] or "", ""])
    nombre = "estado-de-cuenta-" + c["documento"].replace(" ", "").replace(".", "") + ".csv"
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
