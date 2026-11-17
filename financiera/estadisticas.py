"""Estadísticas de las operaciones de una persona: resultado de cada venta por costo promedio, comisiones y rendimiento por moneda.

Describen lo que pasó con las órdenes registradas. Si esas órdenes se ejecutaron en el simulador, el resultado es simulado y así se
informa: `simuladas` cuenta las órdenes que no pasaron por un exchange real."""
from datetime import timedelta

from . import db
from .tiempo import ahora_dt, iso

PERIODOS = {"30": ("30 días", 30), "90": ("90 días", 90), "365": ("1 año", 365), "todo": ("Todo", None)}
REALES = ("binance",)


def de_cliente(cliente_id, periodo="todo"):
    dias = PERIODOS.get(periodo, PERIODOS["todo"])[1]
    desde = iso(ahora_dt() - timedelta(days=dias)) if dias else ""
    eventos = []
    for o in db.todos("SELECT * FROM ordenes WHERE cliente_id = ?", (cliente_id,)):
        eventos.append((o["ts"], 0, o["id"], o["activo"], o["lado"], o["cantidad"], o["importe_cent"], o))
    for t in db.todos("SELECT * FROM transferencias WHERE (a_cliente = ? OR de_cliente = ?) AND activo != 'USD'", (cliente_id, cliente_id)):
        eventos.append((t["ts"], 1, t["id"], t["activo"], "entra" if t["a_cliente"] == cliente_id else "sale", t["cantidad"], t["valor_cent"], None))
    pos, ventas, activos = {}, [], {}
    tot = {"ordenes": 0, "compras": 0, "ventas": 0, "volumen": 0, "simuladas": 0, "comisiones": 0}
    for ts, _, _, activo, lado, cant, importe, o in sorted(eventos, key=lambda e: e[:3]):
        e = pos.setdefault(activo, {"cantidad": 0, "costo": 0})
        dentro = ts >= desde
        a = activos.setdefault(activo, {"activo": activo, "compras": 0, "ventas": 0, "volumen": 0, "realizado": 0, "positivas": 0})
        resultado = None
        if lado in ("compra", "entra"):
            e["cantidad"] += cant
            e["costo"] += importe
        elif e["cantidad"] > 0:
            base = round(e["costo"] * min(1.0, cant / e["cantidad"]))
            if lado == "venta":
                resultado = importe - base
            e["costo"] -= base
            e["cantidad"] = max(0, e["cantidad"] - cant)
        if o is None or not dentro:
            continue
        tot["ordenes"] += 1
        tot["volumen"] += importe
        tot["compras" if lado == "compra" else "ventas"] += 1
        a["compras" if lado == "compra" else "ventas"] += 1
        a["volumen"] += importe
        if o["venue"] not in REALES:
            tot["simuladas"] += 1
        if o["comision"]:
            try:
                c = float(o["comision"])
                tot["comisiones"] += round(c * 100) if o["comision_activo"] in ("USD", "USDT", "USDC") else (
                    round(c * float(o["precio"]) * 100) if o["comision_activo"] == activo else 0)
            except (TypeError, ValueError):
                pass
        if resultado is not None:
            ventas.append({"ts": ts, "activo": activo, "resultado": resultado, "importe": importe, "operacion_id": o["operacion_id"]})
            a["realizado"] += resultado
            a["positivas"] += 1 if resultado > 0 else 0
    gestion = db.uno("SELECT COALESCE(SUM(liquidado_cent), 0) AS s FROM operaciones WHERE cliente_id = ? AND tipo = 'comision'"
                     " AND estado = 'liquidada' AND creado >= ?", (cliente_id, desde))["s"]
    positivas = sum(1 for v in ventas if v["resultado"] > 0)
    return {"periodo": periodo, **tot, "gestion": gestion, "cerradas": len(ventas), "positivas": positivas,
            "pct_positivas": positivas / len(ventas) * 100 if ventas else None,
            "acumulado": sum(v["resultado"] for v in ventas),
            "mejor": max(ventas, key=lambda v: v["resultado"]) if ventas else None,
            "peor": min(ventas, key=lambda v: v["resultado"]) if ventas else None,
            "promedio": round(sum(v["resultado"] for v in ventas) / len(ventas)) if ventas else None,
            "activos": sorted((a for a in activos.values() if a["compras"] or a["ventas"]), key=lambda a: -a["volumen"]),
            "ultimas": ventas[::-1][:12], "todo_simulado": tot["ordenes"] > 0 and tot["simuladas"] == tot["ordenes"],
            "algo_simulado": tot["simuladas"] > 0}
