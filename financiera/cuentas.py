"""Alta de usuarios y clientes."""
import re

import click

from . import auditoria, db, seguridad
from datetime import timedelta

from .tiempo import ahora, iso, leer

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
    from . import antilavado
    antilavado.evaluar(cid)
    return cid, clave


CUESTIONARIO = [
    ("plazo", "¿Por cuánto tiempo piensas dejar invertido tu dinero?",
     [("1", "Menos de 1 año"), ("2", "Entre 1 y 3 años"), ("3", "Más de 3 años")]),
    ("caida", "Si tu inversión cae un 30 % en un mes, ¿qué harías?",
     [("1", "Vendería todo para no perder más"), ("2", "Esperaría a que se recupere"), ("3", "Aprovecharía para comprar más")]),
    ("experiencia", "¿Cuánta experiencia tienes con criptomonedas u otras inversiones de riesgo?",
     [("1", "Ninguna"), ("2", "Algo: invertí alguna vez"), ("3", "Bastante: invierto con frecuencia")]),
    ("parte", "¿Qué parte de tus ahorros vas a invertir aquí?",
     [("3", "Menos del 10 %"), ("2", "Entre el 10 % y el 30 %"), ("1", "Más del 30 %")]),
]
MODELO_POR_PERFIL = {"conservador": "reserva", "moderado": "equilibrio", "arriesgado": "impulso"}


def perfil_de(respuestas):
    """Perfil de riesgo a partir del cuestionario (4 a 12 puntos)."""
    puntos = 0
    for clave, _, opciones in CUESTIONARIO:
        valor = respuestas.get(clave)
        if valor not in {v for v, _ in opciones}:
            raise ErrorDatos("Responde todas las preguntas del perfil de inversor.")
        puntos += int(valor)
    return "conservador" if puntos <= 6 else ("moderado" if puntos <= 9 else "arriesgado")


def registrar_web(datos, ip=None, ts=None):
    """Apertura de cuenta desde la web. La cuenta queda con la identidad sin verificar: puede depositar y ver el mercado,
    pero no operar hasta que Cumplimiento acepte sus documentos. Devuelve el id del cliente."""
    if datos.get("web"):  # campo trampa para robots: una persona no lo ve ni lo completa
        raise ErrorDatos("No se pudo crear la cuenta.")
    ts = ts or ahora()
    hace_1h = iso(leer(ts) - timedelta(hours=1))
    if ip and db.uno("SELECT COUNT(*) AS n FROM bitacora WHERE accion = 'cliente.registro_web' AND ip = ? AND ts > ?", (ip, hace_1h))["n"] >= 5:
        raise ErrorDatos("Se crearon demasiadas cuentas desde esta conexión. Vuelve a intentarlo en una hora.")
    if datos.get("acepto") != "si":
        raise ErrorDatos("Para abrir la cuenta tienes que aceptar las condiciones y el aviso de riesgos.")
    if datos.get("clave") != datos.get("clave2"):
        raise ErrorDatos("Las contraseñas no coinciden.")
    error = seguridad.validar_clave_nueva(datos.get("clave") or "", datos.get("email"))
    if error:
        raise ErrorDatos(error)
    perfil = perfil_de(datos)
    cid, _ = crear_cliente({"nombre": datos.get("nombre"), "documento": datos.get("documento"), "tipo": datos.get("tipo"),
                            "telefono": datos.get("telefono"), "email": datos.get("email"), "perfil_riesgo": perfil,
                            "modelo": MODELO_POR_PERFIL[perfil], "clave": datos.get("clave")}, ts=ts)
    with db.transaccion() as c:
        c.execute("UPDATE clientes SET origen = 'web' WHERE id = ?", (cid,))
        cli = c.execute("SELECT * FROM clientes WHERE id = ?", (cid,)).fetchone()
        u = c.execute("SELECT * FROM usuarios WHERE id = ?", (cli["usuario_id"],)).fetchone()
        aceptar_terminos(u, ts=ts)
        auditoria.registrar("cliente.registro_web", f"cliente:{cid}",
                            {"texto": f"{cli['nombre']} ({cli['documento']}) abrió su cuenta en línea con perfil {perfil}.",
                             "perfil": perfil}, usuario=u, ts=ts)
        from . import notificaciones
        notificaciones.notificar_rol(("cumplimiento", "admin"), f"Nueva cuenta abierta en línea: {cli['nombre']}. Revisa su legajo "
                                     "cuando suba los documentos.", f"/equipo/clientes/{cid}", ts=ts)
    from . import antilavado
    antilavado.evaluar(cid)
    return cid


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
        cli = c.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        if not cli:
            raise ErrorDatos("El cliente no existe.")
        if estado == "verificado":
            from . import documentos
            faltan = documentos.faltantes(cli)
            if faltan:
                raise ErrorDatos("Para verificar la identidad faltan documentos aceptados: " + "; ".join(faltan) + ".")
        c.execute("UPDATE clientes SET kyc_estado = ?, kyc_nota = ?, kyc_fecha = ?, kyc_por = ? WHERE id = ?",
                  (estado, nota or None, ts, usuario["id"], cliente_id))
        auditoria.registrar("cliente.kyc", f"cliente:{cliente_id}",
                            {"texto": f"{KYC_TEXTOS[estado]} {cli['nombre']}." + (f" Nota: {nota}" if nota else ""),
                             "estado": estado}, usuario=usuario, ts=ts)
        if cli["usuario_id"] and estado != cli["kyc_estado"] and estado in ("verificado", "observado"):
            from . import notificaciones
            texto = ("Verificamos tu identidad. Ya podemos aprobar tus aportes y retiros." if estado == "verificado" else
                     f"Tu verificación tiene una observación: {nota}")
            notificaciones.notificar(cli["usuario_id"], texto, "/cliente/perfil", ts=ts)


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


TERMINOS_VERSION = seguridad.TERMINOS_VERSION


def aceptar_terminos(usuario, ts=None):
    ts = ts or ahora()
    with db.transaccion() as c:
        c.execute("UPDATE usuarios SET terminos_version = ?, terminos_ts = ? WHERE id = ?", (TERMINOS_VERSION, ts, usuario["id"]))
        auditoria.registrar("terminos.aceptados", f"usuario:{usuario['id']}",
                            {"texto": f"{usuario['email']} aceptó las condiciones y la información de riesgos (versión {TERMINOS_VERSION}).",
                             "version": TERMINOS_VERSION}, usuario=usuario, ts=ts)
