"""Comprobantes de movimientos: identificador único, huella verificable y rastro de auditoría.

Cada operación se identifica como OP-000123 y cada envío como EN-000045. La huella es un HMAC-SHA256 de los datos que
importan (quién, qué, cuánto, cuándo y estado) con una clave del servidor: si alguien altera un comprobante impreso o
en PDF, la huella deja de coincidir, y el equipo lo comprueba en Cumplimiento › Verificar comprobante.
El rastro de auditoría son los registros de la bitácora encadenada (cada uno con su hash) que tocan ese movimiento.
"""
import hashlib
import hmac
import json
import re

from flask import current_app

from . import db

PREFIJOS = {"op": "OP", "envio": "EN"}


def codigo(clase, ident):
    return f"{PREFIJOS[clase]}-{int(ident):06d}"


def leer_codigo(texto):
    m = re.fullmatch(r"\s*(OP|EN)-?0*(\d{1,9})\s*", (texto or "").upper())
    if not m:
        return None
    return ("op" if m.group(1) == "OP" else "envio"), int(m.group(2))


def _clave():
    return hashlib.sha256(("comprobante|" + current_app.config["SECRET_KEY"]).encode()).digest()


def _datos(clase, fila):
    if clase == "op":
        asientos = db.todos("SELECT id, activo, cantidad FROM libro WHERE operacion_id = ? ORDER BY id", (fila["id"],))
        return {"codigo": codigo("op", fila["id"]), "cliente": fila["cliente_id"], "tipo": fila["tipo"], "estado": fila["estado"],
                "activo": fila["activo"], "monto": fila["monto_cent"], "liquidado": fila["liquidado_cent"], "creado": fila["creado"],
                "resuelto": fila["resuelto_ts"], "asientos": [[a["id"], a["activo"], a["cantidad"]] for a in asientos]}
    return {"codigo": codigo("envio", fila["id"]), "de": fila["de_cliente"], "a": fila["a_cliente"], "activo": fila["activo"],
            "cantidad": fila["cantidad"], "valor": fila["valor_cent"], "ts": fila["ts"]}


def huella(clase, fila):
    texto = json.dumps(_datos(clase, fila), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    h = hmac.new(_clave(), texto.encode(), hashlib.sha256).hexdigest()[:24].upper()
    return "-".join(h[i:i + 4] for i in range(0, 24, 4))


def fila(clase, ident):
    if clase == "op":
        return db.uno("SELECT * FROM operaciones WHERE id = ?", (ident,))
    return db.uno("SELECT t.*, d.nombre AS de_nombre, a.nombre AS a_nombre FROM transferencias t JOIN clientes d ON d.id = t.de_cliente"
                  " JOIN clientes a ON a.id = t.a_cliente WHERE t.id = ?", (ident,))


def rastro(clase, ident):
    objeto = f"operacion:{ident}" if clase == "op" else f"transferencia:{ident}"
    return db.todos("SELECT id, ts, accion, detalle, hash FROM bitacora WHERE objeto = ? ORDER BY id", (objeto,))


def verificar(texto_codigo, texto_huella):
    """Devuelve (estado, fila, clase): estado es 'valido', 'no_coincide' o 'no_existe'."""
    leido = leer_codigo(texto_codigo)
    if not leido:
        return "no_existe", None, None
    clase, ident = leido
    f = fila(clase, ident)
    if not f:
        return "no_existe", None, clase
    esperada = huella(clase, f)
    dada = re.sub(r"[^0-9A-F]", "", (texto_huella or "").upper())
    ok = hmac.compare_digest(esperada.replace("-", ""), dada)
    return ("valido" if ok else "no_coincide"), f, clase
