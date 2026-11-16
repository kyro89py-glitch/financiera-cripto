"""v0.9: más monedas, precios en tiempo real, trading, reservas de saldo, depósitos y retiros con revisión,
movimientos con detalle, sesiones por dispositivo y privacidad."""
from datetime import timedelta
from decimal import Decimal

import pytest

from financiera import cartera, db, exchange, notificaciones, operaciones, precios, programadas, transferencias, velas
from financiera.dinero import fmt_precio, fmt_unidades
from financiera.formato import compacto
from financiera.tiempo import ahora_dt, iso

from .binance_falso import CLAVE as CLAVE_BX, SECRETO, BinanceFalso
from .conftest import CLAVE, cliente, usuario


def _saldo(monto=100000):
    laura = cliente("laura@x.com")
    operaciones.aprobar(operaciones.solicitar_aporte(laura, monto, "saldo", "T", None), usuario("op@x.com"))
    return laura, usuario("laura@x.com")


def test_monedas_nuevas_y_formatos(ctx):
    acts = precios.activos()
    assert len(acts) == 27 and {"PEPE", "SHIB", "DOGE", "ADA", "AAVE", "POL"} <= {a["codigo"] for a in acts}
    assert {a["categoria"] for a in acts} <= set(precios.CATEGORIAS)
    assert fmt_precio(Decimal("0.0000039")) == "US$ 0,000003900" and fmt_precio(Decimal("0.1534")) == "US$ 0,1534"
    assert fmt_precio(Decimal("64666")) == "US$ 64.666,00"
    assert compacto(1.30059e12) == "US$ 1,30 B" and compacto(49.17e9) == "US$ 49,17 mil M" and compacto(345.7e6) == "US$ 345,7 M"
    assert precios.redondear(0.00000389123456) == Decimal("0.00000389123")


def test_comprar_una_moneda_de_precio_muy_bajo(ctx):
    laura, u = _saldo()
    _, r = operaciones.operar(laura, "PEPE", "compra", 10000, u)                  # US$ 100 a 0,00000389
    assert r == "liquidada"
    unidades = cartera.tenencias(laura["id"])["PEPE"]
    assert abs(unidades / 10 ** 8 - 100 / 0.00000389) < 1
    assert fmt_unidades(unidades, "PEPE").endswith(" PEPE")
    operaciones.operar(laura, "PEPE", "venta", 0, u, todo=True)
    assert "PEPE" not in cartera.tenencias(laura["id"])


def test_mercados_filtros_y_mapa(nav, ctx):
    n = nav("laura@x.com")
    r = n.get("/mercado?cat=memes")
    assert r.status_code == 200 and b'data-buscar="pepe' in r.data and b'data-buscar="btc ' not in r.data
    assert b'data-buscar="sol ' in n.get("/mercado?q=sol").data and b'data-buscar="eth ' not in n.get("/mercado?q=sol").data
    r = n.get("/mercado?orden=volumen")
    assert b"Mapa de calor" in r.data and b"data-mapa=" in r.data and b"Dominancia de Bitcoin" in r.data
    j = n.get("/mercado/precios.json").get_json()
    assert set(j) >= {"precios", "vivo", "seg", "fuente"} and j["precios"]["PEPE"]["dec"] == 9


def test_trading_pantalla_y_datos(nav, ctx):
    n = nav("laura@x.com")
    r = n.get("/trading")
    assert r.status_code == 302 and r.headers["Location"].endswith("/trading/BTC")
    r = n.get("/trading/eth?i=4h")
    assert r.status_code == 200 and b"ETH" in r.data and "Modo demostración".encode() in r.data and b'id="f-orden"' in r.data
    assert "par=ETH" in r.headers["Set-Cookie"]
    assert n.get("/trading").headers["Location"].endswith("/trading/ETH")       # recuerda el último par
    assert n.get("/trading/NADA").status_code == 404
    for i in velas.INTERVALOS:
        j = n.get(f"/mercado/BTC/velas.json?i={i}").get_json()
        assert j["v"], i
        for t, o, h, lo, c, _ in j["v"]:
            assert h >= max(o, c) and lo <= min(o, c)
    assert n.get("/mercado/BTC/velas.json?i=3m").status_code == 404
    j = n.get("/mercado/BTC/libro.json").get_json()
    assert j["simulado"] and j["compras"][0][0] < 70000 < j["ventas"][0][0] and len(j["ops"]) > 5
    assert [x[0] for x in j["ventas"]] == sorted(x[0] for x in j["ventas"])                 # de mejor a peor
    assert [x[0] for x in j["compras"]] == sorted((x[0] for x in j["compras"]), reverse=True)
    # el equipo ve la pantalla, sin panel de órdenes
    r = nav("op@x.com").get("/trading/BTC")
    assert r.status_code == 200 and b'id="f-orden"' not in r.data


def test_velas_del_historial(ctx):
    for k in range(30):
        db.ejecutar("INSERT INTO precios_historial (activo, precio, ts) VALUES ('SOL', ?, ?)",
                    (str(100 + k), iso(ahora_dt() - timedelta(minutes=30 - k))))
    v, con_volumen = velas.velas("SOL", "1m")
    assert not con_volumen and len(v) >= 30 and v[-1][4] == 100.0          # cierra con el precio vigente
    assert all(v[i][1] == v[i - 1][4] for i in range(1, len(v)))             # cada vela abre donde cerró la anterior


def test_orden_limite_desde_trading_con_tipo(nav, ctx):
    laura, _ = _saldo()
    n = nav("laura@x.com")
    base = {"activo": "BTC", "lado": "compra", "monto": "100", "volver": "/trading/BTC?i=1h"}
    r = n.post("/cliente/programadas", dict(base, tipo="limite", precio="75.000"))
    assert r.headers["Location"].endswith("/trading/BTC?i=1h") and not programadas.del_cliente(laura["id"])
    assert "menor al actual".encode() in n.get("/trading/BTC").data
    n.post("/cliente/programadas", dict(base, tipo="stop", precio="75.000"))   # compra si sube: válida
    o = programadas.del_cliente(laura["id"])[0]
    assert (o["condicion"], programadas.nombre(o)) == ("mayor", "Compra si sube")
    r = n.post("/cliente/operar", dict(base, monto="50"))
    assert r.headers["Location"].endswith("/trading/BTC?i=1h")
    assert n.post("/cliente/operar", dict(base, volver="https://otro.sitio/x")).headers["Location"].endswith("/mercado/BTC")


def test_reservas_de_saldo_por_ordenes(ctx):
    laura, u = _saldo(50000)
    programadas.crear(laura, "BTC", "compra", Decimal("60000"), 30000, u)
    assert cartera.bloqueado(laura["id"]) == {"USD": 30000}
    assert cartera.disponible(laura["id"])["USD"] == 20000
    with pytest.raises(operaciones.ErrorNegocio, match="reservado"):
        operaciones.operar(laura, "ETH", "compra", 25000, u)
    with pytest.raises(operaciones.ErrorNegocio, match="disponible suficiente"):
        programadas.crear(laura, "ETH", "compra", Decimal("1500"), 25000, u)
    assert operaciones.reservado_cent(laura["id"]) == 30000
    with pytest.raises(operaciones.ErrorNegocio, match="supera lo disponible"):
        operaciones.solicitar_retiro(laura, 25000, u)
    cuentas_cli = cliente("pedro@x.com")
    from financiera import cuentas
    from .conftest import legajo_completo
    legajo_completo(cuentas_cli["id"])
    cuentas.marcar_kyc(cuentas_cli["id"], "verificado", "", usuario("cum@x.com"))
    with pytest.raises(transferencias.ErrorEnvio, match="saldo suficiente"):
        transferencias.enviar(laura, "pedro@x.com", "USD", 25000, u, CLAVE)
    programadas.cancelar(programadas.del_cliente(laura["id"])[0]["id"], laura, u)
    assert cartera.bloqueado(laura["id"]) == {} and operaciones.operar(laura, "ETH", "compra", 25000, u)[1] == "liquidada"


def test_monedas_suspendidas(nav, ctx):
    laura, u = _saldo()
    operaciones.operar(laura, "DOGE", "compra", 5000, u)
    a = nav("admin@x.com")
    assert a.get("/admin/precios").status_code == 200
    a.post("/admin/precios/DOGE/habilitar")
    assert db.uno("SELECT habilitado FROM activos WHERE codigo = 'DOGE'")["habilitado"] == 0
    with pytest.raises(operaciones.ErrorNegocio, match="no está disponible"):
        operaciones.operar(laura, "DOGE", "compra", 1000, u)
    operaciones.operar(laura, "DOGE", "venta", 1000, u)                       # vender sí se puede
    r = nav("laura@x.com").get("/mercado")
    assert b'data-buscar="doge ' in r.data and "Solo venta".encode() in r.data   # la tiene: la sigue viendo
    r = nav("pedro@x.com").get("/mercado")
    assert b'data-buscar="doge ' not in r.data and b'data-px="DOGE"' not in r.data      # ni en la tabla ni en la cinta
    assert db.uno("SELECT 1 FROM bitacora WHERE accion = 'activo.suspendido'")


def test_precios_simulados_en_vivo_e_historial(ctx):
    ctx.config["FUENTE_PRECIOS"] = "simulada"
    antes = precios.vigentes()["BTC"]["precio"]
    n0 = db.uno("SELECT COUNT(*) AS n FROM precios_historial")["n"]
    assert precios.actualizar(auditar=False) == 27
    v = precios.vigentes()["BTC"]
    assert v["fuente"] == "Simulado" and v["precio"] != antes and v["max"] >= v["precio"] >= v["min"]
    n1 = db.uno("SELECT COUNT(*) AS n FROM precios_historial")["n"]
    precios.actualizar(auditar=False, historial_min=1)                          # enseguida: no suma historial
    assert db.uno("SELECT COUNT(*) AS n FROM precios_historial")["n"] == n1 and n1 > n0
    assert precios.vivo()[0] is True
    ctx.config["ENTORNO"] = "produccion"
    with pytest.raises(precios.ErrorPrecio):
        precios.actualizar_simulado()
    ctx.config["ENTORNO"] = "pruebas"


def test_poda_del_historial(ctx):
    db.ejecutar("DELETE FROM precios_historial")
    base = ahora_dt() - timedelta(days=10)
    for k in range(240):  # un punto por minuto durante 4 horas, hace 10 días
        db.ejecutar("INSERT INTO precios_historial (activo, precio, ts) VALUES ('ETH', ?, ?)", (str(2000 + k), iso(base + timedelta(minutes=k))))
    for k in range(30):   # recientes: quedan todos
        db.ejecutar("INSERT INTO precios_historial (activo, precio, ts) VALUES ('ETH', '2000', ?)", (iso(ahora_dt() - timedelta(minutes=k)),))
    precios.podar_historial()
    viejos = db.uno("SELECT COUNT(*) AS n FROM precios_historial WHERE ts < ?", (iso(ahora_dt() - timedelta(days=5)),))["n"]
    assert viejos in (4, 5)                                                      # uno por hora
    assert db.uno("SELECT COUNT(*) AS n FROM precios_historial WHERE ts > ?", (iso(ahora_dt() - timedelta(hours=1)),))["n"] == 30


@pytest.fixture
def bx(ctx):
    falso = BinanceFalso({"BTC": "70000", "ETH": "2000", "SOL": "100"})
    ctx.config["FUENTE_PRECIOS"] = "binance"
    ctx.extensions["broker_pruebas"] = exchange.Binance(CLAVE_BX, SECRETO, exchange.URL_BINANCE_PRUEBAS, sesion=falso)
    velas._CACHE.clear()
    yield falso
    ctx.extensions.pop("broker_pruebas", None)
    velas._CACHE.clear()


def test_datos_de_mercado_desde_binance(bx, ctx):
    bx.estricto = True                                       # pide 26 símbolos y Binance no conoce la mayoría
    assert precios.actualizar_binance(auditar=False) == 4    # BTC, ETH, SOL y USDT
    v = precios.vigentes()["BTC"]
    assert v["fuente"] == "Binance" and v["volumen"] == 123456789.5 and v["max"] == Decimal("71400.00")
    filas, con_volumen = velas.velas("BTC", "1m")
    assert con_volumen and filas[0][4] == 70000.0 and len(filas) == velas.INTERVALOS["1m"][2]
    compras, ventas, sim = velas.libro("BTC")
    assert not sim and compras[0][0] == Decimal("69999") and ventas[0][0] == Decimal("70001")
    ops, sim = velas.operaciones_mercado("BTC")
    assert not sim and len(ops) == 3


def test_deposito_con_metodo_y_revision(nav, ctx):
    n = nav("laura@x.com")
    datos = {"monto": "500", "modelo": "saldo", "referencia": "TRF-9", "metodo": "transferencia", "moneda": "USD"}
    r = n.post("/cliente/invertir", dict(datos, paso="revisar"))
    assert r.status_code == 200 and "Revisa tu depósito".encode() in r.data and not db.uno("SELECT 1 FROM operaciones")
    r = n.post("/cliente/invertir", dict(datos, paso="editar"))
    assert r.status_code == 200 and b'value="TRF-9"' in r.data and not db.uno("SELECT 1 FROM operaciones")
    r = n.post("/cliente/invertir", dict(datos, paso="confirmar"))
    op = db.uno("SELECT * FROM operaciones")
    assert r.headers["Location"].endswith(f"/cliente/movimientos/{op['id']}") and op["metodo"] == "transferencia"
    r = n.get(f"/cliente/movimientos/{op['id']}")
    assert r.status_code == 200 and "Transferencia bancaria".encode() in r.data and b"linea-tiempo" in r.data
    # efectivo solo si hay oficina configurada; USDT solo en dólares y con dirección cargada
    r = n.post("/cliente/invertir", dict(datos, metodo="efectivo", paso="revisar"))
    assert "Elige cómo vas a depositar".encode() in r.data
    ctx.config["OFICINA_DIRECCION"] = "Av. Mcal. López 1234, Asunción"
    ctx.config["DEPOSITO_USDT_DIRECCION"] = "TXyz123"
    assert "Efectivo en la oficina".encode() in n.get("/cliente/invertir").data
    assert b"TXyz123" in n.get("/cliente/invertir").data
    with pytest.raises(operaciones.ErrorNegocio, match="USDT"):
        operaciones.solicitar_aporte(cliente("laura@x.com"), 0, "saldo", "h", None, monto_pyg=1_000_000, metodo="usdt")


def test_retiro_con_revision_y_estado(nav, ctx):
    _saldo()
    n = nav("laura@x.com")
    assert n.get("/cliente/retirar").status_code == 200
    r = n.post("/cliente/retirar", {"monto": "100", "moneda": "USD", "metodo": "transferencia", "paso": "revisar"})
    assert r.status_code == 200 and "Revisa tu retiro".encode() in r.data
    assert not db.uno("SELECT 1 FROM operaciones WHERE tipo = 'retiro'")
    r = n.post("/cliente/retirar", {"monto": "100", "moneda": "USD", "metodo": "transferencia", "paso": "confirmar"})
    op = db.uno("SELECT * FROM operaciones WHERE tipo = 'retiro'")
    assert op["metodo"] == "transferencia" and r.headers["Location"].endswith(f"/cliente/movimientos/{op['id']}")
    r = n.post("/cliente/retirar", {"monto": "999999", "moneda": "USD", "metodo": "transferencia", "paso": "revisar"})
    assert "supera lo disponible".encode() in r.data
    assert "Cancelar solicitud".encode() in n.get(f"/cliente/movimientos/{op['id']}").data


def test_movimientos_busqueda_y_detalle(nav, ctx):
    laura, u = _saldo()
    operaciones.operar(laura, "SOL", "compra", 20000, u)
    n = nav("laura@x.com")
    assert b"Compra de SOL" in n.get("/cliente/movimientos?q=sol").data
    r = n.get("/cliente/movimientos?q=zzz")
    assert "No hay movimientos que coincidan".encode() in r.data
    assert b"Compra de SOL" not in n.get("/cliente/movimientos?ver=depositos").data
    op = db.uno("SELECT id FROM operaciones WHERE tipo = 'compra'")["id"]
    r = n.get(f"/cliente/movimientos/{op}")
    assert r.status_code == 200 and "Órdenes ejecutadas".encode() in r.data and b"Simulador" in r.data
    assert nav("pedro@x.com").get(f"/cliente/movimientos/{op}").status_code == 404
    assert n.get("/cliente/").status_code == 200 and "Actividad reciente".encode() in n.get("/cliente/").data


def test_sesiones_por_dispositivo(app, ctx, nav):
    a = nav("laura@x.com")
    u = usuario("laura@x.com")
    assert db.uno("SELECT COUNT(*) AS n FROM sesiones WHERE usuario_id = ?", (u["id"],))["n"] == 1
    # otro dispositivo: queda registrado y se avisa
    from .conftest import Navegador
    b = Navegador(app)
    b.c.environ_base["HTTP_USER_AGENT"] = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit Safari/604.1"
    assert b.ingresar("laura@x.com").status_code == 302
    assert "Safari en iPhone" in notificaciones.listar(u["id"])[0]["texto"]
    r = a.get("/cuenta/sesiones")
    assert r.status_code == 200 and "Safari en iPhone".encode() in r.data and "Este dispositivo".encode() in r.data
    sid = db.uno("SELECT id FROM sesiones WHERE dispositivo = 'Safari en iPhone'")["id"]
    a.post(f"/cuenta/sesiones/{sid}/cerrar")
    assert b.get("/cliente/").status_code == 302                               # el iPhone quedó afuera
    assert a.get("/cliente/").status_code == 200
    a.post("/salir")
    assert db.uno("SELECT COUNT(*) AS n FROM sesiones WHERE cerrada IS NULL")["n"] == 0
    assert db.uno("SELECT cierre FROM sesiones WHERE id = ?", (sid,))["cierre"] == "usuario"


def test_cerrar_otras_sesiones_y_cambio_de_clave(app, ctx, nav):
    a, b = nav("laura@x.com"), nav("laura@x.com")
    a.post("/cuenta/sesiones/cerrar-otras")
    assert b.get("/cliente/").status_code == 302 and a.get("/cliente/").status_code == 200
    c = nav("laura@x.com")
    r = a.post("/cuenta/clave", {"actual": CLAVE, "nueva": "Otra-Clave-2026", "repetir": "Otra-Clave-2026"})
    assert r.status_code == 302 and c.get("/cliente/").status_code == 302 and a.get("/cliente/").status_code == 200
    assert db.uno("SELECT COUNT(*) AS n FROM sesiones WHERE cierre = 'clave'")["n"] >= 1


def test_privacidad(nav, ctx):
    n = nav("laura@x.com")
    assert b"data-ocultar" not in n.get("/cliente/cartera").data
    n.post("/cuenta/privacidad", {"accion": "saldos", "volver": "/cliente/cartera"})
    assert b"data-ocultar" in n.get("/cliente/cartera").data
    n.post("/cuenta/privacidad", {"accion": "envios"})
    assert transferencias.buscar("laura@x.com") is None
    n.post("/cuenta/privacidad", {"accion": "envios"})
    assert transferencias.buscar("laura@x.com")["id"] == cliente("laura@x.com")["id"]
    r = n.get("/cuenta/mis-datos.json")
    j = r.get_json()
    assert "attachment" in r.headers["Content-Disposition"] and j["cliente"]["documento"] == "CI 1" and j["sesiones"]
    assert "clave_hash" not in r.data.decode() and "totp" not in r.data.decode()
