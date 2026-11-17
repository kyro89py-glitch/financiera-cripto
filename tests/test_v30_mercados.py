"""v0.30 · Mercados: noticias y acontecimientos con fuente, enlace y fecha verificables; importación RSS/Atom en revisión; mapa."""
from datetime import timedelta

import pytest

from financiera import db, noticias
from financiera.tiempo import ahora_dt

from .conftest import usuario

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Medio</title>
<item><title>Bitcoin supera un nuevo maximo</title><link>https://medio.example/btc</link><guid>a1</guid>
<pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate><description>Texto del medio que no se copia</description></item>
<item><title>Ethereum prepara su actualizacion</title><link>https://medio.example/eth</link><guid>a2</guid>
<pubDate>Sun, 15 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>Sin fecha</title><link>https://medio.example/x</link><guid>a3</guid></item>
</channel></rss>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Otro</title>
<entry><title>Solana y XRP en foco</title><link rel="alternate" href="https://otro.example/sol"/><id>urn:1</id>
<published>2026-11-14T12:00:00Z</published></entry></feed>"""
BOMBA = b"""<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><rss><channel><item><title>&b;</title></item></channel></rss>"""


def _base(**kw):
    return {"tipo": "noticia", "titulo": "BTC cierra la semana en alza", "fuente": "Medio Ejemplo", "url": "https://medio.example/n",
            "fecha": (ahora_dt() - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M"), "activos": ["BTC", "NOEXISTE"]} | kw


def test_validaciones_de_noticias(app):
    with app.app_context():
        adm = usuario("admin@x.com")
        nid = noticias.crear(_base(), adm)
        n = db.uno("SELECT * FROM noticias WHERE id = ?", (nid,))
        assert n["activos"] == "BTC" and n["estado"] == "publicada" and n["fecha"].endswith("Z")
        for malo in (_base(url="javascript:alert(1)"), _base(url="medio.example/n"), _base(fuente=""), _base(titulo="abc"),
                     _base(fecha=""), _base(fecha="ayer"), _base(fecha="1990-01-01"),
                     _base(fecha=(ahora_dt() + timedelta(days=3)).strftime("%Y-%m-%d"))):       # noticia con fecha futura
            with pytest.raises(noticias.ErrorNoticia):
                noticias.crear(malo, adm)
        ev = noticias.crear(_base(tipo="evento", titulo="Reunión de la Reserva Federal", fecha=(ahora_dt() + timedelta(days=5)).strftime("%Y-%m-%d"),
                                  importancia="alta", activos=[]), adm)
        assert [e["id"] for e in noticias.proximos_eventos()] == [ev]
        assert db.uno("SELECT COUNT(*) AS n FROM bitacora WHERE accion = 'noticia.creada'")["n"] == 2


def test_importacion_rss_y_atom_queda_en_revision(app):
    with app.app_context():
        assert noticias.importar(RSS, "Medio") == (2, 1)
        assert noticias.importar(RSS, "Medio") == (0, 3)                  # no duplica
        assert noticias.importar(ATOM, "Otro") == (1, 0)
        filas = {r["titulo"]: r for r in db.todos("SELECT * FROM noticias")}
        assert all(r["estado"] == "revision" and r["origen"] == "rss" and r["resumen"] == "" for r in filas.values())
        assert filas["Bitcoin supera un nuevo maximo"]["activos"] == "BTC"
        assert filas["Solana y XRP en foco"]["activos"] == "SOL,XRP"
        assert filas["Bitcoin supera un nuevo maximo"]["fecha"].startswith("2026-11-16T10:00")
        assert noticias.publicadas() == []                                 # nada importado se muestra sin revisión
        with pytest.raises(noticias.ErrorNoticia):
            noticias.importar(BOMBA, "Malo")
        with pytest.raises(noticias.ErrorNoticia):
            noticias.importar(b"no es xml", "Malo")
        with pytest.raises(noticias.ErrorNoticia):
            noticias.descargar("http://medio.example/rss")                # solo https


def test_flujo_del_equipo_y_lo_que_ven_los_clientes(nav, app):
    c = nav("cum@x.com")
    assert c.get("/equipo/noticias").status_code == 200
    assert nav("op@x.com").get("/equipo/noticias").status_code == 403
    assert nav("laura@x.com").get("/equipo/noticias").status_code in (302, 403)
    datos = _base()
    datos["accion"] = "crear"
    datos.pop("activos")
    c.post("/equipo/noticias", datos | {"activos": "BTC"})
    with app.app_context():
        noticias.importar(RSS, "Medio")
        rev = db.uno("SELECT id FROM noticias WHERE estado = 'revision' ORDER BY id LIMIT 1")["id"]
    n = nav("laura@x.com")
    h = n.get("/mercado/noticias").get_data(as_text=True)
    assert "BTC cierra la semana en alza" in h and "Medio Ejemplo" in h and 'rel="noopener noreferrer nofollow"' in h
    assert "Bitcoin supera" not in h                                       # en revisión
    c.post("/equipo/noticias", {"accion": "estado", "id": rev, "estado": "publicada"})
    assert "Bitcoin supera" in n.get("/mercado/noticias").get_data(as_text=True)
    assert "Bitcoin supera" in n.get("/mercado/BTC").get_data(as_text=True)          # ficha de la moneda
    assert "Bitcoin supera" not in n.get("/mercado/noticias?activo=ETH").get_data(as_text=True)
    assert "BTC cierra la semana" in n.get("/mercado").get_data(as_text=True)
    c.post("/equipo/noticias", {"accion": "estado", "id": rev, "estado": "oculta"})
    assert "Bitcoin supera" not in n.get("/mercado/noticias").get_data(as_text=True)
    assert n.get("/mercado/noticias?ver=eventos&activo=<x>").status_code == 200
    assert nav().get("/mercado/noticias").status_code in (302, 401)
    with app.app_context():
        assert db.uno("SELECT COUNT(*) AS n FROM bitacora WHERE accion = 'noticia.estado'")["n"] == 2


def test_mapa_por_volumen_y_detalle(nav):
    n = nav("laura@x.com")
    h = n.get("/mercado?peso=vol").get_data(as_text=True)
    assert "tamaño según volumen" in h and "data-det=" in h and 'id="mapa-det"' in h
    assert "tamaño según capitalización" in n.get("/mercado?peso=otro").get_data(as_text=True)
