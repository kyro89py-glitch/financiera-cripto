"""v0.20 · Módulo 5: historial con filtros y exportación, comprobantes verificables, saldo pendiente y vista en guaraníes."""
import csv
import io
import re

from financiera import comprobantes, db, guarani, operaciones
from financiera import transferencias as tr

from .conftest import CLAVE, cliente, usuario


def _saldo(monto=500000):
    cli = cliente("laura@x.com")
    opid = operaciones.solicitar_aporte(cli, monto, None, "T-saldo", None)
    operaciones.aprobar(opid, usuario("op@x.com"))
    return cli, opid


def test_filtros_por_moneda_fecha_y_exportacion(nav, ctx):
    cli, _ = _saldo()
    operaciones.operar(cli, "BTC", "compra", 100000, usuario("laura@x.com"))
    operaciones.operar(cli, "ETH", "compra", 50000, usuario("laura@x.com"))
    n = nav("laura@x.com")
    html = n.get("/cliente/movimientos?moneda=BTC").data.decode()
    assert "1 resultado" in html
    assert "0 resultados" in n.get("/cliente/movimientos?hasta=2000-01-01").data.decode()
    assert n.get("/cliente/movimientos?desde=no-es-fecha&moneda=XXX").status_code == 200  # filtros inválidos se ignoran
    r = n.get("/cliente/movimientos.csv?moneda=ETH")
    filas = list(csv.reader(io.StringIO(r.data.decode("utf-8-sig")), delimiter=";"))
    assert filas[1][0] == "codigo" and len(filas) == 3
    assert re.fullmatch(r"OP-\d{6}", filas[2][0]) and re.fullmatch(r"([0-9A-F]{4}-){5}[0-9A-F]{4}", filas[2][8])


def test_comprobante_con_huella_verificable(nav, ctx):
    cli, opid = _saldo()
    n = nav("laura@x.com")
    html = n.get(f"/cliente/movimientos/{opid}/comprobante").data.decode()
    codigo = comprobantes.codigo("op", opid)
    huella = comprobantes.huella("op", db.uno("SELECT * FROM operaciones WHERE id = ?", (opid,)))
    assert codigo in html and huella in html and "Rastro de auditoría" in html
    assert comprobantes.verificar(codigo, huella)[0] == "valido"
    assert comprobantes.verificar(codigo, huella.lower().replace("-", ""))[0] == "valido"
    assert comprobantes.verificar(codigo, "0000-0000-0000-0000-0000-0000")[0] == "no_coincide"
    assert comprobantes.verificar("OP-999999", huella)[0] == "no_existe"
    assert nav("pedro@x.com").get(f"/cliente/movimientos/{opid}/comprobante").status_code == 404  # no es suyo
    eq = nav("cum@x.com")
    r = eq.post("/equipo/verificar-comprobante", {"codigo": codigo, "huella": huella})
    assert "Comprobante válido" in r.data.decode()
    assert db.uno("SELECT 1 FROM bitacora WHERE accion = 'comprobante.verificado'")
    assert n.get("/equipo/verificar-comprobante").status_code == 403


def test_comprobante_de_envio_para_las_dos_partes(nav, ctx):
    cli, _ = _saldo()
    db.ejecutar("UPDATE clientes SET kyc_estado = 'verificado' WHERE id = ?", (cliente("pedro@x.com")["id"],))
    tid = tr.enviar(cli, "pedro@x.com", "USD", 10000, usuario("laura@x.com"), CLAVE)
    assert "EN-%06d" % tid in nav("laura@x.com").get(f"/cliente/envios/{tid}/comprobante").data.decode()
    assert nav("pedro@x.com").get(f"/cliente/envios/{tid}/comprobante").status_code == 200


def test_saldo_pendiente_y_vista_en_guaranies(nav, ctx):
    cli, _ = _saldo(100000)
    operaciones.solicitar_aporte(cli, 25000, None, "T-pend", None)
    guarani.fijar(7400, 7200, usuario("admin@x.com"))
    n = nav("laura@x.com")
    html = n.get("/cliente/cartera").data.decode()
    assert "Pendiente de acreditar" in html and "US$ 250,00" in html and "solo de referencia" in html
    assert n.post("/cuenta/preferencias", {"accion": "moneda", "moneda": "PYG", "volver": "/cliente/cartera"}).status_code == 302
    html = n.get("/cliente/cartera").data.decode()
    assert '<div class="cifra-mayor num">₲ 7.300.000</div>' in html and "= US$ 1.000,00" in html
