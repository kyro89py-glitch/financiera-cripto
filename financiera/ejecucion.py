"""Motor de ejecución de operaciones en dos fases.

1. ``planificar``: calcula los tramos (un activo por tramo) a precios vigentes y con las reglas del exchange
   (importe mínimo, incremento de cantidad). Puede consultar el exchange, por eso va fuera de toda transacción.
2. ``registrar_plan``: dentro de la transacción de aprobación, guarda los tramos y deja la operación 'ejecutando'.
3. ``continuar``: envía cada tramo pendiente con un id de orden propio y fijo. Antes de enviar marca el tramo como
   'enviada' (si el proceso se corta, al reintentar se consulta al exchange en vez de reenviar: nunca se duplica una
   orden). Si todos los tramos quedaron ejecutados u omitidos, ``liquidar`` asienta en el libro las cantidades y
   precios reales, cierra la operación y avisa al cliente.

Un tramo 'fallida' (el exchange lo rechazó) deja la operación 'ejecutando' con una alerta; se reintenta desde la
pantalla de la operación. Una pausa de emergencia (Administración → Ejecución) detiene todo envío.
"""
import json
from decimal import ROUND_CEILING, Decimal

from flask import current_app

from . import auditoria, cartera, db, exchange, notificaciones
from .dinero import fmt_unidades, fmt_usd, unidades_por, valor_cent
from .tiempo import ahora

PAUSA = "ejecucion_pausada"
ESTADOS_TRAMO = {
    "pendiente": ("warn", "Pendiente"),
    "enviada": ("info", "Enviada, sin confirmar"),
    "ejecutada": ("ok", "Ejecutada"),
    "omitida": ("", "Omitida"),
    "fallida": ("bad", "Falló"),
}
CONCEPTO_PAGO = {"retiro": "pago_retiro", "comision": "comision"}


class ErrorEjecucion(Exception):
    pass


# ---------- pausa de emergencia ----------
def pausada():
    f = db.uno("SELECT valor FROM ajustes WHERE clave = ?", (PAUSA,))
    return bool(f and f["valor"] == "1")


def pausar(activar, usuario, motivo=""):
    ts = ahora()
    with db.transaccion() as c:
        c.execute("INSERT INTO ajustes (clave, valor, ts, por) VALUES (?, ?, ?, ?) ON CONFLICT(clave) DO UPDATE SET"
                  " valor = excluded.valor, ts = excluded.ts, por = excluded.por", (PAUSA, "1" if activar else "0", ts, usuario["id"]))
        texto = ("Pausó la ejecución de órdenes" if activar else "Reanudó la ejecución de órdenes") + (f": {motivo}" if motivo else ".")
        auditoria.registrar("ejecucion.pausa" if activar else "ejecucion.reanudada", "ejecucion", {"texto": texto},
                            usuario=usuario, ts=ts)
    if activar:
        notificaciones.notificar_rol(("operador", "cumplimiento", "admin"), "La ejecución de órdenes está en pausa. "
                                     "No se pueden aprobar aportes ni retiros hasta reanudarla.", "/admin/ejecucion",
                                     excepto=usuario["id"], ts=ts)


def exigir_activa():
    if pausada():
        raise ErrorEjecucion("La ejecución de órdenes está en pausa. Un administrador puede reanudarla en Ajustes → Ejecución.")


# ---------- planificación ----------
def _prefijo():
    return current_app.config.get("ORDEN_PREFIJO", "fc")


def id_orden(opid, activo, lado):
    """Id propio de la orden (Binance acepta hasta 36 caracteres: letras, números, '.', ':', '/', '_' y '-')."""
    return f"{_prefijo()}-{opid}-{'C' if lado == 'compra' else 'V'}-{activo}"[:36]


def _ejecutor_de(brk, activo):
    return brk.nombre if brk.opera(activo) else "interno"


def _plan_compra(op, pr, brk):
    pesos = cartera.pesos_modelo(op["modelo"])
    if sum(pb for _, pb in pesos) != 10000:
        raise ErrorEjecucion("La cartera modelo está mal configurada: los pesos no suman 100 %.")
    monto, restante, out = op["monto_cent"], op["monto_cent"], []
    for i, (activo, pb) in enumerate(pesos):
        usd = restante if i == len(pesos) - 1 else monto * pb // 10000
        restante -= usd
        if usd <= 0:
            continue
        p = pr.get(activo)
        if not p:
            raise ErrorEjecucion(f"No hay precio para {activo}.")
        venue = _ejecutor_de(brk, activo)
        estado, nota = "pendiente", None
        if venue != "interno":
            minimo = brk.reglas(activo).minimo_cent
            if usd < minimo:
                estado, nota = "omitida", f"{fmt_usd(usd)} es menos que el mínimo por orden ({fmt_usd(minimo)}): queda en dólares."
        if estado == "pendiente" and unidades_por(usd, p["precio"]) <= 0:
            estado, nota = "omitida", f"{fmt_usd(usd)} no alcanza para una unidad mínima: queda en dólares."
        out.append({"activo": activo, "lado": "compra", "venue": venue, "importe_pedido_cent": usd,
                    "cantidad_pedida": None, "estado": estado, "nota": nota})
    return out


def _plan_venta(cliente_id, monto, pr, brk):
    """Ventas para juntar `monto` en dólares: primero se usa el saldo en dólares y el resto se vende en proporción a
    cada tenencia. Los tramos menores al mínimo del exchange se suman al de la tenencia más grande."""
    ten = cartera.tenencias(cliente_id)
    _, total = cartera.posiciones(cliente_id, pr, ten)
    if monto > total:
        raise ErrorEjecucion("El monto supera el valor actual de la cartera.")
    falta = monto - ten.get("USD", 0)
    if falta <= 0:
        return []
    items = []
    for activo, u in ten.items():
        if activo == "USD" or u <= 0:
            continue
        p = pr.get(activo)
        if not p:
            raise ErrorEjecucion(f"No hay precio para {activo}.")
        venue = _ejecutor_de(brk, activo)
        reglas = brk.reglas(activo) if venue != "interno" else exchange.Reglas()
        margen = brk.margen_venta if venue != "interno" else Decimal(0)
        items.append({"activo": activo, "u": u, "precio": Decimal(p["precio"]), "valor": valor_cent(activo, u, p["precio"]),
                      "venue": venue, "reglas": reglas, "margen": margen})
    items.sort(key=lambda x: -x["valor"])
    resto = sum(i["valor"] for i in items)
    if resto <= 0:
        return []
    todo = falta >= resto
    for it in items:
        if todo:
            it["q"] = it["u"]
        else:
            q = Decimal(it["u"]) * Decimal(falta) * (1 + it["margen"]) / Decimal(resto)
            it["q"] = min(it["u"], int(q.to_integral_value(ROUND_CEILING)))
    if not todo:  # tramos chicos: se suman al más grande
        deficit = 0
        for it in items:
            if it["q"] and valor_cent(it["activo"], it["q"], it["precio"]) < it["reglas"].minimo_cent:
                deficit += valor_cent(it["activo"], it["q"], it["precio"])
                it["q"] = 0
        if deficit or not any(it["q"] for it in items):
            mayor = items[0]
            extra = unidades_por(max(deficit, 0), mayor["precio"]) + 1
            minimo_u = unidades_por(int(mayor["reglas"].minimo_cent * 102 // 100), mayor["precio"]) + 1 \
                if mayor["reglas"].minimo_cent else 0
            mayor["q"] = min(mayor["u"], max(mayor["q"] + extra, minimo_u))
    out = []
    for it in items:
        if not it["q"]:
            continue
        r = it["reglas"]
        maximo = it["u"] - it["u"] % r.paso
        q = min(maximo, -(-it["q"] // r.paso) * r.paso)
        estado, nota = "pendiente", None
        if q < max(r.minimo_unidades, 1) or valor_cent(it["activo"], q, it["precio"]) < r.minimo_cent:
            estado, nota = "omitida", "La cantidad es menor al mínimo que acepta el exchange."
            q = max(q, 0)
        out.append({"activo": it["activo"], "lado": "venta", "venue": it["venue"], "importe_pedido_cent": None,
                    "cantidad_pedida": q, "estado": estado, "nota": nota})
    return out


def _plan_orden(op, cliente_id, pr, brk):
    """Un solo tramo: la compra o la venta de una moneda que pidió el cliente."""
    activo, lado = op["activo"], op["tipo"]
    p = pr.get(activo)
    if not p:
        raise ErrorEjecucion(f"No hay precio para {activo}.")
    venue = _ejecutor_de(brk, activo)
    reglas = brk.reglas(activo) if venue != "interno" else exchange.Reglas()
    if lado == "compra":
        usd = op["monto_cent"]
        if usd > cartera.tenencias(cliente_id).get("USD", 0):
            raise ErrorEjecucion("No tienes saldo en dólares suficiente para esta compra.")
        if usd < reglas.minimo_cent or unidades_por(usd, p["precio"]) <= 0:
            raise ErrorEjecucion(f"El monto mínimo para comprar {activo} es de {fmt_usd(max(reglas.minimo_cent, 100))}.")
        return [{"activo": activo, "lado": "compra", "venue": venue, "importe_pedido_cent": usd, "cantidad_pedida": None,
                 "estado": "pendiente", "nota": None}]
    tengo = cartera.tenencias(cliente_id).get(activo, 0)
    q = min(op["cantidad_pedida"], tengo)
    q -= q % reglas.paso
    if q < max(reglas.minimo_unidades, 1) or valor_cent(activo, q, p["precio"]) < max(reglas.minimo_cent, 1):
        raise ErrorEjecucion(f"La cantidad es menor al mínimo para vender {activo}"
                             + (f" ({fmt_usd(reglas.minimo_cent)})." if reglas.minimo_cent else "."))
    return [{"activo": activo, "lado": "venta", "venue": venue, "importe_pedido_cent": None, "cantidad_pedida": q,
             "estado": "pendiente", "nota": None}]


def planificar(op, cliente, pr):
    """Tramos de la operación a precios vigentes. Para aportes en Binance verifica que haya USDT libre suficiente."""
    exigir_activa()
    brk = exchange.broker(pr)
    try:
        if op["tipo"] in ("compra", "venta"):
            tramos = _plan_orden(op, cliente["id"], pr, brk)
        elif op["tipo"] == "aporte":
            tramos = _plan_compra(op, pr, brk) if op["modelo"] else []
        else:
            tramos = _plan_venta(cliente["id"], op["monto_cent"], pr, brk)
        if op["tipo"] in ("aporte", "compra"):
            necesita = sum(t["importe_pedido_cent"] for t in tramos if t["estado"] == "pendiente" and t["venue"] == brk.nombre)
            if necesita and brk.nombre == "binance":
                libre = brk.disponible(exchange.MONEDA_COTIZACION)
                if libre < necesita * 10 ** 6:
                    raise ErrorEjecucion(
                        f"No hay USDT suficiente en Binance: hay {fmt_unidades(libre, 'USDT')} libres y esta operación necesita "
                        f"{fmt_usd(necesita)}. Convierte y deposita los fondos antes de aprobar.")
    except exchange.ErrorExchange as e:
        raise ErrorEjecucion(f"No se pudo preparar la ejecución: {e}") from None
    return tramos


def registrar_plan(c, op, tramos, usuario, ts):
    """Dentro de una transacción: guarda los tramos y deja la operación 'ejecutando'."""
    otra = c.execute("SELECT id FROM operaciones WHERE cliente_id = ? AND estado = 'ejecutando' AND id != ?",
                     (op["cliente_id"], op["id"])).fetchone()
    if otra and op["tipo"] not in ("aporte", "compra"):
        raise ErrorEjecucion(f"La operación #{otra['id']} de este cliente todavía se está ejecutando; termínala primero.")
    if op["tipo"] not in ("aporte", "compra"):  # las tenencias no pueden haber bajado entre el plan y ahora
        ten = {r["activo"]: r["u"] for r in c.execute(
            "SELECT activo, SUM(cantidad) AS u FROM libro WHERE cliente_id = ? GROUP BY activo", (op["cliente_id"],))}
        for t in tramos:
            if (t["cantidad_pedida"] or 0) > ten.get(t["activo"], 0):
                raise ErrorEjecucion("Las tenencias del cliente cambiaron mientras se preparaba la operación; vuelve a intentarlo.")
    for t in tramos:
        c.execute("INSERT INTO ejecuciones (operacion_id, activo, lado, venue, id_orden, importe_pedido_cent, cantidad_pedida,"
                  " estado, nota, creado, actualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (op["id"], t["activo"], t["lado"], t["venue"], id_orden(op["id"], t["activo"], t["lado"]),
                   t["importe_pedido_cent"], t["cantidad_pedida"], t["estado"], t["nota"], ts, ts))
    c.execute("UPDATE operaciones SET estado = 'ejecutando', ejecucion_inicio = ?, ejecucion_por = ? WHERE id = ?",
              (ts, usuario["id"] if usuario else None, op["id"]))


# ---------- envío ----------
def tramos(opid):
    return db.todos("SELECT * FROM ejecuciones WHERE operacion_id = ? ORDER BY id", (opid,))


def _guardar(tid, ts, **campos):
    campos["actualizado"] = ts
    sets = ", ".join(f"{k} = ?" for k in campos)
    with db.transaccion() as c:
        c.execute(f"UPDATE ejecuciones SET {sets} WHERE id = ?", (*campos.values(), tid))


def _ejecutada(t, r, ts):
    nota = "Ejecución parcial: el exchange no completó toda la orden." if r.parcial else None
    _guardar(t["id"], ts, estado="ejecutada", cantidad_bruta=r.cantidad_bruta, cantidad=r.cantidad, precio=str(r.precio),
             importe_cent=r.importe_cent, comision=str(r.comision) if r.comision else None, comision_activo=r.comision_activo,
             ref_exchange=r.ref, nota=nota, respuesta=json.dumps(r.respuesta, default=str)[:4000] if r.respuesta else None)


def _procesar(t, ejecutor, ts):
    if t["estado"] == "enviada":  # resultado desconocido: preguntar antes de reenviar
        try:
            r = ejecutor.consultar(t["activo"], t["id_orden"])
        except exchange.ErrorExchange as e:
            if e.definitivo:
                _guardar(t["id"], ts, estado="fallida", nota=str(e))
            else:
                _guardar(t["id"], ts, nota=f"{e} Se volverá a consultar antes de reenviar.")
            return
        if r is not None:
            _ejecutada(t, r, ts)
            return
    with db.transaccion() as c:  # marca 'enviada' solo si nadie tomó el tramo mientras tanto
        n = c.execute("UPDATE ejecuciones SET estado = 'enviada', intentos = intentos + 1, actualizado = ?"
                      " WHERE id = ? AND estado = ? AND intentos = ?", (ts, t["id"], t["estado"], t["intentos"])).rowcount
    if not n:
        return
    try:
        if t["lado"] == "compra":
            r = ejecutor.comprar(t["activo"], t["importe_pedido_cent"], t["id_orden"])
        else:
            r = ejecutor.vender(t["activo"], t["cantidad_pedida"], t["id_orden"])
    except exchange.ErrorExchange as e:
        if e.definitivo:
            _guardar(t["id"], ts, estado="fallida", nota=str(e))
        else:
            _guardar(t["id"], ts, nota=f"{e} Se consultará al exchange antes de reenviar.")
        return
    _ejecutada(t, r, ts)


def continuar(opid, usuario=None, ts=None, precios_usar=None):
    """Envía los tramos pendientes y, si todo quedó ejecutado, liquida. Devuelve 'liquidada' o 'incompleta'."""
    from . import precios as precios_mod
    exigir_activa()
    ts = ts or ahora()
    pr = precios_usar if precios_usar is not None else precios_mod.vigentes()
    brk = exchange.broker(pr)
    interno = exchange.Interno(pr)
    for t in tramos(opid):
        if t["estado"] in ("pendiente", "enviada"):
            _procesar(t, brk if t["venue"] == brk.nombre else interno, ts)
    return liquidar(opid, usuario, ts)


def reintentar(opid, usuario):
    ts = ahora()
    op = db.uno("SELECT * FROM operaciones WHERE id = ?", (opid,))
    if not op or op["estado"] != "ejecutando":
        raise ErrorEjecucion("La operación no tiene una ejecución en curso.")
    exigir_activa()
    brk = exchange.broker()
    ajustes = {}
    for t in tramos(opid):  # ventas rechazadas por el filtro de cantidad: se ajustan a las reglas vigentes del par
        if t["estado"] == "fallida" and t["lado"] == "venta" and t["venue"] == brk.nombre:
            try:
                paso = brk.reglas(t["activo"]).paso
            except exchange.ErrorExchange:
                continue
            q = t["cantidad_pedida"] - t["cantidad_pedida"] % paso
            if q != t["cantidad_pedida"] and q > 0:
                ajustes[t["id"]] = q
    with db.transaccion() as c:
        for tid, q in ajustes.items():
            c.execute("UPDATE ejecuciones SET cantidad_pedida = ? WHERE id = ?", (q, tid))
        n = c.execute("UPDATE ejecuciones SET estado = 'pendiente', actualizado = ? WHERE operacion_id = ? AND estado = 'fallida'",
                      (ts, opid)).rowcount
        auditoria.registrar("ejecucion.reintento", f"operacion:{opid}",
                            {"texto": f"Reintentó la ejecución de la operación #{opid} ({n} tramo{'s' if n != 1 else ''} fallido{'s' if n != 1 else ''})."},
                            usuario=usuario, ts=ts)
    return continuar(opid, usuario, ts)


# ---------- liquidación ----------
def _asiento(c, cid, activo, cantidad, concepto, opid, ts):
    c.execute("INSERT INTO libro (cliente_id, activo, cantidad, concepto, operacion_id, ts) VALUES (?, ?, ?, ?, ?, ?)",
              (cid, activo, cantidad, concepto, opid, ts))


def _orden(c, op, t, ts):
    """Orden vista desde el cliente: en compras, lo que recibe; en ventas, lo que entrega."""
    if t["cantidad"] <= 0:
        return
    c.execute("INSERT INTO ordenes (operacion_id, cliente_id, activo, lado, cantidad, precio, importe_cent, ts, venue, comision,"
              " comision_activo, ref_exchange) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (op["id"], op["cliente_id"], t["activo"], t["lado"], t["cantidad"], t["precio"], t["importe_cent"], ts, t["venue"], t["comision"], t["comision_activo"], t["ref_exchange"]))


def liquidar(opid, usuario, ts):
    with db.transaccion() as c:
        op = c.execute("SELECT * FROM operaciones WHERE id = ?", (opid,)).fetchone()
        if op["estado"] != "ejecutando":
            return op["estado"]
        ts_ = c.execute("SELECT * FROM ejecuciones WHERE operacion_id = ? ORDER BY id", (opid,)).fetchall()
        if any(t["estado"] not in ("ejecutada", "omitida") for t in ts_):
            return "incompleta"
        cid, tipo, monto = op["cliente_id"], op["tipo"], op["monto_cent"]
        hechas = [t for t in ts_ if t["estado"] == "ejecutada"]
        if tipo in ("aporte", "compra"):
            if tipo == "aporte":
                _asiento(c, cid, "USD", monto, "deposito", opid, ts)
            for t in hechas:
                _asiento(c, cid, "USD", -t["importe_cent"], "compra", opid, ts)
                if t["cantidad"] > 0:
                    _asiento(c, cid, t["activo"], t["cantidad"], "compra", opid, ts)
                _orden(c, op, t, ts)
            liquidado = monto if tipo == "aporte" else sum(t["importe_cent"] for t in hechas)
            if tipo == "aporte" and op["modelo"]:
                c.execute("UPDATE clientes SET modelo = ? WHERE id = ?", (op["modelo"], cid))
        else:
            for t in hechas:
                _asiento(c, cid, t["activo"], -t["cantidad"], "venta", opid, ts)
                _asiento(c, cid, "USD", t["importe_cent"], "venta", opid, ts)
                _orden(c, op, t, ts)
            if tipo == "venta":
                liquidado = sum(t["importe_cent"] for t in hechas)
            else:
                caja = c.execute("SELECT COALESCE(SUM(cantidad), 0) AS s FROM libro WHERE cliente_id = ? AND activo = 'USD'",
                                 (cid,)).fetchone()["s"]
                liquidado = max(0, min(monto, caja))
                if liquidado:
                    _asiento(c, cid, "USD", -liquidado, CONCEPTO_PAGO[tipo], opid, ts)
        negativo = c.execute("SELECT activo FROM libro WHERE cliente_id = ? GROUP BY activo HAVING SUM(cantidad) < 0",
                             (cid,)).fetchone()
        if negativo:
            raise ErrorEjecucion(f"La liquidación dejaría saldo negativo de {negativo['activo']}; revisa los tramos.")
        c.execute("UPDATE operaciones SET estado = 'liquidada', resuelto_ts = ?, resuelto_por = ?, liquidado_cent = ? WHERE id = ?",
                  (ts, usuario["id"] if usuario else None, liquidado, opid))
        cli = c.execute("SELECT nombre, usuario_id FROM clientes WHERE id = ?", (cid,)).fetchone()
        venues = sorted({t["venue"] for t in hechas})
        donde = f" en {', '.join(venues)}" if venues else ""
        if tipo == "comision":
            texto_b = f"Cobró la comisión de gestión de {cli['nombre']} ({op['periodo']}): {fmt_usd(liquidado)}{donde}."
        elif tipo in ("compra", "venta"):
            texto_b = f"{cli['nombre']} {'compró' if tipo == 'compra' else 'vendió'} {op['activo']} por {fmt_usd(liquidado)}{donde} (orden #{opid})."
        else:
            texto_b = f"Liquidó el {tipo} #{opid} de {cli['nombre']} por {fmt_usd(liquidado)}{donde}."
        auditoria.registrar({"comision": "comision.cobrada", "compra": "orden.ejecutada", "venta": "orden.ejecutada"}.get(tipo, "operacion.liquidada"), f"operacion:{opid}",
                            {"texto": texto_b, "monto_cent": monto, "liquidado_cent": liquidado,
                             "ordenes": [{"activo": t["activo"], "lado": t["lado"], "venue": t["venue"], "ref": t["ref_exchange"]}
                                         for t in hechas]}, usuario=usuario, ts=ts)
        if cli["usuario_id"] and tipo not in ("compra", "venta"):
            if tipo == "aporte":
                texto = f"Tu aporte #{opid} de {fmt_usd(monto)} fue aprobado" + (" e invertido." if op["modelo"] else " y está en tu saldo en dólares.")
            elif tipo == "retiro":
                texto = f"Tu retiro #{opid} de {fmt_usd(liquidado)} fue aprobado. El pago se acredita en tu cuenta bancaria."
                if liquidado < monto:
                    texto += f" Se pagaron {fmt_usd(liquidado)} de {fmt_usd(monto)} por los mínimos de negociación del exchange."
            else:
                from .comisiones import nombre_periodo
                texto = f"Comisión de gestión de {nombre_periodo(op['periodo'])}: {fmt_usd(liquidado)}"
                texto += f" ({op['motivo']})." if op["motivo"] else "."
            notificaciones.notificar(cli["usuario_id"], texto, "/cliente/movimientos", ts=ts)
        return "liquidada"


def incompletas():
    return db.todos("SELECT o.*, c.nombre FROM operaciones o JOIN clientes c ON c.id = o.cliente_id"
                    " WHERE o.estado = 'ejecutando' ORDER BY o.ejecucion_inicio")
