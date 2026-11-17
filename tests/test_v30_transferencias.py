"""v0.30 · Centro de transferencias: revisión antes de confirmar, comprobante, contactos frecuentes y flujo externo de demostración."""
from financiera import cartera, db, operaciones

from .conftest import CLAVE, cliente, usuario
from .test_v08 import _saldo, _verificar_pedro


def _cantidad_transferencias():
    return db.uno("SELECT COUNT(*) AS n FROM transferencias")["n"]


def test_revisar_no_mueve_nada_y_confirmar_si(nav, ctx):
    laura, _ = _saldo()
    _verificar_pedro()
    nav("pedro@x.com").post("/cuenta/datos", {"accion": "usuario", "usuario": "pedrito"})
    n = nav("laura@x.com")
    r = n.post("/cliente/enviar", {"accion": "revisar", "destino": "@pedrito", "activo": "USD", "monto": "25", "nota": "Almuerzo", "idem": "k1"})
    h = r.get_data(as_text=True)
    assert r.status_code == 200 and "Revisa y confirma" in h and "Pedro P." in h and "@pedrito" in h and "FC" in h
    assert "US$ 25,00" in h and "«Almuerzo»" in h and "Sin comisión" in h
    assert _cantidad_transferencias() == 0 and cartera.tenencias(laura["id"])["USD"] == 100000      # nada se movió
    # errores de validación se informan en el paso 1, sin pedir contraseña
    r = n.post("/cliente/enviar", {"accion": "revisar", "destino": "@nadie", "activo": "USD", "monto": "25", "idem": "k2"})
    assert "No encontramos" in r.get_data(as_text=True) and _cantidad_transferencias() == 0
    r = n.post("/cliente/enviar", {"accion": "revisar", "destino": "@pedrito", "activo": "USD", "monto": "5000", "idem": "k3"})
    assert "límite diario" in r.get_data(as_text=True) or "saldo" in r.get_data(as_text=True)
    # editar vuelve al formulario con los datos
    r = n.post("/cliente/enviar", {"accion": "editar", "destino": "@pedrito", "activo": "USD", "monto": "25", "nota": "Almuerzo", "idem": "k1"})
    assert 'value="@pedrito"' in r.get_data(as_text=True) and 'value="Almuerzo"' in r.get_data(as_text=True)
    # confirmar con contraseña incorrecta no envía
    r = n.post("/cliente/enviar", {"accion": "confirmar", "destino": "@pedrito", "activo": "USD", "monto": "25", "clave": "mala", "idem": "k1"})
    assert "contraseña no es correcta" in r.get_data(as_text=True) and _cantidad_transferencias() == 0
    r = n.post("/cliente/enviar", {"accion": "confirmar", "destino": "@pedrito", "activo": "USD", "monto": "25", "nota": "Almuerzo", "clave": CLAVE, "idem": "k1"})
    assert r.status_code == 302 and "/cliente/envios/" in r.headers["Location"]
    assert _cantidad_transferencias() == 1 and cartera.tenencias(cliente("pedro@x.com")["id"])["USD"] == 2500
    # el mismo formulario reenviado no duplica el envío
    n.post("/cliente/enviar", {"accion": "confirmar", "destino": "@pedrito", "activo": "USD", "monto": "25", "clave": CLAVE, "idem": "k1"})
    assert _cantidad_transferencias() == 1
    det = n.get(r.headers["Location"]).get_data(as_text=True)
    assert "Completada" in det and "EN-000001" in det and "Concepto" in det


def test_centro_de_transferencias(nav, ctx):
    laura, u = _saldo()
    _verificar_pedro()
    from financiera import transferencias as tr
    nav("pedro@x.com").post("/cuenta/datos", {"accion": "usuario", "usuario": "pedrito"})
    tr.enviar(laura, "pedro@x.com", "USD", 3000, u, CLAVE, nota="Regalo")
    tr.enviar(cliente("pedro@x.com"), "laura@x.com", "USD", 1000, usuario("pedro@x.com"), CLAVE)
    n = nav("laura@x.com")
    h = n.get("/cliente/transferencias").get_data(as_text=True)
    assert "Envías seguido a" in h and "@pedrito" in h and "/cliente/enviar?a=pedrito" in h
    assert "US$ 30,00" in h and "Recibiste de" in h and "Enviaste a" in h
    from financiera import cuenta
    cod = cuenta.codigo(usuario("pedro@x.com")["id"])
    assert f'value="{cod}"' in n.get(f"/cliente/enviar?a={cod}").get_data(as_text=True)
    assert tr.buscar("@" + cod, laura["id"])["id"] == cliente("pedro@x.com")["id"]
    assert "Recibiste de" not in n.get("/cliente/transferencias?ver=enviadas").get_data(as_text=True)
    assert "Enviaste a" not in n.get("/cliente/transferencias?ver=recibidas").get_data(as_text=True)
    assert nav("cum@x.com").get("/cliente/transferencias").status_code in (302, 403)


def test_transferencia_externa_es_solo_demostracion(nav, ctx):
    laura, _ = _saldo()
    antes_libro = db.uno("SELECT COUNT(*) AS n FROM libro")["n"]
    antes_ops = db.uno("SELECT COUNT(*) AS n FROM operaciones")["n"]
    n = nav("laura@x.com")
    h = n.get("/cliente/transferencias/externa").get_data(as_text=True)
    assert "Modo demostración" in h and "no se envía dinero" in h
    datos = {"tipo": "banco", "titular": "Ana Pérez", "entidad": "Banco X", "cuenta": "123-456", "monto": "150", "concepto": "Alquiler"}
    r = n.post("/cliente/transferencias/externa", datos | {"accion": "revisar"})
    assert "US$ 150,00" in r.get_data(as_text=True) and "Terminar la demostración" in r.get_data(as_text=True)
    r = n.post("/cliente/transferencias/externa", datos | {"accion": "confirmar"})
    h = r.get_data(as_text=True)
    assert "Demostración terminada" in h and "No enviada" in h and "no quedó ningún movimiento" in h
    assert db.uno("SELECT COUNT(*) AS n FROM libro")["n"] == antes_libro and db.uno("SELECT COUNT(*) AS n FROM operaciones")["n"] == antes_ops
    assert cartera.tenencias(laura["id"])["USD"] == 100000
    r = n.post("/cliente/transferencias/externa", datos | {"monto": "0,5", "accion": "revisar"})
    assert "al menos US$ 1" in r.get_data(as_text=True)
    r = n.post("/cliente/transferencias/externa", datos | {"titular": "", "accion": "revisar"})
    assert "Completa: titular" in r.get_data(as_text=True)
