"""Reglas de negocio de aportes y retiros: solicitud, doble firma, aprobación, rechazo y alertas."""
from flask import current_app

from . import auditoria, cartera, conciliacion, db, notificaciones, precios
from .dinero import fmt_usd
from .tiempo import ahora

ESTADOS_ABIERTOS = ("pendiente", "primera_firma")
RIESGO_MAX = {"conservador": 2, "moderado": 3, "arriesgado": 5}
NOMBRE_TIPO = {"aporte": "aporte", "retiro": "retiro", "comision": "comisión"}


class ErrorNegocio(Exception):
    pass


def _umbral(clave):
    return current_app.config[clave] * 100


def requiere_origen(op):
    return op["tipo"] == "aporte" and op["monto_cent"] >= _umbral("UMBRAL_ORIGEN_FONDOS_USD")


def requiere_doble_firma(op):
    return op["monto_cent"] >= _umbral("UMBRAL_DOBLE_FIRMA_USD")


def fuera_de_perfil(cliente, modelo):
    """True si la cartera tiene más riesgo que el que admite el perfil del cliente (evaluación de idoneidad)."""
    return modelo["riesgo"] > RIESGO_MAX.get(cliente["perfil_riesgo"], 5)


def solicitar_aporte(cliente, monto, modelo, referencia, usuario, ts=None, acepta_riesgo=False):
    minimo = _umbral("APORTE_MINIMO_USD")
    if monto < minimo:
        raise ErrorNegocio(f"El aporte mínimo es de {fmt_usd(minimo, 0)}.")
    m = db.uno("SELECT * FROM modelos WHERE codigo = ? AND activo = 1", (modelo,))
    if not m:
        raise ErrorNegocio("Elige una cartera.")
    fuera = fuera_de_perfil(cliente, m)
    if fuera and not acepta_riesgo:
        raise ErrorNegocio(f"La cartera {m['nombre']} tiene más riesgo que tu perfil {cliente['perfil_riesgo']}. "
                           "Para continuar, confirma que entiendes y aceptas ese riesgo.")
    ts = ts or ahora()
    with db.transaccion() as c:
        cur = c.execute(
            "INSERT INTO operaciones (cliente_id, tipo, monto_cent, modelo, referencia, estado, creado, creado_por, fuera_perfil)"
            " VALUES (?, 'aporte', ?, ?, ?, 'pendiente', ?, ?, ?)",
            (cliente["id"], monto, modelo, (referencia or "").strip()[:80] or None, ts, usuario["id"] if usuario else None,
             1 if fuera else 0),
        )
        opid = cur.lastrowid
        extra = " Confirmó que acepta un riesgo mayor al de su perfil." if fuera else ""
        auditoria.registrar("operacion.solicitada", f"operacion:{opid}",
                            {"texto": f"{cliente['nombre']} solicitó un aporte de {fmt_usd(monto)} a la cartera {m['nombre']}.{extra}",
                             "tipo": "aporte", "monto_cent": monto, "fuera_perfil": fuera}, usuario=usuario, ts=ts)
        _avisar_equipo(f"{cliente['nombre']} solicitó un aporte de {fmt_usd(monto)}.", opid, usuario, ts)
    return opid


def _avisar_equipo(texto, opid, usuario, ts):
    notificaciones.notificar_rol(("operador", "admin"), texto, f"/equipo/operaciones/{opid}",
                                 excepto=usuario["id"] if usuario else None, ts=ts)


def solicitar_retiro(cliente, monto, usuario, ts=None):
    if monto <= 0:
        raise ErrorNegocio("Escribe el monto que quieres retirar.")
    ts = ts or ahora()
    with db.transaccion() as c:
        _, total = cartera.posiciones(cliente["id"])
        pendiente = c.execute(
            "SELECT COALESCE(SUM(monto_cent), 0) AS s FROM operaciones WHERE cliente_id = ? AND tipo = 'retiro'"
            " AND estado IN ('pendiente', 'primera_firma')", (cliente["id"],)).fetchone()["s"]
        disponible = total - pendiente
        if monto > disponible:
            raise ErrorNegocio(f"El retiro supera lo disponible en tu cartera ({fmt_usd(max(disponible, 0))}).")
        cur = c.execute(
            "INSERT INTO operaciones (cliente_id, tipo, monto_cent, estado, creado, creado_por)"
            " VALUES (?, 'retiro', ?, 'pendiente', ?, ?)", (cliente["id"], monto, ts, usuario["id"] if usuario else None))
        opid = cur.lastrowid
        auditoria.registrar("operacion.solicitada", f"operacion:{opid}",
                            {"texto": f"{cliente['nombre']} solicitó un retiro de {fmt_usd(monto)}.",
                             "tipo": "retiro", "monto_cent": monto}, usuario=usuario, ts=ts)
        _avisar_equipo(f"{cliente['nombre']} solicitó un retiro de {fmt_usd(monto)}.", opid, usuario, ts)
    return opid


def cancelar(opid, cliente, usuario):
    with db.transaccion() as c:
        op = c.execute("SELECT * FROM operaciones WHERE id = ? AND cliente_id = ?", (opid, cliente["id"])).fetchone()
        if not op:
            raise ErrorNegocio("La solicitud no existe.")
        if op["estado"] != "pendiente":
            raise ErrorNegocio("Solo se pueden cancelar solicitudes que nadie empezó a revisar.")
        c.execute("UPDATE operaciones SET estado = 'cancelada', resuelto_ts = ?, resuelto_por = ? WHERE id = ?",
                  (ahora(), usuario["id"], opid))
        auditoria.registrar("operacion.cancelada", f"operacion:{opid}",
                            {"texto": f"{cliente['nombre']} canceló su {op['tipo']} de {fmt_usd(op['monto_cent'])}."},
                            usuario=usuario)


def _activos_afectados(op):
    if op["tipo"] == "aporte":
        return [a for a, _ in cartera.pesos_modelo(op["modelo"])]
    return [a for a, u in cartera.tenencias(op["cliente_id"]).items() if a != "USD" and u > 0]


def requisitos(op, cli, usuario):
    """Lista de controles para mostrar en la pantalla de la operación: (estado, texto). estado: True, False o None."""
    out = []
    ok = cli["kyc_estado"] == "verificado"
    out.append((ok, "Identidad del cliente verificada" if ok else "La identidad del cliente no está verificada"))
    if requiere_origen(op):
        ok = bool(cli["origen_fondos"])
        out.append((ok, "Origen de los fondos registrado" if ok else
                    f"Falta registrar el origen de los fondos (aportes desde {fmt_usd(_umbral('UMBRAL_ORIGEN_FONDOS_USD'), 0)})"))
    if op["tipo"] == "aporte" and op["fuera_perfil"]:
        out.append((None, "La cartera tiene más riesgo que el perfil del cliente; el cliente lo confirmó al solicitar"))
    if requiere_doble_firma(op):
        if op["estado"] == "pendiente":
            out.append((None, f"Requiere dos firmas (montos desde {fmt_usd(_umbral('UMBRAL_DOBLE_FIRMA_USD'), 0)}): tu aprobación sería la primera"))
        elif op["estado"] == "primera_firma":
            otra = usuario["id"] != op["firma1_por"]
            rol = usuario["rol"] in ("cumplimiento", "admin")
            out.append((otra and rol, "Puedes dar la segunda firma" if otra and rol else
                        "La segunda firma tiene que darla otra persona de Cumplimiento o un administrador"))
    if op["estado"] in ESTADOS_ABIERTOS:
        viejos = precios.antiguos(_activos_afectados(op))
        out.append((not viejos, "Precios actualizados" if not viejos else
                    "Hay precios sin cargar o desactualizados: " + ", ".join(a for a, _ in viejos)))
    return out


def aprobar(opid, usuario, ts=None, precios_usar=None):
    """Aprueba una operación. Devuelve 'primera_firma' o 'liquidada'."""
    ts = ts or ahora()
    with db.transaccion() as c:
        op = c.execute("SELECT * FROM operaciones WHERE id = ?", (opid,)).fetchone()
        if not op:
            raise ErrorNegocio("La operación no existe.")
        if op["estado"] not in ESTADOS_ABIERTOS:
            raise ErrorNegocio("Esta operación ya fue resuelta.")
        cli = c.execute("SELECT * FROM clientes WHERE id = ?", (op["cliente_id"],)).fetchone()
        monto, tipo = op["monto_cent"], op["tipo"]
        if cli["kyc_estado"] != "verificado":
            raise ErrorNegocio(f"No se puede aprobar: la identidad de {cli['nombre']} no está verificada.")
        if requiere_origen(op) and not cli["origen_fondos"]:
            raise ErrorNegocio(f"No se puede aprobar: falta registrar el origen de los fondos de {cli['nombre']}.")
        doble = requiere_doble_firma(op)
        if doble and op["estado"] == "pendiente":
            c.execute("UPDATE operaciones SET estado = 'primera_firma', firma1_por = ?, firma1_ts = ? WHERE id = ?",
                      (usuario["id"], ts, opid))
            auditoria.registrar("operacion.primera_firma", f"operacion:{opid}",
                                {"texto": f"Dio la primera firma al {tipo} #{opid} de {cli['nombre']} por {fmt_usd(monto)}.",
                                 "monto_cent": monto}, usuario=usuario, ts=ts)
            notificaciones.notificar_rol(("cumplimiento", "admin"),
                                         f"El {tipo} #{opid} de {cli['nombre']} por {fmt_usd(monto)} espera la segunda firma.",
                                         f"/equipo/operaciones/{opid}", excepto=usuario["id"], ts=ts)
            return "primera_firma"
        if doble:
            if op["firma1_por"] == usuario["id"]:
                raise ErrorNegocio("La segunda firma tiene que darla otra persona.")
            if usuario["rol"] not in ("cumplimiento", "admin"):
                raise ErrorNegocio("La segunda firma corresponde a Cumplimiento o a un administrador.")
        if precios_usar is None:
            try:
                precios.exigir_frescura(_activos_afectados(op))
            except precios.ErrorPrecio as e:
                raise ErrorNegocio(str(e)) from None
        pr = precios_usar if precios_usar is not None else precios.vigentes()
        try:
            if tipo == "aporte":
                liquidado = cartera.ejecutar_aporte(c, op, cartera.pesos_modelo(op["modelo"]), pr, ts)
                c.execute("UPDATE clientes SET modelo = ? WHERE id = ?", (op["modelo"], cli["id"]))
            else:
                liquidado = cartera.ejecutar_retiro(c, op, pr, ts)
        except cartera.ErrorCartera as e:
            raise ErrorNegocio(str(e)) from None
        if doble:
            c.execute("UPDATE operaciones SET firma2_por = ?, firma2_ts = ? WHERE id = ?", (usuario["id"], ts, opid))
        else:
            c.execute("UPDATE operaciones SET firma1_por = ?, firma1_ts = ? WHERE id = ?", (usuario["id"], ts, opid))
        c.execute("UPDATE operaciones SET estado = 'liquidada', resuelto_ts = ?, resuelto_por = ?, liquidado_cent = ?"
                  " WHERE id = ?", (ts, usuario["id"], liquidado, opid))
        verbo = "Liquidó el aporte" if tipo == "aporte" else "Liquidó el retiro"
        auditoria.registrar("operacion.liquidada", f"operacion:{opid}",
                            {"texto": f"{verbo} #{opid} de {cli['nombre']} por {fmt_usd(liquidado)}.",
                             "monto_cent": monto, "liquidado_cent": liquidado}, usuario=usuario, ts=ts)
        if cli["usuario_id"]:
            texto = (f"Tu aporte #{opid} de {fmt_usd(monto)} fue aprobado e invertido." if tipo == "aporte" else
                     f"Tu retiro #{opid} de {fmt_usd(liquidado)} fue aprobado. El pago se acredita en tu cuenta bancaria.")
            notificaciones.notificar(cli["usuario_id"], texto, "/cliente/movimientos", ts=ts)
        return "liquidada"


def rechazar(opid, usuario, motivo, ts=None):
    motivo = (motivo or "").strip()
    if len(motivo) < 5:
        raise ErrorNegocio("Escribe el motivo del rechazo; el cliente lo verá.")
    ts = ts or ahora()
    with db.transaccion() as c:
        op = c.execute("SELECT * FROM operaciones WHERE id = ?", (opid,)).fetchone()
        if not op:
            raise ErrorNegocio("La operación no existe.")
        if op["estado"] not in ESTADOS_ABIERTOS:
            raise ErrorNegocio("Esta operación ya fue resuelta.")
        cli = c.execute("SELECT nombre, usuario_id FROM clientes WHERE id = ?", (op["cliente_id"],)).fetchone()
        c.execute("UPDATE operaciones SET estado = 'rechazada', resuelto_ts = ?, resuelto_por = ?, motivo = ? WHERE id = ?",
                  (ts, usuario["id"], motivo[:300], opid))
        auditoria.registrar("operacion.rechazada", f"operacion:{opid}",
                            {"texto": f"Rechazó el {op['tipo']} #{opid} de {cli['nombre']} por {fmt_usd(op['monto_cent'])}: {motivo[:300]}",
                             "motivo": motivo[:300]}, usuario=usuario, ts=ts)
        if cli["usuario_id"]:
            notificaciones.notificar(cli["usuario_id"],
                                     f"Tu {op['tipo']} #{opid} de {fmt_usd(op['monto_cent'])} fue rechazado: {motivo[:300]}",
                                     "/cliente/movimientos", ts=ts)


def alertas():
    """Alertas de cumplimiento abiertas: (gravedad, texto, enlace_operacion o enlace_cliente)."""
    out = []
    abiertas = db.todos(
        "SELECT o.*, c.nombre, c.kyc_estado, c.origen_fondos FROM operaciones o JOIN clientes c ON c.id = o.cliente_id"
        " WHERE o.estado IN ('pendiente', 'primera_firma') ORDER BY o.creado")
    for o in abiertas:
        if o["kyc_estado"] != "verificado":
            out.append(("alta", f"{o['nombre']}: tiene un {o['tipo']} de {fmt_usd(o['monto_cent'])} pendiente y su identidad no está verificada.", ("op", o["id"])))
        if requiere_origen(o) and not o["origen_fondos"]:
            out.append(("media", f"{o['nombre']}: aporte de {fmt_usd(o['monto_cent'])} sin origen de fondos registrado.", ("op", o["id"])))
        if o["estado"] == "primera_firma":
            out.append(("info", f"{o['nombre']}: {o['tipo']} de {fmt_usd(o['monto_cent'])} espera la segunda firma.", ("op", o["id"])))
        if o["tipo"] == "aporte" and o["fuera_perfil"]:
            out.append(("info", f"{o['nombre']}: eligió una cartera con más riesgo que su perfil y lo confirmó.", ("op", o["id"])))
    for c in db.todos("SELECT id, nombre, kyc_nota FROM clientes WHERE kyc_estado = 'observado' ORDER BY nombre"):
        out.append(("media", f"{c['nombre']}: verificación observada. {c['kyc_nota'] or ''}".strip(), ("cliente", c["id"])))
    from . import documentos
    n_docs = len(documentos.pendientes_revision())
    if n_docs:
        out.append(("info", f"{n_docs} documento{'s' if n_docs > 1 else ''} del legajo esperan revisión.", ("documentos", None)))
    viejos = precios.antiguos()
    if viejos:
        out.append(("media", "Precios sin cargar o desactualizados: " + ", ".join(a for a, _ in viejos) + ".", ("precios", None)))
    estado, ult = conciliacion.estado()
    if estado == "diferencias":
        out.append(("alta", "La última conciliación de custodia tiene diferencias entre el libro y los saldos reales.", ("conciliacion", None)))
    elif estado == "vencida":
        out.append(("media", "La conciliación de custodia tiene más de un día. Regístrala de nuevo.", ("conciliacion", None)))
    elif estado == "nunca":
        out.append(("media", "Todavía no se registró ninguna conciliación de custodia.", ("conciliacion", None)))
    orden = {"alta": 0, "media": 1, "info": 2}
    return sorted(out, key=lambda x: orden[x[0]])
