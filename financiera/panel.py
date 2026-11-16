"""Inteligencia del panel de inicio: rendimiento por período contra referencias, riesgo, mejores y peores activos,
alertas importantes, sugerencias informativas y resumen del mercado en palabras.

Todo sale de datos propios (libro, precios e historial). Las sugerencias explican el porqué y nunca dicen qué comprar
o vender: son información para que la persona decida.
"""
from datetime import timedelta
from decimal import Decimal

from flask import current_app

from . import cartera, db, precios
from .dinero import fmt_usd
from .tiempo import ahora_dt, iso, leer, minutos_desde

PERIODOS = (("24 horas", 1), ("7 días", 7), ("30 días", 30), ("1 año", 365))
NIVEL_PERFIL = {"conservador": "bajo", "moderado": "medio", "arriesgado": "alto"}


def _flujos(cliente_id, desde):
    out = {}
    for f in db.todos("SELECT tipo, liquidado_cent, resuelto_ts FROM operaciones WHERE cliente_id = ? AND estado = 'liquidada'"
                      " AND tipo IN ('aporte', 'retiro') AND resuelto_ts > ?", (cliente_id, desde)):
        out[f["resuelto_ts"]] = out.get(f["resuelto_ts"], 0) + (f["liquidado_cent"] if f["tipo"] == "aporte" else -f["liquidado_cent"])
    for t in db.todos("SELECT ts, valor_cent, a_cliente FROM transferencias WHERE (a_cliente = ? OR de_cliente = ?) AND ts > ?",
                      (cliente_id, cliente_id, desde)):
        out[t["ts"]] = out.get(t["ts"], 0) + (t["valor_cent"] if t["a_cliente"] == cliente_id else -t["valor_cent"])
    return dict(sorted(out.items()))


def twr(cliente_id, desde, total_actual):
    """Rentabilidad ponderada por tiempo desde `desde` (sin que la distorsionen depósitos ni retiros), en %."""
    previo, _ = cartera.valor_en(cliente_id, desde)
    factor = Decimal(1)
    for ts, neto in _flujos(cliente_id, desde).items():
        despues, _ = cartera.valor_en(cliente_id, ts)
        if previo > 0:
            factor *= Decimal(max(despues - neto, 0)) / Decimal(previo)
        previo = despues
    if previo <= 0:
        return None
    factor *= Decimal(total_actual) / Decimal(previo)
    return float((factor - 1) * 100)


def _cambio(activo, desde, vig):
    p0 = cartera.precio_en(activo, desde)
    if not p0 or activo not in vig:
        return None
    return float((vig[activo]["precio"] / p0 - 1) * 100)


def rendimientos(cliente_id, total, mercado):
    """Por período: patrimonio al inicio, cambio total, rentabilidad propia y referencias (BTC, ETH, índice Top 10)."""
    primero = db.uno("SELECT MIN(ts) AS ts FROM libro WHERE cliente_id = ?", (cliente_id,))["ts"]
    if not primero:
        return []
    vig = precios.vigentes()
    top10 = [m["codigo"] for m in sorted((m for m in mercado if not m["estable"] and m["cap"]), key=lambda m: -m["cap"])[:10]]
    out = []
    for etiqueta, dias in PERIODOS:
        desde = iso(ahora_dt() - timedelta(days=dias))
        parcial = desde < primero
        if parcial:
            desde = primero
        inicio, _ = cartera.valor_en(cliente_id, desde)
        cambios = [c for c in (_cambio(a, desde, vig) for a in top10) if c is not None]
        out.append({"etiqueta": etiqueta, "dias": dias, "parcial": parcial, "inicio": inicio, "cambio": total - inicio,
                    "twr": twr(cliente_id, desde, total), "btc": _cambio("BTC", desde, vig), "eth": _cambio("ETH", desde, vig),
                    "top10": sum(cambios) / len(cambios) if cambios else None})
    return out


def riesgo(cliente, filas, ind):
    estables = {a["codigo"] for a in precios.activos() if a["categoria"] == "estable"} | {"USD"}
    pesos = [f["peso"] for f in filas if f["valor"] > 0]
    hhi = sum(p * p for p in pesos)
    vol = ind.get("volatilidad")
    nivel = None if vol is None else ("bajo" if vol < 25 else "medio" if vol < 60 else "alto")
    esperado = NIVEL_PERFIL.get(cliente["perfil_riesgo"], "medio")
    orden = ["bajo", "medio", "alto"]
    if nivel is None:
        texto = "Todavía no hay historia suficiente para medir la volatilidad de tu cartera."
    elif orden.index(nivel) > orden.index(esperado):
        texto = (f"La volatilidad de tu cartera es de nivel {nivel}, más alta que lo esperable para tu perfil "
                 f"{cliente['perfil_riesgo']}.")
    else:
        texto = f"La volatilidad de tu cartera es de nivel {nivel}, acorde con tu perfil {cliente['perfil_riesgo']}."
    return {"nivel": nivel, "volatilidad": vol, "efectivos": (1 / hhi) if hhi else 0, "estables": sum(f["peso"] for f in filas if f["activo"] in estables) * 100,
            "mayor": ind.get("mayor"), "texto": texto, "perfil": cliente["perfil_riesgo"], "esperado": esperado}


def ranking(filas, costos):
    """Mejores y peores de la cartera por resultado sobre el costo promedio."""
    items = []
    for f in filas:
        k = costos.get(f["activo"])
        if f["activo"] == "USD" or not k or not k["costo"] or k["cantidad"] <= 0:
            continue
        items.append({"activo": f["activo"], "nombre": f["nombre"], "color": f["color"], "valor": f["valor"],
                      "resultado": f["valor"] - k["costo"], "pct": (f["valor"] / k["costo"] - 1) * 100, "cambio": f["cambio"]})
    items.sort(key=lambda x: -x["pct"])
    return {"mejores": [x for x in items if x["pct"] >= 0][:3], "peores": [x for x in reversed(items) if x["pct"] < 0][:3]}


def alertas(cliente, usuario, filas, total, abiertas, ind):
    """Lo que conviene mirar hoy: (nivel, texto, enlace). Nivel: 'bad', 'warn' o 'info'."""
    out = []
    vig = precios.vigentes()
    if vig and min(minutos_desde(p["ts"]) for p in vig.values()) > current_app.config["PRECIO_MAX_MINUTOS"]:
        out.append(("warn", "Los precios no se actualizan hace un rato: las operaciones esperan a que vuelvan.", "/mercado"))
    if not usuario["totp_secreto"]:
        out.append(("warn", "Tu cuenta no tiene verificación en dos pasos.", "/cuenta/seguridad"))
    for o in db.todos("SELECT * FROM programadas WHERE cliente_id = ? AND estado = 'abierta'", (cliente["id"],)):
        p = vig.get(o["activo"])
        if p:
            dist = abs(float(p["precio"] / Decimal(o["precio"]) - 1)) * 100
            if dist <= 2:
                out.append(("info", f"Tu orden de {o['activo']} a {Decimal(o['precio']):,.2f} está a {dist:.1f} % de activarse."
                            .replace(",", "X").replace(".", ",").replace("X", "."), f"/trading/{o['activo']}"))
    retiros = [o for o in abiertas if o["tipo"] == "retiro"]
    if retiros:
        out.append(("info", f"Tienes {len(retiros)} retiro{'s' if len(retiros) > 1 else ''} en revisión por "
                    f"{fmt_usd(sum(o['monto_cent'] for o in retiros))}.", "/cliente/movimientos?ver=retiros"))
    if ind.get("mayor") and ind["mayor"][0] != "USD" and ind["mayor"][1] > 50:
        out.append(("warn", f"El {ind['mayor'][1]:.0f} % de tu cartera está en {ind['mayor'][0]}.", "/cliente/cartera"))
    nuevas_seg = db.uno("SELECT COUNT(*) AS n FROM notificaciones WHERE usuario_id = ? AND categoria = 'seguridad' AND leida = 0",
                        (usuario["id"],))["n"]
    if nuevas_seg:
        out.append(("bad", f"Tienes {nuevas_seg} aviso{'s' if nuevas_seg > 1 else ''} de seguridad sin leer.", "/cuenta/avisos?cat=seguridad"))
    nuevas_px = db.uno("SELECT COUNT(*) AS n FROM notificaciones WHERE usuario_id = ? AND categoria = 'precios' AND leida = 0",
                       (usuario["id"],))["n"]
    if nuevas_px:
        out.append(("info", f"{nuevas_px} aviso{'s' if nuevas_px > 1 else ''} de precios y órdenes sin leer.", "/cuenta/avisos?cat=precios"))
    return out


def sugerencias(cliente, usuario, filas, total, desvio_max, riesgo_d, modelo):
    """Sugerencias informativas con su porqué. No son asesoramiento ni órdenes de compra o venta."""
    out = []
    if not usuario["totp_secreto"]:
        out.append({"titulo": "Protege tu acceso", "texto": "Con la verificación en dos pasos, aunque alguien sepa tu contraseña "
                    "no puede entrar ni enviar dinero.", "enlace": "/cuenta/seguridad", "accion": "Activar"})
    usd = next((f for f in filas if f["activo"] == "USD"), None)
    if usd and total >= 10000 and usd["peso"] > 0.2:
        out.append({"titulo": f"{usd['peso'] * 100:.0f} % en dólares sin invertir",
                    "texto": "El saldo en dólares no varía con el mercado ni genera rendimiento. Puede ser tu reserva o "
                             "puedes invertirlo según tu perfil: la decisión es tuya.", "enlace": "/cliente/cartera", "accion": "Ver billetera"})
    if riesgo_d["mayor"] and riesgo_d["mayor"][0] != "USD" and riesgo_d["mayor"][1] > 50:
        out.append({"titulo": f"Concentración en {riesgo_d['mayor'][0]}",
                    "texto": "Cuando una sola moneda pesa más de la mitad, tu patrimonio depende casi por completo de ella. "
                             "Repartir entre varias reduce ese riesgo, a cambio de no aprovechar tanto sus subas.",
                    "enlace": "/cliente/cartera", "accion": "Ver billetera"})
    if desvio_max >= 5 and modelo:
        out.append({"titulo": f"Tu cartera se alejó de {modelo['nombre']}",
                    "texto": f"Los precios movieron los pesos {desvio_max:.1f} puntos respecto de la composición que elegiste. "
                             "Tu próximo depósito se invierte con la composición objetivo.", "enlace": "/cliente/cartera#composicion",
                    "accion": "Ver composición"})
    protegidas = {o["activo"] for o in db.todos("SELECT activo FROM programadas WHERE cliente_id = ? AND estado = 'abierta' AND lado = 'venta'",
                                                (cliente["id"],))}
    sin = [f for f in filas if f["activo"] != "USD" and f["peso"] > 0.15 and f["activo"] not in protegidas
           and f["activo"] not in ("USDT", "USDC")]
    if sin:
        f = sin[0]
        out.append({"titulo": f"{f['activo']} sin orden de salida", "texto": f"{f['activo']} pesa {f['peso'] * 100:.0f} % de tu cartera "
                    "y no tiene un corte de pérdida programado. Es opcional: limita cuánto podrías perder si cae.",
                    "enlace": f"/trading/{f['activo']}", "accion": "Ir a Trading"})
    if riesgo_d["nivel"] and riesgo_d["nivel"] != riesgo_d["esperado"] and ["bajo", "medio", "alto"].index(riesgo_d["nivel"]) > \
            ["bajo", "medio", "alto"].index(riesgo_d["esperado"]):
        out.append({"titulo": "Más volatilidad que tu perfil", "texto": riesgo_d["texto"] + " Revisa si sigue reflejando lo que "
                    "estás dispuesto a soportar.", "enlace": "/cliente/perfil", "accion": "Ver perfil"})
    if not db.uno("SELECT 1 FROM alertas_precio WHERE usuario_id = ?", (usuario["id"],)):
        out.append({"titulo": "Recibe avisos de precio", "texto": "Una alerta te avisa cuando una moneda llega al precio que te "
                    "interesa, sin tener que mirar la pantalla.", "enlace": "/mercado", "accion": "Elegir moneda"})
    return out[:4]


def resumen_mercado(mercado):
    """El mercado en cuatro frases, con números calculados (no inventados)."""
    con = [m for m in mercado if m["cambio"] is not None and m["habilitado"]]
    if not con:
        return []
    cap = sum(m["cap"] or 0 for m in con)
    pond = sum((m["cap"] or 0) * float(m["cambio"]) for m in con) / cap if cap else None
    movibles = [m for m in con if not m["estable"]]
    suben = sum(1 for m in movibles if m["cambio"] > 0)
    mejor = max(movibles, key=lambda m: m["cambio"]) if movibles else None
    peor = min(movibles, key=lambda m: m["cambio"]) if movibles else None
    btc = next((m for m in con if m["codigo"] == "BTC"), None)
    frases = []
    if pond is not None:
        frases.append(("El mercado " + ("sube" if pond >= 0 else "baja") + f" {abs(pond):.2f} % en 24 horas", "ponderado por capitalización"))
    frases.append((f"{suben} de {len(movibles)} monedas suben", "sin contar las estables"))
    if mejor and peor and mejor["cambio"] != peor["cambio"]:
        frases.append((f"La mayor suba es {mejor['codigo']} ({float(mejor['cambio']):+.1f} %) y la mayor baja {peor['codigo']} "
                       f"({float(peor['cambio']):+.1f} %)", ""))
    if btc and cap:
        frases.append((f"Bitcoin representa el {btc['cap'] / cap * 100:.1f} % del valor del mercado", "dominancia"))
    return [(t.replace(".", ","), n) for t, n in frases]


def leer_ts(ts):
    return leer(ts)
