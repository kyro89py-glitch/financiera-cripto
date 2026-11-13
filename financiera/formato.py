"""Filtros y ayudas para las plantillas."""
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import current_app, g, request, url_for
from markupsafe import Markup

from . import dinero, seguridad, tiempo
from .version import VERSION

MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
                "noviembre", "diciembre"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
ROLES = {"cliente": "Cliente", "operador": "Operaciones", "cumplimiento": "Cumplimiento", "admin": "Administración"}
ESTADOS = {
    "pendiente": ("warn", "Pendiente"),
    "primera_firma": ("info", "Espera segunda firma"),
    "liquidada": ("ok", "Liquidada"),
    "rechazada": ("bad", "Rechazada"),
    "cancelada": ("", "Cancelada"),
}
KYC = {"verificado": ("ok", "Identidad verificada"), "pendiente": ("warn", "Verificación pendiente"),
       "observado": ("bad", "Verificación observada")}
PERFILES = {"conservador": "Conservador", "moderado": "Moderado", "arriesgado": "Arriesgado"}
TIPOS_OP = {"aporte": "Aporte", "retiro": "Retiro", "comision": "Comisión de gestión"}

ICONOS = {
    "inicio": '<path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z"/>',
    "cartera": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5V12l6 6"/>',
    "invertir": '<circle cx="12" cy="12" r="8.5"/><path d="M12 16V8M8.5 11.5L12 8l3.5 3.5"/>',
    "movimientos": '<path d="M5 7h14M5 12h14M5 17h9"/>',
    "resumen": '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    "operaciones": '<path d="M4 7l2 2 3-4M12 7h8M4 16l2 2 3-4M12 16h8"/>',
    "clientes": '<circle cx="9" cy="8.5" r="3.5"/><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5M16 5.2a3.5 3.5 0 0 1 0 6.6M18.5 14.8c1.7.8 2.7 2.6 3 5.2"/>',
    "cumplimiento": '<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "perfil": '<circle cx="12" cy="8" r="4"/><path d="M4 20.5c.8-4 4-6 8-6s7.2 2 8 6"/>',
    "campana": '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2.2 2.2 0 0 0 4 0"/>',
    "documento": '<path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    "custodia": '<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="12" cy="12" r="3.2"/><path d="M12 8.8V7M12 17v-1.8M15.2 12H17M7 12h1.8"/>',
    "descargar": '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/>',
    "imprimir": '<path d="M7 9V4h10v5M7 17H5a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-2"/><rect x="7" y="14" width="10" height="6" rx="1"/>',
    "escudo": '<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/>',
    "cadena": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "llave": '<circle cx="8" cy="15" r="4"/><path d="M11 12l8-8M16 7l2 2M14 9l2 2"/>',
    "ajustes": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>',
}

NAV = {
    "cliente": [("cliente.inicio", "Inicio", "inicio", None), ("cliente.cartera", "Cartera", "cartera", None),
                ("cliente.invertir", "Invertir", "invertir", None), ("cliente.movimientos", "Movimientos", "movimientos", None),
                ("cliente.perfil", "Perfil", "perfil", None)],
    "equipo": [("equipo.resumen", "Resumen", "resumen", None), ("equipo.operaciones", "Operaciones", "operaciones", None),
               ("equipo.clientes", "Clientes", "clientes", None),
               ("equipo.cumplimiento", "Cumplimiento", "cumplimiento", "cumplimiento.ver"),
               ("admin.precios", "Ajustes", "ajustes", "precios.editar")],
}
ACTIVO = {  # qué rutas marcan cada pestaña como activa
    "cliente.movimientos": ("cliente.movimientos", "cliente.estado_mensual"),
    "equipo.operaciones": ("equipo.operaciones", "equipo.operacion"),
    "equipo.clientes": ("equipo.clientes", "equipo.cliente", "equipo.cliente_nuevo", "equipo.estado_mensual"),
    "equipo.cumplimiento": ("equipo.cumplimiento", "equipo.bitacora", "equipo.documentos", "equipo.conciliacion"),
    "admin.precios": ("admin.precios", "admin.usuarios", "admin.comisiones"),
}


def zona():
    return ZoneInfo(current_app.config["ZONA_HORARIA"])


def f_fecha(iso_txt, con_hora=True):
    if not iso_txt:
        return "—"
    d = tiempo.leer(iso_txt).astimezone(zona())
    base = f"{d.day} {MESES[d.month - 1]} {d.year}"
    return f"{base}, {d.hour:02d}:{d.minute:02d}" if con_hora else base


def f_hace(iso_txt):
    if not iso_txt:
        return "—"
    m = tiempo.minutos_desde(iso_txt)
    if m < 1:
        return "hace instantes"
    if m < 60:
        return f"hace {int(m)} min"
    if m < 60 * 24:
        return f"hace {int(m // 60)} h"
    return f"hace {int(m // 1440)} d"


def f_pct(valor, decimales=2, signo=True):
    if valor is None:
        return "—"
    d = Decimal(str(valor))
    s = dinero.fmt_num(d, decimales) + "%"
    return ("+" + s) if signo and d > 0 else s


def iniciales(nombre):
    partes = [p for p in (nombre or "").split() if p[:1].isalpha()]
    return ("".join(p[0] for p in partes[:2]) or "?").upper()


def icono(nombre):
    return Markup('<svg viewBox="0 0 24 24" aria-hidden="true" class="ico">' + ICONOS.get(nombre, "") + "</svg>")


def navegacion():
    u = g.get("usuario")
    if not u or u["debe_cambiar_clave"]:
        return []
    grupo = "cliente" if u["rol"] == "cliente" else "equipo"
    out = []
    for ep, texto, ico, permiso in NAV[grupo]:
        if permiso and not seguridad.puede(permiso):
            continue
        activo = request.endpoint in ACTIVO.get(ep, (ep,))
        cuenta = 0
        if ep == "equipo.operaciones":
            from . import db
            cuenta = db.uno("SELECT COUNT(*) AS n FROM operaciones WHERE estado IN ('pendiente', 'primera_firma')")["n"]
        out.append({"url": url_for(ep), "texto": texto, "icono": ico, "activo": activo, "cuenta": cuenta})
    return out


def avisos_no_leidos():
    u = g.get("usuario")
    if not u:
        return 0
    from . import notificaciones
    return notificaciones.no_leidas(u["id"])


def periodo_txt(periodo):
    a, m = periodo.split("-")
    return f"{MESES_LARGOS[int(m) - 1]} de {a}"


def init_app(app):
    app.jinja_env.filters.update(
        usd=lambda c, d=2: dinero.fmt_usd(c or 0, d),
        precio=dinero.fmt_precio,
        unidades=dinero.fmt_unidades,
        pct=f_pct,
        fecha=f_fecha,
        dia=lambda s: f_fecha(s, False),
        hace=f_hace,
    )
    app.jinja_env.filters["periodo"] = periodo_txt
    app.jinja_env.globals.update(ROLES=ROLES, ESTADOS=ESTADOS, KYC=KYC, PERFILES=PERFILES, TIPOS_OP=TIPOS_OP,
                                 iniciales=iniciales, icono=icono, navegacion=navegacion, avisos_no_leidos=avisos_no_leidos,
                                 VERSION=VERSION, ahora=tiempo.ahora)
