"""Geometría de gráficos SVG dibujados en el servidor (sin bibliotecas de terceros)."""
import math

from . import dinero
from .formato import f_fecha


def _escala_bonita(maximo, marcas=4):
    if maximo <= 0:
        return 1, [0]
    paso = 10 ** math.floor(math.log10(maximo / marcas))
    for m in (1, 2, 2.5, 5, 10):
        if maximo / (paso * m) <= marcas:
            paso *= m
            break
    tope = math.ceil(maximo / paso) * paso
    return tope, [paso * i for i in range(int(tope / paso) + 1)]


def _paso_bonito(rango, marcas=4):
    paso = 10 ** math.floor(math.log10(rango / marcas))
    for m in (1, 2, 2.5, 5, 10):
        if rango / (paso * m) <= marcas:
            return paso * m
    return paso * 10


def _corto(cent, paso_cent=None, ref_cent=None):
    """Monto abreviado para un eje. Con paso_cent usa los decimales justos para que dos marcas no se lean igual;
    ref_cent fija la unidad (mil, M) para todo el eje."""
    if cent == 0:
        return "0"
    usd = cent / 100
    ref = abs(ref_cent if ref_cent is not None else cent) / 100
    div, suf = (1_000_000, " M") if ref >= 1_000_000 else ((1_000, " mil") if ref >= 1_000 else (1, ""))
    if paso_cent:
        p = paso_cent / 100 / div
        dec = next((d for d in range(3) if abs(round(p * 10 ** d) - p * 10 ** d) < 1e-6), 2)
    else:
        dec = 1 if div == 1_000_000 else 0
    texto = dinero.fmt_num(usd / div, dec)
    if not paso_cent and texto.endswith(",0"):
        texto = texto[:-2]
    return texto + suf


def linea(serie, ancho=640, alto=200):
    """serie: [(ts_iso, valor_cent)]. Eje vertical que no arranca en cero para que se vea el movimiento."""
    if len(serie) < 2:
        return None
    izq, der, arr, aba = 56, 8, 10, 26
    vals = [v for _, v in serie]
    mn, mx = min(vals), max(vals)
    paso = _paso_bonito(max(mx - mn, mx * 0.01, 100) * 1.2, 4)
    lo, hi = max(0, math.floor(mn / paso) * paso), math.ceil(mx / paso) * paso
    if mn - lo < paso * 0.15 and lo > 0:
        lo = max(0, lo - paso)
    if hi - mx < paso * 0.15:
        hi += paso
    w, h = ancho - izq - der, alto - arr - aba

    def xy(i, v):
        return izq + i / (len(vals) - 1) * w, arr + (1 - (v - lo) / (hi - lo)) * h

    pts = [xy(i, v) for i, v in enumerate(vals)]
    puntos = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    marcas = []
    v = lo
    while v <= hi + paso / 1000:
        marcas.append({"y": arr + (1 - (v - lo) / (hi - lo)) * h, "texto": _corto(v, paso, hi)})
        v += paso
    etiquetas = [{"x": izq + w * f, "texto": f_fecha(serie[int(f * (len(serie) - 1))][0], False), "ancla": a}
                 for f, a in ((0, "start"), (0.5, "middle"), (1, "end"))]
    return {"ancho": ancho, "alto": alto, "puntos": puntos, "area": f"{izq},{arr + h} {puntos} {izq + w},{arr + h}",
            "marcas": marcas, "etiquetas": etiquetas, "izq": izq, "der": ancho - der, "fin": pts[-1],
            "sube": vals[-1] >= vals[0], "inicio_valor": vals[0], "fin_valor": vals[-1]}


def barras(dias, ancho=640, alto=200):
    """dias: [(fecha_iso, aportes_cent, retiros_cent)]. Aportes hacia arriba, retiros hacia abajo."""
    if not dias:
        return None
    izq, der, arr, aba = 56, 8, 10, 26
    w, h = ancho - izq - der, alto - arr - aba
    tope, _ = _escala_bonita(max(max(a, r) for _, a, r in dias) or 1, 2)
    cero = arr + h / 2
    paso = w / len(dias)
    ancho_barra = max(2, paso * 0.6)
    out = []
    for i, (f, a, r) in enumerate(dias):
        x = izq + i * paso + (paso - ancho_barra) / 2
        ha, hr = a / tope * h / 2, r / tope * h / 2
        out.append({"x": x, "w": ancho_barra, "ya": cero - ha, "ha": ha, "yr": cero, "hr": hr, "fecha": f,
                    "titulo": f"{f_fecha(f, False)}: aportes {dinero.fmt_usd(a, 0)}, retiros {dinero.fmt_usd(r, 0)}"})
    marcas = [{"y": arr, "texto": "+" + _corto(tope)}, {"y": cero, "texto": "0"}, {"y": arr + h, "texto": "−" + _corto(tope)}]
    etiquetas = [{"x": x, "texto": f_fecha(dias[i][0], False), "ancla": a}
                 for i, x, a in ((0, izq, "start"), (len(dias) // 2, izq + paso * (len(dias) // 2 + 0.5), "middle"),
                                 (len(dias) - 1, izq + w, "end"))]
    return {"ancho": ancho, "alto": alto, "barras": out, "marcas": marcas, "etiquetas": etiquetas, "izq": izq,
            "der": ancho - der, "cero": cero}
