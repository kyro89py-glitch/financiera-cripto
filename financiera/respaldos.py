"""Respaldos automáticos cifrados y prueba de restauración (hallazgo S-05).

`flask respaldo crear` hace una copia consistente de la base en caliente, le suma los documentos (ya cifrados) y un
manifiesto con conteos y huellas, empaqueta todo y lo cifra con CLAVE_CIFRADO (o CLAVE_RESPALDO si se define otra).
Conserva los últimos RESPALDOS_CONSERVAR y, si RESPALDO_COMANDO está definido, lo ejecuta para copiar el archivo
fuera del servidor (por ejemplo `rclone copy {archivo} remoto:financiera`).

`flask respaldo probar ARCHIVO` lo descifra en una carpeta temporal y comprueba que la base abre, que pasa el
control de integridad de SQLite, que la cadena de la bitácora está intacta y que los saldos coinciden con el
manifiesto. Nunca toca la base en uso. `flask respaldo restaurar` deja la base restaurada en otra ruta.
"""
import hashlib
import io
import json
import os
import shlex
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

import click
from flask import current_app
from flask.cli import with_appcontext

from . import auditoria, cifrado, db
from .tiempo import ahora

EXT = ".fcbak"


class ErrorRespaldo(Exception):
    pass


def _resumen(conn):
    """Conteos y totales que se guardan en el manifiesto y se comparan al restaurar."""
    conn.row_factory = sqlite3.Row
    tablas = {}
    for t in ("usuarios", "clientes", "operaciones", "libro", "bitacora", "transferencias", "documentos"):
        tablas[t] = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
    saldos = {r["activo"]: r["s"] for r in conn.execute("SELECT activo, SUM(cantidad) AS s FROM libro GROUP BY activo")}
    ult = conn.execute("SELECT hash FROM bitacora ORDER BY id DESC LIMIT 1").fetchone()
    return {"tablas": tablas, "saldos": saldos, "bitacora_ultima": ult["hash"] if ult else None}


def crear(carpeta=None):
    """Crea un respaldo cifrado. Devuelve la ruta del archivo."""
    cfg = current_app.config
    carpeta = carpeta or cfg["RESPALDOS_DIR"]
    os.makedirs(carpeta, exist_ok=True)
    marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    with tempfile.TemporaryDirectory() as tmp:
        copia = os.path.join(tmp, "financiera.db")
        dst = sqlite3.connect(copia)
        with dst:
            db.conexion().backup(dst)
        resumen = _resumen(dst)
        dst.close()
        with open(copia, "rb") as f:
            huella_db = hashlib.sha256(f.read()).hexdigest()
        from .version import VERSION
        manifiesto = {"version": VERSION, "creado": ahora(), "sha256_db": huella_db, **resumen}
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(copia, arcname="financiera.db")
            docs = cfg["DOCUMENTOS_DIR"]
            if os.path.isdir(docs):
                for nombre in sorted(os.listdir(docs)):
                    ruta = os.path.join(docs, nombre)
                    if os.path.isfile(ruta) and not nombre.endswith(".tmp"):
                        tar.add(ruta, arcname="documentos/" + nombre)
            datos = json.dumps(manifiesto, ensure_ascii=False, indent=1).encode()
            info = tarfile.TarInfo("manifiesto.json")
            info.size = len(datos)
            tar.addfile(info, io.BytesIO(datos))
    cifrado_bytes = cifrado.cifrar_bytes(buf.getvalue())
    destino = os.path.join(carpeta, f"respaldo-{marca}{EXT}")
    tmp_dest = destino + ".tmp"
    with open(tmp_dest, "wb") as f:
        f.write(cifrado_bytes)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp_dest, 0o600)
    os.replace(tmp_dest, destino)
    huella = hashlib.sha256(cifrado_bytes).hexdigest()
    detalle = None
    if cfg.get("RESPALDO_COMANDO"):
        args = [a.replace("{archivo}", destino) for a in shlex.split(cfg["RESPALDO_COMANDO"])]
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=900)
            detalle = "copia externa ok" if r.returncode == 0 else f"copia externa falló ({r.returncode}): {r.stderr[-300:]}"
        except (OSError, subprocess.TimeoutExpired) as e:
            detalle = f"copia externa falló: {e.__class__.__name__}"
    db.ejecutar("INSERT INTO respaldos (archivo, creado, bytes, sha256, detalle) VALUES (?, ?, ?, ?, ?)",
                (os.path.basename(destino), ahora(), len(cifrado_bytes), huella, detalle))
    auditoria.registrar("respaldo.creado", None, {"texto": f"Respaldo cifrado {os.path.basename(destino)}"
                                                  f" ({len(cifrado_bytes) // 1024} KB).", "sha256": huella})
    _rotar(carpeta)
    return destino


def _rotar(carpeta):
    conservar = current_app.config["RESPALDOS_CONSERVAR"]
    archivos = sorted(f for f in os.listdir(carpeta) if f.startswith("respaldo-") and f.endswith(EXT))
    for viejo in archivos[:-conservar] if conservar > 0 else []:
        os.remove(os.path.join(carpeta, viejo))


def _abrir(archivo, tmp):
    with open(archivo, "rb") as f:
        datos = f.read()
    if not cifrado.esta_cifrado(datos):
        raise ErrorRespaldo("El archivo no es un respaldo cifrado de la plataforma.")
    try:
        plano = cifrado.descifrar_bytes(datos)
    except cifrado.ErrorCifrado as e:
        raise ErrorRespaldo(str(e)) from e
    with tarfile.open(fileobj=io.BytesIO(plano), mode="r:gz") as tar:
        tar.extractall(tmp, filter="data")
    with open(os.path.join(tmp, "manifiesto.json"), encoding="utf-8") as f:
        return json.load(f)


def probar(archivo, registrar=True):
    """Restaura en una carpeta temporal y verifica. Devuelve dict con ok y detalle; nunca toca la base en uso."""
    resultado = {"ok": False, "archivo": os.path.basename(archivo), "controles": []}

    def control(nombre, ok, texto=""):
        resultado["controles"].append({"control": nombre, "ok": bool(ok), "texto": texto})
        return ok

    with tempfile.TemporaryDirectory() as tmp:
        try:
            man = _abrir(archivo, tmp)
        except (ErrorRespaldo, tarfile.TarError, OSError, ValueError) as e:
            control("descifrar y abrir", False, str(e))
            return _guardar(resultado, registrar)
        control("descifrar y abrir", True)
        ruta_db = os.path.join(tmp, "financiera.db")
        with open(ruta_db, "rb") as f:
            control("huella de la base", hashlib.sha256(f.read()).hexdigest() == man["sha256_db"])
        conn = sqlite3.connect(ruta_db)
        conn.row_factory = sqlite3.Row
        try:
            ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
            control("integridad de SQLite", ic == "ok", ic)
            cadena = auditoria.verificar(conn)
            control("cadena de la bitácora", cadena["ok"] and cadena["ultimo"] == (man["bitacora_ultima"] or auditoria.GENESIS),
                    f"{cadena['registros']} registros")
            actual = _resumen(conn)
            control("conteos de tablas", actual["tablas"] == man["tablas"],
                    ", ".join(f"{k} {v}" for k, v in actual["tablas"].items()))
            control("saldos del libro", actual["saldos"] == man["saldos"], f"{len(actual['saldos'])} activos")
            docs = conn.execute("SELECT archivo FROM documentos").fetchall()
            faltan = [d["archivo"] for d in docs if not os.path.exists(os.path.join(tmp, "documentos", d["archivo"]))]
            control("documentos", not faltan, f"{len(docs) - len(faltan)} de {len(docs)}")
        finally:
            conn.close()
    resultado["ok"] = all(c["ok"] for c in resultado["controles"])
    return _guardar(resultado, registrar)


def _guardar(resultado, registrar):
    if registrar:
        texto = "; ".join(f"{c['control']}: {'ok' if c['ok'] else 'FALLA'}" for c in resultado["controles"])
        db.ejecutar("UPDATE respaldos SET probado = ?, prueba_ok = ?, detalle = COALESCE(detalle || ' · ', '') || ? WHERE archivo = ?",
                    (ahora(), int(resultado["ok"]), "prueba: " + ("ok" if resultado["ok"] else "falla"), resultado["archivo"]))
        auditoria.registrar("respaldo.probado", None, {"texto": f"Prueba de restauración de {resultado['archivo']}: "
                                                       + ("correcta." if resultado["ok"] else "con fallas.") , "controles": texto})
    return resultado


def restaurar(archivo, destino):
    if os.path.exists(destino):
        raise ErrorRespaldo("El destino ya existe. Elige otra ruta: la restauración nunca pisa una base.")
    r = probar(archivo, registrar=False)
    if not r["ok"]:
        raise ErrorRespaldo("El respaldo no pasó la verificación; no se restaura.")
    with tempfile.TemporaryDirectory() as tmp:
        _abrir(archivo, tmp)
        os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
        os.replace(os.path.join(tmp, "financiera.db"), destino)
        docs_dest = os.path.join(os.path.dirname(os.path.abspath(destino)), "documentos-restaurados")
        if os.path.isdir(os.path.join(tmp, "documentos")):
            os.makedirs(docs_dest, exist_ok=True)
            for n in os.listdir(os.path.join(tmp, "documentos")):
                os.replace(os.path.join(tmp, "documentos", n), os.path.join(docs_dest, n))
    return destino


def ultimo():
    return db.uno("SELECT * FROM respaldos ORDER BY id DESC LIMIT 1")


@click.group("respaldo")
def cmd_respaldo():
    """Respaldos cifrados y pruebas de restauración."""


@cmd_respaldo.command("crear")
@click.option("--carpeta", default=None, help="Carpeta destino (por defecto RESPALDOS_DIR).")
@click.option("--probar/--sin-probar", "y_probar", default=True, help="Probar la restauración apenas se crea.")
@with_appcontext
def cmd_crear(carpeta, y_probar):
    """Crea un respaldo cifrado de la base y los documentos."""
    ruta = crear(carpeta)
    click.echo("Respaldo creado: " + ruta)
    if y_probar:
        r = probar(ruta)
        for c in r["controles"]:
            click.echo(f"  {'✓' if c['ok'] else '✗'} {c['control']} {c['texto']}")
        if not r["ok"]:
            raise click.ClickException("La prueba de restauración falló.")


@cmd_respaldo.command("probar")
@click.argument("archivo")
@with_appcontext
def cmd_probar(archivo):
    """Restaura un respaldo en una carpeta temporal y verifica que esté completo."""
    r = probar(archivo)
    for c in r["controles"]:
        click.echo(f"  {'✓' if c['ok'] else '✗'} {c['control']} {c['texto']}")
    if not r["ok"]:
        raise click.ClickException("El respaldo tiene fallas.")
    click.echo("Respaldo verificado.")


@cmd_respaldo.command("restaurar")
@click.argument("archivo")
@click.argument("destino")
@with_appcontext
def cmd_restaurar(archivo, destino):
    """Restaura un respaldo verificado en una base nueva (nunca pisa la que está en uso)."""
    try:
        click.echo("Base restaurada en " + restaurar(archivo, destino))
    except ErrorRespaldo as e:
        raise click.ClickException(str(e)) from e
