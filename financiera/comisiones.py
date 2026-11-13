"""Comisión de gestión: un porcentaje anual que se cobra una vez por mes sobre el valor de cada cartera."""
import re
from decimal import ROUND_HALF_UP, Decimal

import click
from flask import current_app

from . import auditoria, cartera, db, notificaciones, precios
from .dinero import fmt_usd
from .formato import MESES, zona
from .tiempo import ahora, ahora_dt, leer


class ErrorComision(Exception):
    pass


def tasa():
    return Decimal(str(current_app.config["COMISION_ANUAL_PCT"]))


def periodo_anterior():
    hoy = ahora_dt().astimezone(zona())
    a, m = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    return f"{a:04d}-{m:02d}"


def nombre_periodo(periodo):
    a, m = periodo.split("-")
    return f"{MESES[int(m) - 1]} {a}"


def calcular(valor_cent, fraccion=1):
    """Comisión de un mes sobre un valor; fraccion < 1 cuando el cliente invirtió solo parte del mes."""
    return int((Decimal(valor_cent) * tasa() / 100 / 12 * Decimal(fraccion)).to_integral_value(ROUND_HALF_UP))


def base(cliente, periodo):
    """(valor_al_cierre_cent, fraccion_del_mes, dias). La base es el valor de la cartera al cierre del mes, con los
    precios de ese momento; si el cliente invirtió por primera vez durante el mes, se cobra en proporción a los días."""
    ini, fin, _ = cartera.limites_periodo(periodo)
    valor, _ = cartera.valor_en(cliente["id"], fin)
    if valor <= 0:
        return 0, Decimal(0), 0
    primero = db.uno("SELECT MIN(ts) AS ts FROM libro WHERE cliente_id = ?", (cliente["id"],))["ts"]
    t_ini, t_fin = leer(ini), leer(fin)
    desde = max(t_ini, leer(primero)) if primero else t_ini
    fraccion = Decimal((t_fin - desde).total_seconds()) / Decimal((t_fin - t_ini).total_seconds())
    return valor, min(Decimal(1), max(Decimal(0), fraccion)), round((t_fin - desde).total_seconds() / 86400)


def cobrar(periodo, usuario=None, ts=None, precios_usar=None):
    """Cobra la comisión del período a cada cliente con saldo. Es idempotente: no cobra dos veces el mismo mes."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", periodo or ""):
        raise ErrorComision("El período tiene que tener el formato AAAA-MM.")
    if tasa() <= 0:
        raise ErrorComision("La comisión de gestión está desactivada (COMISION_ANUAL_PCT = 0).")
    if cartera.limites_periodo(periodo)[2]:
        raise ErrorComision(f"Solo se cobran meses cerrados: {nombre_periodo(periodo)} todavía no terminó.")
    ts = ts or ahora()
    pr = precios_usar
    if pr is None:
        try:
            precios.exigir_frescura([a["codigo"] for a in precios.activos()])
        except precios.ErrorPrecio as e:
            raise ErrorComision(str(e)) from None
        pr = precios.vigentes()
    cobradas, total, ya = 0, 0, 0
    for cli in db.todos("SELECT * FROM clientes ORDER BY id"):
        if db.uno("SELECT 1 FROM operaciones WHERE cliente_id = ? AND tipo = 'comision' AND periodo = ?", (cli["id"], periodo)):
            ya += 1
            continue
        valor, fraccion, dias = base(cli, periodo)
        _, actual = cartera.posiciones(cli["id"], pr)
        monto = min(calcular(valor, fraccion), actual)
        if monto <= 0:
            continue
        with db.transaccion() as c:
            cur = c.execute(
                "INSERT INTO operaciones (cliente_id, tipo, monto_cent, periodo, estado, creado, creado_por, resuelto_ts, resuelto_por)"
                " VALUES (?, 'comision', ?, ?, 'liquidada', ?, ?, ?, ?)",
                (cli["id"], monto, periodo, ts, usuario["id"] if usuario else None, ts, usuario["id"] if usuario else None))
            opid = cur.lastrowid
            op = c.execute("SELECT * FROM operaciones WHERE id = ?", (opid,)).fetchone()
            cobrado = cartera.ejecutar_retiro(c, op, pr, ts, concepto="comision")
            c.execute("UPDATE operaciones SET liquidado_cent = ? WHERE id = ?", (cobrado, opid))
            detalle = f"{tasa()} % anual sobre {fmt_usd(valor)}, el valor de tu cartera al cierre del mes"
            if fraccion < 1:
                detalle += f", en proporción a {dias} {'día' if dias == 1 else 'días'} invertidos"
            texto = f"Comisión de gestión de {nombre_periodo(periodo)}: {fmt_usd(cobrado)} ({detalle})."
            auditoria.registrar("comision.cobrada", f"operacion:{opid}", {"texto": f"{cli['nombre']}: {texto}", "monto_cent": cobrado},
                                usuario=usuario, ts=ts)
            if cli["usuario_id"]:
                notificaciones.notificar(cli["usuario_id"], texto, "/cliente/movimientos", ts=ts)
        cobradas += 1
        total += cobrado
    auditoria.registrar("comision.periodo", f"periodo:{periodo}",
                        {"texto": f"Cobró la comisión de {nombre_periodo(periodo)} a {cobradas} clientes por {fmt_usd(total)}.",
                         "clientes": cobradas, "total_cent": total}, usuario=usuario, ts=ts)
    return {"cobradas": cobradas, "total": total, "ya_cobradas": ya}


def resumen_periodos(limite=12):
    return db.todos("SELECT periodo, COUNT(*) AS clientes, SUM(liquidado_cent) AS total, MAX(resuelto_ts) AS ts FROM operaciones"
                    " WHERE tipo = 'comision' GROUP BY periodo ORDER BY periodo DESC LIMIT ?", (limite,))


@click.command("cobrar-comisiones")
@click.option("--periodo", default=None, help="Mes a cobrar, AAAA-MM. Por defecto, el mes anterior.")
def cmd_cobrar(periodo):
    """Cobra la comisión de gestión del mes (pensado para ejecutarse el día 1 de cada mes)."""
    periodo = periodo or periodo_anterior()
    try:
        r = cobrar(periodo)
    except ErrorComision as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"{nombre_periodo(periodo)}: {r['cobradas']} comisiones por {fmt_usd(r['total'])}; {r['ya_cobradas']} ya estaban cobradas.")
