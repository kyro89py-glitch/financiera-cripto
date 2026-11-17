"""Centro de actividad: todo lo que pasó en la cuenta, en una sola línea de tiempo con filtros.

Junta los registros de la bitácora que corresponden a la persona (ingresos, seguridad, perfil, configuración) con sus
operaciones, envíos, órdenes programadas y alertas. Son datos del servidor: nada se toma del navegador.
"""
import json

from . import db
from .dinero import fmt_usd
from .formato import ESTADOS, TIPOS_OP, zona
from .tiempo import leer

CATEGORIAS = {"sesiones": "Inicios de sesión", "seguridad": "Seguridad", "perfil": "Perfil y datos", "config": "Configuración",
              "operaciones": "Compras y ventas", "depositos": "Depósitos", "retiros": "Retiros", "transferencias": "Transferencias",
              "ordenes": "Órdenes y alertas"}
POR_ACCION = {
    "ingreso.ok": ("sesiones", "ok", "Correcto"), "ingreso.fallido": ("sesiones", "bad", "Fallido"), "salida": ("sesiones", "", "Cerrada"),
    "sesion.cerrada": ("seguridad", "ok", "Hecho"), "clave.cambiada": ("seguridad", "ok", "Hecho"),
    "clave.recuperacion": ("seguridad", "warn", "Solicitado"), "clave.recuperada": ("seguridad", "ok", "Hecho"),
    "2fa.activada": ("seguridad", "ok", "Hecho"), "2fa.desactivada": ("seguridad", "warn", "Hecho"),
    "perfil.correo_pedido": ("seguridad", "warn", "Esperando confirmación"), "perfil.correo": ("seguridad", "ok", "Hecho"),
    "privacidad.cambiada": ("config", "ok", "Guardado"), "preferencias.cambiadas": ("config", "ok", "Guardado"),
    "perfil.datos": ("perfil", "ok", "Guardado"), "perfil.foto": ("perfil", "ok", "Guardado"), "perfil.usuario": ("perfil", "ok", "Guardado"),
    "cuenta.correccion_pedido": ("perfil", "warn", "En revisión"), "cuenta.cierre_pedido": ("perfil", "warn", "En revisión"),
    "documento.subido": ("perfil", "ok", "Recibido"), "terminos.aceptados": ("perfil", "ok", "Aceptado"),
    "datos.descargados": ("perfil", "ok", "Hecho"),
    "programada.creada": ("ordenes", "ok", "Creada"), "programada.oco": ("ordenes", "ok", "Creada"),
    "programada.cancelada": ("ordenes", "", "Cancelada"), "plan.creado": ("ordenes", "ok", "Creado"), "plan.cancelado": ("ordenes", "", "Cancelado"),
}


PROPIO = {"ingreso.ok": "Inicio de sesión", "ingreso.fallido": "Intento de ingreso con contraseña o código incorrecto",
          "salida": "Cierre de sesión"}


def _texto(detalle):
    try:
        return json.loads(detalle).get("texto") or "Acción registrada"
    except (ValueError, TypeError, AttributeError):
        return detalle or "Acción registrada"


def eventos(usuario, cliente=None, categoria=None, desde=None, hasta=None, limite=400):
    """Lista de eventos, del más nuevo al más viejo: ts, cat, texto, estado (clase, etiqueta), enlace, ip."""
    out = []
    marcas = ",".join("?" * len(POR_ACCION))
    for b in db.todos(f"SELECT ts, accion, detalle, ip FROM bitacora WHERE (usuario_id = ? OR objeto = ?) AND accion IN ({marcas})"
                      " ORDER BY id DESC LIMIT 600", (usuario["id"], f"usuario:{usuario['id']}", *POR_ACCION)):
        cat, clase, etiqueta = POR_ACCION[b["accion"]]
        out.append({"ts": b["ts"], "cat": cat, "texto": PROPIO.get(b["accion"]) or _texto(b["detalle"]), "estado": (clase, etiqueta), "enlace": None, "ip": b["ip"]})
    if cliente:
        for o in db.todos("SELECT * FROM operaciones WHERE cliente_id = ? ORDER BY id DESC LIMIT 400", (cliente["id"],)):
            cat = {"aporte": "depositos", "retiro": "retiros"}.get(o["tipo"], "operaciones")
            monto = o["liquidado_cent"] if o["liquidado_cent"] is not None else o["monto_cent"]
            out.append({"ts": o["creado"], "cat": cat, "texto": f"{TIPOS_OP[o['tipo']]}{' de ' + o['activo'] if o['activo'] else ''} por {fmt_usd(monto)}",
                        "estado": ESTADOS[o["estado"]], "enlace": f"/cliente/movimientos/{o['id']}", "ip": None})
        for t in db.todos("SELECT t.*, d.nombre AS de_nombre, a.nombre AS a_nombre FROM transferencias t JOIN clientes d ON d.id = t.de_cliente"
                          " JOIN clientes a ON a.id = t.a_cliente WHERE t.de_cliente = ? OR t.a_cliente = ? ORDER BY t.id DESC LIMIT 200",
                          (cliente["id"], cliente["id"])):
            sale = t["de_cliente"] == cliente["id"]
            out.append({"ts": t["ts"], "cat": "transferencias", "estado": ("ok", "Hecho"), "enlace": f"/cliente/envios/{t['id']}", "ip": None,
                        "texto": (f"Enviaste {fmt_usd(t['valor_cent'])} a {t['a_nombre'].split()[0]}" if sale
                                  else f"Recibiste {fmt_usd(t['valor_cent'])} de {t['de_nombre'].split()[0]}")})
        for p in db.todos("SELECT * FROM programadas WHERE cliente_id = ? AND estado IN ('ejecutada', 'fallida') ORDER BY id DESC LIMIT 100",
                          (cliente["id"],)):
            out.append({"ts": p["resuelta_ts"] or p["creado"], "cat": "ordenes", "enlace": f"/trading/{p['activo']}", "ip": None,
                        "texto": f"Orden programada de {p['lado']} de {p['activo']} " + ("ejecutada" if p["estado"] == "ejecutada" else "no se pudo ejecutar"),
                        "estado": ("ok", "Ejecutada") if p["estado"] == "ejecutada" else ("bad", "Fallida")})
    for a in db.todos("SELECT * FROM alertas_precio WHERE usuario_id = ? AND disparada_ts IS NOT NULL ORDER BY id DESC LIMIT 100", (usuario["id"],)):
        out.append({"ts": a["disparada_ts"], "cat": "ordenes", "texto": f"Se activó tu alerta de {a['activo']}", "estado": ("info", "Avisada"),
                    "enlace": f"/mercado/{a['activo']}", "ip": None})
    if categoria in CATEGORIAS:
        out = [e for e in out if e["cat"] == categoria]
    if desde or hasta:
        z = zona()
        dia = lambda e: leer(e["ts"]).astimezone(z).date().isoformat()  # noqa: E731
        out = [e for e in out if (not desde or dia(e) >= desde) and (not hasta or dia(e) <= hasta)]
    out.sort(key=lambda e: e["ts"], reverse=True)
    return out[:limite]


def por_dia(lista):
    """Agrupa por fecha local para mostrar la línea de tiempo."""
    z, grupos = zona(), {}
    for e in lista:
        grupos.setdefault(leer(e["ts"]).astimezone(z).date(), []).append(e)
    return grupos
