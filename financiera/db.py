"""Acceso a la base de datos SQLite y comandos de mantenimiento."""
import contextlib
import os
import sqlite3
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


def crear_esquema():
    c = conexion()
    if current_app.config["DATABASE"] != ":memory:":
        c.execute("PRAGMA journal_mode = WAL")
    sql = resources.files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")
    c.executescript(sql)


@click.command("init-db")
def cmd_init_db():
    """Crea las tablas y los datos base si no existen."""
    crear_esquema()
    click.echo("Base de datos lista en " + current_app.config["DATABASE"])


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
    app.cli.add_command(cmd_init_db)
    app.cli.add_command(cmd_respaldar)
