"""Compra automática (ahorro programado): el cliente elige una moneda, un monto y cada cuánto; el sistema compra solo."""
import calendar
from datetime import timedelta

import click
from flask.cli import with_appcontext

from . import auditoria, db, notificaciones, operaciones
from .dinero import fmt_usd
from .tiempo import ahora, ahora_dt, iso, leer

FRECUENCIAS = {"semanal": "Cada semana", "quincenal": "Cada 15 días", "mensual": "Cada mes"}
MAX_POR_CLIENTE = 10


def _siguiente(dt, frecuencia):
    if frecuencia == "semanal":
        return dt + timedelta(days=7)
    if frecuencia == "quincenal":
        return dt + timedelta(days=15)
    anio, mes = (dt.year + 1, 1) if dt.month == 12 else (dt.year, dt.month + 1)
    return dt.replace(year=anio, month=mes, day=min(dt.day, calendar.monthrange(anio, mes)[1]))


def crear(cliente, activo, monto_cent, frecuencia, usuario, ts=None):
    if frecuencia not in FRECUENCIAS:
        raise operaciones.ErrorNegocio("Elige cada cuánto quieres comprar.")
    if not db.uno("SELECT 1 FROM activos WHERE codigo = ?", (activo,)):
        raise operaciones.ErrorNegocio("Esa moneda no está disponible.")
    if monto_cent < 1000:
        raise operaciones.ErrorNegocio("El mínimo de una compra automática es de US$ 10.")
    if monto_cent > operaciones._umbral("ORDEN_MAXIMA_USD"):
        raise operaciones.ErrorNegocio("El monto supera el máximo por orden.")
    if db.uno("SELECT COUNT(*) AS n FROM planes WHERE cliente_id = ? AND estado = 'activo'", (cliente["id"],))["n"] >= MAX_POR_CLIENTE:
        raise operaciones.ErrorNegocio(f"Puedes tener hasta {MAX_POR_CLIENTE} compras automáticas activas.")
    ts = ts or ahora()
    proxima = iso(_siguiente(leer(ts), frecuencia))
    with db.transaccion() as c:
        pid = c.execute("INSERT INTO planes (cliente_id, activo, monto_cent, frecuencia, proxima, creado) VALUES (?, ?, ?, ?, ?, ?)",
                        (cliente["id"], activo, monto_cent, frecuencia, proxima, ts)).lastrowid
        auditoria.registrar("plan.creado", f"plan:{pid}",
                            {"texto": f"{cliente['nombre']} programó una compra automática de {fmt_usd(monto_cent)} en {activo}, "
                                      f"{FRECUENCIAS[frecuencia].lower()}."}, usuario=usuario, ts=ts)
    return pid


def cancelar(pid, cliente, usuario):
    with db.transaccion() as c:
        n = c.execute("UPDATE planes SET estado = 'cancelado' WHERE id = ? AND cliente_id = ? AND estado = 'activo'",
                      (pid, cliente["id"])).rowcount
        if n:
            auditoria.registrar("plan.cancelado", f"plan:{pid}", {"texto": f"{cliente['nombre']} canceló la compra automática #{pid}."},
                                usuario=usuario)
    return bool(n)


def del_cliente(cliente_id, activo=None):
    sql, args = "SELECT * FROM planes WHERE cliente_id = ? AND estado = 'activo'", [cliente_id]
    if activo:
        sql += " AND activo = ?"
        args.append(activo)
    return db.todos(sql + " ORDER BY proxima", args)


def ejecutar_pendientes(ts=None, precios_usar=None):
    """Ejecuta las compras cuya fecha llegó. Si una no se puede hacer (sin saldo, precio viejo, pausa), se avisa al cliente
    y se reprograma para la fecha siguiente: nunca se acumulan compras atrasadas. Devuelve (hechas, fallidas)."""
    ts = ts or ahora()
    hechas = fallidas = 0
    for p in db.todos("SELECT * FROM planes WHERE estado = 'activo' AND proxima <= ? ORDER BY proxima, id", (ts,)):
        cli = db.uno("SELECT * FROM clientes WHERE id = ?", (p["cliente_id"],))
        proxima = leer(p["proxima"])
        while iso(proxima) <= ts:
            proxima = _siguiente(proxima, p["frecuencia"])
        try:
            _, r = operaciones.operar(cli, p["activo"], "compra", p["monto_cent"], None, ts=ts, precios_usar=precios_usar)
            nota = "Compra realizada." if r == "liquidada" else "La orden quedó en proceso."
            hechas += 1
            if cli["usuario_id"]:
                notificaciones.notificar(cli["usuario_id"], f"Compra automática: se compraron {fmt_usd(p['monto_cent'])} de {p['activo']}.",
                                         f"/mercado/{p['activo']}", ts=ts)
        except operaciones.ErrorNegocio as e:
            nota = str(e)
            fallidas += 1
            if cli["usuario_id"]:
                notificaciones.notificar(cli["usuario_id"], f"No se pudo hacer tu compra automática de {p['activo']}: {nota} "
                                         "Se vuelve a intentar en la próxima fecha.", f"/mercado/{p['activo']}", ts=ts)
        db.ejecutar("UPDATE planes SET proxima = ?, ultima_ts = ?, ultima_nota = ?, ejecuciones = ejecuciones + ? WHERE id = ?",
                    (iso(proxima), ts, nota[:200], 1 if nota.startswith(("Compra", "La orden")) else 0, p["id"]))
    return hechas, fallidas


@click.command("ejecutar-planes")
@with_appcontext
def cmd_ejecutar():
    """Ejecuta las compras automáticas cuya fecha llegó (pensado para correr cada pocos minutos)."""
    h, f = ejecutar_pendientes()
    click.echo(f"Compras automáticas: {h} hechas, {f} sin poder ejecutarse.")
