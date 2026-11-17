"""Control dual: las acciones críticas de administración no se ejecutan cuando alguien las pide, sino cuando otra persona
autorizada las aprueba. Quien pide no puede aprobar lo suyo. Cada pedido, aprobación, rechazo y resultado queda en la bitácora."""
import json
from datetime import timedelta

from flask import current_app

from . import auditoria, db, notificaciones, seguridad
from .tiempo import ahora, ahora_dt, iso

VIGENCIA_H = 48
ESTADOS = {"pendiente": ("warn", "Pendiente"), "ejecutada": ("ok", "Aprobada y ejecutada"), "rechazada": ("bad", "Rechazada"),
           "cancelada": ("", "Cancelada"), "vencida": ("", "Vencida"), "fallida": ("bad", "Aprobada, no se pudo ejecutar")}


class ErrorAutorizacion(Exception):
    pass


def activo():
    return bool(current_app.config.get("CONTROL_DUAL", True))


# ---------- acciones: validar al pedir (sin cambiar nada) y ejecutar al aprobar ----------
def _limites_validar(d):
    from . import niveles
    cambios, partes = {}, []
    for clave, dolares in (d.get("cambios") or {}).items():
        if clave not in niveles.LIMITES:
            raise ErrorAutorizacion("Límite desconocido.")
        t, _, mn, mx = niveles.LIMITES[clave]
        if not isinstance(dolares, int) or not mn <= dolares <= mx:
            raise ErrorAutorizacion(f"{t}: elige un valor entre US$ {mn:,} y US$ {mx:,}.".replace(",", "."))
        if niveles.valor(clave) != dolares:
            cambios[clave] = dolares
            partes.append(f"{t}: de US$ {niveles.valor(clave):,} a US$ {dolares:,}".replace(",", "."))
    if not cambios:
        raise ErrorAutorizacion("No hay cambios: los valores son los vigentes.")
    return {"cambios": cambios}, "Cambiar límites — " + "; ".join(partes)


def _limites_ejecutar(d, solicitante):
    from . import niveles
    n = sum(1 for k, v in d["cambios"].items() if niveles.fijar(k, v, solicitante))
    return f"{n} límite(s) actualizados."


def _usuario_validar(d):
    u = db.uno("SELECT * FROM usuarios WHERE id = ? AND rol != 'cliente'", (d.get("uid"),))
    if not u:
        raise ErrorAutorizacion("Usuario del equipo inexistente.")
    if d.get("solicitante") == u["id"]:
        raise ErrorAutorizacion("No puedes desactivar tu propio usuario.")
    nuevo = 0 if u["activo"] else 1
    return {"uid": u["id"], "activo": nuevo}, f"{'Reactivar' if nuevo else 'Desactivar'} al usuario del equipo {u['email']} ({u['rol']})"


def _usuario_ejecutar(d, solicitante):
    u = db.uno("SELECT * FROM usuarios WHERE id = ?", (d["uid"],))
    with db.transaccion() as c:
        c.execute("UPDATE usuarios SET activo = ?, sesion_ver = sesion_ver + 1 WHERE id = ?", (d["activo"], d["uid"]))
        auditoria.registrar("usuario.estado", f"usuario:{d['uid']}",
                            {"texto": f"{'Reactivó' if d['activo'] else 'Desactivó'} al usuario {u['email']}."}, usuario=solicitante)
    return "Usuario " + ("reactivado." if d["activo"] else "desactivado; sus sesiones se cerraron.")


def _comision_validar(d):
    from . import comisiones
    periodo = (d.get("periodo") or "").strip()
    if not comisiones.tasa():
        raise ErrorAutorizacion("La comisión de gestión está desactivada (COMISION_ANUAL_PCT = 0).")
    try:
        nombre = comisiones.nombre_periodo(periodo)
    except Exception:  # noqa: BLE001
        raise ErrorAutorizacion("Período inválido.") from None
    return {"periodo": periodo}, f"Cobrar la comisión de gestión de {nombre} a los clientes con cartera administrada"


def _comision_ejecutar(d, solicitante):
    from . import comisiones
    r = comisiones.cobrar(d["periodo"], solicitante)
    return f"Se cobró a {r['cobradas']} clientes" + (f"; {r['ya_cobradas']} ya estaban cobrados" if r["ya_cobradas"] else "") + \
        (f"; {len(r.get('errores', []))} con error" if r.get("errores") else "") + "."


ACCIONES = {
    "limites": ("Cambio de límites de operación", "limites.editar", _limites_validar, _limites_ejecutar),
    "usuario_estado": ("Alta o baja de un usuario del equipo", "usuarios.gestionar", _usuario_validar, _usuario_ejecutar),
    "comision": ("Cobro de la comisión de gestión", "comisiones.cobrar", _comision_validar, _comision_ejecutar),
}


def solicitar(accion, detalle, motivo, usuario):
    if accion not in ACCIONES:
        raise ErrorAutorizacion("Acción desconocida.")
    nombre, permiso, validar, _ = ACCIONES[accion]
    if not seguridad.puede(permiso, usuario):
        raise ErrorAutorizacion("No tienes permiso para pedir esa acción.")
    motivo = " ".join((motivo or "").split())[:300]
    if len(motivo) < 5:
        raise ErrorAutorizacion("Explica brevemente el motivo: lo lee quien autoriza y queda en la bitácora.")
    detalle, resumen = validar(dict(detalle or {}, solicitante=usuario["id"]))
    if db.uno("SELECT 1 FROM autorizaciones WHERE estado = 'pendiente' AND accion = ? AND detalle = ? AND vence > ?",
              (accion, json.dumps(detalle, sort_keys=True), ahora())):
        raise ErrorAutorizacion("Ya hay un pedido igual esperando autorización.")
    ts = ahora()
    aid = db.ejecutar("INSERT INTO autorizaciones (accion, detalle, resumen, motivo, solicitada_por, solicitada, vence) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (accion, json.dumps(detalle, sort_keys=True), resumen, motivo, usuario["id"], ts,
                       iso(ahora_dt() + timedelta(hours=VIGENCIA_H)))).lastrowid
    auditoria.registrar("autorizacion.pedida", f"autorizacion:{aid}", {"texto": f"Pidió autorización: {resumen}. Motivo: {motivo}"}, usuario=usuario)
    notificaciones.notificar_rol(("admin", "cumplimiento"), f"{usuario['nombre']} pide autorización: {resumen}.", "/equipo/autorizaciones",
                                 excepto=usuario["id"])
    return aid


def vencer():
    return db.ejecutar("UPDATE autorizaciones SET estado = 'vencida' WHERE estado = 'pendiente' AND vence <= ?", (ahora(),)).rowcount


def resolver(aid, aprobar, nota, revisor):
    vencer()
    a = db.uno("SELECT * FROM autorizaciones WHERE id = ?", (aid,))
    if not a or a["estado"] != "pendiente":
        raise ErrorAutorizacion("Ese pedido ya no está pendiente.")
    if a["solicitada_por"] == revisor["id"]:
        raise ErrorAutorizacion("Una acción crítica la tiene que autorizar otra persona, no quien la pidió.")
    if not seguridad.puede("autorizaciones.resolver", revisor):
        raise ErrorAutorizacion("No tienes permiso para autorizar.")
    nota = " ".join((nota or "").split())[:300]
    if not aprobar and len(nota) < 5:
        raise ErrorAutorizacion("Al rechazar, explica el motivo.")
    ts = ahora()
    # se marca primero como tomada para que dos personas no la ejecuten a la vez
    if db.ejecutar("UPDATE autorizaciones SET estado = ?, resuelta_por = ?, resuelta = ?, nota = ? WHERE id = ? AND estado = 'pendiente'",
                   ("ejecutada" if aprobar else "rechazada", revisor["id"], ts, nota or None, aid)).rowcount != 1:
        raise ErrorAutorizacion("Ese pedido ya no está pendiente.")
    solicitante = db.uno("SELECT * FROM usuarios WHERE id = ?", (a["solicitada_por"],))
    if not aprobar:
        auditoria.registrar("autorizacion.rechazada", f"autorizacion:{aid}", {"texto": f"Rechazó: {a['resumen']}. Nota: {nota}"}, usuario=revisor)
        notificaciones.notificar(solicitante["id"], f"Rechazaron tu pedido «{a['resumen']}»: {nota}", "/equipo/autorizaciones", categoria="cuenta")
        return None
    auditoria.registrar("autorizacion.aprobada", f"autorizacion:{aid}",
                        {"texto": f"Autorizó: {a['resumen']} (pedido por {solicitante['nombre']})." + (f" Nota: {nota}" if nota else "")}, usuario=revisor)
    try:
        resultado = ACCIONES[a["accion"]][3](json.loads(a["detalle"]), solicitante)
        db.ejecutar("UPDATE autorizaciones SET resultado = ? WHERE id = ?", (resultado, aid))
    except Exception as e:  # noqa: BLE001  la aprobación queda registrada aunque la ejecución falle
        resultado = f"No se pudo ejecutar: {e}"
        db.ejecutar("UPDATE autorizaciones SET estado = 'fallida', resultado = ? WHERE id = ?", (resultado, aid))
        auditoria.registrar("autorizacion.fallida", f"autorizacion:{aid}", {"texto": resultado}, usuario=revisor)
    notificaciones.notificar(solicitante["id"], f"Autorizaron tu pedido «{a['resumen']}». {resultado}", "/equipo/autorizaciones", categoria="cuenta")
    return resultado


def cancelar(aid, usuario):
    a = db.uno("SELECT * FROM autorizaciones WHERE id = ?", (aid,))
    if not a or a["estado"] != "pendiente" or a["solicitada_por"] != usuario["id"]:
        raise ErrorAutorizacion("Solo quien pidió puede cancelar un pedido pendiente.")
    db.ejecutar("UPDATE autorizaciones SET estado = 'cancelada', resuelta = ? WHERE id = ?", (ahora(), aid))
    auditoria.registrar("autorizacion.cancelada", f"autorizacion:{aid}", {"texto": f"Canceló su pedido: {a['resumen']}."}, usuario=usuario)


def pendientes():
    vencer()
    return db.uno("SELECT COUNT(*) AS n FROM autorizaciones WHERE estado = 'pendiente'")["n"]


def lista(limite=100):
    vencer()
    return db.todos("SELECT a.*, s.nombre AS solicitante, r.nombre AS revisor FROM autorizaciones a JOIN usuarios s ON s.id = a.solicitada_por"
                    " LEFT JOIN usuarios r ON r.id = a.resuelta_por ORDER BY a.estado = 'pendiente' DESC, a.id DESC LIMIT ?", (limite,))
