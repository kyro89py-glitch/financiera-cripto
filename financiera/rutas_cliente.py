"""Portal del cliente."""
import csv
import io
from decimal import Decimal

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for

from . import alertas, cartera, programadas, cuentas, db, documentos, graficos, guarani, operaciones, planes, precios, seguridad, limites, comprobantes, dinero
from .dinero import fmt_num, leer_monto, valor_cent
from .formato import ESTADOS, f_fecha

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


def _mercado():
    out = precios.mercado()
    for m in out:
        m["chispa"] = graficos.chispa(m["serie"])
    return out


def _abiertas(cid):
    return db.todos("SELECT * FROM operaciones WHERE cliente_id = ? AND estado IN ('pendiente', 'primera_firma', 'ejecutando')"
                    " ORDER BY creado DESC", (cid,))


@bp.get("/")
def inicio():
    c = g.cliente
    pr = precios.vigentes()
    ten = cartera.tenencias(c["id"])
    filas, total = cartera.posiciones(c["id"], pr, ten)
    aportado = cartera.aportado_neto(c["id"])
    modelo = db.uno("SELECT * FROM modelos WHERE codigo = ?", (c["modelo"],))
    faltan = documentos.faltantes(c) if c["kyc_estado"] != "verificado" else []
    desv, mayor = cartera.desvio(filas, total, c["modelo"]) if total else ([], 0)
    bloq = cartera.bloqueado(c["id"], ten=ten)
    mercado = [m for m in _mercado() if m["habilitado"]]
    movibles = [m for m in mercado if m["cambio"] is not None and not m["estable"]]
    destacados = {"suben": sorted(movibles, key=lambda m: -m["cambio"])[:4], "bajan": sorted(movibles, key=lambda m: m["cambio"])[:4],
                  "principales": mercado[:4]}
    from .tiempo import leer
    rangos = {}
    for k, (dias, puntos) in list(cartera.RANGOS_PATRIMONIO.items()) + [("Todo", (None, 120))]:
        serie = cartera.serie_patrimonio(c["id"], dias, puntos)
        if serie:
            rangos[k] = [[int(leer(t).timestamp() * 1000), v] for t, v in serie]
    abiertas = _abiertas(c["id"])
    cap = sum(m["cap"] or 0 for m in mercado)
    resumen = {"cap": cap, "volumen": sum(m["volumen"] or 0 for m in mercado),
               "dominancia": next((m["cap"] for m in mercado if m["codigo"] == "BTC"), 0) / cap * 100 if cap else None,
               "suben": sum(1 for m in movibles if m["cambio"] > 0), "bajan": sum(1 for m in movibles if m["cambio"] < 0)}
    costos = cartera.costos(c["id"])
    pr_v = precios.vigentes()
    no_realizado = sum(valor_cent(a, k["cantidad"], pr_v[a]["precio"]) - k["costo"] for a, k in costos.items()
                       if a in pr_v and k["cantidad"] > 0)
    from . import panel, preferencias
    pref = preferencias.leer(g.usuario["id"])
    ind = cartera.indicadores(c["id"], filas, total, ten)
    riesgo_d = panel.riesgo(c, filas, ind)
    vivo = {"ten": {a: u for a, u in ten.items() if u}, "precios": {a: float(p["precio"]) for a, p in pr_v.items()}}
    return render_template("cliente/inicio.html", pref=pref, modulos=preferencias.MODULOS, vivo=vivo,
                           rendimientos=panel.rendimientos(c["id"], total, mercado) if "rendimientos" not in pref["ocultos"] else [],
                           riesgo=riesgo_d, ranking=panel.ranking(filas, costos),
                           alertas_hoy=panel.alertas(c, g.usuario, filas, total, abiertas, ind),
                           sugerencias=panel.sugerencias(c, g.usuario, filas, total, mayor, riesgo_d, modelo),
                           frases=panel.resumen_mercado(mercado),
                           filas=filas, total=total, aportado=aportado, modelo=modelo,
                           abiertas=abiertas, faltan=faltan, rend=cartera.rendimiento(c["id"], total),
                           datos3d=datos3d(filas, ""), destacados=destacados, mayor_desvio=mayor, resumen=resumen,
                           disp_usd=ten.get("USD", 0) - bloq.get("USD", 0), reservado=operaciones.reservado_cent(c["id"]),
                           en_retiros=sum(o["monto_cent"] for o in abiertas if o["tipo"] == "retiro"),
                           ultimos=_movimientos(c)[:6], actividad=_actividad_mes(c["id"]),
                           ind=ind, no_realizado=no_realizado,
                           realizado=sum(k["realizado"] for k in costos.values()), rangos=rangos)


def _actividad_mes(cliente_id):
    """Resumen del mes en curso: cantidad e importe de cada tipo de movimiento."""
    from datetime import datetime

    from .formato import zona
    from .tiempo import iso
    hoy = datetime.now(zona())
    desde = iso(hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    out = {}
    for tipo, n, s in [(f["tipo"], f["n"], f["s"]) for f in db.todos(
            "SELECT tipo, COUNT(*) AS n, COALESCE(SUM(COALESCE(liquidado_cent, monto_cent)), 0) AS s FROM operaciones"
            " WHERE cliente_id = ? AND creado >= ? AND estado NOT IN ('rechazada', 'cancelada') GROUP BY tipo", (cliente_id, desde))]:
        out[tipo] = (n, s)
    e = db.uno("SELECT COUNT(*) AS n, COALESCE(SUM(valor_cent), 0) AS s FROM transferencias WHERE (de_cliente = ? OR a_cliente = ?)"
               " AND ts >= ?", (cliente_id, cliente_id, desde))
    out["envios"] = (e["n"], e["s"])
    out["mes"] = hoy
    return out


@bp.post("/operar")
@limites.idempotente("operar")
def operar():
    activo = (request.form.get("activo") or "").upper()
    lado = request.form.get("lado")
    todo = request.form.get("todo") == "si"
    destino = _volver(activo)
    try:
        monto = 0 if (todo and lado == "venta") else leer_monto(request.form.get("monto"))
    except ValueError:
        flash("Escribe el monto en dólares, por ejemplo 250 o 250,50.", "error")
        return redirect(destino)
    # Toma de ganancia y corte de pérdida opcionales para una compra a mercado: se validan ANTES de comprar, para que
    # nunca quede una compra sin la protección que la persona pidió.
    from .dinero import leer_precio
    tp = sl = None
    try:
        if lado == "compra" and (request.form.get("tp") or "").strip():
            tp = leer_precio(request.form.get("tp"))
        if lado == "compra" and (request.form.get("sl") or "").strip():
            sl = leer_precio(request.form.get("sl"))
    except ValueError:
        flash("Escribe los precios de toma de ganancia y corte de pérdida como números, por ejemplo 72000.", "error")
        return redirect(destino)
    vig = precios.vigentes().get(activo)
    if vig and tp is not None and tp <= vig["precio"]:
        flash("La toma de ganancia tiene que estar por encima del precio actual.", "error")
        return redirect(destino)
    if vig and sl is not None and not (0 < sl < vig["precio"]):
        flash("El corte de pérdida tiene que estar por debajo del precio actual.", "error")
        return redirect(destino)
    try:
        opid, r = operaciones.operar(g.cliente, activo, lado, monto, g.usuario, todo=todo)
    except operaciones.ErrorNegocio as e:
        flash(str(e), "error")
        return redirect(destino)
    proteccion = ""
    if r == "liquidada" and (tp or sl):
        neto = db.uno("SELECT COALESCE(SUM(cantidad), 0) AS u FROM libro WHERE operacion_id = ? AND activo = ?", (opid, activo))["u"]
        try:
            if tp and sl:
                programadas.crear_oco(g.cliente, activo, "venta", tp, sl, 0, g.usuario, cantidad=neto, proteccion=True)
                proteccion = " Quedaron programadas la toma de ganancia y el corte de pérdida (OCO): cuando se active una, la otra se cancela."
            else:
                programadas.crear(g.cliente, activo, "venta", tp or sl, 0, g.usuario, cantidad=neto, origen="tp" if tp else "sl")
                proteccion = " Quedó programada la " + ("toma de ganancia." if tp else "orden de corte de pérdida.")
        except operaciones.ErrorNegocio as e:
            proteccion = f" Atención: no se pudo programar la protección ({e}). Prográmala desde Órdenes abiertas."
    if r == "liquidada":
        o = db.uno("SELECT * FROM ordenes WHERE operacion_id = ?", (opid,))
        from .dinero import fmt_precio, fmt_unidades, fmt_usd
        flash(f"{'Compraste' if lado == 'compra' else 'Vendiste'} {fmt_unidades(o['cantidad'], activo)} a {fmt_precio(Decimal(o['precio']))} "
              f"por {fmt_usd(o['importe_cent'])}." + proteccion, "warn" if "Atención" in proteccion else "ok")
    else:
        flash("Tu orden quedó en proceso: el equipo ya fue avisado y la vas a ver en Movimientos.", "warn")
    return redirect(destino)


def _volver(activo):
    """Página a la que se vuelve después de operar: la que mandó el formulario (si es de la casa) o la de la moneda."""
    v = request.form.get("volver") or ""
    if v.startswith(("/trading", "/mercado", "/cliente")) and "//" not in v and "\\" not in v:
        return v
    return url_for("auth.moneda", codigo=activo) if activo.isalnum() else url_for("auth.mercado")


TIPOS_ORDEN = {  # tipo elegido en Trading -> (lado, condición que tiene que cumplir el precio respecto del actual)
    ("limite", "compra"): ("menor", "Una compra límite se activa cuando el precio baja: elige un precio menor al actual."),
    ("stop", "compra"): ("mayor", "Una compra stop se activa cuando el precio sube: elige un precio mayor al actual."),
    ("limite", "venta"): ("mayor", "Una venta límite se activa cuando el precio sube: elige un precio mayor al actual."),
    ("stop", "venta"): ("menor", "Un stop de venta se activa cuando el precio baja: elige un precio menor al actual."),
}


@bp.post("/programadas")
@limites.idempotente("programada")
def programada_crear():
    activo = (request.form.get("activo") or "").upper()
    todo = request.form.get("todo") == "si"
    try:
        from .dinero import leer_precio
        monto = 0 if todo else leer_monto(request.form.get("monto"))
        precio = leer_precio(request.form.get("precio"))
        if request.form.get("tipo") == "oco":
            stop = leer_precio(request.form.get("precio_stop"))
            programadas.crear_oco(g.cliente, activo, request.form.get("lado"), precio, stop, monto, g.usuario, todo=todo)
            flash("OCO programada: dos órdenes enlazadas. Cuando se active una, la otra se cancela sola.", "ok")
            return redirect(_volver(activo) + ("" if request.form.get("volver") else "#programadas"))
        regla = TIPOS_ORDEN.get((request.form.get("tipo"), request.form.get("lado")))
        vig = precios.vigentes().get(activo)
        if regla and vig and ((regla[0] == "menor" and precio >= vig["precio"]) or (regla[0] == "mayor" and precio <= vig["precio"])):
            raise operaciones.ErrorNegocio(regla[1])
        programadas.crear(g.cliente, activo, request.form.get("lado"), precio, monto, g.usuario, todo=todo)
        flash("Orden programada. Se ejecuta sola cuando el precio llegue a ese nivel y te avisamos.", "ok")
    except (ValueError, operaciones.ErrorNegocio) as e:
        flash(str(e), "error")
    return redirect(_volver(activo) + ("" if request.form.get("volver") else "#programadas"))


@bp.post("/programadas/<int:oid>/cancelar")
def programada_cancelar(oid):
    if programadas.cancelar(oid, g.cliente, g.usuario):
        flash("Orden programada cancelada.", "ok")
    return redirect(_volver((request.form.get("activo") or "").upper()) + ("" if request.form.get("volver") else "#programadas"))


@bp.route("/convertir", methods=["GET", "POST"])
@limites.idempotente("convertir")
def convertir():
    c = g.cliente
    pr = precios.vigentes()
    if request.method == "POST":
        de, a = (request.form.get("de") or "").upper(), (request.form.get("a") or "").upper()
        todo = request.form.get("todo") == "si" and de != "USD"
        try:
            monto = 0 if todo else leer_monto(request.form.get("monto"))
            flash(operaciones.convertir(c, de, a, monto, g.usuario, todo=todo), "ok")
            return redirect(url_for("cliente.cartera"))
        except (ValueError, operaciones.ErrorNegocio) as e:
            flash(str(e), "error")
    filas, total = cartera.posiciones(c["id"], pr)
    monedas = [{"codigo": x["codigo"], "nombre": x["nombre"], "color": x["color"]} for x in precios.activos()]
    datos = {"precios": {k: float(v["precio"]) for k, v in pr.items()}, "tengo": {f["activo"]: f["valor"] for f in filas}}
    return render_template("cliente/convertir.html", filas=filas, monedas=monedas, datos=datos,
                           de=(request.values.get("de") or "USD").upper(), a=(request.values.get("a") or "BTC").upper())


@bp.route("/enviar", methods=["GET", "POST"])
@limites.idempotente("enviar")
def enviar():
    from . import transferencias as tr
    c = g.cliente
    error, form = None, {}
    if request.method == "POST":
        form = request.form.to_dict()
        todo = form.get("todo") == "si"
        try:
            monto = 0 if todo else leer_monto(form.get("monto"))
            tr.enviar(c, form.get("destino"), form.get("activo"), monto, g.usuario, form.get("clave"), form.get("codigo"),
                      nota=form.get("nota"), todo=todo)
            dest = tr.buscar(form.get("destino"), c["id"])
            flash(f"Envío hecho a {tr.ocultar(dest['nombre']).rstrip('.')}. Ya lo tiene en su billetera.", "ok")
            return redirect(url_for("cliente.enviar"))
        except ValueError:
            error = "Escribe el monto en dólares, por ejemplo 50 o 50,25."
        except tr.ErrorEnvio as e:
            error = str(e)
        form.pop("clave", None)
        form.pop("codigo", None)
    filas, _ = cartera.posiciones(c["id"])
    return render_template("cliente/enviar.html", filas=filas, error=error, form=form, historial=tr.del_cliente(c["id"]),
                           hoy=tr.enviado_hoy(c["id"]), limite=tr.limite_dia(), dos_pasos=bool(g.usuario["totp_secreto"]),
                           tengo={f["activo"]: f["valor"] for f in filas})


@bp.get("/enviar/destinatario")
def destinatario():
    from . import transferencias as tr
    limites.exigir(("destinatario", f"u{g.usuario['id']}"), ("destinatario_ip", limites.ip()))
    d = tr.buscar(request.args.get("q"), g.cliente["id"])
    if not d:
        return {"ok": False, "texto": "No encontramos a otro cliente con ese dato."}
    if d["kyc_estado"] != "verificado":
        return {"ok": False, "texto": f"{tr.ocultar(d['nombre'])} todavía no puede recibir envíos."}
    nombre = tr.ocultar(d["nombre"])
    return {"ok": True, "texto": f"Vas a enviar a {nombre}" + ("" if nombre.endswith(".") else ".")}


@bp.post("/planes")
@limites.idempotente("plan")
def plan_crear():
    activo = (request.form.get("activo") or "").upper()
    try:
        planes.crear(g.cliente, activo, leer_monto(request.form.get("monto")), request.form.get("frecuencia"), g.usuario)
        flash("Compra automática programada. Te avisamos cada vez que se ejecute.", "ok")
    except (ValueError, operaciones.ErrorNegocio) as e:
        flash(str(e), "error")
    return redirect(_volver(activo) + "#automatica")


@bp.post("/planes/<int:pid>/cancelar")
def plan_cancelar(pid):
    if planes.cancelar(pid, g.cliente, g.usuario):
        flash("Compra automática cancelada.", "ok")
    destino = request.form.get("volver", "")
    return redirect(destino if destino.startswith("/") and not destino.startswith("//") else url_for("cliente.cartera"))


@bp.post("/alertas")
def alerta_crear():
    activo = (request.form.get("activo") or "").upper()
    if request.form.get("tipo") == "variacion":
        try:
            umbral = float((request.form.get("umbral") or "").replace(",", ".").replace("%", "").strip())
            alertas.crear_variacion(g.usuario, activo, umbral, request.form.get("sentido"))
            umb = f"{umbral:g}".replace(".", ",")
            flash(f"Listo: te avisamos cuando {activo} {'suba' if request.form.get('sentido') == 'sube' else 'baje'} "
                  f"{umb} % o más en 24 horas.", "ok")
        except ValueError:
            flash("Escribe la variación como número, por ejemplo 5.", "error")
        except operaciones.ErrorNegocio as e:
            flash(str(e), "error")
        return redirect(_volver(activo) + "#alertas")
    try:
        from .dinero import leer_precio
        vig = precios.vigentes().get(activo)
        _, sentido = alertas.crear(g.usuario, activo, leer_precio(request.form.get("precio")), vig["precio"] if vig else None)
        flash(f"Listo: te avisamos cuando {activo} {'suba' if sentido == 'sube' else 'baje'} a ese precio.", "ok")
    except (ValueError, operaciones.ErrorNegocio) as e:
        flash(str(e), "error")
    return redirect(_volver(activo) + "#alertas")


@bp.post("/alertas/<int:aid>/borrar")
def alerta_borrar(aid):
    alertas.borrar(aid, g.usuario)
    return redirect(_volver((request.form.get("activo") or "").upper()) + "#alertas")


@bp.get("/cartera", endpoint="cartera")
def ver_cartera():
    c = g.cliente
    filas, total = cartera.posiciones(c["id"])
    desv, mayor = cartera.desvio(filas, total, c["modelo"]) if total else ([], 0)
    modelo = db.uno("SELECT * FROM modelos WHERE codigo = ?", (c["modelo"],))
    costos = cartera.costos(c["id"])
    ten = cartera.tenencias(c["id"])
    bloq = cartera.bloqueado(c["id"], ten=ten)
    pend_retiro = sum(o["monto_cent"] for o in _abiertas(c["id"]) if o["tipo"] == "retiro")
    pend_aporte = sum(o["monto_cent"] for o in _abiertas(c["id"]) if o["tipo"] == "aporte")
    from . import preferencias
    moneda_ver = preferencias.leer(g.usuario["id"])["moneda"]
    realizado = sum(x["realizado"] for x in costos.values())
    no_realizado = sum(f["valor"] - costos[f["activo"]]["costo"] for f in filas if f["activo"] in costos and costos[f["activo"]]["cantidad"])
    return render_template("cliente/cartera.html", pend_aporte=pend_aporte, moneda_ver=moneda_ver, cambio_ref=guarani.referencia(),
                           filas=filas, total=total, desvio=desv, mayor_desvio=mayor, modelo=modelo,
                           costos=costos, realizado=realizado, no_realizado=no_realizado, bloq=bloq,
                           disp_usd=ten.get("USD", 0) - bloq.get("USD", 0), reservado=operaciones.reservado_cent(c["id"]),
                           pend_retiro=pend_retiro, ultimos=_movimientos(c)[:5],
                           planes=planes.del_cliente(c["id"]), frecuencias=planes.FRECUENCIAS,
                           rend=cartera.rendimiento(c["id"], total), aportado=cartera.aportado_neto(c["id"]),
                           datos3d=datos3d(filas, f"Cartera de {c['nombre'].split()[0]}"))


@bp.route("/invertir", methods=["GET", "POST"])
@limites.idempotente("aporte")
def invertir():
    c = g.cliente
    error = None
    form = {"monto": "", "modelo": c["modelo"], "referencia": "", "acepta_riesgo": "", "metodo": "transferencia", "moneda": "USD"}
    if request.method == "POST":
        form = {k: (request.form.get(k) or "").strip() for k in form}
        form["metodo"] = form["metodo"] or "transferencia"
        paso = request.form.get("paso", "")
        try:
            en_gs = form["moneda"] == "PYG"
            monto = 0 if en_gs else leer_monto(form["monto"])
            args = dict(acepta_riesgo=form["acepta_riesgo"] == "si", monto_pyg=guarani.leer(form["monto"]) if en_gs else None,
                        metodo=form["metodo"])
            if paso == "revisar":
                v = operaciones.solicitar_aporte(c, monto, form["modelo"], form["referencia"], g.usuario, solo_validar=True, **args)
                return render_template("cliente/revisar.html", tipo="aporte", form=form, v=v,
                                       metodo=operaciones.METODOS[form["metodo"]], comisiones=_comisiones())
            if paso != "editar":
                opid = operaciones.solicitar_aporte(c, monto, form["modelo"], form["referencia"], g.usuario, **args)
                flash(f"Solicitud de depósito #{opid} enviada. El equipo confirma la recepción del dinero y te avisa al "
                      "acreditarlo. Aquí ves en qué paso está.", "ok")
                return redirect(url_for("cliente.movimiento", opid=opid))
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
                           datos=datos, disponible=max(total - pend_retiro, 0), metodos=operaciones.metodos("aporte"),
                           comisiones=_comisiones(), recientes=_solicitudes(c["id"], "aporte"))


def _comisiones():
    """Comisiones vigentes para mostrar antes de confirmar (todas salen de la configuración real)."""
    cfg = current_app.config
    return {"cambios": guarani.cambios(), "gestion": cfg["COMISION_ANUAL_PCT"],
            "operacion": operaciones.comision_operacion_pct(), "envios_max": cfg["ENVIO_MAX_DIA_USD"]}


def _solicitudes(cliente_id, tipo, n=5):
    return db.todos("SELECT * FROM operaciones WHERE cliente_id = ? AND tipo = ? ORDER BY id DESC LIMIT ?", (cliente_id, tipo, n))


@bp.route("/retirar", methods=["GET", "POST"])
@limites.idempotente("retirar")
def retirar():
    c = g.cliente
    error = None
    form = {"monto": "", "moneda": "USD", "metodo": "transferencia"}
    if request.method == "POST":
        form = {k: (request.form.get(k) or "").strip() for k in form}
        form["metodo"] = form["metodo"] or "transferencia"
        paso = request.form.get("paso", "")
        try:
            monto = leer_monto(form["monto"])
            args = dict(en_guaranies=form["moneda"] == "PYG", metodo=form["metodo"])
            if paso == "revisar":
                v = operaciones.solicitar_retiro(c, monto, g.usuario, solo_validar=True, **args)
                return render_template("cliente/revisar.html", tipo="retiro", form=form, v=v,
                                       metodo=operaciones.METODOS[form["metodo"]], comisiones=_comisiones())
            if paso != "editar":
                opid = operaciones.solicitar_retiro(c, monto, g.usuario, **args)
                flash(f"Solicitud de retiro #{opid} enviada. Te avisamos cuando el equipo la apruebe y haga el pago.", "ok")
                return redirect(url_for("cliente.movimiento", opid=opid))
        except (ValueError, operaciones.ErrorNegocio) as e:
            error = str(e)
    _, total = cartera.posiciones(c["id"])
    pend = sum(o["monto_cent"] for o in _abiertas(c["id"]) if o["tipo"] == "retiro")
    disponible = max(total - pend - operaciones.reservado_cent(c["id"]), 0)
    return render_template("cliente/retirar.html", error=error, form=form, disponible=disponible, total=total, pend=pend,
                           reservado=operaciones.reservado_cent(c["id"]), metodos=operaciones.metodos("retiro"),
                           comisiones=_comisiones(), recientes=_solicitudes(c["id"], "retiro"))


@bp.post("/retiro")
@limites.idempotente("retiro")
def retiro():
    c = g.cliente
    try:
        monto = leer_monto(request.form.get("monto"))
        opid = operaciones.solicitar_retiro(c, monto, g.usuario, en_guaranies=request.form.get("moneda") == "PYG")
        flash(f"Solicitud de retiro #{opid} enviada. Te avisamos cuando el equipo la apruebe.", "ok")
        return redirect(url_for("cliente.movimiento", opid=opid))
    except (ValueError, operaciones.ErrorNegocio) as e:
        flash(str(e), "error")
        return redirect(url_for("cliente.retirar"))


FILTROS_MOV = {"todos": "Todos", "depositos": "Depósitos", "retiros": "Retiros", "operaciones": "Compras y ventas",
               "envios": "Envíos", "abiertos": "En curso"}


def _movimientos(c, filtro="todos", q="", desde=None, hasta=None, activo=None):
    """Movimientos del cliente en una sola lista (operaciones y envíos), del más nuevo al más viejo."""
    from .formato import TIPOS_OP
    from .transferencias import del_cliente as envios
    ops = db.todos("SELECT * FROM operaciones WHERE cliente_id = ? ORDER BY creado DESC, id DESC LIMIT 400", (c["id"],))
    ordenes = {}
    for o in db.todos("SELECT * FROM ordenes WHERE cliente_id = ? ORDER BY id", (c["id"],)):
        ordenes.setdefault(o["operacion_id"], []).append(o)
    out = []
    for o in ops:
        grupo = {"aporte": "depositos", "retiro": "retiros", "compra": "operaciones", "venta": "operaciones"}.get(o["tipo"], "otros")
        monto = o["liquidado_cent"] if o["liquidado_cent"] is not None else o["monto_cent"]
        texto = " ".join(str(x) for x in (o["id"], TIPOS_OP[o["tipo"]], o["activo"] or "", o["referencia"] or "",
                                           o["estado"], monto / 100)).lower()
        out.append({"clase": "op", "o": o, "ts": o["creado"], "grupo": grupo, "abierto": o["estado"] in ("pendiente", "primera_firma", "ejecutando"),
                    "activo": o["activo"] or "USD", "codigo": comprobantes.codigo("op", o["id"]),
                    "ordenes": ordenes.get(o["id"], []), "monto": monto, "buscar": texto,
                    "url": url_for("cliente.movimiento", opid=o["id"])})
    for t in envios(c["id"], 200):
        sale = t["de_cliente"] == c["id"]
        otro = t["a_nombre"] if sale else t["de_nombre"]
        out.append({"clase": "envio", "t": t, "ts": t["ts"], "grupo": "envios", "abierto": False, "sale": sale,
                    "activo": t["activo"], "codigo": comprobantes.codigo("envio", t["id"]),
                    "otro": otro, "monto": t["valor_cent"], "url": url_for("cliente.envio", tid=t["id"]),
                    "buscar": f"e{t['id']} envío {'enviaste' if sale else 'recibiste'} {otro} {t['activo']} {t['nota'] or ''} {t['valor_cent'] / 100}".lower()})
    out.sort(key=lambda m: m["ts"], reverse=True)
    if filtro == "abiertos":
        out = [m for m in out if m["abierto"]]
    elif filtro in FILTROS_MOV and filtro != "todos":
        out = [m for m in out if m["grupo"] == filtro]
    if activo:
        out = [m for m in out if m["activo"] == activo]
    if desde or hasta:
        from .formato import zona
        from .tiempo import leer
        dia = lambda m: leer(m["ts"]).astimezone(zona()).date().isoformat()  # noqa: E731  fecha local de Paraguay
        out = [m for m in out if (not desde or dia(m) >= desde) and (not hasta or dia(m) <= hasta)]
    if q:
        qq = q.lower().replace("#", "").strip()
        out = [m for m in out if qq in m["buscar"] or qq.upper() == m["codigo"]]
    return out


def _filtros_mov():
    """Lee y valida los filtros del historial desde la dirección."""
    import re as _re
    filtro = request.args.get("ver", "todos")
    if filtro not in FILTROS_MOV:
        filtro = "todos"
    q = (request.args.get("q") or "").strip()[:40]
    fecha = lambda k: request.args.get(k) if _re.fullmatch(r"\d{4}-\d{2}-\d{2}", request.args.get(k) or "") else None  # noqa: E731
    activo = (request.args.get("moneda") or "").upper()
    activo = activo if activo == "USD" or db.uno("SELECT 1 FROM activos WHERE codigo = ?", (activo,)) else None
    return {"filtro": filtro, "q": q, "desde": fecha("desde"), "hasta": fecha("hasta"), "activo": activo}


@bp.get("/movimientos")
def movimientos():
    c = g.cliente
    f = _filtros_mov()
    movs = _movimientos(c, f["filtro"], f["q"], f["desde"], f["hasta"], f["activo"])
    modelos = {m["codigo"]: m["nombre"] for m in db.todos("SELECT codigo, nombre FROM modelos")}
    monedas = ["USD"] + [a["codigo"] for a in precios.activos()]
    return render_template("cliente/movimientos.html", movs=movs[:150], filtro=f["filtro"], filtros=FILTROS_MOV, q=f["q"],
                           desde=f["desde"], hasta=f["hasta"], moneda=f["activo"], monedas=monedas,
                           modelos=modelos, periodos=cartera.periodos_cliente(c), total=len(movs))


@bp.get("/movimientos.csv")
def movimientos_csv():
    """Exporta el historial con los mismos filtros de la pantalla, con identificador único y huella de cada movimiento."""
    import csv
    import io
    from datetime import datetime

    from .formato import TIPOS_OP, zona
    from .tiempo import leer
    limites.exigir(("datos", f"u{g.usuario['id']}"))
    c = g.cliente
    f = _filtros_mov()
    movs = _movimientos(c, f["filtro"], f["q"], f["desde"], f["hasta"], f["activo"])
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([f"Movimientos de {c['nombre']}", f"generado: {datetime.now(zona()).strftime('%Y-%m-%d %H:%M')} (hora de Paraguay)",
                "montos en dólares estadounidenses"])
    w.writerow(["codigo", "fecha", "tipo", "estado", "moneda", "cantidad", "monto_usd", "referencia", "huella"])
    for m in movs:
        fecha = leer(m["ts"]).astimezone(zona()).strftime("%Y-%m-%d %H:%M:%S")
        if m["clase"] == "op":
            o = m["o"]
            cant = sum(r["cantidad"] for r in m["ordenes"]) if m["ordenes"] else ""
            w.writerow([m["codigo"], fecha, TIPOS_OP[o["tipo"]], ESTADOS[o["estado"]][1], m["activo"],
                        dinero.fmt_unidades(cant, o["activo"]).split(" ")[0] if cant != "" and o["activo"] else "",
                        f"{m['monto'] / 100:.2f}", o["referencia"] or "", comprobantes.huella("op", o)])
        else:
            t = m["t"]
            w.writerow([m["codigo"], fecha, "Envío enviado" if m["sale"] else "Envío recibido", "Hecho", t["activo"],
                        dinero.fmt_unidades(t["cantidad"], t["activo"]).split(" ")[0] if t["activo"] != "USD" else "",
                        f"{(-1 if m['sale'] else 1) * t['valor_cent'] / 100:.2f}", t["nota"] or "", comprobantes.huella("envio", t)])
    resp = current_app.response_class("\ufeff" + buf.getvalue(), mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = 'attachment; filename="movimientos.csv"'
    return resp


@bp.get("/movimientos/<int:opid>/comprobante")
def comprobante_op(opid):
    from flask import abort
    o = db.uno("SELECT * FROM operaciones WHERE id = ? AND cliente_id = ?", (opid, g.cliente["id"]))
    if not o:
        abort(404)
    return render_template("cliente/comprobante.html", clase="op", o=o, codigo=comprobantes.codigo("op", opid),
                           huella=comprobantes.huella("op", o), rastro=comprobantes.rastro("op", opid),
                           ordenes=db.todos("SELECT * FROM ordenes WHERE operacion_id = ? ORDER BY id", (opid,)),
                           libro=db.todos("SELECT * FROM libro WHERE operacion_id = ? AND cliente_id = ? ORDER BY id", (opid, g.cliente["id"])))


@bp.get("/envios/<int:tid>/comprobante")
def comprobante_envio(tid):
    from flask import abort
    t = comprobantes.fila("envio", tid)
    if not t or g.cliente["id"] not in (t["de_cliente"], t["a_cliente"]):
        abort(404)
    return render_template("cliente/comprobante.html", clase="envio", t=t, sale=t["de_cliente"] == g.cliente["id"],
                           codigo=comprobantes.codigo("envio", tid), huella=comprobantes.huella("envio", t),
                           rastro=comprobantes.rastro("envio", tid))


@bp.get("/movimientos/<int:opid>")
def movimiento(opid):
    from flask import abort

    from .operaciones import METODOS
    c = g.cliente
    o = db.uno("SELECT * FROM operaciones WHERE id = ? AND cliente_id = ?", (opid, c["id"]))
    if not o:
        abort(404)
    ordenes = db.todos("SELECT * FROM ordenes WHERE operacion_id = ? ORDER BY id", (opid,))
    libro = db.todos("SELECT * FROM libro WHERE operacion_id = ? AND cliente_id = ? ORDER BY id", (opid, c["id"]))
    pasos = [("Solicitada" if o["tipo"] in ("aporte", "retiro") else "Orden recibida", o["creado"], True)]
    if o["tipo"] in ("aporte", "retiro"):
        doble = bool(o["firma2_ts"]) or o["estado"] == "primera_firma"
        pasos.append(("Revisada por el equipo (primera firma)" if doble else "Aprobada por el equipo", o["firma1_ts"], bool(o["firma1_ts"])))
        if doble:
            pasos.append(("Aprobada (segunda firma)", o["firma2_ts"], bool(o["firma2_ts"])))
    if o["ejecucion_inicio"]:
        pasos.append(("Enviada al mercado", o["ejecucion_inicio"], True))
    if o["estado"] == "liquidada":
        pasos.append(("Acreditada" if o["tipo"] == "aporte" else ("Pagada" if o["tipo"] == "retiro" else "Liquidada"),
                      o["resuelto_ts"] or o["firma2_ts"] or o["creado"], True))
    elif o["estado"] in ("rechazada", "cancelada"):
        pasos.append(("Rechazada" if o["estado"] == "rechazada" else "Cancelada", o["resuelto_ts"], True))
    else:
        pasos.append(("Acreditación" if o["tipo"] == "aporte" else "Liquidación", None, False))
    modelo = db.uno("SELECT nombre FROM modelos WHERE codigo = ?", (o["modelo"],)) if o["modelo"] else None
    return render_template("cliente/movimiento.html", o=o, ordenes=ordenes, libro=libro, pasos=pasos, modelo=modelo,
                           metodo=METODOS.get(o["metodo"] or "transferencia") if o["tipo"] in ("aporte", "retiro") else None)


@bp.get("/envios/<int:tid>")
def envio(tid):
    from flask import abort
    c = g.cliente
    t = db.uno("SELECT t.*, d.nombre AS de_nombre, a.nombre AS a_nombre FROM transferencias t JOIN clientes d ON d.id = t.de_cliente"
               " JOIN clientes a ON a.id = t.a_cliente WHERE t.id = ? AND (t.de_cliente = ? OR t.a_cliente = ?)", (tid, c["id"], c["id"]))
    if not t:
        abort(404)
    return render_template("cliente/envio.html", t=t, sale=t["de_cliente"] == c["id"])


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
               "comision": "Comisión de gestión", "envio": "Envío a otro cliente", "recepcion": "Recibido de otro cliente"}
    for f in filas:
        ref = f["operacion_id"] or (f"E{f['transferencia_id']}" if f["transferencia_id"] else "")
        if f["activo"] == "USD":
            w.writerow([f_fecha(f["ts"]), ref, nombres.get(f["concepto"], f["concepto"]), "USD", "", "",
                        fmt_num(Decimal(f["cantidad"]) / 100, 2)])
        else:
            w.writerow([f_fecha(f["ts"]), ref, nombres.get(f["concepto"], f["concepto"]), f["activo"],
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
    from . import niveles, preferencias
    from . import transferencias as tr
    lim = [("Máximo por orden", niveles.cent("ORDEN_MAXIMA_USD"), None),
           ("Envíos por día", niveles.cent("ENVIO_MAX_DIA_USD"), tr.enviado_hoy(c["id"])),
           ("Retiros por día", niveles.cent("RETIRO_MAX_DIA_USD"), niveles.retirado_hoy(c["id"]))]
    actividad = db.todos("SELECT ts, accion, detalle, ip FROM bitacora WHERE usuario_id = ? ORDER BY id DESC LIMIT 15", (g.usuario["id"],))
    return render_template("cliente/perfil.html", nivel=niveles.nivel(c, g.usuario), limites_op=lim,
                           proteccion=niveles.proteccion(c, g.usuario), pref=preferencias.leer(g.usuario["id"]),
                           actividad_cuenta=actividad, doble_firma=niveles.cent("UMBRAL_DOBLE_FIRMA_USD"),
                           legajo=documentos.legajo(c), modelo=modelo,
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


# ---------- v0.20: centro de ayuda, análisis de cartera y Earn (informativo) ----------
@bp.route("/ayuda", methods=["GET", "POST"])
def ayuda():
    from . import soporte
    if request.method == "POST":
        limites.exigir(("consulta", f"u{g.usuario['id']}"))
        try:
            cid = soporte.crear(g.usuario, g.cliente, request.form.get("categoria"), request.form.get("asunto"), request.form.get("texto"))
            flash("Recibimos tu consulta. Te avisamos cuando el equipo responda.", "ok")
            return redirect(url_for("cliente.consulta", cid=cid))
        except soporte.ErrorSoporte as e:
            flash(str(e), "error")
            return redirect(url_for("cliente.ayuda") + "#nueva")
    q = (request.args.get("q") or "").strip().lower()[:40]
    faq = [f for f in soporte.FAQ if not q or q in f[1].lower() or q in f[2].lower()]
    return render_template("cliente/ayuda.html", faq=faq, q=q, categorias=soporte.CATEGORIAS, estados=soporte.ESTADOS,
                           consultas=soporte.del_usuario(g.usuario["id"]))


@bp.route("/ayuda/<int:cid>", methods=["GET", "POST"])
def consulta(cid):
    from . import soporte
    q = db.uno("SELECT * FROM consultas WHERE id = ? AND usuario_id = ?", (cid, g.usuario["id"]))
    if not q:
        abort(404)
    if request.method == "POST":
        limites.exigir(("consulta", f"u{g.usuario['id']}"))
        try:
            if request.form.get("accion") == "cerrar":
                soporte.cerrar(cid, g.usuario, False)
                flash("Consulta cerrada.", "ok")
            else:
                soporte.responder(cid, g.usuario, request.form.get("texto"), False)
        except soporte.ErrorSoporte as e:
            flash(str(e), "error")
        return redirect(url_for("cliente.consulta", cid=cid))
    return render_template("cliente/consulta.html", q=q, mensajes=soporte.mensajes(cid), categorias=soporte.CATEGORIAS,
                           estados=soporte.ESTADOS, equipo=False)


@bp.get("/analisis")
def analisis_cartera():
    from . import analisis, panel
    c = g.cliente
    filas, total = cartera.posiciones(c["id"])
    costos = cartera.costos(c["id"])
    ind = cartera.indicadores(c["id"], filas, total)
    detalle = []
    for f in filas:
        vol = analisis.activo(f["activo"], f["precio"]).get("volatilidad") if f["activo"] != "USD" else 0.0
        k = costos.get(f["activo"])
        res = (f["valor"] - k["costo"]) if k and k["cantidad"] and k["costo"] else None
        detalle.append({**f, "vol": vol, "resultado": res, "res_pct": (res / k["costo"] * 100) if res is not None else None,
                        "riesgo": (f["peso"] * vol) if vol is not None else None})
    suma = sum(d["riesgo"] or 0 for d in detalle) or 1
    for d in detalle:
        d["aporte_riesgo"] = (d["riesgo"] or 0) / suma * 100
    return render_template("cliente/analisis.html", filas=detalle, total=total, ind=ind, riesgo=panel.riesgo(c, filas, ind),
                           rendimientos=panel.rendimientos(c["id"], total, precios.mercado()), ranking=panel.ranking(filas, costos),
                           datos3d=datos3d(filas, ""))


EARN = [
    ("staking", "Staking", "Bloquear monedas de redes de prueba de participación (como ETH o SOL) para ayudar a validar la red y recibir recompensas en la misma moneda.",
     ["La recompensa varía y no está garantizada.", "Las monedas pueden quedar bloqueadas días o semanas.", "El validador puede ser penalizado y perder parte de lo depositado.", "El precio de la moneda puede caer más que la recompensa."]),
    ("ahorro", "Ahorro en monedas estables", "Prestar monedas estables (como USDT o USDC) a un tercero que paga un interés.",
     ["Quien recibe el préstamo puede no devolverlo.", "La moneda estable puede perder su paridad con el dólar.", "No hay garantía de depósitos."]),
    ("prestamos", "Préstamos con garantía", "Dejar criptomonedas como garantía para recibir dólares sin venderlas.",
     ["Si el precio cae, la garantía puede liquidarse con pérdida.", "Se pagan intereses.", "Exige controles de riesgo en tiempo real."]),
]


@bp.route("/earn", methods=["GET", "POST"])
def earn():
    from . import preferencias
    pref = preferencias.leer(g.usuario["id"])
    if request.method == "POST":
        prod = request.form.get("producto")
        if prod in {e[0] for e in EARN}:
            interes = [x for x in pref["earn_interes"] if x != prod] if prod in pref["earn_interes"] else pref["earn_interes"] + [prod]
            preferencias.guardar(g.usuario["id"], {"earn_interes": interes})
            flash("Anotado. Esto no te compromete a nada: solo nos ayuda a decidir qué desarrollar." if prod in interes
                  else "Quitamos tu interés en ese producto.", "ok")
        return redirect(url_for("cliente.earn"))
    return render_template("cliente/earn.html", productos=EARN, interes=pref["earn_interes"])
