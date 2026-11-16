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


def _seg(ts):
    from .tiempo import leer
    try:
        return leer(ts).timestamp()
    except (TypeError, ValueError):
        from datetime import datetime
        return datetime.fromisoformat(ts).timestamp()


def _tiempos(serie):
    """Posición horizontal de cada punto (0 a 1) según su hora real, no según su orden: así un tramo con muchos
    puntos (las últimas horas, que se guardan cada minuto) no se estira sobre días con pocos puntos."""
    t = [_seg(ts) for ts, _ in serie]
    span = (t[-1] - t[0]) or 1
    return [(x - t[0]) / span for x in t]


def _etiquetas_tiempo(serie, izq, w):
    from datetime import datetime, timezone

    from .tiempo import iso
    t0, t1 = _seg(serie[0][0]), _seg(serie[-1][0])
    return [{"x": izq + w * f, "texto": f_fecha(iso(datetime.fromtimestamp(t0 + (t1 - t0) * f, timezone.utc)), False), "ancla": a}
            for f, a in ((0, "start"), (0.5, "middle"), (1, "end"))]


def linea(serie, ancho=640, alto=200, fmt=None, rango_min=100):
    """serie: [(ts_iso, valor_cent)]. Eje vertical que no arranca en cero para que se vea el movimiento."""
    if len(serie) < 2:
        return None
    izq, der, arr, aba = 56, 8, 10, 26
    vals = [v for _, v in serie]
    mn, mx = min(vals), max(vals)
    paso = _paso_bonito(max(mx - mn, mx * 0.01, rango_min) * 1.2, 4)
    lo, hi = max(0, math.floor(mn / paso) * paso), math.ceil(mx / paso) * paso
    if mn - lo < paso * 0.15 and lo > 0:
        lo = max(0, lo - paso)
    if hi - mx < paso * 0.15:
        hi += paso
    w, h = ancho - izq - der, alto - arr - aba
    tiempos = _tiempos(serie)

    def xy(i, v):
        return izq + tiempos[i] * w, arr + (1 - (v - lo) / (hi - lo)) * h

    pts = [xy(i, v) for i, v in enumerate(vals)]
    puntos = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    marcas = []
    v = lo
    while v <= hi + paso / 1000:
        marcas.append({"y": arr + (1 - (v - lo) / (hi - lo)) * h, "texto": fmt(v) if fmt else _corto(v, paso, hi)})
        v += paso
    etiquetas = _etiquetas_tiempo(serie, izq, w)
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


def chispa(valores, ancho=120, alto=34):
    """Minigráfico de línea sin ejes. Devuelve None si no hay al menos dos valores."""
    if len(valores) < 2:
        return None
    if len(valores) > 60:
        paso = len(valores) / 60
        valores = [valores[int(i * paso)] for i in range(60)] + [valores[-1]]
    mn, mx = min(valores), max(valores)
    rango = (mx - mn) or 1
    n = len(valores)
    pts = [(2 + i * (ancho - 4) / (n - 1), 3 + (1 - (v - mn) / rango) * (alto - 6)) for i, v in enumerate(valores)]
    linea_ = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return {"ancho": ancho, "alto": alto, "puntos": linea_, "area": f"2,{alto} {linea_} {ancho - 2},{alto}",
            "sube": valores[-1] >= valores[0], "fin": pts[-1]}


def velas(serie, ancho=760, alto=300, n=42, fmt=None):
    """Gráfico de velas. serie: [(ts_iso, valor)] ordenada. Agrupa en n tramos iguales de tiempo y calcula apertura,
    máximo, mínimo y cierre de cada uno. Devuelve None si no hay datos suficientes."""
    from .tiempo import leer
    if len(serie) < 4:
        return None
    t0, t1 = leer(serie[0][0]).timestamp(), leer(serie[-1][0]).timestamp()
    if t1 <= t0:
        return None
    n = max(4, min(n, len(serie) // 2))
    grupos = [[] for _ in range(n)]
    for ts, v in serie:
        k = min(n - 1, int((leer(ts).timestamp() - t0) / (t1 - t0) * n))
        grupos[k].append(v)
    ohlc, previo = [], None
    for g_ in grupos:
        if not g_:
            ohlc.append(None)
            continue
        ap = previo if previo is not None else g_[0]
        ohlc.append((ap, max(g_ + [ap]), min(g_ + [ap]), g_[-1]))
        previo = g_[-1]
    vals = [x for o in ohlc if o for x in (o[1], o[2])]
    mn, mx = min(vals), max(vals)
    paso = _paso_bonito(max(mx - mn, mx * 0.004) * 1.2, 4)
    lo, hi = max(0, math.floor(mn / paso) * paso), math.ceil(mx / paso) * paso
    izq, der, arr, aba = 56, 8, 10, 26
    w, h = ancho - izq - der, alto - arr - aba
    y = lambda v: arr + (1 - (v - lo) / (hi - lo)) * h  # noqa: E731
    paso_x = w / n
    cuerpo = max(2.0, paso_x * 0.62)
    out = []
    for i, o in enumerate(ohlc):
        if not o:
            continue
        ap, ma, mi, ci = o
        cx = izq + paso_x * (i + 0.5)
        ya, yc = y(ap), y(ci)
        out.append({"x": cx - cuerpo / 2, "w": cuerpo, "cx": cx, "y": min(ya, yc), "h": max(1.2, abs(ya - yc)), "y1": y(ma), "y2": y(mi),
                    "sube": ci >= ap})
    marcas, v = [], lo
    while v <= hi + paso / 1000:
        marcas.append({"y": y(v), "texto": fmt(v) if fmt else _corto(v, paso, hi)})
        v += paso
    etiquetas = [{"x": izq + w * f, "texto": f_fecha(serie[int(f * (len(serie) - 1))][0], False), "ancla": a}
                 for f, a in ((0, "start"), (0.5, "middle"), (1, "end"))]
    return {"ancho": ancho, "alto": alto, "velas": out, "marcas": marcas, "etiquetas": etiquetas, "izq": izq, "der": ancho - der}


def mapa(items, ancho=100.0, alto=60.0):
    """Mapa de calor (treemap «squarified»): items = [(peso, dato)] -> [(x, y, w, h, dato)] en las mismas unidades que
    ancho y alto. Los rectángulos quedan lo más cuadrados posible y ordenados de mayor a menor."""
    items = [(float(p), d) for p, d in items if p and p > 0]
    items.sort(key=lambda t: -t[0])
    total = sum(p for p, _ in items)
    if not total:
        return []
    escala = ancho * alto / total
    pendientes = [(p * escala, d) for p, d in items]
    out = []
    x, y, w, h = 0.0, 0.0, float(ancho), float(alto)

    def peor(fila, lado):
        s = sum(a for a, _ in fila)
        return max(max(lado * lado * a / (s * s), (s * s) / (lado * lado * a)) for a, _ in fila)

    while pendientes:
        lado = min(w, h)
        fila = [pendientes.pop(0)]
        while pendientes and peor(fila + [pendientes[0]], lado) <= peor(fila, lado):
            fila.append(pendientes.pop(0))
        s = sum(a for a, _ in fila)
        if w >= h:  # columna a la izquierda
            ancho_col = s / h
            yy = y
            for a, d in fila:
                alto_r = a / ancho_col
                out.append((x, yy, ancho_col, alto_r, d))
                yy += alto_r
            x, w = x + ancho_col, w - ancho_col
        else:  # fila arriba
            alto_fila = s / w
            xx = x
            for a, d in fila:
                ancho_r = a / alto_fila
                out.append((xx, y, ancho_r, alto_fila, d))
                xx += ancho_r
            y, h = y + alto_fila, h - alto_fila
    return out


def comparacion(series, ancho=760, alto=300):
    """series: [(codigo, color, [(ts_iso, precio)])] -> líneas normalizadas a 100 al inicio del período, para comparar
    el rendimiento de varias monedas con distinto precio en una misma escala."""
    norm = []
    for codigo, color, s in series:
        if len(s) >= 2 and s[0][1]:
            base = s[0][1]
            norm.append((codigo, color, [(t, v / base * 100) for t, v in s]))
    if not norm:
        return None
    izq, der, arr, aba = 48, 64, 10, 26
    todos = [v for _, _, s in norm for _, v in s]
    mn, mx = min(todos), max(todos)
    paso = _paso_bonito(max(mx - mn, 2) * 1.2, 4)
    lo, hi = math.floor(mn / paso) * paso, math.ceil(mx / paso) * paso
    if hi - lo < paso:  # serie plana: deja aire arriba y abajo
        lo, hi = lo - paso, hi + paso
    w, h = ancho - izq - der, alto - arr - aba
    y = lambda v: arr + (1 - (v - lo) / (hi - lo)) * h  # noqa: E731
    lineas = []
    for codigo, color, s in norm:
        tt = _tiempos(s)
        pts = [(izq + tt[i] * w, y(v)) for i, (_, v) in enumerate(s)]
        lineas.append({"codigo": codigo, "color": color, "puntos": " ".join(f"{a:.1f},{b:.1f}" for a, b in pts),
                       "fin": pts[-1], "var": s[-1][1] - 100})
    # Etiquetas finales separadas para que no se pisen.
    for ln in lineas:
        ln["etiqueta_y"] = ln["fin"][1]
    ordenadas = sorted(lineas, key=lambda x: x["fin"][1])
    for a, b in zip(ordenadas, ordenadas[1:]):
        if b["etiqueta_y"] - a["etiqueta_y"] < 14:
            b["etiqueta_y"] = a["etiqueta_y"] + 14
    marcas, v = [], lo
    while v <= hi + paso / 1000:
        marcas.append({"y": y(v), "texto": f"{v - 100:+.0f} %".replace("+0 %", "0 %"), "base": abs(v - 100) < 1e-9})
        v += paso
    etiquetas = _etiquetas_tiempo(norm[0][2], izq, w)
    return {"ancho": ancho, "alto": alto, "lineas": lineas, "marcas": marcas, "etiquetas": etiquetas, "izq": izq,
            "der": ancho - der, "y100": y(100)}
