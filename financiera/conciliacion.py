"""Conciliación de custodia: compara lo que dice el libro con lo que realmente hay en el exchange o custodio y en el banco."""
import json
import re
from decimal import Decimal, InvalidOperation

from . import auditoria, db
from .dinero import CRIPTO, fmt_unidades
from .tiempo import ahora, minutos_desde


class ErrorConciliacion(Exception):
    pass


def saldos_libro():
    filas = db.todos("SELECT activo, SUM(cantidad) AS u FROM libro GROUP BY activo")
    return {f["activo"]: f["u"] or 0 for f in filas}


def activos_a_conciliar():
    return ["USD"] + [a["codigo"] for a in db.todos("SELECT codigo FROM activos ORDER BY orden")]


def leer_cantidad(texto, activo):
    s = str(texto or "").strip().replace(" ", "")
    if not s:
        raise ErrorConciliacion(f"Completa el saldo real de {activo}.")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s and activo == "USD" and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    decimales = 2 if activo == "USD" else 8
    if not re.fullmatch(r"\d{1,15}(\.\d{1,%d})?" % decimales, s):
        raise ErrorConciliacion(f"El saldo de {activo} no es válido.")
    try:
        return int(Decimal(s) * (100 if activo == "USD" else CRIPTO))
    except InvalidOperation:
        raise ErrorConciliacion(f"El saldo de {activo} no es válido.") from None


def registrar(reales, nota, usuario, ts=None):
    """reales: {activo: texto escrito por la persona}. Guarda una conciliación inalterable y devuelve su id."""
    libro = saldos_libro()
    detalle = []
    for a in activos_a_conciliar():
        real = leer_cantidad(reales.get(a), a)
        esperado = libro.get(a, 0)
        detalle.append({"activo": a, "libro": esperado, "real": real, "diferencia": real - esperado})
    diferencias = sum(1 for d in detalle if d["diferencia"] != 0)
    ts = ts or ahora()
    with db.transaccion() as c:
        cur = c.execute("INSERT INTO conciliaciones (ts, usuario_id, nota, detalle, diferencias) VALUES (?, ?, ?, ?, ?)",
                        (ts, usuario["id"], (nota or "").strip()[:300] or None, json.dumps(detalle), diferencias))
        cid = cur.lastrowid
        if diferencias:
            texto = "Registró una conciliación con diferencias en " + ", ".join(
                f"{d['activo']} ({'+' if d['diferencia'] > 0 else ''}{fmt_unidades(d['diferencia'], d['activo'])})"
                for d in detalle if d["diferencia"]) + "."
        else:
            texto = "Registró una conciliación sin diferencias entre el libro y la custodia."
        auditoria.registrar("conciliacion.registrada", f"conciliacion:{cid}", {"texto": texto, "diferencias": diferencias},
                            usuario=usuario, ts=ts)
    return cid


def historial(limite=20):
    out = []
    for f in db.todos("SELECT k.*, u.nombre FROM conciliaciones k JOIN usuarios u ON u.id = k.usuario_id ORDER BY k.id DESC LIMIT ?",
                      (limite,)):
        d = dict(f)
        d["detalle"] = json.loads(f["detalle"])
        out.append(d)
    return out


def estado():
    """('ok' | 'diferencias' | 'vencida' | 'nunca', ultima_conciliacion)."""
    ult = historial(1)
    if not ult:
        return "nunca", None
    u = ult[0]
    if u["diferencias"]:
        return "diferencias", u
    if minutos_desde(u["ts"]) > 26 * 60:
        return "vencida", u
    return "ok", u
