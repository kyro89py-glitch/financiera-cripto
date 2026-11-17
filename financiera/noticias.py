"""Noticias y acontecimientos del mercado, siempre con fuente, enlace y fecha que cualquiera puede verificar.

No se generan textos ni se resumen artículos de terceros automáticamente: el equipo carga cada noticia (título, resumen propio,
fuente y enlace) o la importa de un canal RSS/Atom de un medio, y nada importado se muestra a los clientes sin que una persona
del equipo lo publique."""
import re
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import click
from flask import current_app
from flask.cli import with_appcontext

from . import auditoria, db
from .tiempo import ahora, ahora_dt, iso, leer

try:  # protege contra entidades maliciosas en el XML del canal
    from defusedxml import ElementTree as ET
except ImportError:  # pragma: no cover
    from xml.etree import ElementTree as ET

TIPOS = {"noticia": "Noticia", "evento": "Acontecimiento"}
IMPORTANCIA = {"alta": "Alta", "media": "Media", "baja": "Baja"}
ESTADOS = {"publicada": ("ok", "Publicada"), "revision": ("warn", "En revisión"), "oculta": ("", "Oculta")}
MAX_RSS = 2 * 1024 * 1024


class ErrorNoticia(Exception):
    pass


def _url(texto):
    u = (texto or "").strip()
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc or " " in u or len(u) > 500:
        raise ErrorNoticia("El enlace a la fuente tiene que ser una dirección web completa (https://…).")
    return u


def _fecha(texto, zona=None):
    """Acepta 2026-11-17, 2026-11-17T14:30 (hora local de la plataforma) o ISO con zona. Devuelve ISO UTC."""
    t = (texto or "").strip()
    if not t:
        raise ErrorNoticia("Indica la fecha de publicación o del acontecimiento.")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
            d = datetime.fromisoformat(t + "T12:00")
        else:
            d = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        raise ErrorNoticia("La fecha no es válida.") from None
    if d.tzinfo is None:
        from .formato import zona_plataforma
        d = d.replace(tzinfo=zona or zona_plataforma())
    if not (2009 <= d.year <= ahora_dt().year + 3):
        raise ErrorNoticia("La fecha está fuera de rango.")
    return iso(d.astimezone(timezone.utc))


def _activos(lista):
    codigos = {r["codigo"] for r in db.todos("SELECT codigo FROM activos")}
    if isinstance(lista, str):
        lista = re.split(r"[\s,;]+", lista)
    return ",".join(sorted({c.strip().upper() for c in lista if c and c.strip().upper() in codigos}))


def crear(datos, usuario, estado="publicada", origen="manual", guid=None):
    tipo = datos.get("tipo") if datos.get("tipo") in TIPOS else "noticia"
    titulo = " ".join((datos.get("titulo") or "").split())
    if not 5 <= len(titulo) <= 200:
        raise ErrorNoticia("El título tiene que tener entre 5 y 200 caracteres.")
    resumen = " ".join((datos.get("resumen") or "").split())[:600]
    fuente = " ".join((datos.get("fuente") or "").split())
    if not 2 <= len(fuente) <= 80:
        raise ErrorNoticia("Indica el nombre de la fuente (el medio o la organización).")
    url, fecha = _url(datos.get("url")), _fecha(datos.get("fecha"))
    if tipo == "noticia" and leer(fecha) > ahora_dt():
        raise ErrorNoticia("Una noticia no puede tener fecha de publicación futura. Si es algo que va a pasar, cárgalo como acontecimiento.")
    imp = datos.get("importancia") if datos.get("importancia") in IMPORTANCIA else "media"
    nid = db.ejecutar("INSERT INTO noticias (tipo, titulo, resumen, fuente, url, fecha, activos, importancia, estado, origen, guid, creado, creado_por)"
                      " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (tipo, titulo, resumen, fuente, url, fecha, _activos(datos.get("activos") or ""), imp, estado, origen, guid, ahora(),
                       usuario["id"] if usuario else None)).lastrowid
    if usuario:
        auditoria.registrar("noticia.creada", f"noticia:{nid}", {"texto": f"{TIPOS[tipo]} «{titulo[:80]}» de {fuente} ({estado})."}, usuario=usuario)
    return nid


def cambiar_estado(nid, estado, usuario):
    if estado not in ESTADOS:
        raise ErrorNoticia("Estado desconocido.")
    n = db.uno("SELECT * FROM noticias WHERE id = ?", (nid,))
    if not n:
        raise ErrorNoticia("No existe.")
    db.ejecutar("UPDATE noticias SET estado = ?, revisado_por = ?, revisado = ? WHERE id = ?", (estado, usuario["id"], ahora(), nid))
    auditoria.registrar("noticia.estado", f"noticia:{nid}", {"texto": f"«{n['titulo'][:80]}» pasó a {ESTADOS[estado][1].lower()}."}, usuario=usuario)


def _fila(r):
    d = dict(r)
    d["lista_activos"] = [a for a in r["activos"].split(",") if a]
    d["dominio"] = urlparse(r["url"]).netloc.removeprefix("www.")
    return d


def publicadas(tipo=None, activo=None, limite=30, desde=None, hasta=None):
    sql, args = "SELECT * FROM noticias WHERE estado = 'publicada'", []
    if tipo in TIPOS:
        sql += " AND tipo = ?"
        args.append(tipo)
    if activo:
        sql += " AND (',' || activos || ',') LIKE ?"
        args.append(f"%,{activo.upper()},%")
    if desde:
        sql += " AND fecha >= ?"
        args.append(desde)
    if hasta:
        sql += " AND fecha <= ?"
        args.append(hasta)
    orden = " ORDER BY fecha ASC" if tipo == "evento" and desde else " ORDER BY fecha DESC"
    return [_fila(r) for r in db.todos(sql + orden + " LIMIT ?", (*args, limite))]


def proximos_eventos(activo=None, limite=8):
    return publicadas("evento", activo, limite, desde=iso(ahora_dt().replace(hour=0, minute=0, second=0, microsecond=0)))


def todas(estado=None, limite=200):
    sql = "SELECT n.*, u.nombre AS autor FROM noticias n LEFT JOIN usuarios u ON u.id = n.creado_por"
    args = ()
    if estado in ESTADOS:
        sql += " WHERE n.estado = ?"
        args = (estado,)
    return [_fila(r) for r in db.todos(sql + " ORDER BY n.creado DESC LIMIT ?", (*args, limite))]


# ---------- importación de canales RSS / Atom ----------
_NOMBRES = None


def _detectar_activos(texto):
    """Monedas mencionadas por su código o su nombre completo (palabra entera)."""
    global _NOMBRES
    filas = db.todos("SELECT codigo, nombre FROM activos")
    out = set()
    for f in filas:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(f['codigo'])}(?![A-Za-z0-9])", texto) or \
                (len(f["nombre"]) > 3 and re.search(rf"\b{re.escape(f['nombre'])}\b", texto, re.I)):
            out.add(f["codigo"])
    return sorted(out)


def _texto(el):
    return re.sub(r"<[^>]+>", " ", "".join(el.itertext()) if el is not None else "").strip()


def leer_canal(xml):
    """Devuelve [{titulo, url, fecha, guid, resumen}] de un RSS 2.0 o Atom. El resumen del canal NO se publica: se usa solo
    como ayuda para quien revisa, porque el texto pertenece al medio."""
    try:
        raiz = ET.fromstring(xml)
    except Exception as e:  # noqa: BLE001  XML inválido o con entidades bloqueadas
        raise ErrorNoticia(f"El canal no es un RSS o Atom válido ({type(e).__name__}).") from None
    atom = "{http://www.w3.org/2005/Atom}"
    out = []
    for it in raiz.iter("item"):
        fecha = None
        try:
            fecha = iso(parsedate_to_datetime(_texto(it.find("pubDate"))).astimezone(timezone.utc))
        except (TypeError, ValueError, IndexError):
            pass
        out.append({"titulo": _texto(it.find("title")), "url": _texto(it.find("link")), "fecha": fecha,
                    "guid": _texto(it.find("guid")) or _texto(it.find("link")), "resumen": _texto(it.find("description"))[:400]})
    for en in raiz.iter(f"{atom}entry"):
        link = next((l.get("href") for l in en.findall(f"{atom}link") if l.get("rel", "alternate") == "alternate"), None)
        fecha = None
        try:
            fecha = _fecha(_texto(en.find(f"{atom}published")) or _texto(en.find(f"{atom}updated")))
        except ErrorNoticia:
            pass
        out.append({"titulo": _texto(en.find(f"{atom}title")), "url": link or "", "fecha": fecha,
                    "guid": _texto(en.find(f"{atom}id")) or link, "resumen": _texto(en.find(f"{atom}summary"))[:400]})
    return out


def importar(xml, fuente, usuario=None, maximo=30):
    """Agrega en revisión los artículos nuevos del canal (los repetidos se ignoran). Devuelve (nuevos, omitidos)."""
    nuevos = omitidos = 0
    for a in leer_canal(xml)[:maximo]:
        if not a["fecha"] or not a["titulo"] or not a["url"] or \
                db.uno("SELECT 1 FROM noticias WHERE guid = ? OR url = ?", (a["guid"][:300], a["url"])):
            omitidos += 1
            continue
        try:
            crear({"tipo": "noticia", "titulo": a["titulo"][:200], "resumen": "", "fuente": fuente, "url": a["url"], "fecha": a["fecha"],
                   "activos": _detectar_activos(a["titulo"])}, None, estado="revision", origen="rss", guid=a["guid"][:300])
            nuevos += 1
        except ErrorNoticia:
            omitidos += 1
    if usuario or nuevos:
        auditoria.registrar("noticia.importadas", f"fuente:{fuente[:40]}", {"texto": f"Importó {nuevos} noticias de {fuente} (en revisión)."},
                            usuario=usuario)
    return nuevos, omitidos


def descargar(url):
    u = _url(url)
    if not u.startswith("https://"):
        raise ErrorNoticia("Solo se importan canales con https.")
    req = urllib.request.Request(u, headers={"User-Agent": f"{current_app.config.get('NOMBRE', 'Financiera')}/noticias"})
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310  esquema validado arriba
        datos = r.read(MAX_RSS + 1)
    if len(datos) > MAX_RSS:
        raise ErrorNoticia("El canal es demasiado grande.")
    return datos


@click.command("noticias-importar")
@click.argument("url")
@click.option("--fuente", required=True, help="Nombre del medio, tal como se mostrará.")
@with_appcontext
def cmd_importar(url, fuente):
    """Importa en revisión los artículos de un canal RSS o Atom (para programarlo, por ejemplo, cada hora)."""
    nuevos, omitidos = importar(descargar(url), fuente)
    click.echo(f"{nuevos} nuevas en revisión, {omitidos} omitidas.")
