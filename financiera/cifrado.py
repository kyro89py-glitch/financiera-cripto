"""Cifrado de datos sensibles en reposo (hallazgo S-04).

Se cifran los secretos de verificación en dos pasos (en la base) y los documentos de identidad (en disco) con
Fernet (AES-128-CBC + HMAC-SHA256). La clave vive fuera de la base: variable CLAVE_CIFRADO o un archivo indicado
en CLAVE_CIFRADO_FILE (por ejemplo, un secreto de Docker). Admite varias claves separadas por coma: la primera
cifra y todas descifran, así se puede rotar sin cortar el servicio (`flask cifrado rotar`).

Los datos viejos sin cifrar se siguen leyendo y `flask cifrado migrar` los cifra.
"""
import base64
import hashlib
import os

import click
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from flask import current_app
from flask.cli import with_appcontext

PREFIJO = "enc1:"
MAGIA = b"FCENC1\n"


class ErrorCifrado(Exception):
    pass


def generar_clave():
    return Fernet.generate_key().decode()


def _derivada():
    derivada = hashlib.sha256(("cifrado|" + current_app.config["SECRET_KEY"]).encode()).digest()
    return base64.urlsafe_b64encode(derivada).decode()


def _claves():
    cfg = current_app.config
    texto = cfg.get("CLAVE_CIFRADO") or ""
    claves = [k.strip() for k in texto.split(",") if k.strip()]
    if not claves:
        if cfg["ENTORNO"] == "produccion":
            raise ErrorCifrado("Falta CLAVE_CIFRADO. Genera una con `flask cifrado generar-clave` y guárdala fuera de la base.")
        # Fuera de producción se deriva de SECRET_KEY para que el entorno de desarrollo funcione sin configurar nada.
        claves = [_derivada()]
    elif cfg["ENTORNO"] != "produccion":
        claves.append(_derivada())  # fuera de producción, lo cifrado antes de configurar la clave se sigue leyendo
    try:
        return MultiFernet([Fernet(k.encode()) for k in claves])
    except (ValueError, TypeError) as e:
        raise ErrorCifrado("CLAVE_CIFRADO no es una clave válida (44 caracteres en base64).") from e


def cifrar_texto(texto):
    if texto is None or str(texto).startswith(PREFIJO):
        return texto
    return PREFIJO + _claves().encrypt(str(texto).encode()).decode()


def descifrar_texto(texto):
    if not texto or not str(texto).startswith(PREFIJO):
        return texto
    try:
        return _claves().decrypt(texto[len(PREFIJO):].encode()).decode()
    except InvalidToken as e:
        raise ErrorCifrado("No se pudo descifrar un dato: la clave de cifrado no coincide.") from e


def cifrar_bytes(datos):
    if datos.startswith(MAGIA):
        return datos
    return MAGIA + _claves().encrypt(datos)


def descifrar_bytes(datos):
    if not datos.startswith(MAGIA):
        return datos
    try:
        return _claves().decrypt(datos[len(MAGIA):])
    except InvalidToken as e:
        raise ErrorCifrado("No se pudo descifrar un archivo: la clave de cifrado no coincide.") from e


def esta_cifrado(valor):
    if isinstance(valor, bytes):
        return valor.startswith(MAGIA)
    return bool(valor) and str(valor).startswith(PREFIJO)


def _recifrar(rotar):
    """Cifra lo que esté en claro y, si rotar, vuelve a cifrar todo con la primera clave. Devuelve (campos, archivos)."""
    from . import db, documentos
    f = _claves()
    n_campos = n_archivos = 0
    for u in db.todos("SELECT id, totp_secreto, totp_pendiente FROM usuarios WHERE totp_secreto IS NOT NULL OR totp_pendiente IS NOT NULL"):
        nuevos = {}
        for campo in ("totp_secreto", "totp_pendiente"):
            v = u[campo]
            if not v:
                continue
            if not esta_cifrado(v):
                nuevos[campo] = cifrar_texto(v)
            elif rotar:
                try:
                    nuevos[campo] = PREFIJO + f.rotate(v[len(PREFIJO):].encode()).decode()
                except InvalidToken as e:
                    raise ErrorCifrado(f"El secreto del usuario {u['id']} no se puede leer con ninguna de las claves.") from e
        if nuevos:
            sets = ", ".join(f"{k} = ?" for k in nuevos)
            db.ejecutar(f"UPDATE usuarios SET {sets} WHERE id = ?", (*nuevos.values(), u["id"]))
            n_campos += len(nuevos)
    for d in db.todos("SELECT * FROM documentos"):
        ruta = documentos.ruta(d)
        if not os.path.exists(ruta):
            continue
        with open(ruta, "rb") as fh:
            datos = fh.read()
        if not datos.startswith(MAGIA):
            nuevo = cifrar_bytes(datos)
        elif rotar:
            try:
                nuevo = MAGIA + f.rotate(datos[len(MAGIA):])
            except InvalidToken as e:
                raise ErrorCifrado(f"El documento {d['id']} no se puede leer con ninguna de las claves.") from e
        else:
            continue
        tmp = ruta + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(nuevo)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ruta)
        n_archivos += 1
    return n_campos, n_archivos


@click.group("cifrado")
def cmd_cifrado():
    """Cifrado de datos sensibles en reposo."""


@cmd_cifrado.command("generar-clave")
def cmd_generar():
    """Imprime una clave nueva para CLAVE_CIFRADO."""
    click.echo(generar_clave())


@cmd_cifrado.command("migrar")
@with_appcontext
def cmd_migrar():
    """Cifra los secretos de dos pasos y los documentos que todavía estén en claro."""
    campos, archivos = _recifrar(rotar=False)
    click.echo(f"Listo: {campos} secretos y {archivos} documentos cifrados.")


@cmd_cifrado.command("rotar")
@with_appcontext
def cmd_rotar():
    """Vuelve a cifrar todo con la primera clave de CLAVE_CIFRADO. Después se puede quitar la clave vieja."""
    campos, archivos = _recifrar(rotar=True)
    click.echo(f"Listo: {campos} secretos y {archivos} documentos cifrados con la clave nueva.")
