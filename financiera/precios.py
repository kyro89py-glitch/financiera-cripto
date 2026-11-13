"""Precios de los activos: carga manual o desde CoinGecko, historial y control de antigüedad."""
from decimal import Decimal

import click
import requests
from flask import current_app

from . import auditoria, db
from .dinero import fmt_precio
from .tiempo import ahora, minutos_desde


class ErrorPrecio(Exception):
    pass


def activos():
    return db.todos("SELECT * FROM activos ORDER BY orden")


def vigentes():
    out = {}
    for r in db.todos("SELECT * FROM precios"):
        out[r["activo"]] = {
            "precio": Decimal(r["precio"]),
            "cambio": Decimal(r["cambio_24h"]) if r["cambio_24h"] is not None else None,
            "fuente": r["fuente"],
            "ts": r["ts"],
        }
    return out


def registrar(activo, precio, cambio=None, fuente="manual", ts=None):
    ts = ts or ahora()
    with db.transaccion() as c:
        c.execute(
            "INSERT INTO precios (activo, precio, cambio_24h, fuente, ts) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(activo) DO UPDATE SET precio = excluded.precio, cambio_24h = excluded.cambio_24h,"
            " fuente = excluded.fuente, ts = excluded.ts",
            (activo, str(precio), str(cambio) if cambio is not None else None, fuente, ts),
        )
        c.execute("INSERT INTO precios_historial (activo, precio, ts) VALUES (?, ?, ?)", (activo, str(precio), ts))


def actualizar_manual(activo, precio, usuario):
    if not db.uno("SELECT 1 FROM activos WHERE codigo = ?", (activo,)):
        raise ErrorPrecio("El activo no existe.")
    with db.transaccion():
        anterior = vigentes().get(activo)
        cambio = None
        if anterior and anterior["precio"] > 0:
            cambio = ((precio / anterior["precio"] - 1) * 100).quantize(Decimal("0.01"))
        registrar(activo, precio, cambio, "manual")
        auditoria.registrar("precio.manual", f"activo:{activo}",
                            {"texto": f"Cargó a mano el precio de {activo}: {fmt_precio(precio)}.", "precio": str(precio)},
                            usuario=usuario)


def actualizar_coingecko(usuario=None):
    filas = [a for a in activos() if a["coingecko_id"]]
    ids = ",".join(a["coingecko_id"] for a in filas)
    cabeceras = {"accept": "application/json"}
    clave = current_app.config.get("COINGECKO_API_KEY")
    if clave:
        cabeceras["x-cg-demo-api-key"] = clave
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
                         headers=cabeceras, timeout=10)
        r.raise_for_status()
        datos = r.json()
    except (requests.RequestException, ValueError) as e:
        raise ErrorPrecio(f"No se pudo consultar CoinGecko: {e.__class__.__name__}.") from None
    n, ts = 0, ahora()
    with db.transaccion():
        for a in filas:
            d = datos.get(a["coingecko_id"]) or {}
            if not d.get("usd"):
                continue
            cambio = d.get("usd_24h_change")
            registrar(a["codigo"], Decimal(str(d["usd"])),
                      Decimal(str(round(cambio, 4))) if cambio is not None else None, "CoinGecko", ts)
            n += 1
        if not n:
            raise ErrorPrecio("CoinGecko no devolvió precios.")
        auditoria.registrar("precio.coingecko", "precios",
                            {"texto": f"Actualizó {n} precios desde CoinGecko.", "activos": n}, usuario=usuario, ts=ts)
    return n


def actualizar_binance(usuario=None):
    """Último precio y variación de 24 h de cada activo contra USDT (el USDT vale 1)."""
    from . import exchange
    cli = exchange.cliente_binance()
    try:
        datos = cli.precios([a["codigo"] for a in activos()])
    except exchange.ErrorExchange as e:
        raise ErrorPrecio(f"No se pudo consultar Binance: {e}") from None
    if not datos:
        raise ErrorPrecio("Binance no devolvió precios.")
    ts = ahora()
    with db.transaccion():
        for a, (precio, cambio) in datos.items():
            registrar(a, precio, cambio.quantize(Decimal("0.0001")), "Binance", ts)
        auditoria.registrar("precio.binance", "precios", {"texto": f"Actualizó {len(datos)} precios desde Binance.",
                                                           "activos": len(datos)}, usuario=usuario, ts=ts)
    return len(datos)


def fuente():
    return "Binance" if current_app.config.get("FUENTE_PRECIOS") == "binance" else "CoinGecko"


def actualizar(usuario=None):
    """Actualiza desde la fuente configurada (FUENTE_PRECIOS)."""
    return actualizar_binance(usuario) if fuente() == "Binance" else actualizar_coingecko(usuario)


def antiguos(codigos=None):
    """Lista de (activo, minutos o None) cuyo precio falta o supera la antigüedad permitida."""
    maximo = current_app.config["PRECIO_MAX_MINUTOS"]
    vig = vigentes()
    out = []
    for a in codigos if codigos is not None else [x["codigo"] for x in activos()]:
        p = vig.get(a)
        if not p:
            out.append((a, None))
        elif maximo > 0 and minutos_desde(p["ts"]) > maximo:
            out.append((a, int(minutos_desde(p["ts"]))))
    return out


def exigir_frescura(codigos):
    viejos = antiguos(codigos)
    if viejos:
        a, m = viejos[0]
        if m is None:
            raise ErrorPrecio(f"No hay precio cargado para {a}. Actualiza los precios antes de aprobar.")
        raise ErrorPrecio(f"El precio de {a} tiene {m} minutos de antigüedad. Actualiza los precios antes de aprobar.")


def historial(codigos, desde):
    """Precios desde una fecha, incluido el último anterior a ella, por activo."""
    out = {}
    for a in codigos:
        previo = db.uno("SELECT precio, ts FROM precios_historial WHERE activo = ? AND ts < ? ORDER BY ts DESC LIMIT 1",
                        (a, desde))
        filas = db.todos("SELECT precio, ts FROM precios_historial WHERE activo = ? AND ts >= ? ORDER BY ts, id",
                         (a, desde))
        serie = ([(previo["ts"], Decimal(previo["precio"]))] if previo else []) + [(f["ts"], Decimal(f["precio"])) for f in filas]
        out[a] = serie
    return out


@click.command("actualizar-precios")
def cmd_actualizar():
    """Trae los precios de la fuente configurada (Binance o CoinGecko); pensado para ejecutarse cada pocos minutos."""
    try:
        n = actualizar()
    except ErrorPrecio as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"{n} precios actualizados.")
