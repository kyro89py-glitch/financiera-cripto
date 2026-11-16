"""Centro de ayuda: preguntas frecuentes y consultas con seguimiento."""
from . import auditoria, db, notificaciones
from .tiempo import ahora

CATEGORIAS = {"cuenta": "Mi cuenta y verificación", "depositos": "Depósitos y retiros", "operaciones": "Compras, ventas y órdenes",
              "envios": "Envíos entre clientes", "seguridad": "Seguridad", "otro": "Otro tema"}
ESTADOS = {"abierta": ("warn", "Esperando respuesta"), "respondida": ("ok", "Respondida"), "cerrada": ("", "Cerrada")}
MAX_ABIERTAS = 5

FAQ = [
    ("cuenta", "¿Cómo verifico mi identidad?", "Sube en Perfil › Documentos tu documento de identidad (frente y dorso) y un comprobante de domicilio. El equipo de Cumplimiento los revisa y te avisa. Hasta entonces puedes ver precios, pero no operar."),
    ("cuenta", "¿Qué son los niveles de verificación?", "Nivel 0: cuenta abierta. Nivel 1: identidad verificada, ya puedes depositar, operar, enviar y retirar dentro de los límites. Nivel 2: además activaste la verificación en dos pasos y tienes aprobado un documento de origen de los fondos."),
    ("depositos", "¿Cómo deposito?", "En Billetera › Depositar eliges el método, el monto y envías la solicitud con la referencia de tu transferencia. El equipo confirma que el dinero llegó y lo acredita. Los montos altos necesitan dos aprobaciones."),
    ("depositos", "¿Cuánto tarda un retiro?", "El equipo lo revisa y lo paga a la cuenta registrada a tu nombre. En el detalle del movimiento ves cada paso: solicitado, aprobado y pagado."),
    ("depositos", "¿Puedo operar en guaraníes?", "Puedes depositar y retirar en guaraníes al tipo de cambio que publica la casa para cada caso. Tus saldos se llevan en dólares; la vista en guaraníes de la billetera es solo de referencia."),
    ("operaciones", "¿Qué diferencia hay entre mercado, límite, stop y OCO?", "Mercado: se ejecuta ahora al precio disponible. Límite: se ejecuta sola cuando el precio llega al nivel que elijas. Stop: vende si el precio cae hasta un nivel, para cortar una pérdida. OCO: dos órdenes enlazadas; cuando una se ejecuta, la otra se cancela."),
    ("operaciones", "¿Qué es el saldo reservado?", "Es el dinero o las monedas comprometidos en órdenes abiertas. No se pueden usar para otra cosa hasta que la orden se ejecute o la canceles."),
    ("operaciones", "¿Qué comisiones pago?", "Antes de confirmar cada operación ves el detalle: la comisión de la operación y el importe final. No hay cargos ocultos."),
    ("envios", "¿Cómo envío dinero a otro cliente?", "En Billetera › Enviar escribes su correo o cédula, el monto y confirmas con tu contraseña. Es inmediato, sin costo y no se puede deshacer, así que revisa bien el destinatario."),
    ("seguridad", "¿Cómo protejo mi cuenta?", "Activa la verificación en dos pasos, usa una contraseña que no uses en otro lado y revisa tus sesiones en el Centro de seguridad. Nunca te vamos a pedir tu contraseña ni tus códigos."),
    ("seguridad", "Olvidé mi contraseña", "En la pantalla de ingreso toca «¿Olvidaste tu contraseña?». Te enviamos un enlace de un solo uso que vence en 30 minutos. Si tienes verificación en dos pasos, también te pedimos el código."),
    ("seguridad", "¿Mis criptomonedas están aseguradas?", "No. Las criptomonedas no tienen garantía de depósitos y su precio puede bajar con fuerza. Invierte solo lo que puedas permitirte perder."),
]


class ErrorSoporte(Exception):
    pass


def _texto(t, minimo, maximo, que):
    t = " ".join((t or "").split()) if maximo <= 120 else (t or "").strip()
    if len(t) < minimo:
        raise ErrorSoporte(f"Escribe {que} (al menos {minimo} caracteres).")
    return t[:maximo]


def crear(usuario, cliente, categoria, asunto, texto):
    if categoria not in CATEGORIAS:
        raise ErrorSoporte("Elige un tema.")
    asunto = _texto(asunto, 5, 120, "un asunto")
    texto = _texto(texto, 10, 2000, "tu consulta")
    if db.uno("SELECT COUNT(*) AS n FROM consultas WHERE usuario_id = ? AND estado != 'cerrada'", (usuario["id"],))["n"] >= MAX_ABIERTAS:
        raise ErrorSoporte(f"Ya tienes {MAX_ABIERTAS} consultas en curso. Responde o cierra alguna antes de abrir otra.")
    ts = ahora()
    with db.transaccion() as c:
        cid = c.execute("INSERT INTO consultas (usuario_id, cliente_id, categoria, asunto, creada, actualizada) VALUES (?, ?, ?, ?, ?, ?)",
                        (usuario["id"], cliente["id"] if cliente else None, categoria, asunto, ts, ts)).lastrowid
        c.execute("INSERT INTO consulta_mensajes (consulta_id, autor_id, del_equipo, texto, ts) VALUES (?, ?, 0, ?, ?)",
                  (cid, usuario["id"], texto, ts))
    notificaciones.notificar_rol(("operador", "cumplimiento", "admin"), f"Nueva consulta de {usuario['nombre']}: {asunto}",
                                 f"/equipo/soporte/{cid}", ts=ts)
    return cid


def responder(cid, autor, texto, del_equipo):
    texto = _texto(texto, 2, 2000, "tu mensaje")
    q = db.uno("SELECT * FROM consultas WHERE id = ?", (cid,))
    if not q or (not del_equipo and q["usuario_id"] != autor["id"]):
        raise ErrorSoporte("No encontramos esa consulta.")
    if q["estado"] == "cerrada":
        raise ErrorSoporte("La consulta está cerrada. Abre una nueva si necesitas algo más.")
    ts = ahora()
    with db.transaccion() as c:
        c.execute("INSERT INTO consulta_mensajes (consulta_id, autor_id, del_equipo, texto, ts) VALUES (?, ?, ?, ?, ?)",
                  (cid, autor["id"], 1 if del_equipo else 0, texto, ts))
        c.execute("UPDATE consultas SET estado = ?, actualizada = ? WHERE id = ?", ("respondida" if del_equipo else "abierta", ts, cid))
    if del_equipo:
        notificaciones.notificar(q["usuario_id"], f"Respondimos tu consulta «{q['asunto']}».", f"/cliente/ayuda/{cid}", ts=ts, categoria="cuenta")
        auditoria.registrar("soporte.respuesta", f"consulta:{cid}", {"texto": f"Respondió la consulta #{cid}."}, usuario=autor, ts=ts)
    else:
        notificaciones.notificar_rol(("operador", "cumplimiento", "admin"), f"{autor['nombre']} respondió en la consulta #{cid}.",
                                     f"/equipo/soporte/{cid}", ts=ts)


def cerrar(cid, autor, del_equipo):
    q = db.uno("SELECT * FROM consultas WHERE id = ?", (cid,))
    if not q or (not del_equipo and q["usuario_id"] != autor["id"]):
        raise ErrorSoporte("No encontramos esa consulta.")
    db.ejecutar("UPDATE consultas SET estado = 'cerrada', actualizada = ? WHERE id = ?", (ahora(), cid))


def del_usuario(usuario_id):
    return db.todos("SELECT * FROM consultas WHERE usuario_id = ? ORDER BY actualizada DESC LIMIT 50", (usuario_id,))


def mensajes(cid):
    return db.todos("SELECT m.*, u.nombre FROM consulta_mensajes m JOIN usuarios u ON u.id = m.autor_id WHERE m.consulta_id = ? ORDER BY m.id", (cid,))


def cola(estado=None):
    sql = ("SELECT q.*, u.nombre, u.email, (SELECT COUNT(*) FROM consulta_mensajes m WHERE m.consulta_id = q.id) AS n"
           " FROM consultas q JOIN usuarios u ON u.id = q.usuario_id")
    args = ()
    if estado in ESTADOS:
        sql += " WHERE q.estado = ?"
        args = (estado,)
    return db.todos(sql + " ORDER BY CASE q.estado WHEN 'abierta' THEN 0 WHEN 'respondida' THEN 1 ELSE 2 END, q.actualizada DESC LIMIT 200", args)
