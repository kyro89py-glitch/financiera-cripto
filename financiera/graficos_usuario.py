"""Configuración del gráfico de trading guardada en la cuenta: indicadores, parámetros, plantillas, dibujos y anotaciones."""
import json
import math

from . import db, preferencias
from .tiempo import ahora

IND = {"ma": True, "ema": False, "boll": False, "vwap": False, "vol": True, "rsi": False, "macd": False, "estoc": False, "sr": False}
PAR = {"ma1": (7, 2, 200), "ma2": (25, 2, 300), "ema": (20, 2, 200), "bb": (20, 5, 100), "bbk": (2, 1, 4), "rsi": (14, 2, 50),
       "mf": (12, 2, 50), "ms": (26, 3, 100), "mg": (9, 2, 50), "ek": (14, 3, 50), "ed": (3, 2, 20)}
MAX_PLANTILLAS, MAX_DIBUJOS, MAX_NOTAS = 6, 30, 50


class ErrorGrafico(Exception):
    pass


def _ind(d):
    d = d if isinstance(d, dict) else {}
    return {k: bool(d[k]) if isinstance(d.get(k), bool) else v for k, v in IND.items()}


def _par(d):
    d = d if isinstance(d, dict) else {}
    out = {}
    for k, (defecto, mn, mx) in PAR.items():
        x = d.get(k)
        out[k] = min(mx, max(mn, x)) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else defecto
        if k != "bbk":
            out[k] = int(out[k])
    if out["ms"] <= out["mf"]:
        out["ms"] = out["mf"] + 1
    return out


def limpiar(g):
    """Deja una configuración válida a partir de lo guardado (o de nada)."""
    g = g if isinstance(g, dict) else {}
    plantillas = []
    for p in g.get("plantillas", []) if isinstance(g.get("plantillas"), list) else []:
        nombre = " ".join(str(p.get("nombre") or "").split())[:30] if isinstance(p, dict) else ""
        if nombre:
            plantillas.append({"nombre": nombre, "ind": _ind(p.get("ind")), "par": _par(p.get("par"))})
    comparar = g.get("comparar") if isinstance(g.get("comparar"), str) and len(g["comparar"]) <= 12 else ""
    return {"ind": _ind(g.get("ind")), "par": _par(g.get("par")), "comparar": comparar, "plantillas": plantillas[:MAX_PLANTILLAS]}


def leer(usuario_id):
    return preferencias.leer(usuario_id)["grafico"]


def guardar(usuario_id, cambio):
    """cambio: {"ind", "par", "comparar"} y, opcionalmente, {"plantilla": nombre} para guardar la configuración como plantilla
    o {"borrar_plantilla": índice}."""
    actual = leer(usuario_id)
    if "ind" in cambio:
        actual["ind"] = _ind(cambio["ind"])
    if "par" in cambio:
        actual["par"] = _par(cambio["par"])
    if "comparar" in cambio:
        c = str(cambio["comparar"] or "").upper()[:12]
        actual["comparar"] = c if c and db.uno("SELECT 1 FROM activos WHERE codigo = ?", (c,)) else ""
    nombre = " ".join(str(cambio.get("plantilla") or "").split())[:30]
    if nombre:
        resto = [p for p in actual["plantillas"] if p["nombre"].lower() != nombre.lower()]
        if len(resto) >= MAX_PLANTILLAS:
            raise ErrorGrafico(f"Puedes guardar hasta {MAX_PLANTILLAS} plantillas. Borra una para agregar otra.")
        actual["plantillas"] = resto + [{"nombre": nombre, "ind": dict(actual["ind"]), "par": dict(actual["par"])}]
    i = cambio.get("borrar_plantilla")
    if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(actual["plantillas"]):
        actual["plantillas"].pop(i)
    preferencias.guardar(usuario_id, {"grafico": actual})
    return actual


# ---------- dibujos y anotaciones ----------
def _precio(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0 or x > 1e12:
        raise ErrorGrafico("Precio inválido.")
    return float(x)


def _tiempo(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not (1e12 < x < 4e12):
        raise ErrorGrafico("Fecha inválida.")
    return int(x)


def agregar(usuario_id, activo, tipo, d):
    if not db.uno("SELECT 1 FROM activos WHERE codigo = ?", (activo,)):
        raise ErrorGrafico("Moneda desconocida.")
    d = d if isinstance(d, dict) else {}
    if tipo == "nivel":
        datos = {"precio": _precio(d.get("precio"))}
    elif tipo == "tendencia":
        datos = {"t1": _tiempo(d.get("t1")), "p1": _precio(d.get("p1")), "t2": _tiempo(d.get("t2")), "p2": _precio(d.get("p2"))}
        if datos["t1"] == datos["t2"]:
            raise ErrorGrafico("Los dos puntos de la línea tienen que estar en velas distintas.")
    elif tipo == "nota":
        texto = " ".join(str(d.get("texto") or "").split())[:500]
        if len(texto) < 3:
            raise ErrorGrafico("Escribe la anotación.")
        datos = {"texto": texto}
        if d.get("precio") is not None:
            datos["precio"] = _precio(d["precio"])
    else:
        raise ErrorGrafico("Tipo de dibujo desconocido.")
    maximo = MAX_NOTAS if tipo == "nota" else MAX_DIBUJOS
    n = db.uno("SELECT COUNT(*) AS n FROM dibujos WHERE usuario_id = ? AND activo = ? AND (tipo = 'nota') = ?",
               (usuario_id, activo, 1 if tipo == "nota" else 0))["n"]
    if n >= maximo:
        raise ErrorGrafico(f"Llegaste al máximo de {maximo} para esta moneda. Borra alguno para agregar otro.")
    return db.ejecutar("INSERT INTO dibujos (usuario_id, activo, tipo, datos, creado) VALUES (?, ?, ?, ?, ?)",
                       (usuario_id, activo, tipo, json.dumps(datos), ahora())).lastrowid


def borrar(usuario_id, did=None, activo=None):
    """Borra uno propio, o todos los dibujos (no las anotaciones) de una moneda."""
    if did:
        return db.ejecutar("DELETE FROM dibujos WHERE id = ? AND usuario_id = ?", (did, usuario_id)).rowcount
    return db.ejecutar("DELETE FROM dibujos WHERE usuario_id = ? AND activo = ? AND tipo != 'nota'", (usuario_id, activo)).rowcount


def de(usuario_id, activo):
    dib, notas = [], []
    for r in db.todos("SELECT * FROM dibujos WHERE usuario_id = ? AND activo = ? ORDER BY id", (usuario_id, activo)):
        d = json.loads(r["datos"]) | {"id": r["id"], "tipo": r["tipo"], "creado": r["creado"]}
        (notas if r["tipo"] == "nota" else dib).append(d)
    return dib, notas[::-1]
