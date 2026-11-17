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
    "favoritos": ("Tus favoritos", "medio"),
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
              "cuenta": "Cuenta y verificación", "mercado": "Novedades del mercado", "comunicaciones": "Comunicaciones de la plataforma"}
DETALLE_CATEGORIAS = {"operaciones": "Confirmaciones de compras y ventas, depósitos, retiros y envíos.",
                      "precios": "Alertas de precio, variaciones y órdenes programadas.",
                      "seguridad": "Inicios de sesión, cambios de contraseña o correo y actividad sospechosa.",
                      "cuenta": "Verificación de identidad, documentos, solicitudes y consultas.",
                      "mercado": "Movimientos fuertes de las monedas que sigues.", "comunicaciones": "Novedades y anuncios del equipo."}
CANALES = {"app": "En la plataforma", "correo": "Correo", "push": "Push"}
# Accesos rápidos del inicio: clave -> (texto, ruta, icono). La persona elige cuáles y en qué orden.
ACCESOS = {"depositar": ("Depositar", "cliente.invertir", "invertir"), "comprar": ("Comprar", "auth.trading", "trading"),
           "vender": ("Vender", "auth.trading", "mercado"), "convertir": ("Convertir", "cliente.convertir", "convertir"),
           "enviar": ("Enviar", "cliente.enviar", "enviar"), "retirar": ("Retirar", "cliente.retirar", "retiro"),
           "mercados": ("Mercados", "auth.mercado", "mercado"), "movimientos": ("Movimientos", "cliente.movimientos", "movimientos"),
           "analisis": ("Análisis", "cliente.analisis_cartera", "resumen"), "comparar": ("Comparar", "auth.comparar", "operaciones"),
           "actividad": ("Actividad", "cuenta.actividad", "dispositivo"), "academia": ("Academia", "auth.academia", "documento"),
           "herramientas": ("Herramientas", "auth.herramientas", "ajustes"), "ayuda": ("Ayuda", "cliente.ayuda", "campana")}
ACCESOS_DEFECTO = ["depositar", "comprar", "vender", "convertir", "enviar", "retirar"]
RANGOS = ("7D", "1M", "3M", "1A", "Todo")
MAX_VISTAS = 5
DEFECTO = {
    "orden": list(MODULOS),
    "ocultos": [],
    "moneda": "USD",
    "accesos": list(ACCESOS_DEFECTO),
    "rango": "",          # período con el que abre el gráfico de patrimonio; vacío = el primero disponible
    "vistas": [],         # configuraciones guardadas del inicio: nombre, orden, ocultos, accesos, rango
    "correo": {k: True for k in CATEGORIAS},
    "app": {k: True for k in CATEGORIAS},
    "push": {k: False for k in CATEGORIAS},   # se guarda la elección; el envío push todavía no está integrado
    "aviso_ingreso": "nuevo",                 # nuevo = solo dispositivos nuevos · siempre = cada inicio de sesión
    "tema": "oscuro",
    "zona": "",          # vacío = la de la plataforma
    "idioma": "es",
    "publico": {"activo": True, "foto": True, "bio": True, "ubicacion": False, "antiguedad": True, "nivel": True},
    "lecciones": [],
    "earn_interes": [],
}


def _accesos(lista):
    return [a for a in dict.fromkeys(x for x in lista if isinstance(x, str)) if a in ACCESOS][:8] or list(ACCESOS_DEFECTO)


def _vista(v):
    nombre = " ".join(str(v.get("nombre") or "").split())[:30]
    if not nombre:
        return None
    orden = [m for m in v.get("orden", []) if m in MODULOS]
    return {"nombre": nombre, "orden": list(dict.fromkeys(orden)) + [m for m in MODULOS if m not in orden],
            "ocultos": [m for m in v.get("ocultos", []) if m in MODULOS and m != "patrimonio"],
            "accesos": _accesos(v.get("accesos") or []), "rango": v.get("rango") if v.get("rango") in RANGOS else ""}


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
    if isinstance(guardado.get("accesos"), list):
        out["accesos"] = _accesos(guardado["accesos"])
    out["rango"] = guardado.get("rango") if guardado.get("rango") in RANGOS else ""
    out["vistas"] = [v for v in (_vista(x) for x in guardado.get("vistas", []) if isinstance(x, dict)) if v][:MAX_VISTAS]
    for k in CATEGORIAS:
        if isinstance(guardado.get("correo", {}).get(k), bool):
            out["correo"][k] = guardado["correo"][k]
    for canal in ("app", "push"):
        for k in CATEGORIAS:
            if isinstance(guardado.get(canal, {}).get(k), bool):
                out[canal][k] = guardado[canal][k]
    out["correo"]["seguridad"] = out["app"]["seguridad"] = True  # los avisos de seguridad siempre llegan
    if guardado.get("aviso_ingreso") in ("nuevo", "siempre"):
        out["aviso_ingreso"] = guardado["aviso_ingreso"]
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
    if isinstance(cambios.get("accesos"), list):
        actual["accesos"] = _accesos(cambios["accesos"])
    if "rango" in cambios:
        actual["rango"] = cambios["rango"] if cambios["rango"] in RANGOS else ""
    if cambios.get("guardar_vista"):
        v = _vista({"nombre": cambios["guardar_vista"], "orden": actual["orden"], "ocultos": actual["ocultos"],
                    "accesos": actual["accesos"], "rango": actual["rango"]})
        if v:
            actual["vistas"] = ([x for x in actual["vistas"] if x["nombre"].lower() != v["nombre"].lower()] + [v])[-MAX_VISTAS:]
    if isinstance(cambios.get("aplicar_vista"), int) and 0 <= cambios["aplicar_vista"] < len(actual["vistas"]):
        v = actual["vistas"][cambios["aplicar_vista"]]
        actual.update(orden=list(v["orden"]), ocultos=list(v["ocultos"]), accesos=list(v["accesos"]), rango=v["rango"])
    if isinstance(cambios.get("borrar_vista"), int) and 0 <= cambios["borrar_vista"] < len(actual["vistas"]):
        actual["vistas"].pop(cambios["borrar_vista"])
    if isinstance(cambios.get("correo"), dict):
        for k in CATEGORIAS:
            if k in cambios["correo"]:
                actual["correo"][k] = bool(cambios["correo"][k])
        actual["correo"]["seguridad"] = True
    for canal in ("app", "push"):
        if isinstance(cambios.get(canal), dict):
            for k in CATEGORIAS:
                if k in cambios[canal]:
                    actual[canal][k] = bool(cambios[canal][k])
    actual["app"]["seguridad"] = True
    if cambios.get("aviso_ingreso") in ("nuevo", "siempre"):
        actual["aviso_ingreso"] = cambios["aviso_ingreso"]
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
