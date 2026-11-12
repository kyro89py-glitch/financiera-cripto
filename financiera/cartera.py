"""Tenencias, valuación y ejecución de compras y ventas sobre el libro contable."""
from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_CEILING, Decimal

from . import db, precios as precios_mod
from .dinero import unidades_por, valor_cent
from .tiempo import ahora_dt, iso

COLOR_USD = "#94A3B8"


class ErrorCartera(Exception):
    pass


def info_activos():
    return {a["codigo"]: a for a in db.todos("SELECT * FROM activos ORDER BY orden")}


def tenencias(cliente_id):
    filas = db.todos("SELECT activo, SUM(cantidad) AS u FROM libro WHERE cliente_id = ? GROUP BY activo", (cliente_id,))
    return {f["activo"]: f["u"] for f in filas if f["u"]}


def posiciones(cliente_id, precios=None, ten=None):
    """Devuelve (filas, total_cent). Cada fila: activo, nombre, color, unidades, valor, peso, precio, cambio."""
    precios = precios if precios is not None else precios_mod.vigentes()
    ten = ten if ten is not None else tenencias(cliente_id)
    info = info_activos()
    filas, total = [], 0
    for a, u in ten.items():
        if not u:
            continue
        if a == "USD":
            filas.append({"activo": "USD", "nombre": "Saldo en dólares", "color": COLOR_USD, "unidades": u,
                          "valor": u, "precio": None, "cambio": None})
            total += u
            continue
        p = precios.get(a)
        v = valor_cent(a, u, p["precio"]) if p else 0
        filas.append({"activo": a, "nombre": info[a]["nombre"] if a in info else a,
                      "color": info[a]["color"] if a in info else COLOR_USD, "unidades": u, "valor": v,
                      "precio": p["precio"] if p else None, "cambio": p.get("cambio") if p else None})
        total += v
    filas.sort(key=lambda f: -f["valor"])
    for f in filas:
        f["peso"] = (f["valor"] / total) if total else 0
    return filas, total


def aportado_neto(cliente_id):
    f = db.uno("SELECT COALESCE(SUM(cantidad), 0) AS s FROM libro WHERE cliente_id = ? AND activo = 'USD'"
               " AND concepto IN ('deposito', 'pago_retiro')", (cliente_id,))
    return f["s"]


def serie_tenencias(ten, dias=7, puntos=29):
    """Valor de las tenencias actuales a lo largo de los últimos días, con los precios de cada momento."""
    fin = ahora_dt()
    ini = fin - timedelta(days=dias)
    cripto = [a for a, u in ten.items() if a != "USD" and u]
    hist = precios_mod.historial(cripto, iso(ini))
    vig = precios_mod.vigentes()
    ptr = defaultdict(int)
    out = []
    for k in range(puntos):
        t = iso(ini + (fin - ini) * k / (puntos - 1))
        total = ten.get("USD", 0)
        for a in cripto:
            h = hist.get(a) or []
            while ptr[a] + 1 < len(h) and h[ptr[a] + 1][0] <= t:
                ptr[a] += 1
            p = h[ptr[a]][1] if h else (vig[a]["precio"] if a in vig else None)
            if p is not None:
                total += valor_cent(a, ten[a], p)
        out.append((t, total))
    return out


def grafico(serie, ancho=320, alto=120):
    if len(serie) < 2:
        return None
    vals = [v for _, v in serie]
    mn, mx = min(vals), max(vals)
    rango = (mx - mn) or 1
    pts = " ".join(f"{i / (len(vals) - 1) * ancho:.1f},{alto - 8 - (v - mn) / rango * (alto - 20):.1f}"
                   for i, v in enumerate(vals))
    return {"puntos": pts, "area": f"0,{alto} {pts} {ancho},{alto}", "ancho": ancho, "alto": alto,
            "min": mn, "max": mx, "sube": vals[-1] >= vals[0], "inicio": vals[0], "fin": vals[-1]}


def pesos_modelo(codigo):
    return [(f["activo"], f["peso_pb"]) for f in
            db.todos("SELECT activo, peso_pb FROM modelo_pesos WHERE modelo = ? ORDER BY peso_pb DESC, activo", (codigo,))]


def modelos():
    out = []
    for m in db.todos("SELECT * FROM modelos WHERE activo = 1 ORDER BY orden"):
        d = dict(m)
        d["pesos"] = pesos_modelo(m["codigo"])
        out.append(d)
    return out


def _asiento(c, cliente_id, activo, cantidad, concepto, operacion_id, ts):
    c.execute("INSERT INTO libro (cliente_id, activo, cantidad, concepto, operacion_id, ts) VALUES (?, ?, ?, ?, ?, ?)",
              (cliente_id, activo, cantidad, concepto, operacion_id, ts))


def _orden(c, op, activo, lado, cantidad, precio, importe, ts):
    c.execute("INSERT INTO ordenes (operacion_id, cliente_id, activo, lado, cantidad, precio, importe_cent, ts)"
              " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (op["id"], op["cliente_id"], activo, lado, cantidad, str(precio), importe, ts))


def ejecutar_aporte(c, op, pesos, precios, ts):
    """Acredita el depósito y compra según los pesos del modelo. Lo que no alcanza a comprar queda en dólares."""
    if sum(pb for _, pb in pesos) != 10000:
        raise ErrorCartera("La cartera modelo está mal configurada: los pesos no suman 100 %.")
    monto, cid = op["monto_cent"], op["cliente_id"]
    _asiento(c, cid, "USD", monto, "deposito", op["id"], ts)
    restante = monto
    for i, (activo, pb) in enumerate(pesos):
        usd = restante if i == len(pesos) - 1 else monto * pb // 10000
        restante -= usd
        p = precios.get(activo)
        if not p:
            raise ErrorCartera(f"No hay precio para {activo}.")
        unidades = unidades_por(usd, p["precio"])
        if unidades <= 0:
            continue
        _asiento(c, cid, "USD", -usd, "compra", op["id"], ts)
        _asiento(c, cid, activo, unidades, "compra", op["id"], ts)
        _orden(c, op, activo, "compra", unidades, p["precio"], usd, ts)
    return monto


def ejecutar_retiro(c, op, precios, ts):
    """Usa primero el saldo en dólares y vende el resto en proporción a cada tenencia. Devuelve lo pagado."""
    cid, monto = op["cliente_id"], op["monto_cent"]
    ten = tenencias(cid)
    _, total = posiciones(cid, precios, ten)
    if monto > total:
        raise ErrorCartera("El retiro supera el valor actual de la cartera.")
    caja = ten.get("USD", 0)
    if caja < monto:
        resto_cripto = total - caja
        fraccion = Decimal(monto - caja) / Decimal(resto_cripto)
        for activo, u in sorted(ten.items()):
            if activo == "USD" or u <= 0:
                continue
            p = precios.get(activo)
            if not p:
                raise ErrorCartera(f"No hay precio para {activo}.")
            vender = min(u, int((Decimal(u) * fraccion).to_integral_value(ROUND_CEILING)))
            if vender <= 0:
                continue
            ingreso = valor_cent(activo, vender, p["precio"])
            _asiento(c, cid, activo, -vender, "venta", op["id"], ts)
            _asiento(c, cid, "USD", ingreso, "venta", op["id"], ts)
            _orden(c, op, activo, "venta", vender, p["precio"], ingreso, ts)
            caja += ingreso
    pago = min(monto, caja)
    _asiento(c, cid, "USD", -pago, "pago_retiro", op["id"], ts)
    return pago


def resumen_casa(precios=None):
    """Valor gestionado por activo, por cliente y por cartera modelo."""
    precios = precios if precios is not None else precios_mod.vigentes()
    info = info_activos()
    por_cliente = defaultdict(int)
    por_activo = defaultdict(int)
    for f in db.todos("SELECT cliente_id, activo, SUM(cantidad) AS u FROM libro GROUP BY cliente_id, activo"):
        if not f["u"]:
            continue
        if f["activo"] == "USD":
            v = f["u"]
        else:
            p = precios.get(f["activo"])
            v = valor_cent(f["activo"], f["u"], p["precio"]) if p else 0
        por_cliente[f["cliente_id"]] += v
        por_activo[f["activo"]] += v
    total = sum(por_activo.values())
    activos_l = [{"activo": a, "nombre": info[a]["nombre"] if a in info else "Saldo en dólares",
                  "color": info[a]["color"] if a in info else COLOR_USD, "valor": v,
                  "peso": v / total if total else 0} for a, v in por_activo.items() if v]
    activos_l.sort(key=lambda x: -x["valor"])
    clientes = {c["id"]: c for c in db.todos("SELECT id, nombre, modelo FROM clientes")}
    por_modelo = defaultdict(int)
    for cid, v in por_cliente.items():
        por_modelo[clientes[cid]["modelo"]] += v
    return {"total": total, "activos": activos_l, "por_cliente": dict(por_cliente), "por_modelo": dict(por_modelo)}
