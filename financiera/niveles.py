"""Límites de operación (editables por Administración), nivel de verificación y estado de protección de la cuenta."""
from datetime import timedelta

from flask import current_app

from . import auditoria, db
from .tiempo import ahora, ahora_dt, iso

# clave de configuración: (título, explicación, mínimo, máximo) en dólares
LIMITES = {
    "ORDEN_MAXIMA_USD": ("Máximo por orden", "Tope de cada compra, venta u orden programada.", 100, 1_000_000),
    "ENVIO_MAX_DIA_USD": ("Envíos por día", "Total que un cliente puede enviar a otros clientes en un día.", 0, 1_000_000),
    "RETIRO_MAX_DIA_USD": ("Retiros por día", "Total que un cliente puede pedir en retiros en un día.", 100, 5_000_000),
    "UMBRAL_DOBLE_FIRMA_USD": ("Doble firma desde", "Los depósitos y retiros desde este monto necesitan dos aprobaciones.", 100, 5_000_000),
    "UMBRAL_AML_USD": ("Umbral antilavado", "Monto desde el cual se genera una alerta de monto alto.", 1000, 5_000_000),
}


def valor(clave):
    """Límite vigente en dólares: el que cargó Administración o, si no hay, el de la configuración."""
    f = db.uno("SELECT valor FROM ajustes WHERE clave = ?", ("limite." + clave,))
    if f:
        try:
            return int(f["valor"])
        except ValueError:
            pass
    return int(current_app.config[clave])


def cent(clave):
    return valor(clave) * 100


def fijar(clave, dolares, usuario):
    if clave not in LIMITES:
        raise ValueError("Límite desconocido.")
    _, _, mn, mx = LIMITES[clave]
    if not mn <= dolares <= mx:
        raise ValueError(f"{LIMITES[clave][0]}: elige un valor entre US$ {mn:,} y US$ {mx:,}.".replace(",", "."))
    antes = valor(clave)
    if antes == dolares:
        return False
    ts = ahora()
    db.ejecutar("INSERT INTO ajustes (clave, valor, ts, por) VALUES (?, ?, ?, ?) ON CONFLICT(clave) DO UPDATE SET"
                " valor = excluded.valor, ts = excluded.ts, por = excluded.por", ("limite." + clave, str(int(dolares)), ts, usuario["id"]))
    auditoria.registrar("limite.cambiado", None, {"texto": f"Cambió el límite «{LIMITES[clave][0]}» de US$ {antes:,} a US$ {int(dolares):,}."
                                                  .replace(",", ".")}, usuario=usuario, ts=ts)
    return True


def retirado_hoy(cliente_id):
    hoy = ahora_dt().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.uno("SELECT COALESCE(SUM(monto_cent), 0) AS s FROM operaciones WHERE cliente_id = ? AND tipo = 'retiro'"
                  " AND estado NOT IN ('rechazada', 'cancelada') AND creado >= ?", (cliente_id, iso(hoy)))["s"]


def nivel(cliente, usuario):
    """Nivel de verificación: 0 cuenta abierta, 1 identidad verificada, 2 verificación reforzada."""
    if cliente["kyc_estado"] != "verificado":
        return {"n": 0, "nombre": "Cuenta abierta", "puede": "Ver precios y completar tu verificación.",
                "falta": "Subir tus documentos y esperar la verificación de identidad."}
    origen = bool(db.uno("SELECT 1 FROM documentos WHERE cliente_id = ? AND tipo = 'ingresos' AND estado = 'aceptado'", (cliente["id"],)))
    if usuario["totp_secreto"] and origen:
        return {"n": 2, "nombre": "Verificación reforzada", "puede": "Operar con todos los límites vigentes.", "falta": None}
    faltan = [t for ok, t in ((usuario["totp_secreto"], "activar la verificación en dos pasos"),
                              (origen, "tener aprobado un documento de origen de los fondos")) if not ok]
    return {"n": 1, "nombre": "Identidad verificada", "puede": "Depositar, operar, enviar y retirar dentro de los límites.",
            "falta": "Para el nivel reforzado: " + " y ".join(faltan) + "."}


def proteccion(cliente, usuario):
    """Estado de protección de la cuenta: lista de controles con su resultado y un puntaje de 0 a 100."""
    from . import seguridad
    controles = []

    def c(ok, peso, titulo, texto, enlace=None, accion=None):
        controles.append({"ok": bool(ok), "peso": peso, "titulo": titulo, "texto": texto, "enlace": enlace, "accion": accion})

    c(usuario["totp_secreto"], 35, "Verificación en dos pasos", "Pide un código de tu teléfono además de la contraseña."
      if not usuario["totp_secreto"] else "Activa: nadie entra solo con tu contraseña.", "/cuenta/seguridad", "Activar")
    c(not usuario["debe_cambiar_clave"] and not seguridad.necesita_rehash(usuario["clave_hash"]), 15, "Contraseña",
      "Propia y guardada con la protección vigente." if not usuario["debe_cambiar_clave"] else "Todavía usas una contraseña temporal.",
      "/cuenta/clave", "Cambiar")
    if cliente:
        c(cliente["kyc_estado"] == "verificado", 20, "Identidad verificada",
          "Tu identidad está confirmada." if cliente["kyc_estado"] == "verificado" else "Falta completar la verificación de identidad.",
          "/cliente/perfil#legajo", "Completar")
    activas = db.uno("SELECT COUNT(*) AS n FROM sesiones WHERE usuario_id = ? AND cerrada IS NULL AND ultima >= ?",
                     (usuario["id"], iso(ahora_dt() - timedelta(days=30))))["n"]
    c(activas <= 3, 10, "Sesiones abiertas", f"Tienes {activas} sesión{'es' if activas != 1 else ''} activa{'s' if activas != 1 else ''}."
      + ("" if activas <= 3 else " Cierra las que no reconozcas."), "/cuenta/sesiones", "Revisar")
    fallidos = db.uno("SELECT COUNT(*) AS n FROM bitacora WHERE objeto = ? AND accion = 'ingreso.fallido' AND ts >= ?",
                      (f"usuario:{usuario['id']}", iso(ahora_dt() - timedelta(days=7))))["n"]
    c(fallidos == 0, 10, "Intentos fallidos", "Sin intentos fallidos de ingreso en los últimos 7 días." if not fallidos
      else f"{fallidos} intento{'s' if fallidos != 1 else ''} fallido{'s' if fallidos != 1 else ''} de ingreso en 7 días. Si no fuiste tú, cambia tu contraseña.",
      "/cuenta/sesiones", "Ver actividad")
    sin_leer = db.uno("SELECT COUNT(*) AS n FROM notificaciones WHERE usuario_id = ? AND categoria = 'seguridad' AND leida = 0",
                      (usuario["id"],))["n"]
    c(sin_leer == 0, 10, "Avisos de seguridad", "No tienes avisos de seguridad sin leer." if not sin_leer
      else f"Tienes {sin_leer} aviso{'s' if sin_leer != 1 else ''} de seguridad sin leer.", "/cuenta/avisos?cat=seguridad", "Leer")
    total = sum(x["peso"] for x in controles)
    puntos = round(sum(x["peso"] for x in controles if x["ok"]) / total * 100) if total else 0
    estado = "alta" if puntos >= 85 else "media" if puntos >= 55 else "baja"
    return {"controles": controles, "puntos": puntos, "estado": estado}
