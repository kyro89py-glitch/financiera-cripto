"""Identidad de la cuenta: fotografía, nombre de usuario, datos de contacto, perfil público, cambio de correo
verificado y solicitudes (corrección de datos verificados y cierre de cuenta).

Regla de fondo: lo que la persona puede cambiar sola son sus datos de presentación y contacto. Los datos con los que
se verificó su identidad (nombre legal, documento, fecha de nacimiento ya cargada) solo cambian con una solicitud que
revisa Cumplimiento. El perfil público nunca incluye saldos, movimientos ni datos de contacto.
"""
import hashlib
import io
import json
import os
import re
import secrets
from datetime import date

from flask import current_app

from . import auditoria, db, notificaciones, seguridad
from .tiempo import ahora, hace  # noqa: F401  (ahora se usa también desde las rutas)

FOTO_MAX_BYTES = 6 * 1024 * 1024
FOTO_LADO = 512
FORMATOS = {"JPEG", "PNG", "WEBP"}
AVATARES = 6          # estilos del avatar predeterminado
RESERVADOS = {"admin", "administrador", "soporte", "ayuda", "equipo", "sistema", "seguridad", "cumplimiento", "financiera",
              "financieracripto", "oficial", "root", "api", "null", "undefined", "binance", "banco", "bcp", "seprelad", "dnit",
              "staff", "moderador", "cuenta", "usuario", "cliente", "pagos", "retiros", "depositos"}
PAISES = ["Paraguay", "Argentina", "Bolivia", "Brasil", "Chile", "Colombia", "Ecuador", "España", "Estados Unidos", "México",
          "Perú", "Uruguay", "Venezuela", "Otro"]
CAMPOS_VERIFICADOS = {"nombre": "Nombre y apellido", "documento": "Número de documento", "nacimiento": "Fecha de nacimiento"}
ESTADOS_SOLICITUD = {"abierta": ("warn", "En revisión"), "aprobada": ("ok", "Aprobada"), "rechazada": ("bad", "Rechazada"),
                     "cancelada": ("", "Cancelada")}


class ErrorCuenta(Exception):
    pass


# ---------- identificador de cuenta ----------
def codigo(uid):
    """Identificador público y estable de la cuenta: FC + 7 dígitos + dígito verificador (detecta errores de tipeo)."""
    base = f"{int(uid):07d}"
    dv = sum((i + 2) * int(ch) for i, ch in enumerate(reversed(base))) % 10
    return f"FC{base}{dv}"


def leer_codigo(texto):
    m = re.fullmatch(r"FC-?(\d{7})-?(\d)", re.sub(r"\s", "", (texto or "").upper()))
    if not m or codigo(int(m.group(1))) != f"FC{m.group(1)}{m.group(2)}":
        return None
    return int(m.group(1))


# ---------- nombre de usuario ----------
def normalizar_usuario(texto):
    t = (texto or "").strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z][a-z0-9_.]{2,19}", t):
        raise ErrorCuenta("El nombre de usuario lleva de 3 a 20 caracteres: letras sin acento, números, punto o guion bajo, "
                          "y empieza con una letra.")
    if ".." in t or "__" in t or t[-1] in "._":
        raise ErrorCuenta("No repitas puntos o guiones seguidos ni termines con uno.")
    if t in RESERVADOS or any(t.startswith(r) for r in ("admin", "soporte", "financiera")):
        raise ErrorCuenta("Ese nombre de usuario está reservado.")
    return t


def disponible(texto, uid):
    """(ok, mensaje). No dice de quién es un nombre ocupado."""
    try:
        t = normalizar_usuario(texto)
    except ErrorCuenta as e:
        return False, str(e)
    otro = db.uno("SELECT id FROM usuarios WHERE usuario = ? COLLATE NOCASE", (t,))
    if otro and otro["id"] != uid:
        return False, "Ese nombre de usuario ya está en uso."
    return True, "Disponible."


def fijar_usuario(usuario, texto):
    t = normalizar_usuario(texto)
    if (usuario["usuario"] or "") == t:
        return t
    ok, msg = disponible(t, usuario["id"])
    if not ok:
        raise ErrorCuenta(msg)
    if usuario["usuario"] and usuario["usuario_ts"] and usuario["usuario_ts"] > hace(days=30):
        raise ErrorCuenta("Cambiaste tu nombre de usuario hace menos de 30 días. Así evitamos que alguien se haga pasar por otra persona.")
    ts = ahora()
    try:
        db.ejecutar("UPDATE usuarios SET usuario = ?, usuario_ts = ? WHERE id = ?", (t, ts, usuario["id"]))
    except db.sqlite3.IntegrityError as e:  # dos personas lo pidieron a la vez: gana la primera
        raise ErrorCuenta("Ese nombre de usuario ya está en uso.") from e
    auditoria.registrar("perfil.usuario", f"usuario:{usuario['id']}",
                        {"texto": f"Cambió su nombre de usuario a @{t}" + (f" (antes @{usuario['usuario']})." if usuario["usuario"] else ".")},
                        usuario=usuario, ts=ts)
    return t


# ---------- fotografía ----------
def carpeta_fotos():
    ruta = current_app.config["FOTOS_DIR"]
    os.makedirs(ruta, exist_ok=True)
    return ruta


def ruta_foto(usuario):
    if not usuario["foto"] or not re.fullmatch(r"[a-f0-9]{32}\.jpg", usuario["foto"]):
        return None
    ruta = os.path.join(carpeta_fotos(), usuario["foto"])
    return ruta if os.path.exists(ruta) else None


def guardar_foto(usuario, datos):
    """Valida y recodifica la imagen. Nunca se guarda el archivo tal como llegó: se decodifica, se endereza según su
    orientación, se recorta al centro en cuadrado, se reduce a 512 px y se vuelve a escribir como JPEG sin metadatos
    (ubicación GPS, cámara, etc.). Así un archivo malicioso disfrazado de imagen no llega nunca al disco."""
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as e:  # pragma: no cover - depende de la instalación
        raise ErrorCuenta("El servidor no tiene instalado el procesador de imágenes (Pillow).") from e
    if not datos:
        raise ErrorCuenta("Elige una imagen.")
    if len(datos) > FOTO_MAX_BYTES:
        raise ErrorCuenta("La imagen pesa más de 6 MB. Elige una más liviana.")
    Image.MAX_IMAGE_PIXELS = 40_000_000  # frena las «bombas de descompresión»
    try:
        with Image.open(io.BytesIO(datos)) as im:
            if im.format not in FORMATOS:
                raise ErrorCuenta("Formato no admitido. Usa una imagen JPG, PNG o WebP.")
            im.verify()
        with Image.open(io.BytesIO(datos)) as im:
            im = ImageOps.exif_transpose(im)
            if min(im.size) < 96:
                raise ErrorCuenta("La imagen es muy chica: usa una de al menos 96 píxeles de lado.")
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                fondo = Image.new("RGB", im.size, (255, 255, 255))
                fondo.paste(im, mask=im.split()[-1])
                im = fondo
            else:
                im = im.convert("RGB")
            im = ImageOps.fit(im, (FOTO_LADO, FOTO_LADO), Image.LANCZOS, centering=(0.5, 0.5))
            salida = io.BytesIO()
            im.save(salida, "JPEG", quality=88, optimize=True)
    except ErrorCuenta:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as e:
        raise ErrorCuenta("No pudimos leer ese archivo como imagen. Prueba con otra foto.") from e
    nombre = secrets.token_hex(16) + ".jpg"
    destino = os.path.join(carpeta_fotos(), nombre)
    with open(destino, "xb") as f:
        f.write(salida.getvalue())
    os.chmod(destino, 0o600)
    vieja = ruta_foto(usuario)
    ts = ahora()
    db.ejecutar("UPDATE usuarios SET foto = ?, foto_ts = ? WHERE id = ?", (nombre, ts, usuario["id"]))
    if vieja:
        os.remove(vieja)
    auditoria.registrar("perfil.foto", f"usuario:{usuario['id']}", {"texto": "Cambió su fotografía de perfil."}, usuario=usuario, ts=ts)
    return nombre


def borrar_foto(usuario):
    vieja = ruta_foto(usuario)
    db.ejecutar("UPDATE usuarios SET foto = NULL, foto_ts = ? WHERE id = ?", (ahora(), usuario["id"]))
    if vieja:
        os.remove(vieja)
        auditoria.registrar("perfil.foto", f"usuario:{usuario['id']}", {"texto": "Quitó su fotografía de perfil."}, usuario=usuario)


# ---------- datos que la persona edita sola ----------
def _limpio(t, maximo):
    return " ".join((t or "").split())[:maximo] or None


def actualizar_datos(usuario, form):
    """Presentación y contacto. Devuelve la lista de campos que cambiaron."""
    nuevo = {
        "nombre_publico": _limpio(form.get("nombre_publico"), 40),
        "bio": _limpio(form.get("bio"), 160),
        "telefono": _limpio(form.get("telefono"), 30),
        "pais": form.get("pais") if form.get("pais") in PAISES else None,
        "ciudad": _limpio(form.get("ciudad"), 60),
        "direccion": _limpio(form.get("direccion"), 160),
    }
    if nuevo["telefono"] and not re.fullmatch(r"\+?[0-9 ()-]{6,30}", nuevo["telefono"]):
        raise ErrorCuenta("Escribe el teléfono solo con números, por ejemplo 0981 123 456 o +595 981 123456.")
    if nuevo["nombre_publico"] and re.search(r"[<>@/\\]|https?:", nuevo["nombre_publico"], re.I):
        raise ErrorCuenta("El nombre público no puede tener enlaces ni símbolos como @ o /.")
    try:
        nuevo["avatar"] = min(max(int(form.get("avatar", usuario["avatar"])), 0), AVATARES - 1)
    except (TypeError, ValueError):
        nuevo["avatar"] = usuario["avatar"]
    nac = (form.get("nacimiento") or "").strip()
    if nac and not usuario["nacimiento"]:
        try:
            d = date.fromisoformat(nac)
        except ValueError as e:
            raise ErrorCuenta("La fecha de nacimiento no es válida.") from e
        edad = (date.today() - d).days / 365.25
        if not 18 <= edad <= 110:
            raise ErrorCuenta("Para tener una cuenta hay que ser mayor de 18 años.")
        nuevo["nacimiento"] = nac
    cambios = [k for k, v in nuevo.items() if v != usuario[k]]
    if not cambios:
        return []
    sets = ", ".join(f"{k} = ?" for k in cambios)
    ts = ahora()
    with db.transaccion() as c:
        c.execute(f"UPDATE usuarios SET {sets} WHERE id = ?", (*[nuevo[k] for k in cambios], usuario["id"]))
        if "telefono" in cambios:
            c.execute("UPDATE clientes SET telefono = ? WHERE usuario_id = ?", (nuevo["telefono"], usuario["id"]))
    nombres = {"nombre_publico": "nombre público", "bio": "presentación", "telefono": "teléfono", "pais": "país", "ciudad": "ciudad",
               "direccion": "dirección", "avatar": "avatar", "nacimiento": "fecha de nacimiento"}
    auditoria.registrar("perfil.datos", f"usuario:{usuario['id']}",
                        {"texto": "Actualizó su perfil: " + ", ".join(nombres[k] for k in cambios) + "."}, usuario=usuario, ts=ts)
    return cambios


# ---------- cambio de correo con verificación ----------
def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def pedir_cambio_email(usuario, nuevo, clave, url_base):
    """Devuelve el enlace de confirmación (se envía al correo NUEVO). El correo actual recibe un aviso."""
    nuevo = (nuevo or "").strip().lower()[:200]
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}", nuevo):
        raise ErrorCuenta("Escribe un correo válido.")
    if nuevo == usuario["email"].lower():
        raise ErrorCuenta("Ese ya es tu correo.")
    if not seguridad.verificar_clave(usuario["clave_hash"], clave or ""):
        raise ErrorCuenta("La contraseña no es correcta.")
    if db.uno("SELECT id FROM usuarios WHERE lower(email) = ?", (nuevo,)):
        # No se revela que el correo pertenece a otra cuenta: la respuesta es la misma, pero no se crea ni envía ningún enlace.
        auditoria.registrar("perfil.correo_pedido", f"usuario:{usuario['id']}", {"texto": "Pidió cambiar el correo a una dirección ya registrada."},
                            usuario=usuario)
        return None
    token = secrets.token_urlsafe(32)
    ts = ahora()
    with db.transaccion() as c:
        c.execute("UPDATE cambios_email SET usada = ? WHERE usuario_id = ? AND usada IS NULL", (ts, usuario["id"]))
        c.execute("INSERT INTO cambios_email (usuario_id, nuevo, token_hash, creada, vence) VALUES (?, ?, ?, ?, ?)",
                  (usuario["id"], nuevo, _hash(token), ts, hace(minutes=-60)))
    enlace = f"{url_base}/cuenta/correo/{token}"
    nombre = current_app.config["NOMBRE"]
    notificaciones.encolar_correo(nuevo, f"Confirma tu nuevo correo en {nombre}",
                                  f"Hola:\n\nPara usar esta dirección en tu cuenta de {nombre}, abre este enlace dentro de la próxima hora:\n\n"
                                  f"{enlace}\n\nSi no pediste este cambio, ignora este mensaje.\n\n{nombre}")
    notificaciones.notificar(usuario["id"], "Se pidió cambiar el correo de tu cuenta. Si no fuiste tú, cambia tu contraseña ahora.",
                             "/cuenta/centro-seguridad", ts=ts, categoria="seguridad")
    auditoria.registrar("perfil.correo_pedido", f"usuario:{usuario['id']}", {"texto": "Pidió cambiar el correo de la cuenta."},
                        usuario=usuario, ts=ts)
    return enlace


def confirmar_email(token):
    """Aplica el cambio. Devuelve el usuario actualizado o lanza ErrorCuenta."""
    r = db.uno("SELECT * FROM cambios_email WHERE token_hash = ?", (_hash(token or ""),))
    if not r or r["usada"] or r["vence"] < ahora():
        raise ErrorCuenta("El enlace venció o ya se usó. Pide el cambio de nuevo desde tu cuenta.")
    u = db.uno("SELECT * FROM usuarios WHERE id = ?", (r["usuario_id"],))
    ts = ahora()
    try:
        with db.transaccion() as c:
            if not c.execute("UPDATE cambios_email SET usada = ? WHERE id = ? AND usada IS NULL", (ts, r["id"])).rowcount:
                raise ErrorCuenta("El enlace ya se usó.")
            c.execute("UPDATE usuarios SET email = ?, sesion_ver = sesion_ver + 1 WHERE id = ?", (r["nuevo"], u["id"]))
    except db.sqlite3.IntegrityError as e:
        raise ErrorCuenta("No se pudo usar ese correo. Prueba con otra dirección.") from e
    seguridad.cerrar_sesiones(u["id"], "correo")
    auditoria.registrar("perfil.correo", f"usuario:{u['id']}", {"texto": f"Cambió el correo de la cuenta de {u['email']} a {r['nuevo']}."},
                        usuario=u, ts=ts)
    notificaciones.encolar_correo(u["email"], "El correo de tu cuenta cambió",
                                  f"El correo de tu cuenta de {current_app.config['NOMBRE']} ahora es {r['nuevo']}. "
                                  "Si no fuiste tú, contáctanos de inmediato.")
    notificaciones.notificar(u["id"], f"El correo de tu cuenta ahora es {r['nuevo']}. Se cerraron todas tus sesiones.",
                             "/cuenta/centro-seguridad", ts=ts, categoria="seguridad")
    return db.uno("SELECT * FROM usuarios WHERE id = ?", (u["id"],))


# ---------- solicitudes: corrección de datos verificados y cierre ----------
def solicitar_correccion(usuario, form):
    pedido = {}
    for campo in CAMPOS_VERIFICADOS:
        v = _limpio(form.get(campo), 120)
        if v:
            pedido[campo] = v
    if "nacimiento" in pedido:
        try:
            date.fromisoformat(pedido["nacimiento"])
        except ValueError as e:
            raise ErrorCuenta("La fecha de nacimiento no es válida.") from e
    motivo = _limpio(form.get("motivo"), 400)
    if not pedido:
        raise ErrorCuenta("Indica qué dato quieres corregir.")
    if not motivo or len(motivo) < 10:
        raise ErrorCuenta("Cuéntanos el motivo de la corrección (al menos 10 caracteres).")
    return _crear_solicitud(usuario, "correccion", {"campos": pedido, "motivo": motivo},
                            "pidió corregir datos verificados: " + ", ".join(CAMPOS_VERIFICADOS[k].lower() for k in pedido))


def solicitar_cierre(usuario, cliente, motivo, clave):
    if not seguridad.verificar_clave(usuario["clave_hash"], clave or ""):
        raise ErrorCuenta("La contraseña no es correcta.")
    pend = pendientes_para_cerrar(cliente)
    if pend:
        raise ErrorCuenta("Antes de cerrar la cuenta: " + "; ".join(pend) + ".")
    sid = _crear_solicitud(usuario, "cierre", {"motivo": _limpio(motivo, 400) or "Sin motivo"}, "pidió cerrar su cuenta")
    db.ejecutar("UPDATE usuarios SET estado_cuenta = 'cierre_solicitado' WHERE id = ?", (usuario["id"],))
    return sid


def pendientes_para_cerrar(cliente):
    """Lo que impide cerrar la cuenta. Lista vacía = se puede pedir."""
    if not cliente:
        return []
    from . import cartera
    out = []
    ten = {a: u for a, u in cartera.tenencias(cliente["id"]).items() if u > 0}
    if ten:
        out.append("retira o vende tus fondos (todavía tienes " + ", ".join(sorted(ten)) + ")")
    if db.uno("SELECT 1 FROM operaciones WHERE cliente_id = ? AND estado IN ('pendiente', 'primera_firma', 'ejecutando')", (cliente["id"],)):
        out.append("espera a que terminen tus solicitudes en curso")
    if db.uno("SELECT 1 FROM programadas WHERE cliente_id = ? AND estado = 'abierta'", (cliente["id"],)):
        out.append("cancela tus órdenes abiertas")
    return out


def _crear_solicitud(usuario, tipo, detalle, texto):
    if db.uno("SELECT 1 FROM solicitudes_cuenta WHERE usuario_id = ? AND tipo = ? AND estado = 'abierta'", (usuario["id"], tipo)):
        raise ErrorCuenta("Ya tienes una solicitud de ese tipo en revisión.")
    ts = ahora()
    sid = db.ejecutar("INSERT INTO solicitudes_cuenta (usuario_id, tipo, detalle, creada) VALUES (?, ?, ?, ?)",
                      (usuario["id"], tipo, json.dumps(detalle, ensure_ascii=False), ts)).lastrowid
    auditoria.registrar(f"cuenta.{tipo}_pedido", f"usuario:{usuario['id']}", {"texto": f"{usuario['nombre']} {texto}."}, usuario=usuario, ts=ts)
    notificaciones.notificar_rol(("cumplimiento", "admin"), f"{usuario['nombre']} {texto}.", "/equipo/solicitudes", ts=ts)
    return sid


def cancelar_solicitud(sid, usuario):
    s = db.uno("SELECT * FROM solicitudes_cuenta WHERE id = ? AND usuario_id = ? AND estado = 'abierta'", (sid, usuario["id"]))
    if not s:
        raise ErrorCuenta("Esa solicitud ya no se puede cancelar.")
    db.ejecutar("UPDATE solicitudes_cuenta SET estado = 'cancelada', resuelta = ? WHERE id = ?", (ahora(), sid))
    if s["tipo"] == "cierre":
        db.ejecutar("UPDATE usuarios SET estado_cuenta = 'activa' WHERE id = ?", (usuario["id"],))


def resolver_solicitud(sid, aprobar, nota, revisor):
    """La resuelve el equipo. Aprobar una corrección aplica los datos y deja la identidad pendiente de nueva verificación;
    aprobar un cierre desactiva el acceso (los registros se conservan el plazo legal)."""
    nota = _limpio(nota, 400)
    if not nota or len(nota) < 5:
        raise ErrorCuenta("Escribe una nota: queda en la bitácora.")
    s = db.uno("SELECT * FROM solicitudes_cuenta WHERE id = ? AND estado = 'abierta'", (sid,))
    if not s:
        raise ErrorCuenta("La solicitud ya fue resuelta.")
    if s["usuario_id"] == revisor["id"]:
        raise ErrorCuenta("No puedes resolver tu propia solicitud.")
    u = db.uno("SELECT * FROM usuarios WHERE id = ?", (s["usuario_id"],))
    cli = db.uno("SELECT * FROM clientes WHERE usuario_id = ?", (u["id"],))
    det = json.loads(s["detalle"])
    ts = ahora()
    if aprobar and s["tipo"] == "cierre":
        pend = pendientes_para_cerrar(cli)
        if pend:
            raise ErrorCuenta("No se puede cerrar todavía: " + "; ".join(pend) + ".")
    try:
        with db.transaccion() as c:
            c.execute("UPDATE solicitudes_cuenta SET estado = ?, resuelta = ?, resuelta_por = ?, nota = ? WHERE id = ?",
                      ("aprobada" if aprobar else "rechazada", ts, revisor["id"], nota, sid))
            if aprobar and s["tipo"] == "correccion":
                campos = det["campos"]
                if "nombre" in campos:
                    c.execute("UPDATE usuarios SET nombre = ? WHERE id = ?", (campos["nombre"], u["id"]))
                    c.execute("UPDATE clientes SET nombre = ? WHERE usuario_id = ?", (campos["nombre"], u["id"]))
                if "documento" in campos and cli:
                    c.execute("UPDATE clientes SET documento = ? WHERE id = ?", (campos["documento"], cli["id"]))
                if "nacimiento" in campos:
                    c.execute("UPDATE usuarios SET nacimiento = ? WHERE id = ?", (campos["nacimiento"], u["id"]))
                if cli and ("nombre" in campos or "documento" in campos):
                    c.execute("UPDATE clientes SET kyc_estado = 'pendiente', kyc_nota = ? WHERE id = ?",
                              ("Datos corregidos: falta verificar la identidad con el documento actualizado.", cli["id"]))
            elif aprobar and s["tipo"] == "cierre":
                c.execute("UPDATE usuarios SET activo = 0, estado_cuenta = 'cerrada', sesion_ver = sesion_ver + 1 WHERE id = ?", (u["id"],))
            elif s["tipo"] == "cierre":
                c.execute("UPDATE usuarios SET estado_cuenta = 'activa' WHERE id = ?", (u["id"],))
    except db.sqlite3.IntegrityError as e:
        raise ErrorCuenta("Ese documento ya pertenece a otro cliente.") from e
    if aprobar and s["tipo"] == "cierre":
        seguridad.cerrar_sesiones(u["id"], "cierre")
    que = "corrección de datos" if s["tipo"] == "correccion" else "cierre de cuenta"
    auditoria.registrar(f"cuenta.{s['tipo']}_{'aprobado' if aprobar else 'rechazado'}", f"usuario:{u['id']}",
                        {"texto": f"{'Aprobó' if aprobar else 'Rechazó'} la solicitud de {que} de {u['nombre']}: {nota}"},
                        usuario=revisor, ts=ts)
    if not (aprobar and s["tipo"] == "cierre"):
        notificaciones.notificar(u["id"], f"Tu solicitud de {que} fue {'aprobada' if aprobar else 'rechazada'}: {nota}",
                                 "/cuenta/solicitudes", ts=ts, categoria="cuenta")


def solicitudes_de(uid):
    return [dict(s, det=json.loads(s["detalle"])) for s in
            db.todos("SELECT * FROM solicitudes_cuenta WHERE usuario_id = ? ORDER BY id DESC LIMIT 30", (uid,))]


# ---------- perfil público ----------
def nombre_visible(u):
    return u["nombre_publico"] or (u["nombre"].split()[0] if u["nombre"] else "Usuario")


def perfil_publico(u, pref):
    """Solo lo que la persona eligió mostrar. Nunca saldos, movimientos, correo, teléfono, documento ni dirección."""
    if not u or not u["activo"] or not u["usuario"] or not pref["publico"]["activo"]:
        return None
    cli = db.uno("SELECT kyc_estado, recibir_envios FROM clientes WHERE usuario_id = ?", (u["id"],))
    p = pref["publico"]
    return {"id": u["id"], "usuario": u["usuario"], "nombre": nombre_visible(u), "bio": u["bio"] if p["bio"] else None,
            "foto": bool(u["foto"]) and p["foto"], "foto_ts": u["foto_ts"], "avatar": u["avatar"],
            "ubicacion": ", ".join(x for x in (u["ciudad"], u["pais"]) if x) if p["ubicacion"] else None,
            "desde": u["creado"] if p["antiguedad"] else None,
            "verificado": (cli is not None and cli["kyc_estado"] == "verificado") if p["nivel"] else None,
            "recibe": bool(cli and cli["recibir_envios"]), "codigo": codigo(u["id"])}
