"""Simulador de inversiones con precios históricos: «¿qué habría pasado si…?». Usa el historial de precios guardado por la
plataforma (con su fuente) y el precio vigente. Es un cálculo sobre el pasado: no predice ni promete resultados futuros."""
from bisect import bisect_right
from datetime import timedelta

from . import db, precios
from .tiempo import ahora_dt, iso, leer

FRECUENCIAS = {"semanal": ("Cada semana", 7), "quincenal": ("Cada 15 días", 15), "mensual": ("Cada mes", 30)}
PLAZOS = {3: "3 meses", 6: "6 meses", 12: "1 año"}


class ErrorSimulacion(Exception):
    pass


def dca(activo, monto_cent, frecuencia="mensual", meses=12, comision_pct=0.0):
    """Compras periódicas de `monto_cent` desde hace `meses` hasta hoy, cada una al último precio registrado antes de esa fecha.
    Compara con invertir todo junto el primer día."""
    if not db.uno("SELECT 1 FROM activos WHERE codigo = ?", (activo,)):
        raise ErrorSimulacion("Moneda desconocida.")
    if frecuencia not in FRECUENCIAS or meses not in PLAZOS:
        raise ErrorSimulacion("Elige una frecuencia y un plazo de la lista.")
    if not 100 <= monto_cent <= 100_000_00:
        raise ErrorSimulacion("El monto por compra tiene que estar entre US$ 1 y US$ 100.000.")
    vig = precios.vigentes().get(activo)
    if not vig:
        raise ErrorSimulacion(f"No hay precio vigente de {activo}.")
    fin = ahora_dt()
    ini = fin - timedelta(days=meses * 30)
    hist = precios.historial([activo], iso(ini - timedelta(days=3)))[activo]
    if not hist or leer(hist[0][0]) > ini + timedelta(days=FRECUENCIAS[frecuencia][1]):
        primero = leer(hist[0][0]).date().isoformat() if hist else None
        raise ErrorSimulacion(f"No hay historial de {activo} suficiente para ese plazo" + (f" (empieza el {primero})." if primero else "."))
    tiempos = [leer(t) for t, _ in hist]
    c = max(0.0, min(5.0, float(comision_pct))) / 100
    paso = timedelta(days=FRECUENCIAS[frecuencia][1])
    unidades = invertido = 0.0
    compras, serie, fecha = 0, [], ini
    while fecha <= fin:
        i = bisect_right(tiempos, fecha) - 1
        if i >= 0:
            p = float(hist[i][1])
            unidades += monto_cent / 100 * (1 - c) / p
            invertido += monto_cent / 100
            compras += 1
            serie.append((iso(fecha), round(invertido, 2), round(unidades * p, 2)))
        fecha += paso
    actual = float(vig["precio"])
    valor = unidades * actual
    serie.append((iso(fin), round(invertido, 2), round(valor, 2)))
    p0 = float(hist[max(0, bisect_right(tiempos, ini) - 1)][1])
    unico = invertido * (1 - c) / p0 * actual
    return {"activo": activo, "compras": compras, "invertido": round(invertido * 100), "valor": round(valor * 100),
            "resultado": round((valor - invertido) * 100), "pct": (valor / invertido - 1) * 100 if invertido else 0,
            "unidades": unidades, "precio_medio": invertido * (1 - c) / unidades if unidades else None, "precio_actual": actual,
            "precio_inicial": p0, "unico_valor": round(unico * 100), "unico_pct": (unico / invertido - 1) * 100 if invertido else 0,
            "desde": iso(ini), "serie": serie, "fuente": vig["fuente"], "ts": vig["ts"]}
