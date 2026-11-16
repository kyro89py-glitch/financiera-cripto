"""Análisis descriptivo de un activo y de la exposición del cliente.

Son estadísticas calculadas con las velas diarias disponibles (rendimientos, volatilidad, rango, RSI y tendencia
respecto de sus medias). Describen lo que pasó; no son recomendaciones de compra o venta.
"""
import math
from decimal import Decimal

from . import cartera, velas
from .dinero import valor_cent


def _rsi(cierres, n=14):
    if len(cierres) <= n:
        return None
    g = p = 0.0
    for i in range(1, n + 1):
        d = cierres[i] - cierres[i - 1]
        g += max(d, 0)
        p += max(-d, 0)
    g, p = g / n, p / n
    for i in range(n + 1, len(cierres)):
        d = cierres[i] - cierres[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        p = (p * (n - 1) + max(-d, 0)) / n
    return 100.0 if p == 0 else 100 - 100 / (1 + g / p)


def _media(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def activo(codigo, precio_actual=None):
    """Estadísticas del activo con las velas diarias. Devuelve dict (vacío si no hay historia suficiente)."""
    filas, _ = velas.velas(codigo, "1d")
    cierres = [float(f[4]) for f in filas if f[4]]
    if len(cierres) < 8:
        return {}
    actual = float(precio_actual) if precio_actual else cierres[-1]
    out = {"dias": len(cierres), "rend": {}}
    for etiqueta, dias in (("7 días", 7), ("30 días", 30), ("90 días", 90), ("1 año", 365)):
        if len(cierres) > dias:
            out["rend"][etiqueta] = (actual / cierres[-1 - dias] - 1) * 100
    rets = [math.log(cierres[i] / cierres[i - 1]) for i in range(max(1, len(cierres) - 30), len(cierres)) if cierres[i - 1] > 0]
    if len(rets) >= 5:
        m = sum(rets) / len(rets)
        out["volatilidad"] = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(365) * 100
    altos = [float(f[2]) for f in filas]
    bajos = [float(f[3]) for f in filas]
    out["maximo"], out["minimo"] = max(altos), min(bajos)
    out["desde_maximo"] = (actual / out["maximo"] - 1) * 100
    out["rsi"] = _rsi(cierres)
    m20, m50 = _media(cierres, 20), _media(cierres, 50)
    out["media20"], out["media50"] = m20, m50
    if m20 and m50:
        if actual > m20 > m50:
            out["tendencia"] = ("alcista", "El precio está sobre sus medias de 20 y 50 días, y la de 20 sobre la de 50.")
        elif actual < m20 < m50:
            out["tendencia"] = ("bajista", "El precio está bajo sus medias de 20 y 50 días, y la de 20 bajo la de 50.")
        else:
            out["tendencia"] = ("lateral", "El precio y sus medias de 20 y 50 días no muestran una dirección clara.")
    if out.get("rsi") is not None:
        r = out["rsi"]
        out["rsi_texto"] = ("zona de sobrecompra (70 o más)" if r >= 70 else "zona de sobreventa (30 o menos)" if r <= 30
                            else "zona neutral")
    return out


def exposicion(cliente_id, codigo, vig):
    """Posición del cliente en el activo: unidades, valor, peso en la cartera, costo promedio y resultado."""
    filas, total = cartera.posiciones(cliente_id, vig)
    fila = next((f for f in filas if f["activo"] == codigo), None)
    k = cartera.costos(cliente_id).get(codigo)
    out = {"total": total, "unidades": fila["unidades"] if fila else 0, "valor": fila["valor"] if fila else 0,
           "peso": (fila["peso"] * 100) if fila else 0.0, "costo": None, "resultado": None, "promedio": None}
    if k and k["cantidad"] > 0 and codigo in vig:
        out["costo"] = k["costo"]
        out["resultado"] = valor_cent(codigo, k["cantidad"], vig[codigo]["precio"]) - k["costo"]
        out["promedio"] = (Decimal(k["costo"]) / 100) / (Decimal(k["cantidad"]) / Decimal(10 ** 8)) if k["cantidad"] else None
    return out
