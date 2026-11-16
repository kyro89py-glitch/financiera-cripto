"""v0.20 · Módulo 4: mercados, comparación, historial exportable, alertas por variación y ficha de cada moneda."""
import csv
import io
from decimal import Decimal

from financiera import alertas, db, mercado_info, precios

from .conftest import usuario


def test_listado_con_ranking_fuente_y_mapa_por_periodo(nav, ctx):
    n = nav("laura@x.com")
    html = n.get("/mercado").data.decode()
    assert "<th class=\"r oc\">#</th>" in html and "Fuente:" in html and "Comparar monedas" in html
    assert "Tendencia 7 días" in html and "mapa-leyenda" in html
    assert n.get("/mercado?mapa=7d&orden=tendencia").status_code == 200


def test_comparar_monedas(nav, ctx):
    n = nav("laura@x.com")
    r = n.get("/mercado/comparar?m=BTC&m=ETH&m=NOEXISTE&r=30")
    html = r.data.decode()
    assert r.status_code == 200 and "Lado a lado" in html and "NOEXISTE ·" not in html
    assert html.count('class="activo-cel"') == 2
    solo = n.get("/mercado/comparar?m=SOL").data.decode()
    assert solo.count('class="activo-cel"') == 2  # con una sola moneda se completa con otra para poder comparar


def test_historial_exportable_con_fuente_y_zona(nav, ctx):
    r = nav("laura@x.com").get("/mercado/BTC/historial.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    filas = list(csv.reader(io.StringIO(r.data.decode("utf-8-sig")), delimiter=";"))
    assert "fuente:" in filas[0][1] and "America/Asuncion" in filas[0][2]
    assert filas[1][:5] == ["fecha", "apertura", "maximo", "minimo", "cierre"] and len(filas) >= 3


def test_alerta_por_variacion_de_24_horas(nav, ctx):
    n = nav("laura@x.com")
    r = n.post("/cliente/alertas", {"activo": "SOL", "tipo": "variacion", "sentido": "baja", "umbral": "5"})
    assert r.status_code == 302
    a = db.uno("SELECT * FROM alertas_precio WHERE tipo = 'variacion'")
    assert a["umbral"] == 5 and a["sentido"] == "baja"
    precios.registrar("SOL", Decimal("95"), Decimal("-3"), "pruebas")
    assert alertas.revisar(precios.vigentes()) == 0
    precios.registrar("SOL", Decimal("90"), Decimal("-6.2"), "pruebas")
    assert alertas.revisar(precios.vigentes()) == 1
    aviso = db.uno("SELECT * FROM notificaciones WHERE usuario_id = ? ORDER BY id DESC", (usuario("laura@x.com")["id"],))
    assert "baja 6,2 % en 24 horas" in aviso["texto"] and aviso["categoria"] == "precios"
    assert alertas.revisar(precios.vigentes()) == 0  # avisa una sola vez
    assert n.post("/cliente/alertas", {"activo": "SOL", "tipo": "variacion", "sentido": "sube", "umbral": "200"}).status_code == 302
    assert db.uno("SELECT COUNT(*) AS n FROM alertas_precio WHERE tipo = 'variacion'")["n"] == 1  # 200 % no es válido


def test_ficha_completa_de_cada_moneda(nav, ctx):
    assert all(mercado_info.ficha(a["codigo"]) for a in precios.activos(solo_habilitados=True))
    html = nav("laura@x.com").get("/mercado/BTC").data.decode()
    for texto in ("Sobre Bitcoin", "Satoshi Nakamoto", "Estadísticas", "Fuente:", "Actividad del mercado", "Cotizaciones diarias",
                  "Exportar CSV", "al menos (%)"):
        assert texto in html, texto
