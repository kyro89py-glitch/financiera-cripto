"""Alta de usuarios y clientes."""
import re

import click

from . import auditoria, db, seguridad
from .tiempo import ahora

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")


class ErrorDatos(Exception):
    pass


def crear_usuario(email, nombre, rol, clave, debe_cambiar=True, creador=None, ts=None):
    email = (email or "").strip().lower()
    nombre = (nombre or "").strip()
    if not EMAIL.match(email):
        raise ErrorDatos("Escribe un correo válido.")
    if not nombre:
        raise ErrorDatos("Escribe el nombre.")
    if rol not in ("cliente", "operador", "cumplimiento", "admin"):
        raise ErrorDatos("Elige un rol válido.")
    if db.uno("SELECT 1 FROM usuarios WHERE email = ?", (email,)):
        raise ErrorDatos("Ya existe un usuario con ese correo.")
    ts = ts or ahora()
    with db.transaccion() as c:
        cur = c.execute(
            "INSERT INTO usuarios (email, nombre, rol, clave_hash, debe_cambiar_clave, creado) VALUES (?, ?, ?, ?, ?, ?)",
            (email, nombre, rol, seguridad.hash_clave(clave), 1 if debe_cambiar else 0, ts),
        )
        uid = cur.lastrowid
        auditoria.registrar("usuario.creado", f"usuario:{uid}",
                            {"texto": f"Creó el usuario {email} con rol {rol}.", "rol": rol},
                            usuario=creador, ts=ts)
    return uid


def crear_cliente(datos, creador=None, ts=None):
    """datos: nombre, documento, tipo, telefono, email, perfil_riesgo, modelo. Devuelve (cliente_id, clave_temporal)."""
    nombre = (datos.get("nombre") or "").strip()
    documento = (datos.get("documento") or "").strip().upper()
    tipo = datos.get("tipo")
    perfil = datos.get("perfil_riesgo")
    modelo = datos.get("modelo")
    if not nombre or not documento:
        raise ErrorDatos("Completa el nombre y el documento.")
    if tipo not in ("persona", "empresa"):
        raise ErrorDatos("Elige si es persona o empresa.")
    if perfil not in ("conservador", "moderado", "arriesgado"):
        raise ErrorDatos("Elige el perfil de riesgo.")
    if not db.uno("SELECT 1 FROM modelos WHERE codigo = ? AND activo = 1", (modelo,)):
        raise ErrorDatos("Elige una cartera modelo.")
    if db.uno("SELECT 1 FROM clientes WHERE documento = ?", (documento,)):
        raise ErrorDatos("Ya existe un cliente con ese documento.")
    ts = ts or ahora()
    clave = datos.get("clave") or seguridad.clave_temporal()
    with db.transaccion() as c:
        uid = crear_usuario(datos.get("email"), nombre, "cliente", clave,
                            debe_cambiar=not datos.get("clave"), creador=creador, ts=ts)
        cur = c.execute(
            "INSERT INTO clientes (usuario_id, nombre, documento, tipo, telefono, perfil_riesgo, modelo, creado, creado_por)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, nombre, documento, tipo, (datos.get("telefono") or "").strip() or None, perfil, modelo, ts,
             creador["id"] if creador else None),
        )
        cid = cur.lastrowid
        auditoria.registrar("cliente.creado", f"cliente:{cid}",
                            {"texto": f"Dio de alta al cliente {nombre} ({documento}).", "documento": documento},
                            usuario=creador, ts=ts)
    return cid, clave


@click.command("crear-admin")
@click.option("--email", prompt="Correo")
@click.option("--nombre", prompt="Nombre")
@click.option("--clave", prompt="Contraseña", hide_input=True, confirmation_prompt="Repite la contraseña")
def cmd_crear_admin(email, nombre, clave):
    """Crea un usuario administrador."""
    error = seguridad.validar_clave_nueva(clave, email)
    if error:
        raise click.ClickException(error)
    try:
        crear_usuario(email, nombre, "admin", clave, debe_cambiar=False)
    except ErrorDatos as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"Administrador {email} creado.")


KYC_TEXTOS = {"verificado": "Verificó la identidad de", "observado": "Observó la verificación de",
              "pendiente": "Volvió a dejar pendiente la verificación de"}


def marcar_kyc(cliente_id, estado, nota, usuario, ts=None):
    if estado not in KYC_TEXTOS:
        raise ErrorDatos("Elige un estado válido.")
    nota = (nota or "").strip()[:300]
    if estado == "observado" and len(nota) < 5:
        raise ErrorDatos("Escribe qué falta o qué se observó.")
    ts = ts or ahora()
    with db.transaccion() as c:
        cli = c.execute("SELECT nombre FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        if not cli:
            raise ErrorDatos("El cliente no existe.")
        c.execute("UPDATE clientes SET kyc_estado = ?, kyc_nota = ?, kyc_fecha = ?, kyc_por = ? WHERE id = ?",
                  (estado, nota or None, ts, usuario["id"], cliente_id))
        auditoria.registrar("cliente.kyc", f"cliente:{cliente_id}",
                            {"texto": f"{KYC_TEXTOS[estado]} {cli['nombre']}." + (f" Nota: {nota}" if nota else ""),
                             "estado": estado}, usuario=usuario, ts=ts)


def registrar_origen(cliente_id, texto, usuario, ts=None):
    texto = (texto or "").strip()[:400]
    if len(texto) < 10:
        raise ErrorDatos("Describe el origen de los fondos y el respaldo presentado.")
    ts = ts or ahora()
    with db.transaccion() as c:
        cli = c.execute("SELECT nombre FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        if not cli:
            raise ErrorDatos("El cliente no existe.")
        c.execute("UPDATE clientes SET origen_fondos = ?, origen_fondos_fecha = ?, origen_fondos_por = ? WHERE id = ?",
                  (texto, ts, usuario["id"], cliente_id))
        auditoria.registrar("cliente.origen_fondos", f"cliente:{cliente_id}",
                            {"texto": f"Registró el origen de fondos de {cli['nombre']}: {texto}"}, usuario=usuario, ts=ts)
