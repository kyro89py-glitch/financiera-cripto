"""Acceso a la base de datos SQLite y comandos de mantenimiento."""
import contextlib
import os
import sqlite3

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
from datetime import datetime, timezone
from importlib import resources

import click
from flask import current_app, g


def conexion():
    if "db" not in g:
        c = sqlite3.connect(current_app.config["DATABASE"], timeout=15, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA busy_timeout = 15000")
        g.db = c
    return g.db


def cerrar(_error=None):
    c = g.pop("db", None)
    if c is not None:
        c.close()


def uno(sql, args=()):
    return conexion().execute(sql, args).fetchone()


def todos(sql, args=()):
    return conexion().execute(sql, args).fetchall()


def ejecutar(sql, args=()):
    return conexion().execute(sql, args)


@contextlib.contextmanager
def transaccion():
    """Agrupa varias escrituras en una transacción exclusiva. Admite anidamiento."""
    c = conexion()
    if c.in_transaction:
        yield c
        return
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
    except BaseException:
        c.execute("ROLLBACK")
        raise
    else:
        c.execute("COMMIT")


def _migraciones():
    carpeta = resources.files(__package__).joinpath("migraciones")
    out = []
    for f in carpeta.iterdir():
        nombre = f.name
        if nombre.endswith(".sql") and nombre[:4].isdigit():
            out.append((int(nombre[:4]), nombre, f.read_text(encoding="utf-8")))
    return sorted(out)


@contextlib.contextmanager
def _candado():
    """Evita que dos procesos apliquen migraciones a la vez (por ejemplo, varios workers al arrancar)."""
    ruta = current_app.config["DATABASE"]
    if ruta == ":memory:" or fcntl is None:
        yield
        return
    with open(ruta + ".lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def migrar():
    """Aplica en orden las migraciones pendientes. La versión aplicada se guarda en PRAGMA user_version."""
    c = conexion()
    aplicadas = []
    with _candado():
        if current_app.config["DATABASE"] != ":memory:":
            c.execute("PRAGMA journal_mode = WAL")
        version = c.execute("PRAGMA user_version").fetchone()[0]
        for numero, nombre, sql in _migraciones():
            if numero <= version:
                continue
            c.executescript(f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version = {numero};\nCOMMIT;")
            aplicadas.append(nombre)
    return aplicadas


def version():
    return conexion().execute("PRAGMA user_version").fetchone()[0]


@click.command("migrar")
def cmd_migrar():
    """Crea o actualiza la base de datos aplicando las migraciones pendientes."""
    aplicadas = migrar()
    for nombre in aplicadas:
        click.echo("Aplicada " + nombre)
    click.echo(f"Base de datos en la versión {version()}: " + current_app.config["DATABASE"])


@click.command("respaldar")
@click.argument("destino", required=False)
def cmd_respaldar(destino):
    """Copia la base de datos en caliente a un archivo de respaldo."""
    if not destino:
        marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        base = os.path.dirname(os.path.abspath(current_app.config["DATABASE"]))
        destino = os.path.join(base, f"respaldo-{marca}.db")
    dst = sqlite3.connect(destino)
    with dst:
        conexion().backup(dst)
    dst.close()
    click.echo("Respaldo guardado en " + destino)


def init_app(app):
    app.teardown_appcontext(cerrar)
    app.cli.add_command(cmd_migrar)
    app.cli.add_command(cmd_respaldar)
