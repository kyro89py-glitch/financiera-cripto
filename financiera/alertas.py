"""Alertas de precio: el usuario pide que le avisen cuando una moneda sube o baja hasta un precio."""
from decimal import Decimal

from . import db, notificaciones, operaciones
from .dinero import fmt_precio
from .tiempo import ahora

MAX_POR_USUARIO = 20


def crear(usuario, activo, precio, vigente):
    if not db.uno("SELECT 1 FROM activos WHERE codigo = ?", (activo,)):
        raise operaciones.ErrorNegocio("Esa moneda no está disponible.")
    if precio <= 0:
        raise operaciones.ErrorNegocio("Escribe un precio mayor que cero.")
    if vigente is None or precio == vigente:
        raise operaciones.ErrorNegocio("Elige un precio distinto del actual.")
    if db.uno("SELECT COUNT(*) AS n FROM alertas_precio WHERE usuario_id = ? AND disparada_ts IS NULL", (usuario["id"],))["n"] >= MAX_POR_USUARIO:
        raise operaciones.ErrorNegocio(f"Puedes tener hasta {MAX_POR_USUARIO} alertas activas.")
    sentido = "sube" if precio > vigente else "baja"
    return db.ejecutar("INSERT INTO alertas_precio (usuario_id, activo, sentido, precio, creado) VALUES (?, ?, ?, ?, ?)",
                       (usuario["id"], activo, sentido, str(precio), ahora())).lastrowid, sentido


def crear_variacion(usuario, activo, umbral, sentido):
    """Alerta cuando la variación de 24 horas llega a +umbral % (sube) o −umbral % (baja)."""
    if not db.uno("SELECT 1 FROM activos WHERE codigo = ?", (activo,)):
        raise operaciones.ErrorNegocio("Esa moneda no está disponible.")
    if sentido not in ("sube", "baja"):
        raise operaciones.ErrorNegocio("Elige si te avisamos cuando suba o cuando baje.")
    if not 0.5 <= umbral <= 90:
        raise operaciones.ErrorNegocio("Elige una variación entre 0,5 % y 90 %.")
    if db.uno("SELECT COUNT(*) AS n FROM alertas_precio WHERE usuario_id = ? AND disparada_ts IS NULL", (usuario["id"],))["n"] >= MAX_POR_USUARIO:
        raise operaciones.ErrorNegocio(f"Puedes tener hasta {MAX_POR_USUARIO} alertas activas.")
    return db.ejecutar("INSERT INTO alertas_precio (usuario_id, activo, sentido, precio, creado, tipo, umbral) VALUES (?, ?, ?, '0', ?, 'variacion', ?)",
                       (usuario["id"], activo, sentido, ahora(), float(umbral))).lastrowid


def borrar(aid, usuario):
    db.ejecutar("DELETE FROM alertas_precio WHERE id = ? AND usuario_id = ? AND disparada_ts IS NULL", (aid, usuario["id"]))


def del_usuario(usuario_id, activo=None):
    sql, args = "SELECT * FROM alertas_precio WHERE usuario_id = ? AND disparada_ts IS NULL", [usuario_id]
    if activo:
        sql += " AND activo = ?"
        args.append(activo)
    return db.todos(sql + " ORDER BY activo, id", args)


def revisar(vigentes, ts=None):
    """Dispara las alertas alcanzadas con los precios dados. Cada alerta avisa una sola vez. Devuelve cuántas disparó."""
    ts = ts or ahora()
    n = 0
    for a in db.todos("SELECT * FROM alertas_precio WHERE disparada_ts IS NULL"):
        p = vigentes.get(a["activo"])
        if not p:
            continue
        if a["tipo"] == "variacion":
            cambio = float(p.get("cambio") or 0)
            if (a["sentido"] == "sube" and cambio >= a["umbral"]) or (a["sentido"] == "baja" and cambio <= -a["umbral"]):
                db.ejecutar("UPDATE alertas_precio SET disparada_ts = ? WHERE id = ?", (ts, a["id"]))
                pct = f"{abs(cambio):.1f}".replace(".", ",")
                umb = f"{a['umbral']:g}".replace(".", ",")
                notificaciones.notificar(a["usuario_id"], f"{a['activo']} {'sube' if cambio >= 0 else 'baja'} {pct} % en 24 horas"
                                         f" (tu alerta de variación: {umb} %).", f"/mercado/{a['activo']}", ts=ts, categoria="precios")
                n += 1
            continue
        objetivo, actual = Decimal(a["precio"]), Decimal(p["precio"])
        if (a["sentido"] == "sube" and actual >= objetivo) or (a["sentido"] == "baja" and actual <= objetivo):
            db.ejecutar("UPDATE alertas_precio SET disparada_ts = ? WHERE id = ?", (ts, a["id"]))
            notificaciones.notificar(a["usuario_id"], f"{a['activo']} {'subió' if a['sentido'] == 'sube' else 'bajó'} a "
                                     f"{fmt_precio(actual)} (tu alerta de precio: {fmt_precio(objetivo)}).", f"/mercado/{a['activo']}", ts=ts,
                                     categoria="precios")
            n += 1
    return n
