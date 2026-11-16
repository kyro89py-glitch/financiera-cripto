"""Ingreso, salida, cambio de contraseña y verificación en dos pasos."""
import time
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from . import auditoria, db, seguridad, cifrado, limites
from .tiempo import ahora, ahora_dt, iso, leer  # noqa: F401

bp = Blueprint("auth", __name__)


def _destino(u):
    return url_for("cliente.inicio") if u["rol"] == "cliente" else url_for("equipo.resumen")


def _seguro(destino):
    if destino and destino.startswith("/") and not destino.startswith("//") and "\\" not in destino:
        return destino
    return None


def _fallo(u, motivo):
    if not u:
        return
    fallos = u["fallos"] + 1
    bloqueo = None
    if fallos >= current_app.config["INTENTOS_LOGIN"]:
        bloqueo = iso(ahora_dt() + timedelta(minutes=current_app.config["BLOQUEO_MIN"]))
    db.ejecutar("UPDATE usuarios SET fallos = ?, bloqueado_hasta = ? WHERE id = ?", (fallos, bloqueo, u["id"]))
    texto = f"Ingreso fallido de {u['email']} ({motivo})." + (" Cuenta bloqueada temporalmente." if bloqueo else "")
    auditoria.registrar("ingreso.fallido", f"usuario:{u['id']}", {"texto": texto, "fallos": fallos},
                        usuario=None, actor=u["email"])


def _bloqueado(u):
    return bool(u and u["bloqueado_hasta"] and leer(u["bloqueado_hasta"]) > ahora_dt())


def _completar(u, siguiente):
    seguridad.iniciar_sesion(u)
    db.ejecutar("UPDATE usuarios SET fallos = 0, bloqueado_hasta = NULL, ultimo_ingreso = ? WHERE id = ?", (ahora(), u["id"]))
    auditoria.registrar("ingreso.ok", f"usuario:{u['id']}", {"texto": f"Ingresó {u['email']}."}, usuario=u)
    return redirect(_seguro(siguiente) or _destino(u))


@bp.route("/ingresar", methods=["GET", "POST"])
def ingresar():
    if g.usuario:
        return redirect(_destino(g.usuario))
    error, email = None, ""
    siguiente = request.values.get("siguiente", "")
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()[:200]
        clave = request.form.get("clave") or ""
        limites.exigir(("ingreso_ip", limites.ip()), ("ingreso_email", email))
        u = db.uno("SELECT * FROM usuarios WHERE email = ?", (email,))
        if u and seguridad.verificar_clave(u["clave_hash"], clave) and seguridad.necesita_rehash(u["clave_hash"]):
            # S-08: la contraseña se vuelve a guardar con el costo vigente la primera vez que se ingresa bien.
            db.ejecutar("UPDATE usuarios SET clave_hash = ? WHERE id = ?", (seguridad.hash_clave(clave), u["id"]))
            u = db.uno("SELECT * FROM usuarios WHERE id = ?", (u["id"],))
        if _bloqueado(u):
            error = "La cuenta está bloqueada por varios intentos fallidos. Vuelve a intentar en unos minutos."
        else:
            valida = seguridad.verificar_clave(u["clave_hash"] if u else seguridad.hash_ficticio(), clave)
            if not (u and valida and u["activo"]):
                _fallo(u, "contraseña incorrecta" if u and not valida else "usuario inactivo" if u else "")
                if not u:
                    auditoria.registrar("ingreso.fallido", None, {"texto": "Intento de ingreso con un correo no registrado."},
                                        usuario=None, actor=email or "desconocido")
                error = "El correo o la contraseña no son correctos."
            elif u["totp_secreto"]:
                session.clear()
                session["pre"] = {"uid": u["id"], "t": time.time(), "sig": _seguro(siguiente) or ""}
                seguridad.csrf_token()
                return redirect(url_for("auth.codigo"))
            else:
                return _completar(u, siguiente)
    return render_template("auth/ingresar.html", error=error, email=email, siguiente=siguiente,
                           vencida=g.get("sesion_vencida"))


@bp.route("/ingresar/codigo", methods=["GET", "POST"])
def codigo():
    pre = session.get("pre")
    if not pre or time.time() - pre.get("t", 0) > 300:
        session.pop("pre", None)
        flash("Vuelve a escribir tu correo y contraseña.", "info")
        return redirect(url_for("auth.ingresar"))
    u = db.uno("SELECT * FROM usuarios WHERE id = ?", (pre["uid"],))
    if not u or not u["activo"]:
        session.clear()
        return redirect(url_for("auth.ingresar"))
    error = None
    if request.method == "POST":
        limites.exigir(("ingreso_ip", limites.ip()))
        if _bloqueado(u):
            error = "La cuenta está bloqueada por varios intentos fallidos. Vuelve a intentar en unos minutos."
        else:
            contador = seguridad.totp_verificar(u["totp_secreto"], request.form.get("codigo"), u["totp_ultimo"])
            if contador is None:
                _fallo(u, "código de verificación incorrecto")
                error = "El código no es correcto o ya se usó. Escribe el código que muestra ahora tu aplicación."
            else:
                db.ejecutar("UPDATE usuarios SET totp_ultimo = ? WHERE id = ?", (contador, u["id"]))
                return _completar(u, pre.get("sig"))
    return render_template("auth/codigo.html", error=error)


@bp.post("/salir")
def salir():
    u = g.get("usuario")
    if u:
        auditoria.registrar("salida", f"usuario:{u['id']}", {"texto": f"Cerró sesión {u['email']}."}, usuario=u)
        if session.get("sid"):
            db.ejecutar("UPDATE sesiones SET cerrada = ?, cierre = 'salida' WHERE id = ? AND cerrada IS NULL", (ahora(), session["sid"]))
    session.clear()
    flash("Cerraste sesión.", "info")
    return redirect(url_for("auth.ingresar"))


@bp.route("/cuenta/clave", methods=["GET", "POST"])
def clave():
    r = seguridad.exigir_sesion()
    if r:
        return r
    u = g.usuario
    error = None
    if request.method == "POST":
        actual = request.form.get("actual") or ""
        nueva = request.form.get("nueva") or ""
        if not seguridad.verificar_clave(u["clave_hash"], actual):
            error = "La contraseña actual no es correcta."
        elif nueva != (request.form.get("repetir") or ""):
            error = "Las contraseñas nuevas no coinciden."
        elif nueva == actual:
            error = "La contraseña nueva tiene que ser distinta de la actual."
        else:
            error = seguridad.validar_clave_nueva(nueva, u["email"])
        if not error:
            db.ejecutar("UPDATE usuarios SET clave_hash = ?, debe_cambiar_clave = 0, sesion_ver = sesion_ver + 1 WHERE id = ?",
                        (seguridad.hash_clave(nueva), u["id"]))
            auditoria.registrar("clave.cambiada", f"usuario:{u['id']}", {"texto": f"{u['email']} cambió su contraseña."}, usuario=u)
            u = db.uno("SELECT * FROM usuarios WHERE id = ?", (u["id"],))
            seguridad.cerrar_sesiones(u["id"], "clave", excepto=session.get("sid"))
            seguridad.iniciar_sesion(u, motivo="clave")
            from . import notificaciones
            notificaciones.notificar(u["id"], "Cambiaste tu contraseña. Si no fuiste tú, contáctanos de inmediato.", "/cuenta/sesiones")
            flash("Contraseña actualizada. Se cerraron tus otras sesiones.", "ok")
            return redirect(_destino(u))
    return render_template("auth/clave.html", error=error, forzado=bool(u["debe_cambiar_clave"]))


@bp.route("/cuenta/seguridad", methods=["GET", "POST"], endpoint="seguridad")
def seguridad_cuenta():
    r = seguridad.exigir_sesion()
    if r:
        return r
    u = g.usuario
    error = None
    obligatorio = u["rol"] in seguridad.ROLES_EQUIPO and current_app.config["EXIGIR_2FA_EQUIPO"]
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "activar" and not u["totp_secreto"] and u["totp_pendiente"]:
            contador = seguridad.totp_verificar(u["totp_pendiente"], request.form.get("codigo"))
            if contador is None:
                error = "El código no coincide. Revisa que la hora del teléfono esté bien y vuelve a intentar."
            else:
                db.ejecutar("UPDATE usuarios SET totp_secreto = totp_pendiente, totp_pendiente = NULL, totp_ultimo = ?,"
                            " sesion_ver = sesion_ver + 1 WHERE id = ?", (contador, u["id"]))
                auditoria.registrar("2fa.activada", f"usuario:{u['id']}",
                                    {"texto": f"{u['email']} activó la verificación en dos pasos."}, usuario=u)
                seguridad.cerrar_sesiones(u["id"], "clave", excepto=session.get("sid"))
                seguridad.iniciar_sesion(db.uno("SELECT * FROM usuarios WHERE id = ?", (u["id"],)), motivo="2fa")
                from . import notificaciones
                notificaciones.notificar(u["id"], "Activaste la verificación en dos pasos. Se cerraron tus otras sesiones.", "/cuenta/sesiones")
                flash("Verificación en dos pasos activada.", "ok")
                return redirect(url_for("auth.seguridad"))
        elif accion == "desactivar" and u["totp_secreto"]:
            if obligatorio:
                error = "Para el equipo la verificación en dos pasos es obligatoria."
            elif not seguridad.verificar_clave(u["clave_hash"], request.form.get("clave") or ""):
                error = "La contraseña no es correcta."
            elif seguridad.totp_verificar(u["totp_secreto"], request.form.get("codigo"), u["totp_ultimo"]) is None:
                error = "El código no es correcto."
            else:
                db.ejecutar("UPDATE usuarios SET totp_secreto = NULL, totp_ultimo = NULL WHERE id = ?", (u["id"],))
                auditoria.registrar("2fa.desactivada", f"usuario:{u['id']}",
                                    {"texto": f"{u['email']} desactivó la verificación en dos pasos."}, usuario=u)
                flash("Verificación en dos pasos desactivada.", "ok")
                return redirect(url_for("auth.seguridad"))
    u = db.uno("SELECT * FROM usuarios WHERE id = ?", (u["id"],))
    secreto = enlace = None
    if not u["totp_secreto"]:
        if not u["totp_pendiente"]:
            db.ejecutar("UPDATE usuarios SET totp_pendiente = ? WHERE id = ?", (cifrado.cifrar_texto(seguridad.totp_secreto()), u["id"]))
            u = db.uno("SELECT * FROM usuarios WHERE id = ?", (u["id"],))
        secreto = cifrado.descifrar_texto(u["totp_pendiente"])
        enlace = seguridad.totp_enlace(secreto, u["email"])
    grupos = " ".join(secreto[i:i + 4] for i in range(0, len(secreto), 4)) if secreto else None
    return render_template("auth/seguridad.html", error=error, activa=bool(u["totp_secreto"]), secreto=grupos,
                           enlace=enlace, obligatorio=obligatorio)



def _cliente_actual():
    if g.usuario["rol"] != "cliente":
        return None
    return db.uno("SELECT * FROM clientes WHERE usuario_id = ?", (g.usuario["id"],))


def _favoritos():
    return {f["activo"] for f in db.todos("SELECT activo FROM favoritos WHERE usuario_id = ?", (g.usuario["id"],))}


@bp.route("/abrir-cuenta", methods=["GET", "POST"])
def abrir_cuenta():
    if g.get("usuario"):
        return redirect(url_for("inicio"))
    from . import cuentas
    error, form = None, {}
    if request.method == "POST":
        limites.exigir(("registro_ip", limites.ip()))
        form = request.form.to_dict()
        try:
            cuentas.registrar_web(form, ip=request.remote_addr)
            flash("¡Tu cuenta está creada! Ingresa con tu correo y contraseña y sube tus documentos para verificar tu identidad.", "ok")
            return redirect(url_for("auth.ingresar"))
        except cuentas.ErrorDatos as e:
            error = str(e)
    form.pop("clave", None)
    form.pop("clave2", None)
    return render_template("auth/abrir_cuenta.html", error=error, form=form, cuestionario=cuentas.CUESTIONARIO,
                           comision=current_app.config["COMISION_ANUAL_PCT"])


@bp.get("/condiciones")
def condiciones_publicas():
    from . import seguridad as seg
    return render_template("condiciones_publicas.html", version=seg.TERMINOS_VERSION, comision=current_app.config["COMISION_ANUAL_PCT"])


@bp.get("/sin-conexion")
def sin_conexion():
    return render_template("sin_conexion.html")


@bp.get("/sw.js")
def service_worker():
    resp = current_app.send_static_file("js/sw.js")
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


EVENTOS_SEGURIDAD = {"ingreso.ok": "Ingreso correcto", "ingreso.fallido": "Intento de ingreso fallido", "salida": "Cierre de sesión",
                     "clave.cambiada": "Cambio de contraseña", "2fa.activada": "Verificación en dos pasos activada",
                     "2fa.desactivada": "Verificación en dos pasos desactivada", "sesion.cerrada": "Sesión cerrada a distancia",
                     "privacidad.cambiada": "Cambio de privacidad"}


@bp.get("/cuenta/sesiones")
def sesiones():
    r = seguridad.exigir_sesion()
    if r:
        return r
    u = g.usuario
    limite = iso(ahora_dt() - timedelta(minutes=current_app.config["INACTIVIDAD_MIN"]))
    todas = db.todos("SELECT * FROM sesiones WHERE usuario_id = ? ORDER BY creada DESC LIMIT 40", (u["id"],))
    activas = [s for s in todas if not s["cerrada"] and s["ultima"] >= limite]
    marcas = ",".join("?" * len(EVENTOS_SEGURIDAD))
    eventos = db.todos(f"SELECT ts, accion, ip FROM bitacora WHERE objeto = ? AND accion IN ({marcas}) ORDER BY id DESC LIMIT 25",
                       (f"usuario:{u['id']}", *EVENTOS_SEGURIDAD))
    cli = _cliente_actual()
    return render_template("auth/sesiones.html", activas=activas, historial=todas, actual=session.get("sid"),
                           eventos=eventos, nombres=EVENTOS_SEGURIDAD, cli=cli, limite=limite)


@bp.post("/cuenta/sesiones/<sid>/cerrar")
def sesion_cerrar(sid):
    r = seguridad.exigir_sesion()
    if r:
        return r
    u = g.usuario
    if sid == session.get("sid"):
        return redirect(url_for("auth.salir"))
    n = db.ejecutar("UPDATE sesiones SET cerrada = ?, cierre = 'usuario' WHERE id = ? AND usuario_id = ? AND cerrada IS NULL",
                    (ahora(), sid, u["id"])).rowcount
    if n:
        auditoria.registrar("sesion.cerrada", f"usuario:{u['id']}", {"texto": f"{u['email']} cerró una sesión desde otro dispositivo."}, usuario=u)
        flash("Sesión cerrada. Ese dispositivo tiene que volver a ingresar.", "ok")
    return redirect(url_for("auth.sesiones"))


@bp.post("/cuenta/sesiones/cerrar-otras")
def sesiones_cerrar_otras():
    r = seguridad.exigir_sesion()
    if r:
        return r
    u = g.usuario
    n = seguridad.cerrar_sesiones(u["id"], "usuario", excepto=session.get("sid"))
    if n:
        auditoria.registrar("sesion.cerrada", f"usuario:{u['id']}", {"texto": f"{u['email']} cerró {n} sesiones en otros dispositivos."}, usuario=u)
    flash("Cerraste todas tus otras sesiones." if n else "No había otras sesiones abiertas.", "ok")
    return redirect(url_for("auth.sesiones"))


@bp.post("/cuenta/privacidad")
def privacidad():
    r = seguridad.exigir_sesion()
    if r:
        return r
    u = g.usuario
    accion = request.form.get("accion")
    destino = _seguro(request.form.get("volver")) or url_for("auth.sesiones")
    if accion == "saldos":
        db.ejecutar("UPDATE usuarios SET ocultar_saldos = 1 - ocultar_saldos WHERE id = ?", (u["id"],))
        return redirect(destino)
    cli = _cliente_actual()
    if accion == "envios" and cli:
        nuevo = 0 if cli["recibir_envios"] else 1
        db.ejecutar("UPDATE clientes SET recibir_envios = ? WHERE id = ?", (nuevo, cli["id"]))
        auditoria.registrar("privacidad.cambiada", f"usuario:{u['id']}",
                            {"texto": f"{cli['nombre']} {'permitió' if nuevo else 'dejó de permitir'} que otros clientes lo encuentren para enviarle."}, usuario=u)
        flash("Listo: otros clientes " + ("ya pueden" if nuevo else "ya no pueden") + " encontrarte para enviarte dinero.", "ok")
    return redirect(destino)


@bp.get("/cuenta/mis-datos.json")
def mis_datos():
    """Copia de los datos personales y de la actividad de la cuenta, para el titular."""
    r = seguridad.exigir_sesion()
    if r:
        return r
    u = g.usuario
    limites.exigir(("datos", f"u{u['id']}"))
    cli = _cliente_actual()
    datos = {"generado": ahora(), "usuario": {k: u[k] for k in ("email", "nombre", "rol", "creado", "ultimo_ingreso", "terminos_version")
                                             if k in u.keys()},
             "sesiones": [{k: s[k] for k in ("creada", "ultima", "ip", "dispositivo", "cerrada", "cierre")}
                          for s in db.todos("SELECT * FROM sesiones WHERE usuario_id = ? ORDER BY creada DESC", (u["id"],))]}
    if cli:
        datos["cliente"] = {k: cli[k] for k in ("nombre", "documento", "tipo", "telefono", "perfil_riesgo", "modelo", "kyc_estado",
                                                "creado", "origen", "recibir_envios") if k in cli.keys()}
        datos["operaciones"] = [dict(o) for o in db.todos(
            "SELECT id, tipo, monto_cent, activo, estado, creado, referencia, metodo, monto_pyg FROM operaciones WHERE cliente_id = ? ORDER BY id", (cli["id"],))]
        datos["libro"] = [dict(x) for x in db.todos("SELECT ts, activo, cantidad, concepto, operacion_id, transferencia_id FROM libro"
                                                    " WHERE cliente_id = ? ORDER BY id", (cli["id"],))]
        datos["documentos"] = [dict(x) for x in db.todos("SELECT tipo, nombre_original, subido_ts, estado FROM documentos WHERE cliente_id = ?",
                                                         (cli["id"],))]
    auditoria.registrar("datos.descargados", f"usuario:{u['id']}", {"texto": f"{u['email']} descargó una copia de sus datos."}, usuario=u)
    resp = current_app.json.response(datos)
    resp.headers["Content-Disposition"] = 'attachment; filename="mis-datos.json"'
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.get("/mercado")
def mercado():
    r = seguridad.exigir_sesion()
    if r:
        return r
    from . import cartera, graficos, precios
    todas = precios.mercado()
    cli = _cliente_actual()
    if g.usuario["rol"] == "cliente":
        pos, _ = cartera.posiciones(cli["id"]) if cli else ([], 0)
        titulo = "Tu billetera"
    else:
        pos, titulo = cartera.resumen_casa()["activos"], "Activos bajo gestión"
    tengo = {p["activo"]: p["valor"] for p in pos}
    todas = [m for m in todas if m["habilitado"] or tengo.get(m["codigo"])]
    for i, m in enumerate(sorted(todas, key=lambda m: -(m["cap"] or 0))):
        m["rank"] = i + 1
    for m in todas:
        m["chispa"] = graficos.chispa(m["serie"], 160, 40)
    favs = _favoritos()
    ver = request.args.get("ver", "todos")
    orden = request.args.get("orden", "")
    cat = request.args.get("cat", "")
    q = (request.args.get("q") or "").strip()[:30]
    filas = todas
    if ver == "favoritos":
        filas = [m for m in filas if m["codigo"] in favs]
    elif ver == "cartera":
        filas = [m for m in filas if tengo.get(m["codigo"])]
    else:
        ver = "todos"
    if cat in precios.CATEGORIAS:
        filas = [m for m in filas if m["categoria"] == cat]
    else:
        cat = ""
    if q:
        qq = q.lower()
        filas = [m for m in filas if qq in m["codigo"].lower() or qq in m["nombre"].lower()]
    var_f = request.args.get("var", "")
    if var_f == "suben":
        filas = [m for m in filas if (m["cambio"] or 0) > 0]
    elif var_f == "bajan":
        filas = [m for m in filas if (m["cambio"] or 0) < 0]
    else:
        var_f = ""
    tam = request.args.get("tam", "")
    rangos_cap = {"grande": (10e9, float("inf")), "mediana": (1e9, 10e9), "chica": (0, 1e9)}
    if tam in rangos_cap:
        lo, hi = rangos_cap[tam]
        filas = [m for m in filas if m["cap"] is not None and lo <= m["cap"] < hi]
    else:
        tam = ""
    claves = {"suben": lambda m: -(m["cambio"] or 0), "bajan": lambda m: (m["cambio"] or 0), "tendencia": lambda m: -(m["var"] or 0),
              "volumen": lambda m: -(m["volumen"] or 0), "nombre": lambda m: m["nombre"].lower()}
    if orden in claves:
        filas = sorted(filas, key=claves[orden])
    else:
        orden = ""
    con_px = [m for m in todas if m["cambio"] is not None and not m["estable"]]
    destacados = {
        "suben": sorted(con_px, key=lambda m: -m["cambio"])[:3],
        "bajan": sorted(con_px, key=lambda m: m["cambio"])[:3],
        "volumen": sorted([m for m in todas if m["volumen"]], key=lambda m: -m["volumen"])[:3],
        "tendencia": sorted([m for m in con_px if m["var"] is not None], key=lambda m: -m["var"])[:3],
        "actividad": sorted([m for m in todas if m["volumen"] and m["cap"] and not m["estable"]],
                            key=lambda m: -(m["volumen"] / m["cap"]))[:3],
    }
    cap_total = sum(m["cap"] or 0 for m in todas)
    resumen = {"cap": cap_total, "volumen": sum(m["volumen"] or 0 for m in todas),
               "dominancia": (next((m["cap"] for m in todas if m["codigo"] == "BTC"), 0) or 0) / cap_total * 100 if cap_total else None,
               "suben": sum(1 for m in con_px if m["cambio"] > 0), "bajan": sum(1 for m in con_px if m["cambio"] < 0)}
    peso = lambda m: (m["cap"] or m["volumen"] or 1e8) ** 0.5  # noqa: E731  escala comprimida para que se lean las chicas
    periodo_mapa = "7d" if request.args.get("mapa") == "7d" else "24h"
    for m in todas:
        v = m["var"] if periodo_mapa == "7d" else m["cambio"]
        m["mapa_var"] = float(v) if v is not None else None
    mapa = graficos.mapa([(peso(m), m) for m in todas if not m["estable"]], 100, 56)
    ult = db.uno("SELECT MAX(ts) AS ts FROM precios")["ts"]
    datos = {"titulo": titulo, "grupos": [{"label": p["activo"] if p["activo"] != "USD" else "Saldo USD", "value": p["valor"],
                                           "col": p["color"]} for p in pos if p["valor"] > 0]}
    return render_template("mercado.html", filas=filas, tengo=tengo, datos3d=datos, fuente=precios.fuente(), favs=favs,
                           ver=ver, orden=orden, cat=cat, q=q, var_f=var_f, tam=tam, categorias=precios.CATEGORIAS, destacados=destacados,
                           resumen=resumen, mapa=mapa, total=len(todas), vivo=precios.vivo(), periodo_mapa=periodo_mapa, actualizado=ult)


@bp.get("/mercado/precios.json")
def mercado_json():
    limites.api()
    r = seguridad.exigir_sesion()
    if r:
        return {"error": "sesion"}, 401
    from . import precios
    from .dinero import decimales_precio
    from .dinero import fmt_precio as f_precio
    from .formato import compacto, f_pct
    # S-10: si los precios no cambiaron desde la última consulta del navegador, se responde 304 sin armar nada.
    import hashlib
    ult = db.uno("SELECT MAX(ts) AS ts, COUNT(*) AS n FROM precios")
    en_vivo, seg, fuente = precios.vivo()
    etiqueta = hashlib.sha1(f"{ult['ts']}|{ult['n']}|{en_vivo}|{fuente}".encode()).hexdigest()[:20]
    if request.if_none_match.contains(etiqueta):
        resp = current_app.response_class(status=304)
        resp.set_etag(etiqueta)
        resp.headers["Cache-Control"] = "private, no-cache"
        return resp
    out = {}
    for a, p in precios.vigentes().items():
        out[a] = {"precio": f_precio(p["precio"]), "valor": float(p["precio"]),
                  "cambio": f_pct(p["cambio"]) if p["cambio"] is not None else "", "c": float(p["cambio"] or 0),
                  "sube": (p["cambio"] or 0) >= 0, "dec": decimales_precio(p["precio"]),
                  "max": f_precio(p["max"]) if p["max"] else "", "min": f_precio(p["min"]) if p["min"] else "",
                  "vol": compacto(p["volumen"]) if p["volumen"] else ""}
    resp = current_app.json.response({"precios": out, "vivo": en_vivo, "seg": round(seg or 0), "fuente": fuente})
    resp.set_etag(etiqueta)
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp


@bp.get("/mercado/<codigo>/velas.json")
def velas_json(codigo):
    limites.api()
    r = seguridad.exigir_sesion()
    if r:
        return {"error": "sesion"}, 401
    from . import precios, velas
    from .dinero import decimales_precio
    a = db.uno("SELECT codigo FROM activos WHERE codigo = ?", (codigo.upper(),))
    i = request.args.get("i", "15m")
    if not a or i not in velas.INTERVALOS:
        return {"error": "parametros"}, 404
    filas, con_volumen = velas.velas(a["codigo"], i)
    vig = precios.vigentes().get(a["codigo"])
    resp = current_app.json.response({"i": i, "v": filas, "vol": con_volumen, "seg": velas.INTERVALOS[i][0],
                                      "dec": decimales_precio(vig["precio"]) if vig else 2,
                                      "simulado": precios.fuente() != "Binance"})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.get("/mercado/<codigo>/libro.json")
def libro_json(codigo):
    limites.api()
    r = seguridad.exigir_sesion()
    if r:
        return {"error": "sesion"}, 401
    from . import velas
    a = db.uno("SELECT codigo FROM activos WHERE codigo = ?", (codigo.upper(),))
    if not a:
        return {"error": "moneda"}, 404
    compras, ventas, sim1 = velas.libro(a["codigo"])
    ops, sim2 = velas.operaciones_mercado(a["codigo"])
    resp = current_app.json.response({
        "compras": [[float(p), float(q)] for p, q in compras], "ventas": [[float(p), float(q)] for p, q in ventas],
        "ops": [[t, float(p), float(q), c] for t, p, q, c in ops], "simulado": sim1 or sim2})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.get("/trading", defaults={"codigo": None})
@bp.get("/trading/<codigo>")
def trading(codigo):
    r = seguridad.exigir_sesion()
    if r:
        return r
    from decimal import Decimal

    from flask import abort

    from . import cartera, exchange, operaciones, precios, programadas, velas
    from .dinero import decimales_precio, valor_cent
    if codigo is None:  # /trading: el último par usado (o BTC)
        ult = (request.cookies.get("par") or "BTC").upper()
        if not db.uno("SELECT 1 FROM activos WHERE codigo = ?", (ult,)):
            ult = "BTC"
        return redirect(url_for("auth.trading", codigo=ult, **({"i": request.args["i"]} if "i" in request.args else {})))
    codigo = codigo.upper()
    a = db.uno("SELECT * FROM activos WHERE codigo = ?", (codigo,))
    if not a:
        abort(404)
    vig = precios.vigentes()
    p = vig.get(codigo)
    intervalo = request.args.get("i", "15m")
    if intervalo not in velas.INTERVALOS:
        intervalo = "15m"
    pares = [{"codigo": x["codigo"], "nombre": x["nombre"], "color": x["color"], "categoria": x["categoria"],
              "precio": vig[x["codigo"]]["precio"] if x["codigo"] in vig else None,
              "cambio": vig[x["codigo"]]["cambio"] if x["codigo"] in vig else None}
             for x in precios.activos(solo_habilitados=True)]
    cli = _cliente_actual()
    from . import analisis
    ctx = {"disp_usd": 0, "disp_u": 0, "bloq_usd": 0, "bloq_u": 0, "abiertas": [], "historial": [], "tengo_usd": 0,
           "canceladas": [], "expo": None}
    if cli:
        ten = cartera.tenencias(cli["id"])
        bloq = cartera.bloqueado(cli["id"], ten=ten)
        ctx.update(disp_usd=ten.get("USD", 0) - bloq.get("USD", 0), disp_u=ten.get(codigo, 0) - bloq.get(codigo, 0),
                   bloq_usd=bloq.get("USD", 0), bloq_u=bloq.get(codigo, 0),
                   abiertas=programadas.del_cliente(cli["id"], solo_abiertas=True, limite=20),
                   historial=db.todos("SELECT * FROM ordenes WHERE cliente_id = ? ORDER BY id DESC LIMIT 20", (cli["id"],)),
                   canceladas=db.todos("SELECT * FROM programadas WHERE cliente_id = ? AND estado IN ('cancelada', 'fallida')"
                                       " ORDER BY COALESCE(resuelta_ts, creado) DESC LIMIT 20", (cli["id"],)))
        if p:
            ctx["tengo_usd"] = valor_cent(codigo, ctx["disp_u"], p["precio"])
            ctx["expo"] = analisis.exposicion(cli["id"], codigo, vig)
    datos = {"activo": codigo, "intervalo": intervalo, "dec": decimales_precio(p["precio"]) if p else 2,
             "precio": float(p["precio"]) if p else None, "disp_usd": ctx["disp_usd"], "disp_u": ctx["disp_u"],
             "comision": float(operaciones.comision_operacion_pct()), "maximo": current_app.config["ORDEN_MAXIMA_USD"] * 100,
             "cliente": bool(cli) and cli["kyc_estado"] == "verificado",
             "simulador": exchange.modo() != "binance",
             "expo": {"valor": ctx["expo"]["valor"], "total": ctx["expo"]["total"]} if ctx["expo"] else None}
    resp = current_app.make_response(render_template(
        "trading.html", a=a, vig=p, pares=pares, intervalo=intervalo, intervalos=velas.INTERVALOS, cli=cli, datos=datos,
        favorito=codigo in _favoritos(), nombre_prog=programadas.nombre, simulador=exchange.modo() != "binance",
        precios_sim=precios.fuente() != "Binance" or (p and p["fuente"] in ("Simulado", "Datos de ejemplo")),
        comision=operaciones.comision_operacion_pct(), Decimal=Decimal, analisis=analisis.activo(codigo, p["precio"] if p else None),
        estados_prog=programadas.ESTADOS, **ctx))
    resp.set_cookie("par", codigo, max_age=60 * 60 * 24 * 180, samesite="Lax", secure=current_app.config["SESSION_COOKIE_SECURE"])
    return resp


RANGOS = {"1": (1, "24 h"), "7": (7, "7 días"), "30": (30, "30 días"), "90": (90, "90 días"), "365": (365, "1 año")}


@bp.get("/mercado/<codigo>")
def moneda(codigo):
    r = seguridad.exigir_sesion()
    if r:
        return r
    from decimal import Decimal

    from flask import abort

    from . import cartera, graficos, precios
    from .dinero import fmt_precio as f_precio
    from .dinero import valor_cent
    a = db.uno("SELECT * FROM activos WHERE codigo = ?", (codigo.upper(),))
    if not a:
        abort(404)
    codigo = a["codigo"]
    rango = request.args.get("r", "7")
    if rango not in RANGOS:
        rango = "7"
    vig = precios.vigentes().get(codigo)
    hist = precios.historial([codigo], iso(ahora_dt() - timedelta(days=RANGOS[rango][0])))[codigo]
    serie = [(ts, float(p)) for ts, p in hist]
    if vig:
        serie.append((ahora(), float(vig["precio"])))
    graf = stats = velas = None
    modo = "velas" if request.args.get("g") == "velas" else "linea"
    fmt_eje = lambda v: (f"{v:,.0f}".replace(",", ".") if v >= 1000 else f_precio(Decimal(str(round(v, 6)))).replace("US$ ", ""))  # noqa: E731
    if modo == "velas":
        velas = graficos.velas(serie, 760, 300, fmt=fmt_eje)
    if len(serie) >= 2:
        vals = [v for _, v in serie]
        graf = graficos.linea(serie, 760, 300, fmt=lambda v: (f"{v:,.0f}".replace(",", ".") if v >= 1000
                                             else f_precio(Decimal(str(round(v, 6)))).replace("US$ ", "")),
                              rango_min=max(vals) * 0.004)
        stats = {"max": Decimal(str(max(vals))), "min": Decimal(str(min(vals))), "var": (vals[-1] / vals[0] - 1) * 100 if vals[0] else None}
    cli = _cliente_actual()
    cli_es = bool(cli)
    from . import alertas, planes
    ctx = {"tengo_u": 0, "tengo_usd": 0, "caja": 0, "promedio": None, "ordenes": [], "grupos": [],
           "planes": [], "programadas": [], "frecuencias": planes.FRECUENCIAS, "alertas": alertas.del_usuario(g.usuario["id"], codigo) if cli_es else []}
    if cli:
        from . import programadas
        ctx["planes"] = planes.del_cliente(cli["id"], codigo)
        ctx["programadas"] = programadas.del_cliente(cli["id"], codigo, solo_abiertas=False, limite=8)
        ctx["nombre_prog"], ctx["estados_prog"] = programadas.nombre, programadas.ESTADOS
    if cli:
        ten = cartera.tenencias(cli["id"])
        filas, total = cartera.posiciones(cli["id"], None, ten)
        ctx["tengo_u"] = ten.get(codigo, 0)
        ctx["tengo_usd"] = valor_cent(codigo, ctx["tengo_u"], vig["precio"]) if vig else 0
        ctx["caja"] = ten.get("USD", 0)
        c = db.uno("SELECT SUM(importe_cent) AS usd, SUM(cantidad) AS u FROM ordenes WHERE cliente_id = ? AND activo = ? AND lado = 'compra'",
                   (cli["id"], codigo))
        if c["u"]:
            ctx["promedio"] = Decimal(c["usd"]) / 100 / (Decimal(c["u"]) / 10 ** 8)
        ctx["ordenes"] = db.todos("SELECT * FROM ordenes WHERE cliente_id = ? AND activo = ? ORDER BY id DESC LIMIT 8", (cli["id"], codigo))
        resto = total - ctx["tengo_usd"]
        ctx["grupos"] = [g_ for g_ in ({"label": f"Tu {codigo}", "value": ctx["tengo_usd"], "col": a["color"]},
                                       {"label": "Resto", "value": resto, "col": "#4A5878"}) if g_["value"] > 0]
    else:
        casa = {x["activo"]: x for x in cartera.resumen_casa()["activos"]}
        ctx["tengo_usd"] = casa[codigo]["valor"] if codigo in casa else 0
        ctx["tengo_u"] = db.uno("SELECT COALESCE(SUM(cantidad), 0) AS u FROM libro WHERE activo = ?", (codigo,))["u"]
        resto = sum(x["valor"] for x in casa.values()) - ctx["tengo_usd"]
        ctx["grupos"] = [g_ for g_ in ({"label": codigo, "value": ctx["tengo_usd"], "col": a["color"]},
                                       {"label": "Resto bajo gestión", "value": resto, "col": "#4A5878"}) if g_["value"] > 0]
    if not ctx["grupos"]:
        ctx["grupos"] = [{"label": codigo, "value": 100000, "col": a["color"]}]
    from . import analisis, mercado_info
    from . import velas as velas_mod
    diarias, _ = velas_mod.velas(codigo, "1d")
    compras, ventas, libro_sim = velas_mod.libro(codigo, 10)
    trades, trades_sim = velas_mod.operaciones_mercado(codigo, 10)
    todas_m = precios.mercado()
    rank = next((i + 1 for i, m in enumerate(sorted(todas_m, key=lambda m: -(m["cap"] or 0))) if m["codigo"] == codigo), None)
    info_m = next((m for m in todas_m if m["codigo"] == codigo), {})
    ctx["extra"] = {"ficha": mercado_info.ficha(codigo), "rank": rank, "cap": info_m.get("cap"), "volumen": info_m.get("volumen"),
                    "var7": info_m.get("var"), "diarias": list(reversed(diarias[-14:])), "analisis": analisis.activo(codigo, vig["precio"] if vig else None),
                    "mejor_compra": compras[0][0] if compras else None, "mejor_venta": ventas[0][0] if ventas else None,
                    "libro_sim": libro_sim, "trades": trades, "trades_sim": trades_sim, "fuente": vig["fuente"] if vig else None,
                    "ts": vig["ts"] if vig else None, "categorias": precios.CATEGORIAS}
    return render_template("moneda.html", a=a, vig=vig, graf=graf, stats=stats, velas=velas, modo=modo, rango=rango, rangos=RANGOS, cli=cli,
                           favorito=codigo in _favoritos(), datos3d={"titulo": a["nombre"], "grupos": ctx["grupos"]},
                           maximo=current_app.config["ORDEN_MAXIMA_USD"], **ctx)


@bp.get("/mercado/comparar")
def comparar():
    r = seguridad.exigir_sesion()
    if r:
        return r
    from . import analisis, graficos, precios
    disponibles = precios.activos(solo_habilitados=True)
    codigos = {a["codigo"]: a for a in disponibles}
    elegidas = list(dict.fromkeys(c.upper() for c in request.args.getlist("m") if c and c.upper() in codigos))[:4]
    for extra in ("BTC", "ETH", "SOL"):
        if len(elegidas) >= 2:
            break
        if extra not in elegidas:
            elegidas.append(extra)
    rango = request.args.get("r", "30")
    if rango not in RANGOS:
        rango = "30"
    desde = iso(ahora_dt() - timedelta(days=RANGOS[rango][0]))
    hist = precios.historial(elegidas, desde)
    vig = precios.vigentes()
    mercado_d = {m["codigo"]: m for m in precios.mercado()}
    rank = {m["codigo"]: i + 1 for i, m in enumerate(sorted(mercado_d.values(), key=lambda m: -(m["cap"] or 0)))}
    series, filas = [], []
    for c in elegidas:
        s = [(ts, float(p)) for ts, p in hist.get(c, [])]
        if c in vig:
            s.append((ahora(), float(vig[c]["precio"])))
        series.append((c, codigos[c]["color"], s))
        an = analisis.activo(c, vig[c]["precio"] if c in vig else None)
        m = mercado_d.get(c, {})
        filas.append({"codigo": c, "nombre": codigos[c]["nombre"], "color": codigos[c]["color"], "precio": vig[c]["precio"] if c in vig else None,
                      "cambio": vig[c]["cambio"] if c in vig else None, "var": (s[-1][1] / s[0][1] - 1) * 100 if len(s) >= 2 and s[0][1] else None,
                      "vol": an.get("volatilidad"), "rsi": an.get("rsi"), "desde_max": an.get("desde_maximo"), "cap": m.get("cap"),
                      "volumen": m.get("volumen"), "rank": rank.get(c), "fuente": vig[c]["fuente"] if c in vig else None})
    return render_template("comparar.html", graf=graficos.comparacion(series), filas=filas, elegidas=elegidas, disponibles=disponibles,
                           rango=rango, rangos=RANGOS)


@bp.get("/mercado/<codigo>/historial.csv")
def historial_csv(codigo):
    r = seguridad.exigir_sesion()
    if r:
        return r
    limites.exigir(("datos", f"u{g.usuario['id']}"))
    import csv
    import io

    from . import precios, velas
    from .formato import zona
    a = db.uno("SELECT * FROM activos WHERE codigo = ?", (codigo.upper(),))
    if not a:
        from flask import abort
        abort(404)
    filas, con_volumen = velas.velas(a["codigo"], "1d")
    fuente = precios.fuente()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([f"Cotizaciones diarias de {a['codigo']}/USD", f"fuente: {fuente}", f"zona horaria: {current_app.config['ZONA_HORARIA']}",
                f"generado: {datetime.now(zona()).strftime('%Y-%m-%d %H:%M')}"])
    w.writerow(["fecha", "apertura", "maximo", "minimo", "cierre", "volumen" if con_volumen else "volumen (no disponible)"])
    for t, o, h, lo, c, v in filas:
        w.writerow([datetime.fromtimestamp(t / 1000, zona()).strftime("%Y-%m-%d"), f"{o:.8g}", f"{h:.8g}", f"{lo:.8g}", f"{c:.8g}",
                    f"{v:.8g}" if con_volumen else ""])
    resp = current_app.response_class("\ufeff" + buf.getvalue(), mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="cotizaciones-{a["codigo"]}.csv"'
    return resp


@bp.post("/mercado/<codigo>/favorito")
def favorito(codigo):
    r = seguridad.exigir_sesion()
    if r:
        return r
    a = db.uno("SELECT codigo FROM activos WHERE codigo = ?", (codigo.upper(),))
    if a:
        if db.uno("SELECT 1 FROM favoritos WHERE usuario_id = ? AND activo = ?", (g.usuario["id"], a["codigo"])):
            db.ejecutar("DELETE FROM favoritos WHERE usuario_id = ? AND activo = ?", (g.usuario["id"], a["codigo"]))
        else:
            db.ejecutar("INSERT INTO favoritos (usuario_id, activo, creado) VALUES (?, ?, ?)", (g.usuario["id"], a["codigo"], ahora()))
    destino = request.form.get("volver", "")
    return redirect(destino if destino.startswith("/mercado") else url_for("auth.mercado"))


@bp.post("/cuenta/tema")
def tema():
    actual = request.cookies.get("tema", "oscuro")
    destino = request.form.get("volver", "")
    resp = redirect(destino if destino.startswith("/") and not destino.startswith("//") else url_for("inicio"))
    resp.set_cookie("tema", "claro" if actual != "claro" else "oscuro", max_age=365 * 86400, samesite="Lax",
                    secure=current_app.config.get("SESSION_COOKIE_SECURE", False), httponly=True)
    return resp


@bp.get("/cuenta/avisos")
def avisos():
    r = seguridad.exigir_sesion()
    if r:
        return r
    from . import notificaciones, preferencias
    from .formato import zona
    from .tiempo import leer
    cat = request.args.get("cat") if request.args.get("cat") in preferencias.CATEGORIAS else None
    nuevas = request.args.get("ver") == "nuevas"
    lista = notificaciones.listar(g.usuario["id"], 100, categoria=cat, solo_no_leidas=nuevas)
    hoy = datetime.now(zona()).date()
    grupos = {}
    for a in lista:
        dia = leer(a["ts"]).astimezone(zona()).date()
        clave = "Hoy" if dia == hoy else "Ayer" if (hoy - dia).days == 1 else "Esta semana" if (hoy - dia).days < 7 else "Antes"
        grupos.setdefault(clave, []).append(a)
    ids = [a["id"] for a in lista if not a["leida"]]
    if ids:
        db.ejecutar(f"UPDATE notificaciones SET leida = 1 WHERE usuario_id = ? AND id IN ({','.join('?' * len(ids))})", (g.usuario["id"], *ids))
    return render_template("auth/avisos.html", grupos=grupos, cat=cat, nuevas=nuevas, categorias=preferencias.CATEGORIAS,
                           conteo=notificaciones.por_categoria(g.usuario["id"]), pref=preferencias.leer(g.usuario["id"]),
                           correo=notificaciones.correo_activo())


# ---------- recuperación de contraseña (S-07) ----------
def _token_hash(token):
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def _recuperacion_valida(token):
    from .tiempo import ahora as _ahora
    if not token or len(token) > 100:
        return None
    r = db.uno("SELECT * FROM recuperaciones WHERE token_hash = ?", (_token_hash(token),))
    if not r or r["usada"] or r["vence"] < _ahora():
        return None
    return r


@bp.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    if g.get("usuario"):
        return redirect(url_for("auth.clave"))
    from . import notificaciones
    from .tiempo import hace
    enviado, enlace_prueba = False, None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()[:200]
        limites.exigir(("recuperar_ip", limites.ip()), ("recuperar_email", email))
        u = db.uno("SELECT * FROM usuarios WHERE email = ? AND activo = 1", (email,))
        if u:
            import secrets as _s
            token = _s.token_urlsafe(32)
            minutos = current_app.config["RECUPERACION_MINUTOS"]
            ts = ahora()
            with db.transaccion() as c:
                c.execute("UPDATE recuperaciones SET usada = ? WHERE usuario_id = ? AND usada IS NULL", (ts, u["id"]))
                c.execute("INSERT INTO recuperaciones (usuario_id, token_hash, creada, vence, ip) VALUES (?, ?, ?, ?, ?)",
                          (u["id"], _token_hash(token), ts, hace(minutes=-minutos), request.remote_addr))
            url = (current_app.config["URL_PUBLICA"] or request.host_url.rstrip("/")) + url_for("auth.recuperar_nueva", token=token)
            nombre = current_app.config["NOMBRE"]
            notificaciones.encolar_correo(
                u["email"], f"Recupera tu contraseña de {nombre}",
                f"Hola {u['nombre'].split()[0]}:\n\nPediste cambiar tu contraseña. Abre este enlace dentro de los próximos "
                f"{minutos} minutos (sirve una sola vez):\n\n{url}\n\nSi no fuiste tú, ignora este correo: tu contraseña sigue igual.\n\n{nombre}")
            auditoria.registrar("clave.recuperacion", f"usuario:{u['id']}", {"texto": f"Se pidió recuperar la contraseña de {u['email']}."},
                                usuario=u, actor="Recuperación de contraseña")
            if current_app.config["ENTORNO"] != "produccion" and not notificaciones.correo_activo():
                enlace_prueba = url
        enviado = True
    return render_template("auth/recuperar.html", enviado=enviado, enlace_prueba=enlace_prueba)


@bp.route("/recuperar/<token>", methods=["GET", "POST"], endpoint="recuperar_nueva")
def recuperar_nueva(token):
    r = _recuperacion_valida(token)
    if not r:
        return render_template("auth/recuperar_nueva.html", invalido=True), 410
    u = db.uno("SELECT * FROM usuarios WHERE id = ?", (r["usuario_id"],))
    error = None
    if request.method == "POST":
        limites.exigir(("ingreso_ip", limites.ip()))
        nueva, repetir = request.form.get("nueva") or "", request.form.get("repetir") or ""
        error = seguridad.validar_clave_nueva(nueva, u["email"])
        if not error and nueva != repetir:
            error = "Las dos contraseñas no coinciden."
        contador = None
        if not error and u["totp_secreto"]:
            # La recuperación no saltea la verificación en dos pasos.
            contador = seguridad.totp_verificar(u["totp_secreto"], request.form.get("codigo"), u["totp_ultimo"])
            if contador is None:
                error = "El código de verificación no es correcto."
        if not error:
            ts = ahora()
            with db.transaccion() as c:
                hecho = c.execute("UPDATE recuperaciones SET usada = ? WHERE id = ? AND usada IS NULL", (ts, r["id"])).rowcount
                if hecho:
                    c.execute("UPDATE usuarios SET clave_hash = ?, debe_cambiar_clave = 0, fallos = 0, bloqueado_hasta = NULL,"
                              " sesion_ver = sesion_ver + 1" + (", totp_ultimo = ?" if contador is not None else "") + " WHERE id = ?",
                              (seguridad.hash_clave(nueva), *((contador,) if contador is not None else ()), u["id"]))
            if not hecho:
                return render_template("auth/recuperar_nueva.html", invalido=True), 410
            seguridad.cerrar_sesiones(u["id"], "clave")
            auditoria.registrar("clave.recuperada", f"usuario:{u['id']}", {"texto": f"{u['email']} cambió su contraseña con un enlace de recuperación."},
                                usuario=u, ts=ts)
            from . import notificaciones
            notificaciones.notificar(u["id"], "Tu contraseña se cambió con un enlace de recuperación y se cerraron todas tus sesiones. "
                                     "Si no fuiste tú, avísanos de inmediato.", "/cuenta/sesiones", ts=ts)
            flash("Listo: tu contraseña nueva ya funciona. Ingresa con ella.", "ok")
            return redirect(url_for("auth.ingresar"))
    return render_template("auth/recuperar_nueva.html", invalido=False, dos_pasos=bool(u["totp_secreto"]), error=error)


@bp.post("/cuenta/preferencias")
def preferencias_guardar():
    r = seguridad.exigir_sesion()
    if r:
        return r
    from . import preferencias
    f = request.form
    cambios = {}
    if f.get("accion") == "panel":
        cambios["orden"] = [x for x in (f.get("orden") or "").split(",") if x]
        visibles = set(f.getlist("visible"))
        cambios["ocultos"] = [m for m in preferencias.MODULOS if m not in visibles]
        if f.get("restablecer"):
            cambios = {"orden": list(preferencias.MODULOS), "ocultos": []}
    elif f.get("accion") == "moneda":
        cambios["moneda"] = f.get("moneda")
    elif f.get("accion") == "correo":
        cambios["correo"] = {k: f.get(k) == "si" for k in preferencias.CATEGORIAS}
    preferencias.guardar(g.usuario["id"], cambios)
    flash("Preferencias guardadas.", "ok")
    destino = f.get("volver") or ""
    return redirect(destino if destino.startswith(("/cliente", "/cuenta", "/mercado", "/trading")) and "//" not in destino else url_for("inicio"))


@bp.get("/cuenta/centro-seguridad")
def centro_seguridad():
    r = seguridad.exigir_sesion()
    if r:
        return r
    from . import niveles
    u = g.usuario
    cli = _cliente_actual()
    marcas = ",".join("?" * len(EVENTOS_SEGURIDAD))
    eventos = db.todos(f"SELECT ts, accion, ip FROM bitacora WHERE objeto = ? AND accion IN ({marcas}) ORDER BY id DESC LIMIT 12",
                       (f"usuario:{u['id']}", *EVENTOS_SEGURIDAD))
    activas = db.todos("SELECT * FROM sesiones WHERE usuario_id = ? AND cerrada IS NULL ORDER BY ultima DESC LIMIT 6", (u["id"],))
    return render_template("auth/centro_seguridad.html", p=niveles.proteccion(cli, u), eventos=eventos, nombres=EVENTOS_SEGURIDAD,
                           activas=activas, actual=session.get("sid"), cli=cli)


@bp.get("/academia")
def academia():
    r = seguridad.exigir_sesion()
    if r:
        return r
    from . import academia as ac
    from . import preferencias
    leidas = preferencias.leer(g.usuario["id"])["lecciones"]
    return render_template("academia.html", lecciones=ac.lista(), categorias=ac.CATEGORIAS, leidas=leidas)


@bp.route("/academia/<slug>", methods=["GET", "POST"])
def leccion(slug):
    r = seguridad.exigir_sesion()
    if r:
        return r
    from flask import abort

    from . import academia as ac
    from . import preferencias
    lec = ac.leccion(slug)
    if not lec:
        abort(404)
    pref = preferencias.leer(g.usuario["id"])
    if request.method == "POST":
        if slug not in pref["lecciones"]:
            preferencias.guardar(g.usuario["id"], {"lecciones": pref["lecciones"] + [slug]})
        return redirect(url_for("auth.leccion", slug=lec["siguiente"]) if lec["siguiente"] else url_for("auth.academia"))
    return render_template("leccion.html", lec=lec, categorias=ac.CATEGORIAS, leida=slug in pref["lecciones"],
                           es_cliente=g.usuario["rol"] == "cliente")
