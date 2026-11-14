"""Ingreso, salida, cambio de contraseña y verificación en dos pasos."""
import time
from datetime import timedelta

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from . import auditoria, db, seguridad
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
        u = db.uno("SELECT * FROM usuarios WHERE email = ?", (email,))
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
            seguridad.iniciar_sesion(u)
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
                seguridad.iniciar_sesion(db.uno("SELECT * FROM usuarios WHERE id = ?", (u["id"],)))
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
            db.ejecutar("UPDATE usuarios SET totp_pendiente = ? WHERE id = ?", (seguridad.totp_secreto(), u["id"]))
            u = db.uno("SELECT * FROM usuarios WHERE id = ?", (u["id"],))
        secreto = u["totp_pendiente"]
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


@bp.get("/mercado")
def mercado():
    r = seguridad.exigir_sesion()
    if r:
        return r
    from . import cartera, graficos, precios
    filas = precios.mercado()
    for m in filas:
        m["chispa"] = graficos.chispa(m["serie"], 160, 40)
    cli = _cliente_actual()
    if g.usuario["rol"] == "cliente":
        pos, _ = cartera.posiciones(cli["id"]) if cli else ([], 0)
        titulo = "Tu billetera"
    else:
        pos, titulo = cartera.resumen_casa()["activos"], "Activos bajo gestión"
    tengo = {p["activo"]: p["valor"] for p in pos}
    favs = _favoritos()
    ver = request.args.get("ver", "todos")
    orden = request.args.get("orden", "")
    if ver == "favoritos":
        filas = [m for m in filas if m["codigo"] in favs]
    elif ver == "cartera":
        filas = [m for m in filas if tengo.get(m["codigo"])]
    else:
        ver = "todos"
    if orden == "suben":
        filas.sort(key=lambda m: -(m["cambio"] or 0))
    elif orden == "bajan":
        filas.sort(key=lambda m: (m["cambio"] or 0))
    else:
        orden = ""
    datos = {"titulo": titulo, "grupos": [{"label": p["activo"] if p["activo"] != "USD" else "Saldo USD", "value": p["valor"],
                                           "col": p["color"]} for p in pos if p["valor"] > 0]}
    return render_template("mercado.html", filas=filas, tengo=tengo, datos3d=datos, fuente=precios.fuente(), favs=favs,
                           ver=ver, orden=orden)


@bp.get("/mercado/precios.json")
def mercado_json():
    r = seguridad.exigir_sesion()
    if r:
        return {"error": "sesion"}, 401
    from . import precios
    from .dinero import fmt_precio as f_precio
    from .formato import f_pct
    out = {a: {"precio": f_precio(p["precio"]), "valor": float(p["precio"]), "cambio": f_pct(p["cambio"]) if p["cambio"] is not None else "",
               "sube": (p["cambio"] or 0) >= 0} for a, p in precios.vigentes().items()}
    resp = current_app.json.response(out)
    resp.headers["Cache-Control"] = "no-store"
    return resp


RANGOS = {"1": (1, "24 h"), "7": (7, "7 días"), "30": (30, "30 días")}


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
    graf = stats = None
    if len(serie) >= 2:
        vals = [v for _, v in serie]
        graf = graficos.linea(serie, 760, 300, fmt=lambda v: f_precio(Decimal(str(round(v, 6)))).replace("US$ ", ""),
                              rango_min=max(vals) * 0.004)
        stats = {"max": Decimal(str(max(vals))), "min": Decimal(str(min(vals))), "var": (vals[-1] / vals[0] - 1) * 100 if vals[0] else None}
    cli = _cliente_actual()
    ctx = {"tengo_u": 0, "tengo_usd": 0, "caja": 0, "promedio": None, "ordenes": [], "grupos": []}
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
    return render_template("moneda.html", a=a, vig=vig, graf=graf, stats=stats, rango=rango, rangos=RANGOS, cli=cli,
                           favorito=codigo in _favoritos(), datos3d={"titulo": a["nombre"], "grupos": ctx["grupos"]},
                           maximo=current_app.config["ORDEN_MAXIMA_USD"], **ctx)


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
    from . import notificaciones
    lista = notificaciones.listar(g.usuario["id"])
    notificaciones.marcar_leidas(g.usuario["id"])
    return render_template("auth/avisos.html", lista=lista)
