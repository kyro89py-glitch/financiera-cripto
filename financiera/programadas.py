"""Órdenes programadas por precio. Quedan abiertas hasta que el precio llega al nivel elegido; entonces se ejecutan a
precio de mercado con el mismo motor que una orden común. No reservan saldo: si al dispararse no alcanza, la orden
falla y se avisa al cliente."""
from decimal import Decimal

from . import auditoria, cartera, db, notificaciones, operaciones
from .dinero import fmt_precio, fmt_usd, valor_cent
from .tiempo import ahora

MAX_ABIERTAS = 20
ESTADOS = {"abierta": ("info", "Abierta"), "ejecutada": ("ok", "Ejecutada"), "cancelada": ("", "Cancelada"), "fallida": ("bad", "No se ejecutó")}


def nombre(o):
    """Cómo se llama la orden para el cliente."""
    if o["lado"] == "compra":
        return "Compra límite" if o["condicion"] == "menor" else "Compra si sube"
    return "Venta límite" if o["condicion"] == "mayor" else "Stop (venta si baja)"


def crear(cliente, activo, lado, precio, monto_cent, usuario, todo=False, ts=None):
    if lado not in ("compra", "venta"):
        raise operaciones.ErrorNegocio("Elige comprar o vender.")
    if not db.uno("SELECT 1 FROM activos WHERE codigo = ?", (activo,)):
        raise operaciones.ErrorNegocio("Esa moneda no está disponible.")
    if cliente["kyc_estado"] != "verificado":
        raise operaciones.ErrorNegocio("Para operar primero tenemos que verificar tu identidad. Revisa tu perfil.")
    from . import precios
    vig = precios.vigentes().get(activo)
    if not vig:
        raise operaciones.ErrorNegocio(f"No hay precio de {activo} en este momento.")
    if precio <= 0 or precio == vig["precio"]:
        raise operaciones.ErrorNegocio("Elige un precio distinto del actual.")
    ten = cartera.tenencias(cliente["id"])
    if lado == "venta":
        tengo = ten.get(activo, 0)
        if tengo <= 0:
            raise operaciones.ErrorNegocio(f"No tienes {activo} para vender.")
        valor = valor_cent(activo, tengo, vig["precio"])
        if todo:
            monto_cent = 0
        elif monto_cent > valor:
            raise operaciones.ErrorNegocio(f"Tienes {fmt_usd(valor)} en {activo}; no puedes programar una venta mayor.")
    else:
        todo = False
        if monto_cent > ten.get("USD", 0):
            raise operaciones.ErrorNegocio("No tienes saldo en dólares suficiente para esa compra.")
    if not todo and monto_cent < 1000:
        raise operaciones.ErrorNegocio("El mínimo de una orden programada es de US$ 10.")
    if monto_cent > operaciones._umbral("ORDEN_MAXIMA_USD"):
        raise operaciones.ErrorNegocio("El monto supera el máximo por orden.")
    if db.uno("SELECT COUNT(*) AS n FROM programadas WHERE cliente_id = ? AND estado = 'abierta'", (cliente["id"],))["n"] >= MAX_ABIERTAS:
        raise operaciones.ErrorNegocio(f"Puedes tener hasta {MAX_ABIERTAS} órdenes programadas abiertas.")
    condicion = "menor" if precio < vig["precio"] else "mayor"
    ts = ts or ahora()
    with db.transaccion() as c:
        oid = c.execute("INSERT INTO programadas (cliente_id, activo, lado, condicion, precio, monto_cent, todo, creado)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (cliente["id"], activo, lado, condicion, str(precio), monto_cent,
                                                            1 if todo else 0, ts)).lastrowid
        o = {"lado": lado, "condicion": condicion}
        auditoria.registrar("programada.creada", f"programada:{oid}",
                            {"texto": f"{cliente['nombre']} programó una orden: {nombre(o).lower()} de {activo} a {fmt_precio(precio)}"
                                      + (" por todo lo que tiene." if todo else f" por {fmt_usd(monto_cent)}.")}, usuario=usuario, ts=ts)
    return oid


def cancelar(oid, cliente, usuario):
    with db.transaccion() as c:
        n = c.execute("UPDATE programadas SET estado = 'cancelada', resuelta_ts = ? WHERE id = ? AND cliente_id = ? AND estado = 'abierta'",
                      (ahora(), oid, cliente["id"])).rowcount
        if n:
            auditoria.registrar("programada.cancelada", f"programada:{oid}",
                                {"texto": f"{cliente['nombre']} canceló la orden programada #{oid}."}, usuario=usuario)
    return bool(n)


def del_cliente(cliente_id, activo=None, solo_abiertas=True, limite=30):
    sql, args = "SELECT * FROM programadas WHERE cliente_id = ?", [cliente_id]
    if solo_abiertas:
        sql += " AND estado = 'abierta'"
    if activo:
        sql += " AND activo = ?"
        args.append(activo)
    return db.todos(sql + " ORDER BY id DESC LIMIT ?", (*args, limite))


def revisar(vigentes, ts=None, precios_usar=None):
    """Ejecuta las órdenes cuyo precio se alcanzó. Devuelve (ejecutadas, fallidas)."""
    ts = ts or ahora()
    hechas = fallidas = 0
    for o in db.todos("SELECT * FROM programadas WHERE estado = 'abierta' ORDER BY id"):
        p = vigentes.get(o["activo"])
        if not p:
            continue
        objetivo, actual = Decimal(o["precio"]), Decimal(p["precio"])
        if not ((o["condicion"] == "menor" and actual <= objetivo) or (o["condicion"] == "mayor" and actual >= objetivo)):
            continue
        cli = db.uno("SELECT * FROM clientes WHERE id = ?", (o["cliente_id"],))
        try:
            opid, _ = operaciones.operar(cli, o["activo"], o["lado"], o["monto_cent"], None, todo=bool(o["todo"]), ts=ts,
                                         precios_usar=precios_usar)
            db.ejecutar("UPDATE programadas SET estado = 'ejecutada', resuelta_ts = ?, operacion_id = ? WHERE id = ?", (ts, opid, o["id"]))
            texto = f"Se ejecutó tu orden programada: {nombre(o).lower()} de {o['activo']} con el precio en {fmt_precio(actual)}."
            hechas += 1
        except operaciones.ErrorNegocio as e:
            db.ejecutar("UPDATE programadas SET estado = 'fallida', resuelta_ts = ?, nota = ? WHERE id = ?", (ts, str(e)[:200], o["id"]))
            texto = f"Tu orden programada de {o['activo']} llegó a su precio pero no se pudo ejecutar: {e}"
            fallidas += 1
        if cli["usuario_id"]:
            notificaciones.notificar(cli["usuario_id"], texto, f"/mercado/{o['activo']}", ts=ts)
    return hechas, fallidas
