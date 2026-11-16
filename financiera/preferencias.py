"""Preferencias de cada persona, guardadas en el servidor y validadas (nunca se confía en lo que manda el navegador)."""
import json

from . import db
from .tiempo import ahora

# código: (título, ancho) — ancho "lleno" ocupa toda la fila; "medio", media fila en pantallas grandes.
MODULOS = {
    "patrimonio": ("Patrimonio y gráfico", "lleno"),
    "acciones": ("Accesos rápidos", "lleno"),
    "indicadores": ("Indicadores financieros", "lleno"),
    "alertas": ("Alertas importantes", "medio"),
    "rendimientos": ("Rendimiento por período", "medio"),
    "activos": ("Tus activos", "lleno"),
    "composicion": ("Composición 3D", "medio"),
    "riesgo": ("Riesgo de tu cartera", "medio"),
    "ranking": ("Mejores y peores de tu cartera", "medio"),
    "mercado": ("Resumen del mercado", "medio"),
    "recomendaciones": ("Para considerar", "medio"),
    "actividad": ("Actividad reciente", "medio"),
}
CATEGORIAS = {"operaciones": "Operaciones y movimientos", "precios": "Alertas de precio y órdenes", "seguridad": "Seguridad",
              "cuenta": "Cuenta y verificación", "mercado": "Novedades del mercado"}
DEFECTO = {
    "orden": list(MODULOS),
    "ocultos": [],
    "moneda": "USD",
    "correo": {k: True for k in CATEGORIAS},
    "lecciones": [],
    "earn_interes": [],
}


def leer(usuario_id):
    fila = db.uno("SELECT datos FROM preferencias WHERE usuario_id = ?", (usuario_id,))
    try:
        guardado = json.loads(fila["datos"]) if fila else {}
    except ValueError:
        guardado = {}
    out = json.loads(json.dumps(DEFECTO))
    orden = [m for m in guardado.get("orden", []) if m in MODULOS]
    out["orden"] = orden + [m for m in MODULOS if m not in orden]  # módulos nuevos aparecen al final
    out["ocultos"] = [m for m in guardado.get("ocultos", []) if m in MODULOS]
    out["moneda"] = guardado.get("moneda") if guardado.get("moneda") in ("USD", "PYG") else "USD"
    for k in CATEGORIAS:
        if isinstance(guardado.get("correo", {}).get(k), bool):
            out["correo"][k] = guardado["correo"][k]
    out["correo"]["seguridad"] = True  # los avisos de seguridad siempre llegan
    out["lecciones"] = [x for x in guardado.get("lecciones", []) if isinstance(x, str)][:100]
    out["earn_interes"] = [x for x in guardado.get("earn_interes", []) if isinstance(x, str)][:20]
    return out


def guardar(usuario_id, cambios):
    actual = leer(usuario_id)
    if "orden" in cambios:
        orden = [m for m in cambios["orden"] if m in MODULOS]
        actual["orden"] = list(dict.fromkeys(orden)) + [m for m in MODULOS if m not in orden]
    if "ocultos" in cambios:
        actual["ocultos"] = [m for m in dict.fromkeys(cambios["ocultos"]) if m in MODULOS and m != "patrimonio"]
    if cambios.get("moneda") in ("USD", "PYG"):
        actual["moneda"] = cambios["moneda"]
    if isinstance(cambios.get("correo"), dict):
        for k in CATEGORIAS:
            if k in cambios["correo"]:
                actual["correo"][k] = bool(cambios["correo"][k])
        actual["correo"]["seguridad"] = True
    for clave in ("lecciones", "earn_interes"):
        if isinstance(cambios.get(clave), list):
            actual[clave] = list(dict.fromkeys(str(x)[:60] for x in cambios[clave]))[:100]
    db.ejecutar("INSERT INTO preferencias (usuario_id, datos, actualizado) VALUES (?, ?, ?)"
                " ON CONFLICT(usuario_id) DO UPDATE SET datos = excluded.datos, actualizado = excluded.actualizado",
                (usuario_id, json.dumps(actual, ensure_ascii=False), ahora()))
    return actual
