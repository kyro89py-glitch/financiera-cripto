"""Datos para la pantalla de trading: velas, libro de órdenes y últimas operaciones del mercado.

Con FUENTE_PRECIOS=binance salen de la API pública de Binance (con una caché corta por proceso). Con otra fuente las velas
se arman con el historial de precios propio, y el libro y las operaciones del mercado se simulan alrededor del precio
vigente: la respuesta lo dice (simulado=True) y la pantalla lo muestra.
"""
import random
import time
from datetime import timedelta
from decimal import Decimal

from flask import current_app

from . import db, precios
from .tiempo import ahora_dt, iso, leer

# código: (segundos, etiqueta, velas a mostrar)
INTERVALOS = {"1m": (60, "1m", 120), "15m": (900, "15m", 120), "1h": (3600, "1h", 120), "4h": (14400, "4h", 120),
              "1d": (86400, "1D", 120), "1w": (604800, "1S", 60)}
_CACHE = {}
LUNES = 4 * 86400  # el 1/1/1970 fue jueves: las velas semanales empiezan el lunes, como en los exchanges


def _cache(clave, segundos, fn):
    ahora = time.monotonic()
    v = _CACHE.get(clave)
    if v and v[0] > ahora:
        return v[1]
    datos = fn()
    _CACHE[clave] = (ahora + segundos, datos)
    if len(_CACHE) > 500:
        for k in [k for k, (vence, _) in _CACHE.items() if vence < ahora]:
            _CACHE.pop(k, None)
    return datos


def _binance():
    if precios.fuente() != "Binance":
        return None
    from . import exchange
    return exchange.cliente_binance()


def _inicio(seg, intervalo, t):
    if intervalo == "1w":
        return (t - LUNES) // seg * seg + LUNES
    return t // seg * seg


def velas(activo, intervalo="15m"):
    """Lista de [ms, apertura, máximo, mínimo, cierre, volumen] (floats) y si el volumen es real."""
    seg, _, n = INTERVALOS[intervalo]
    cli = _binance()
    if cli is not None and cli.opera(activo):
        from .exchange import ErrorExchange
        try:
            filas = _cache(("v", activo, intervalo), 5, lambda: cli.velas(activo, intervalo, n))
            return [[t, float(o), float(h), float(lo), float(c), v] for t, o, h, lo, c, v in filas], True
        except ErrorExchange:
            current_app.logger.warning("No se pudieron traer las velas de %s desde Binance", activo)
    return _de_historial(activo, intervalo), False


def _de_historial(activo, intervalo):
    seg, _, n = INTERVALOS[intervalo]
    fin = int(ahora_dt().timestamp())
    desde_t = _inicio(seg, intervalo, fin) - seg * (n - 1)
    desde = iso(ahora_dt() - timedelta(seconds=fin - desde_t))
    previo = db.uno("SELECT precio FROM precios_historial WHERE activo = ? AND ts < ? ORDER BY ts DESC LIMIT 1",
                    (activo, desde))
    puntos = [(int(leer(f["ts"]).timestamp()), float(f["precio"])) for f in db.todos(
        "SELECT precio, ts FROM precios_historial WHERE activo = ? AND ts >= ? ORDER BY ts, id", (activo, desde))]
    vig = precios.vigentes().get(activo)
    if vig:
        puntos.append((fin, float(vig["precio"])))
    if not puntos:
        return []
    cubos = {}
    for t, p in puntos:
        cubos.setdefault(_inicio(seg, intervalo, t), []).append(p)
    out = []
    cierre = float(previo["precio"]) if previo else None
    k = min(cubos)
    while k <= _inicio(seg, intervalo, fin):
        ps = cubos.get(k)
        if ps:
            apertura = cierre if cierre is not None else ps[0]
            out.append([k * 1000, apertura, max(apertura, *ps), min(apertura, *ps), ps[-1], 0])
            cierre = ps[-1]
        elif cierre is not None:  # sin datos en ese tramo: vela plana con el último precio
            out.append([k * 1000, cierre, cierre, cierre, cierre, 0])
        k += seg
    return out[-n:]


def libro(activo, niveles=14):
    """(compras, ventas, simulado): listas de (precio, cantidad) de mejor a peor."""
    cli = _binance()
    if cli is not None and cli.opera(activo):
        from .exchange import ErrorExchange
        try:
            b, a = _cache(("l", activo), 2, lambda: cli.libro(activo, 20))
            return b[:niveles], a[:niveles], False
        except ErrorExchange:
            current_app.logger.warning("No se pudo traer el libro de %s desde Binance", activo)
    vig = precios.vigentes().get(activo)
    if not vig:
        return [], [], True
    p = vig["precio"]
    azar = random.Random(f"{activo}-{int(time.time() // 3)}")
    paso = p * Decimal("0.0002")
    base = Decimal(2500) / p  # cantidades del orden de unos miles de dólares por nivel
    compras, ventas = [], []
    for i in range(niveles):
        dc = paso * (Decimal(i + 1) + Decimal(str(round(azar.random() * 0.4, 4))))  # siempre ordenado: el salto < 1 paso
        dv = paso * (Decimal(i + 1) + Decimal(str(round(azar.random() * 0.4, 4))))
        compras.append((precios.redondear(p - dc), precios.redondear(base * Decimal(str(0.2 + azar.random() * (1 + i / 3))), 5)))
        ventas.append((precios.redondear(p + dv), precios.redondear(base * Decimal(str(0.2 + azar.random() * (1 + i / 3))), 5)))
    return compras, ventas, True


def operaciones_mercado(activo, n=24):
    """(lista de (ms, precio, cantidad, es_compra), simulado)."""
    cli = _binance()
    if cli is not None and cli.opera(activo):
        from .exchange import ErrorExchange
        try:
            return _cache(("t", activo), 2, lambda: cli.operaciones_mercado(activo, n)), False
        except ErrorExchange:
            current_app.logger.warning("No se pudieron traer las operaciones de %s desde Binance", activo)
    vig = precios.vigentes().get(activo)
    if not vig:
        return [], True
    p = vig["precio"]
    ahora_ms = int(time.time() * 1000)
    azar = random.Random(f"{activo}-t-{ahora_ms // 3000}")
    out, t = [], ahora_ms
    for _ in range(n):
        t -= int(azar.random() * 2500) + 150
        out.append((t, precios.redondear(p * Decimal(str(1 + azar.gauss(0, 0.00025)))),
                    precios.redondear(Decimal(400 * azar.random() + 20) / p, 5), azar.random() < 0.5))
    return out, True
