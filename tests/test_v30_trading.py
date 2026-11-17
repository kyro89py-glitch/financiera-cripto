"""v0.30 · Trading: configuración del gráfico en la cuenta, plantillas, dibujos, anotaciones y estadísticas de operaciones."""
import json
from decimal import Decimal

from financiera import db, graficos_usuario, operaciones, precios

from .conftest import cliente, usuario

T = 1_763_000_000_000  # milisegundos (nov. 2025)


def _json(n, url, cuerpo, csrf=True):
    return n.c.post(url, data=json.dumps(cuerpo), content_type="application/json",
                    headers={"X-CSRF-Token": n.token()} if csrf else {})


def test_configuracion_del_grafico_en_la_cuenta(nav, app):
    n = nav("laura@x.com")
    r = _json(n, "/trading/config", {"ind": {"rsi": True, "ma": False, "raro": True}, "par": {"rsi": 999, "mf": 20, "ms": 10, "ek": "x"},
                                     "comparar": "eth"})
    assert r.status_code == 200
    g = r.get_json()["grafico"]
    assert g["ind"]["rsi"] and not g["ind"]["ma"] and "raro" not in g["ind"]
    assert g["par"]["rsi"] == 50 and g["par"]["ms"] == 21 and g["par"]["ek"] == 14 and g["comparar"] == "ETH"
    h = nav("laura@x.com").get("/trading/BTC").get_data(as_text=True)          # otro dispositivo
    datos = json.loads(h.split('id="datos-trading">')[1].split("</script>")[0])
    assert datos["grafico"]["ind"]["rsi"] is True and datos["grafico"]["comparar"] == "ETH" and datos["grafico_nuevo"] is False
    assert _json(n, "/trading/config", {"comparar": "NOEXISTE"}).get_json()["grafico"]["comparar"] == ""
    assert _json(n, "/trading/config", {"ind": {}}, csrf=False).status_code == 400
    assert _json(n, "/trading/config", ["no", "dict"]).status_code == 400


def test_plantillas(nav, app):
    n = nav("laura@x.com")
    _json(n, "/trading/config", {"ind": {"macd": True}, "plantilla": " Momentum "})
    g = _json(n, "/trading/config", {"ind": {"macd": False, "boll": True}, "plantilla": "Bandas"}).get_json()["grafico"]
    assert [p["nombre"] for p in g["plantillas"]] == ["Momentum", "Bandas"] and g["plantillas"][0]["ind"]["macd"] is True
    g = _json(n, "/trading/config", {"plantilla": "momentum"}).get_json()["grafico"]          # mismo nombre: reemplaza
    assert [p["nombre"] for p in g["plantillas"]] == ["Bandas", "momentum"]
    for i in range(4):
        _json(n, "/trading/config", {"plantilla": f"P{i}"})
    r = _json(n, "/trading/config", {"plantilla": "Sobra"})
    assert r.status_code == 400 and "hasta" in r.get_json()["error"]
    g = _json(n, "/trading/config", {"borrar_plantilla": 0}).get_json()["grafico"]
    assert len(g["plantillas"]) == graficos_usuario.MAX_PLANTILLAS - 1


def test_dibujos_validados_y_privados(nav, app):
    n = nav("laura@x.com")
    r = _json(n, "/trading/BTC/dibujos", {"tipo": "nivel", "precio": 65000.5})
    assert r.status_code == 200 and r.get_json()["dibujos"][0]["precio"] == 65000.5
    r = _json(n, "/trading/BTC/dibujos", {"tipo": "tendencia", "t1": T, "p1": 60000, "t2": T + 3_600_000, "p2": 62000})
    assert len(r.get_json()["dibujos"]) == 2
    for malo in ({"tipo": "nivel", "precio": -1}, {"tipo": "nivel", "precio": "1e400"}, {"tipo": "nivel", "precio": True},
                 {"tipo": "tendencia", "t1": T, "p1": 1, "t2": T, "p2": 2}, {"tipo": "tendencia", "t1": 5, "p1": 1, "t2": T, "p2": 2},
                 {"tipo": "circulo"}):
        assert _json(n, "/trading/BTC/dibujos", malo).status_code == 400, malo
    assert _json(n, "/trading/NOEXISTE/dibujos", {"tipo": "nivel", "precio": 1}).status_code == 400
    h = n.get("/trading/BTC").get_data(as_text=True)
    assert '"precio": 65000.5' in h or '"precio":65000.5' in h
    # otra persona no los ve ni los puede borrar
    p = nav("pedro@x.com")
    assert "65000.5" not in p.get("/trading/BTC").get_data(as_text=True)
    with app.app_context():
        did = db.uno("SELECT id FROM dibujos ORDER BY id LIMIT 1")["id"]
    _json(p, "/trading/BTC/dibujos", {"accion": "borrar", "id": did})
    _json(p, "/trading/BTC/dibujos", {"accion": "borrar"})
    with app.app_context():
        assert db.uno("SELECT COUNT(*) AS n FROM dibujos")["n"] == 2
    assert _json(n, "/trading/BTC/dibujos", {"accion": "borrar", "id": did}).get_json()["dibujos"][0]["tipo"] == "tendencia"
    assert _json(n, "/trading/BTC/dibujos", {"accion": "borrar"}).get_json()["dibujos"] == []
    with app.app_context():
        for _ in range(graficos_usuario.MAX_DIBUJOS):
            graficos_usuario.agregar(usuario("laura@x.com")["id"], "ETH", "nivel", {"precio": 1.0})
    assert _json(n, "/trading/ETH/dibujos", {"tipo": "nivel", "precio": 2}).status_code == 400


def test_anotaciones_con_precio_del_servidor(nav, app):
    n = nav("laura@x.com")
    n.post("/trading/BTC/dibujos", {"tipo": "nota", "texto": "Rompió la resistencia", "con_precio": "si", "precio": "1"})
    n.post("/trading/BTC/dibujos", {"tipo": "nota", "texto": "Sin precio"})
    n.post("/trading/BTC/dibujos", {"tipo": "nota", "texto": "x"})                      # demasiado corta
    with app.app_context():
        filas = [json.loads(r["datos"]) for r in db.todos("SELECT datos FROM dibujos WHERE tipo = 'nota' ORDER BY id")]
        vigente = float(precios.vigentes()["BTC"]["precio"])
    assert len(filas) == 2 and filas[0]["precio"] == vigente and "precio" not in filas[1]  # el precio enviado por el navegador se ignora
    h = n.get("/trading/BTC").get_data(as_text=True)
    assert "Rompió la resistencia" in h and "desde entonces" in h
    assert "Rompió la resistencia" not in nav("pedro@x.com").get("/trading/BTC").get_data(as_text=True)


def test_estadisticas_marcan_lo_simulado(nav, app):
    with app.app_context():
        cli = cliente("laura@x.com")
        opid = operaciones.solicitar_aporte(cli, 500000, None, "T-est", None)
        operaciones.aprobar(opid, usuario("op@x.com"))
        operaciones.operar(cli, "BTC", "compra", 200000, usuario("laura@x.com"))
        precios.registrar("BTC", Decimal(str(float(precios.vigentes()["BTC"]["precio"]) * 1.10)), Decimal("10"), "pruebas")
        operaciones.operar(cli, "BTC", "venta", 110000, usuario("laura@x.com"))
        from financiera import estadisticas
        e = estadisticas.de_cliente(cli["id"])
        assert e["ordenes"] == 2 and e["cerradas"] == 1 and e["positivas"] == 1 and e["pct_positivas"] == 100
        assert 9000 <= e["acumulado"] <= 10100 and e["todo_simulado"]
        assert estadisticas.de_cliente(cli["id"], "30")["ordenes"] == 2
    n = nav("laura@x.com")
    h = n.get("/cliente/estadisticas").get_data(as_text=True)
    assert "Resultados simulados" in h and "(simulado)" in h and "BTC" in h
    assert n.get("/cliente/estadisticas?periodo=raro").status_code == 200
    assert "No hay órdenes ejecutadas" in nav("pedro@x.com").get("/cliente/estadisticas").get_data(as_text=True)
