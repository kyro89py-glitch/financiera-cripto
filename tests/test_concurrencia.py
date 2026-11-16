"""Pedidos simultáneos sobre el mismo saldo, con hilos reales contra la base en archivo.

Reproduce el hallazgo S-01 de la auditoría: antes, seis compras simultáneas con fondos para tres mandaban seis órdenes
al ejecutor y tres quedaban trabadas. Ahora el saldo se vuelve a controlar dentro de la transacción que registra cada
compra, así que nunca sale al exchange más de lo que el cliente tiene."""
import threading

from financiera import auditoria, cartera, db, operaciones, transferencias

from .conftest import CLAVE, cliente, legajo_completo, usuario


def _simultaneo(app, n, fn):
    barrera, res, cerrojo = threading.Barrier(n), [], threading.Lock()

    def hilo(k):
        with app.app_context():
            barrera.wait()
            try:
                r = ("ok", fn(k))
            except Exception as e:  # noqa: BLE001 — se clasifica abajo
                r = ("error", f"{type(e).__name__}: {e}")
            with cerrojo:
                res.append(r)

    hilos = [threading.Thread(target=hilo, args=(k,)) for k in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return res


def _fondear(monto):
    laura = cliente("laura@x.com")
    operaciones.aprobar(operaciones.solicitar_aporte(laura, monto, "saldo", "T", None), usuario("op@x.com"))
    return laura["id"], usuario("laura@x.com")


def _sin_negativos():
    return db.uno("SELECT COUNT(*) AS n FROM (SELECT cliente_id, activo, SUM(cantidad) AS s FROM libro"
                  " GROUP BY cliente_id, activo HAVING s < 0)")["n"] == 0


def test_compras_simultaneas_no_mandan_mas_de_lo_que_hay(app, ctx):
    cid, u = _fondear(100000)                                                   # US$ 1.000
    res = _simultaneo(app, 6, lambda k: operaciones.operar(
        db.uno("SELECT * FROM clientes WHERE id = ?", (cid,)), "BTC", "compra", 30000, u))   # 6 × US$ 300
    ok = [r for r in res if r[0] == "ok"]
    assert 1 <= len(ok) <= 3
    assert all("saldo" in r[1].lower() or "ejecutando" in r[1].lower() for r in res if r[0] == "error"), res
    enviadas = db.uno("SELECT COALESCE(SUM(importe_pedido_cent), 0) AS s FROM ejecuciones WHERE lado = 'compra'")["s"]
    assert enviadas <= 100000                                                   # nunca más de lo que había
    assert not db.uno("SELECT 1 FROM operaciones WHERE estado = 'ejecutando'")  # nada quedó trabado
    assert cartera.tenencias(cid)["USD"] == 100000 - 30000 * len(ok)
    assert _sin_negativos() and auditoria.verificar()["ok"]


def test_envios_ventas_y_aprobaciones_simultaneas(app, ctx):
    cid, u = _fondear(100000)
    pedro = cliente("pedro@x.com")
    legajo_completo(pedro["id"])
    from financiera import cuentas
    cuentas.marcar_kyc(pedro["id"], "verificado", "", usuario("cum@x.com"))
    res = _simultaneo(app, 5, lambda k: transferencias.enviar(
        db.uno("SELECT * FROM clientes WHERE id = ?", (cid,)), "pedro@x.com", "USD", 30000, u, CLAVE))
    assert sum(r[0] == "ok" for r in res) == 3 and cartera.tenencias(cid)["USD"] == 10000
    operaciones.operar(db.uno("SELECT * FROM clientes WHERE id = ?", (cid,)), "BTC", "compra", 5000, u)
    res = _simultaneo(app, 6, lambda k: operaciones.operar(
        db.uno("SELECT * FROM clientes WHERE id = ?", (cid,)), "BTC", "venta", 0, u, todo=True))
    assert sum(r[0] == "ok" for r in res) == 1 and "BTC" not in cartera.tenencias(cid)
    op = operaciones.solicitar_retiro(db.uno("SELECT * FROM clientes WHERE id = ?", (cid,)), 2000, u)
    res = _simultaneo(app, 2, lambda k: operaciones.aprobar(op, usuario(("op@x.com", "admin@x.com")[k])))
    assert sum(r[0] == "ok" for r in res) == 1
    assert db.uno("SELECT COUNT(*) AS n FROM libro WHERE operacion_id = ? AND concepto = 'pago_retiro'", (op,))["n"] == 1
    assert _sin_negativos() and auditoria.verificar()["ok"]
