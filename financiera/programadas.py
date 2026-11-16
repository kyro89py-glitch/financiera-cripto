"""Órdenes programadas por precio (límite y stop). Quedan abiertas hasta que el precio llega al nivel elegido; entonces se
ejecutan a precio de mercado con el mismo motor que una orden común. Las órdenes por un monto fijo reservan ese saldo
(dólares para comprar, monedas para vender) mientras están abiertas; «vender todo» no reserva y vende lo que haya. Si al
dispararse no alcanza, la orden falla y se avisa al cliente."""
from decimal import Decimal

from . import auditoria, cartera, db, notificaciones, operaciones
from .dinero import fmt_precio, fmt_unidades, fmt_usd, unidades_por, valor_cent
from .tiempo import ahora

MAX_ABIERTAS = 20
ESTADOS = {"abierta": ("info", "Abierta"), "ejecutada": ("ok", "Ejecutada"), "cancelada": ("", "Cancelada"), "fallida": ("bad", "No se ejecutó")}


ORIGENES = {"tp": "Toma de ganancia", "sl": "Corte de pérdida"}


def nombre(o):
    """Cómo se llama la orden para el cliente."""
    keys = o.keys() if hasattr(o, "keys") else o
    origen = o["origen"] if "origen" in keys else None
    if origen in ORIGENES:
        return ORIGENES[origen]
    if o["lado"] == "compra":
        return "Compra límite" if o["condicion"] == "menor" else "Compra si sube"
    return "Venta límite" if o["condicion"] == "mayor" else "Stop (venta si baja)"


def _base(cliente, activo, lado):
    """Controles comunes del servidor: lado, moneda habilitada, identidad, revisión de cumplimiento, mercado activo y precio."""
    from . import antilavado, ejecucion, precios
    if lado not in ("compra", "venta"):
        raise operaciones.ErrorNegocio("Elige comprar o vender.")
    a = db.uno("SELECT * FROM activos WHERE codigo = ?", (activo,))
    if not a or (lado == "compra" and not a["habilitado"]):
        raise operaciones.ErrorNegocio("Esa moneda no está disponible.")
    if cliente["kyc_estado"] != "verificado":
        raise operaciones.ErrorNegocio("Para operar primero tenemos que verificar tu identidad. Revisa tu perfil.")
    if antilavado.bloqueado(cliente["id"]):
        raise operaciones.ErrorNegocio("Tu cuenta está en revisión de cumplimiento. Escríbenos desde Ayuda si necesitas más información.")
    if ejecucion.pausada():
        raise operaciones.ErrorNegocio("Las operaciones están en pausa por un control de seguridad. Vuelve a intentar más tarde.")
    vig = precios.vigentes().get(activo)
    if not vig:
        raise operaciones.ErrorNegocio(f"No hay precio de {activo} en este momento.")
    return vig


def _saldo(cliente, activo, lado, monto_cent, todo, precio_unidades, cantidad=None, vig=None, legs=1):
    """Verifica que alcance lo disponible y los topes. Devuelve (monto_cent, todo)."""
    ten = cartera.disponible(cliente["id"])
    if lado == "venta":
        tengo = ten.get(activo, 0)
        if tengo <= 0:
            raise operaciones.ErrorNegocio(f"No tienes {activo} disponible para vender.")
        if cantidad is not None:
            if cantidad <= 0 or cantidad > tengo:
                raise operaciones.ErrorNegocio(f"No tienes esa cantidad de {activo} disponible.")
            monto_cent, todo = 0, False
        elif todo:
            monto_cent = 0
        else:
            valor = valor_cent(activo, tengo, vig["precio"])
            if monto_cent > valor:
                raise operaciones.ErrorNegocio(f"Tienes {fmt_usd(valor)} disponibles en {activo}; no puedes programar una venta mayor.")
            if unidades_por(monto_cent, precio_unidades) > tengo:
                raise operaciones.ErrorNegocio(f"A {fmt_precio(precio_unidades)}, {fmt_usd(monto_cent)} son más {activo} "
                                               "de los que tienes disponibles.")
    else:
        todo = False
        if monto_cent > ten.get("USD", 0):
            raise operaciones.ErrorNegocio("No tienes saldo en dólares disponible suficiente para esa compra "
                                           "(lo reservado en otras órdenes no cuenta).")
    if cantidad is None and not todo:
        if monto_cent < 1000:
            raise operaciones.ErrorNegocio("El mínimo de una orden programada es de US$ 10.")
        if monto_cent > operaciones._umbral("ORDEN_MAXIMA_USD"):
            raise operaciones.ErrorNegocio("El monto supera el máximo por orden.")
    if db.uno("SELECT COUNT(*) AS n FROM programadas WHERE cliente_id = ? AND estado = 'abierta'", (cliente["id"],))["n"] + legs > MAX_ABIERTAS:
        raise operaciones.ErrorNegocio(f"Puedes tener hasta {MAX_ABIERTAS} órdenes programadas abiertas.")
    return monto_cent, todo


def _describir(cliente, o, activo, monto_cent, todo, cantidad):
    if cantidad:
        cuanto = f" por {fmt_unidades(cantidad, activo)}"
    else:
        cuanto = " por todo lo que tiene" if todo else f" por {fmt_usd(monto_cent)}"
    return f"{nombre(o).lower()} de {activo} a {fmt_precio(Decimal(o['precio']))}{cuanto}"


def crear(cliente, activo, lado, precio, monto_cent, usuario, todo=False, ts=None, cantidad=None, origen=None):
    vig = _base(cliente, activo, lado)
    if precio <= 0 or precio == vig["precio"]:
        raise operaciones.ErrorNegocio("Elige un precio distinto del actual.")
    if lado == "compra":
        todo = False
    monto_cent, todo = _saldo(cliente, activo, lado, monto_cent, todo, precio, cantidad, vig)
    condicion = "menor" if precio < vig["precio"] else "mayor"
    ts = ts or ahora()
    with db.transaccion() as c:
        oid = c.execute("INSERT INTO programadas (cliente_id, activo, lado, condicion, precio, monto_cent, todo, creado, cantidad, origen)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (cliente["id"], activo, lado, condicion, str(precio), monto_cent,
                                                                  1 if todo else 0, ts, cantidad, origen)).lastrowid
        o = {"lado": lado, "condicion": condicion, "precio": str(precio), "origen": origen}
        auditoria.registrar("programada.creada", f"programada:{oid}",
                            {"texto": f"{cliente['nombre']} programó una orden: " + _describir(cliente, o, activo, monto_cent, todo, cantidad) + "."},
                            usuario=usuario, ts=ts)
    return oid


def crear_oco(cliente, activo, lado, precio_limite, precio_stop, monto_cent, usuario, todo=False, cantidad=None, proteccion=False, ts=None):
    """Dos órdenes enlazadas: la primera que se ejecuta cancela la otra.

    Venta: límite por encima del precio actual (toma de ganancia) y stop por debajo (corte de pérdida).
    Compra: límite por debajo del precio actual y stop por encima (entrar si baja o si rompe hacia arriba).
    Reserva una sola vez el saldo de la pata más exigente. Devuelve (id_limite, id_stop)."""
    import secrets
    vig = _base(cliente, activo, lado)
    actual = vig["precio"]
    if lado == "venta" and not (precio_limite > actual > precio_stop > 0):
        raise operaciones.ErrorNegocio(f"En una OCO de venta, la toma de ganancia va por encima de {fmt_precio(actual)} "
                                       "y el corte de pérdida por debajo.")
    if lado == "compra" and not (0 < precio_limite < actual < precio_stop):
        raise operaciones.ErrorNegocio(f"En una OCO de compra, el precio límite va por debajo de {fmt_precio(actual)} y el stop por encima.")
    if lado == "compra":
        todo = False
    menor = min(precio_limite, precio_stop)  # a menor precio, más unidades: es la pata que más reserva en una venta
    monto_cent, todo = _saldo(cliente, activo, lado, monto_cent, todo, menor, cantidad, vig, legs=2)
    grupo = secrets.token_hex(6)
    ts = ts or ahora()
    origenes = ("tp", "sl") if (lado == "venta" and proteccion) else ("oco", "oco")
    ids = []
    with db.transaccion() as c:
        for precio, origen in ((precio_limite, origenes[0]), (precio_stop, origenes[1])):
            condicion = "menor" if precio < actual else "mayor"
            ids.append(c.execute(
                "INSERT INTO programadas (cliente_id, activo, lado, condicion, precio, monto_cent, todo, creado, cantidad, origen, grupo)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (cliente["id"], activo, lado, condicion, str(precio), monto_cent,
                                                             1 if todo else 0, ts, cantidad, origen, grupo)).lastrowid)
        cuanto = (f"{fmt_unidades(cantidad, activo)}" if cantidad else ("todo lo que tiene" if todo else fmt_usd(monto_cent)))
        auditoria.registrar("programada.oco", f"programada:{ids[0]}",
                            {"texto": f"{cliente['nombre']} programó una OCO de {lado} de {activo} por {cuanto}: límite "
                                      f"{fmt_precio(precio_limite)} y stop {fmt_precio(precio_stop)} (#{ids[0]} y #{ids[1]})."},
                            usuario=usuario, ts=ts)
    return tuple(ids)


def cancelar(oid, cliente, usuario):
    """Cancela una orden; si es parte de una OCO, cancela el grupo entero."""
    with db.transaccion() as c:
        o = c.execute("SELECT grupo FROM programadas WHERE id = ? AND cliente_id = ?", (oid, cliente["id"])).fetchone()
        if o and o["grupo"]:
            n = c.execute("UPDATE programadas SET estado = 'cancelada', resuelta_ts = ? WHERE grupo = ? AND cliente_id = ? AND estado = 'abierta'",
                          (ahora(), o["grupo"], cliente["id"])).rowcount
        else:
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
        if db.uno("SELECT estado FROM programadas WHERE id = ?", (o["id"],))["estado"] != "abierta":
            continue  # la canceló otra pata de su OCO en esta misma vuelta
        cli = db.uno("SELECT * FROM clientes WHERE id = ?", (o["cliente_id"],))
        if o["grupo"]:
            db.ejecutar("UPDATE programadas SET estado = 'cancelada', resuelta_ts = ?, nota = ? WHERE grupo = ? AND id != ? AND estado = 'abierta'",
                        (ts, f"OCO: se activó la orden #{o['id']}", o["grupo"], o["id"]))
        try:
            monto, todo = o["monto_cent"], bool(o["todo"])
            if o["cantidad"]:
                ten = cartera.tenencias(cli["id"])
                libre = cartera.disponible(cli["id"], excepto_programada=o["id"], ten=ten).get(o["activo"], 0)
                unidades = min(o["cantidad"], libre)
                if unidades <= 0:
                    raise operaciones.ErrorNegocio(f"ya no tienes {o['activo']} disponible para vender")
                todo = unidades >= ten.get(o["activo"], 0)
                monto = 0 if todo else max(1, valor_cent(o["activo"], unidades, actual))
            opid, _ = operaciones.operar(cli, o["activo"], o["lado"], monto, None, todo=todo, ts=ts,
                                         precios_usar=precios_usar, excepto_programada=o["id"])
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
