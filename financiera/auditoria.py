"""Bitácora inalterable.

Cada registro guarda la huella (SHA-256) del registro anterior, así que cualquier cambio o
borrado posterior rompe la cadena y se detecta con verificar(). Además, la base de datos
impide modificar o borrar filas de la bitácora.
"""
import hashlib
import json

import click
from flask import g, has_request_context, request

from . import db
from .tiempo import ahora

GENESIS = "0" * 64


def _huella(prev, ts, usuario_id, actor, accion, objeto, detalle, ip):
    base = "|".join([prev, ts, str(usuario_id or ""), actor, accion, objeto or "", detalle, ip or ""])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def registrar(accion, objeto=None, detalle=None, usuario=None, ts=None, actor=None):
    if usuario is None and has_request_context():
        usuario = g.get("usuario")
    uid = usuario["id"] if usuario else None
    if not actor:
        actor = f'{usuario["nombre"]} · {usuario["rol"]}' if usuario else "Sistema"
    ip = request.remote_addr if has_request_context() else None
    ts = ts or ahora()
    texto = json.dumps(detalle or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with db.transaccion() as c:
        fila = c.execute("SELECT hash FROM bitacora ORDER BY id DESC LIMIT 1").fetchone()
        prev = fila["hash"] if fila else GENESIS
        huella = _huella(prev, ts, uid, actor, accion, objeto, texto, ip)
        c.execute(
            "INSERT INTO bitacora (ts, usuario_id, actor, accion, objeto, detalle, ip, hash_prev, hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, uid, actor, accion, objeto, texto, ip, prev, huella),
        )


def verificar():
    prev, n = GENESIS, 0
    for f in db.conexion().execute("SELECT * FROM bitacora ORDER BY id"):
        n += 1
        esperado = _huella(prev, f["ts"], f["usuario_id"], f["actor"], f["accion"], f["objeto"], f["detalle"], f["ip"])
        if f["hash_prev"] != prev or f["hash"] != esperado:
            return {"ok": False, "registros": n, "fallo": f["id"], "ultimo": prev}
        prev = f["hash"]
    return {"ok": True, "registros": n, "fallo": None, "ultimo": prev}


def texto(fila):
    try:
        return json.loads(fila["detalle"]).get("texto") or fila["accion"]
    except (ValueError, AttributeError):
        return fila["accion"]


@click.command("verificar-bitacora")
def cmd_verificar():
    """Recalcula la cadena de huellas de la bitácora."""
    r = verificar()
    if r["ok"]:
        click.echo(f"Bitácora íntegra: {r['registros']} registros. Última huella {r['ultimo']}")
    else:
        raise click.ClickException(f"La cadena se rompe en el registro {r['fallo']}.")
