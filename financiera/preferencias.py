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
ZONAS = {"America/Asuncion": "Paraguay (Asunción)", "America/Argentina/Buenos_Aires": "Argentina (Buenos Aires)",
         "America/Sao_Paulo": "Brasil (São Paulo)", "America/La_Paz": "Bolivia (La Paz)", "America/Santiago": "Chile (Santiago)",
         "America/Montevideo": "Uruguay (Montevideo)", "America/Lima": "Perú (Lima)", "America/Bogota": "Colombia (Bogotá)",
         "America/Mexico_City": "México (Ciudad de México)", "America/New_York": "Estados Unidos (Nueva York)",
         "Europe/Madrid": "España (Madrid)", "UTC": "UTC"}
# El único idioma con la interfaz completa es el español; los demás se anuncian pero todavía no se pueden elegir.
IDIOMAS = {"es": ("Español", True), "gn": ("Guaraní", False), "pt": ("Português", False), "en": ("English", False)}
CATEGORIAS = {"operaciones": "Operaciones y movimientos", "precios": "Alertas de precio y órdenes", "seguridad": "Seguridad",
              "cuenta": "Cuenta y verificación", "mercado": "Novedades del mercado"}
DEFECTO = {
    "orden": list(MODULOS),
    "ocultos": [],
    "moneda": "USD",
    "correo": {k: True for k in CATEGORIAS},
    "tema": "oscuro",
    "zona": "",          # vacío = la de la plataforma
    "idioma": "es",
    "publico": {"activo": True, "foto": True, "bio": True, "ubicacion": False, "antiguedad": True, "nivel": True},
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
    if guardado.get("tema") in ("oscuro", "claro"):
        out["tema"] = guardado["tema"]
    if guardado.get("zona") in ZONAS:
        out["zona"] = guardado["zona"]
    for k in out["publico"]:
        if isinstance(guardado.get("publico", {}).get(k), bool):
            out["publico"][k] = guardado["publico"][k]
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
    if cambios.get("tema") in ("oscuro", "claro"):
        actual["tema"] = cambios["tema"]
    if "zona" in cambios:
        actual["zona"] = cambios["zona"] if cambios["zona"] in ZONAS else ""
    if isinstance(cambios.get("publico"), dict):
        for k in actual["publico"]:
            if k in cambios["publico"]:
                actual["publico"][k] = bool(cambios["publico"][k])
    try:
        from flask import g
        g.pop("_pref", None)
    except RuntimeError:
        pass
    for clave in ("lecciones", "earn_interes"):
        if isinstance(cambios.get(clave), list):
            actual[clave] = list(dict.fromkeys(str(x)[:60] for x in cambios[clave]))[:100]
    db.ejecutar("INSERT INTO preferencias (usuario_id, datos, actualizado) VALUES (?, ?, ?)"
                " ON CONFLICT(usuario_id) DO UPDATE SET datos = excluded.datos, actualizado = excluded.actualizado",
                (usuario_id, json.dumps(actual, ensure_ascii=False), ahora()))
    return actual


def de_sesion():
    """Preferencias de quien tiene la sesión abierta (una lectura por solicitud). None si no hay sesión."""
    from flask import g
    u = g.get("usuario")
    if not u:
        return None
    if g.get("_pref") is None:
        g._pref = leer(u["id"])
    return g._pref
