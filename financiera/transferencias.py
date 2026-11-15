"""Envíos entre clientes de la plataforma: instantáneos, sin comisión y con los mismos controles de cumplimiento.

El dinero no sale de la casa: se mueve de una cuenta a otra dentro del libro, en una sola transacción. Cada envío pide
la contraseña de quien envía (y su código de dos pasos si lo tiene activo), tiene un límite diario y queda en la bitácora.
"""
from datetime import timedelta

from flask import current_app

from . import auditoria, cartera, db, notificaciones, precios, seguridad
from .dinero import fmt_unidades, fmt_usd, unidades_por, valor_cent
from .formato import zona
from .tiempo import ahora, ahora_dt, iso


class ErrorEnvio(Exception):
    pass


def ocultar(nombre):
    """'Laura Giménez Benítez' -> 'Laura G. B.': suficiente para confirmar a quién se envía sin exponer el nombre completo."""
    partes = (nombre or "").split()
    if not partes:
        return "—"
    return " ".join([partes[0]] + [p[0].upper() + "." for p in partes[1:3]])


def buscar(texto, excepto_cliente=None):
    """Cliente destinatario por correo o por número de documento (solo clientes con acceso al portal)."""
    t = (texto or "").strip()
    if not t:
        return None
    if "@" in t:
        c = db.uno("SELECT c.* FROM clientes c JOIN usuarios u ON u.id = c.usuario_id WHERE lower(u.email) = lower(?) AND u.activo = 1", (t,))
    else:
        doc = "".join(ch for ch in t.upper() if ch.isalnum())
        c = next((x for x in db.todos("SELECT c.* FROM clientes c JOIN usuarios u ON u.id = c.usuario_id WHERE u.activo = 1")
                  if "".join(ch for ch in x["documento"].upper() if ch.isalnum()).endswith(doc) and len(doc) >= 5), None)
    if c and excepto_cliente and c["id"] == excepto_cliente:
        return None
    if c and not c["recibir_envios"]:  # eligió no aparecer en las búsquedas de envíos
        return None
    return c


def enviado_hoy(cliente_id):
    """Valor en centavos de lo enviado desde la medianoche de Paraguay."""
    hoy = ahora_dt().astimezone(zona()).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.uno("SELECT COALESCE(SUM(valor_cent), 0) AS s FROM transferencias WHERE de_cliente = ? AND ts >= ?",
                  (cliente_id, iso(hoy)))["s"]


def limite_dia():
    return int(current_app.config.get("ENVIO_MAX_DIA_USD", 5000)) * 100


def enviar(cliente, destino_texto, activo, monto_cent, usuario, clave, codigo=None, nota=None, todo=False, ts=None):
    """Envía `monto_cent` (valor en dólares) de `activo` a otro cliente. Devuelve el id de la transferencia."""
    u = db.uno("SELECT * FROM usuarios WHERE id = ?", (usuario["id"],))
    if not seguridad.verificar_clave(u["clave_hash"], clave or ""):
        raise ErrorEnvio("La contraseña no es correcta.")
    contador = None
    if u["totp_secreto"]:
        contador = seguridad.totp_verificar(u["totp_secreto"], codigo or "", u["totp_ultimo"])
        if contador is None:
            raise ErrorEnvio("El código de verificación no es correcto.")
    if cliente["kyc_estado"] != "verificado":
        raise ErrorEnvio("Para enviar primero tenemos que verificar tu identidad.")
    destino = buscar(destino_texto, cliente["id"])
    if not destino:
        raise ErrorEnvio("No encontramos a ningún otro cliente con ese correo o documento.")
    if destino["kyc_estado"] != "verificado":
        raise ErrorEnvio("Esa persona todavía no tiene la identidad verificada y no puede recibir envíos.")
    activo = (activo or "").upper()
    if activo != "USD" and not db.uno("SELECT 1 FROM activos WHERE codigo = ?", (activo,)):
        raise ErrorEnvio("Elige qué moneda enviar.")
    ten = cartera.disponible(cliente["id"])
    tengo = ten.get(activo, 0)
    if tengo <= 0:
        raise ErrorEnvio(f"No tienes {'dólares' if activo == 'USD' else activo} para enviar.")
    if activo == "USD":
        cantidad = tengo if todo else monto_cent
        valor = cantidad
    else:
        vig = precios.vigentes().get(activo)
        if not vig:
            raise ErrorEnvio(f"No hay precio de {activo} en este momento.")
        cantidad = tengo if todo else min(tengo, unidades_por(monto_cent, vig["precio"]))
        valor = valor_cent(activo, cantidad, vig["precio"])
    if cantidad <= 0 or valor < 100:
        raise ErrorEnvio("El mínimo por envío es de US$ 1.")
    if cantidad > tengo:
        raise ErrorEnvio("No tienes saldo suficiente para ese envío.")
    if enviado_hoy(cliente["id"]) + valor > limite_dia():
        disponible = max(0, limite_dia() - enviado_hoy(cliente["id"]))
        raise ErrorEnvio(f"Superas el límite diario de envíos de {fmt_usd(limite_dia(), 0)}. Hoy puedes enviar hasta {fmt_usd(disponible)}.")
    ts = ts or ahora()
    nota = (nota or "").strip()[:120] or None
    with db.transaccion() as c:
        saldo = c.execute("SELECT COALESCE(SUM(cantidad), 0) AS s FROM libro WHERE cliente_id = ? AND activo = ?",
                          (cliente["id"], activo)).fetchone()["s"]
        if cantidad > saldo:
            raise ErrorEnvio("Tu saldo cambió mientras preparabas el envío; vuelve a intentarlo.")
        if contador is not None:
            c.execute("UPDATE usuarios SET totp_ultimo = ? WHERE id = ?", (contador, u["id"]))
        tid = c.execute("INSERT INTO transferencias (de_cliente, a_cliente, activo, cantidad, valor_cent, nota, ts, por)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (cliente["id"], destino["id"], activo, cantidad, valor, nota, ts, u["id"])).lastrowid
        c.execute("INSERT INTO libro (cliente_id, activo, cantidad, concepto, ts, transferencia_id) VALUES (?, ?, ?, 'envio', ?, ?)",
                  (cliente["id"], activo, -cantidad, ts, tid))
        c.execute("INSERT INTO libro (cliente_id, activo, cantidad, concepto, ts, transferencia_id) VALUES (?, ?, ?, 'recepcion', ?, ?)",
                  (destino["id"], activo, cantidad, ts, tid))
        que = fmt_usd(cantidad) if activo == "USD" else f"{fmt_unidades(cantidad, activo)} ({fmt_usd(valor)})"
        auditoria.registrar("transferencia.enviada", f"transferencia:{tid}",
                            {"texto": f"{cliente['nombre']} envió {que} a {destino['nombre']}.", "valor_cent": valor,
                             "de": cliente["id"], "a": destino["id"]}, usuario=u, ts=ts)
        if destino["usuario_id"]:
            notificaciones.notificar(destino["usuario_id"], f"Recibiste {que} de {ocultar(cliente['nombre'])}."
                                     + (f" Nota: «{nota}»" if nota else ""), "/cliente/cartera", ts=ts)
        aviso = int(current_app.config.get("ENVIO_AVISO_USD", 2000)) * 100
        if valor >= aviso:
            notificaciones.notificar_rol(("cumplimiento", "admin"), f"Envío alto entre clientes: {cliente['nombre']} envió {fmt_usd(valor)} "
                                         f"a {destino['nombre']}.", f"/equipo/clientes/{cliente['id']}", ts=ts)
    return tid


def del_cliente(cliente_id, limite=20):
    return db.todos(
        "SELECT t.*, d.nombre AS de_nombre, a.nombre AS a_nombre FROM transferencias t JOIN clientes d ON d.id = t.de_cliente"
        " JOIN clientes a ON a.id = t.a_cliente WHERE t.de_cliente = ? OR t.a_cliente = ? ORDER BY t.id DESC LIMIT ?",
        (cliente_id, cliente_id, limite))


def en_periodo(cliente_id, ini, fin):
    """(recibido, enviado) en centavos de valor entre dos fechas."""
    f = db.uno("SELECT COALESCE(SUM(CASE WHEN a_cliente = ? THEN valor_cent END), 0) AS r,"
               " COALESCE(SUM(CASE WHEN de_cliente = ? THEN valor_cent END), 0) AS e FROM transferencias"
               " WHERE (a_cliente = ? OR de_cliente = ?) AND ts > ? AND ts <= ?", (cliente_id, cliente_id, cliente_id, cliente_id, ini, fin))
    return f["r"], f["e"]
