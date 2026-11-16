"""Filtros y ayudas para las plantillas."""
from datetime import datetime
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
    "ejecutando": ("warn", "En ejecución"),
    "liquidada": ("ok", "Liquidada"),
    "rechazada": ("bad", "Rechazada"),
    "cancelada": ("", "Cancelada"),
}
KYC = {"verificado": ("ok", "Identidad verificada"), "pendiente": ("warn", "Verificación pendiente"),
       "observado": ("bad", "Verificación observada")}
PERFILES = {"conservador": "Conservador", "moderado": "Moderado", "arriesgado": "Arriesgado"}
TIPOS_OP = {"aporte": "Aporte", "retiro": "Retiro", "comision": "Comisión de gestión", "compra": "Compra", "venta": "Venta"}

ICONOS = {
    "enviar": '<path d="M4 12l16-8-6 16-2.5-6.5z"/><path d="M11.5 13.5L20 4"/>',
    "mercado": '<path d="M4 19V5M4 19h16M8 15l3-4 3 2 5-7"/>',
    "billetera": '<path d="M4 7a2 2 0 0 1 2-2h11v4M4 7v10a2 2 0 0 0 2 2h13a1 1 0 0 0 1-1v-8a1 1 0 0 0-1-1H6a2 2 0 0 1-2-2z"/><circle cx="16" cy="14" r="1.2"/>',
    "estrella": '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.3-4.1 5.9-.9z"/>',
    "tema": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
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

ICONOS["trading"] = ('<path d="M7 3v4M7 17v4M17 3v7M17 18v3"/><rect x="5" y="7" width="4" height="10" rx="1"/>'
                     '<rect x="15" y="10" width="4" height="8" rx="1"/>')
ICONOS["retiro"] = '<circle cx="12" cy="12" r="8.5"/><path d="M12 8v8M8.5 12.5L12 16l3.5-3.5"/>'
ICONOS["convertir"] = '<path d="M7 7h11l-3-3M17 17H6l3 3"/>'
ICONOS["ojo"] = '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'
ICONOS["dispositivo"] = '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>'
ICONOS["buscar"] = '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>'

NAV = {
    "cliente": [("cliente.inicio", "Inicio", "inicio", None), ("auth.mercado", "Mercados", "mercado", None),
                ("auth.trading", "Trading", "trading", None), ("cliente.cartera", "Billetera", "billetera", None),
                ("cliente.perfil", "Perfil", "perfil", None),
                ("cliente.analisis_cartera", "Análisis", "resumen", "sec"), ("auth.academia", "Academia", "documento", "sec"),
                ("cliente.earn", "Earn", "invertir", "sec"), ("cliente.ayuda", "Ayuda", "campana", "sec")],
    "equipo": [("equipo.resumen", "Resumen", "resumen", None), ("auth.mercado", "Mercados", "mercado", None),
               ("auth.trading", "Trading", "trading", None),
               ("equipo.operaciones", "Operaciones", "operaciones", None),
               ("equipo.clientes", "Clientes", "clientes", None),
               ("equipo.soporte", "Soporte", "campana", "soporte.atender"),
               ("equipo.cumplimiento", "Cumplimiento", "cumplimiento", "cumplimiento.ver"),
               ("admin.precios", "Ajustes", "ajustes", "precios.editar")],
}
ACTIVO = {  # qué rutas marcan cada pestaña como activa
    "auth.mercado": ("auth.mercado", "auth.moneda"),
    "cliente.cartera": ("cliente.cartera", "cliente.invertir", "cliente.convertir", "cliente.enviar", "cliente.movimientos",
                        "cliente.estado_mensual", "cliente.movimiento", "cliente.envio", "cliente.retirar"),
    "cliente.perfil": ("cliente.perfil", "auth.seguridad", "auth.clave", "auth.sesiones", "auth.centro_seguridad", "auth.avisos"),
    "auth.academia": ("auth.academia", "auth.leccion"),
    "cliente.ayuda": ("cliente.ayuda", "cliente.consulta"),
    "equipo.soporte": ("equipo.soporte", "equipo.soporte_consulta"),
    "equipo.operaciones": ("equipo.operaciones", "equipo.operacion"),
    "equipo.clientes": ("equipo.clientes", "equipo.cliente", "equipo.cliente_nuevo", "equipo.estado_mensual"),
    "equipo.cumplimiento": ("equipo.cumplimiento", "equipo.bitacora", "equipo.documentos", "equipo.conciliacion", "equipo.antilavado",
                            "equipo.verificar_comprobante"),
    "admin.precios": ("admin.precios", "admin.usuarios", "admin.comisiones", "admin.ejecucion", "admin.guaranies", "admin.respaldos"),
}


def _idem():
    from .limites import nueva_clave
    return nueva_clave()


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


def compacto(valor, moneda=True):
    """Montos grandes abreviados: US$ 1,30 B (billones), US$ 49,17 mil M, US$ 345,7 M."""
    if valor is None:
        return "—"
    v = float(valor)
    for limite, sufijo, dec in ((1e12, " B", 2), (1e9, " mil M", 2), (1e6, " M", 1), (1e3, " mil", 1)):
        if abs(v) >= limite:
            texto = dinero.fmt_num(Decimal(str(round(v / limite, dec))), dec) + sufijo
            break
    else:
        texto = dinero.fmt_num(Decimal(str(round(v, 2))), 2)
    return ("US$ " if moneda else "") + texto


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
        sec = permiso == "sec"  # secundaria: se ve en la barra lateral de escritorio y en «Más» del perfil en el celular
        if permiso and not sec and not seguridad.puede(permiso):
            continue
        activo = request.endpoint in ACTIVO.get(ep, (ep,))
        cuenta = 0
        if ep == "equipo.operaciones":
            from . import db
            cuenta = db.uno("SELECT COUNT(*) AS n FROM operaciones WHERE estado IN ('pendiente', 'primera_firma', 'ejecutando')")["n"]
        if ep == "equipo.soporte":
            from . import db
            cuenta = db.uno("SELECT COUNT(*) AS n FROM consultas WHERE estado = 'abierta'")["n"]
        out.append({"url": url_for(ep), "texto": texto, "icono": ico, "activo": activo, "cuenta": cuenta, "sec": sec})
    return out


def cinta():
    """Precios vigentes para la cinta superior."""
    from . import precios
    try:
        vig = precios.vigentes()
        orden = [a["codigo"] for a in precios.activos(solo_habilitados=True)]
    except Exception:
        return []
    return [{"codigo": a, "precio": vig[a]["precio"], "cambio": vig[a]["cambio"]} for a in orden if a in vig]


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
    from . import guarani
    app.jinja_env.filters["gs"] = guarani.fmt
    app.jinja_env.filters["compacto"] = compacto

    def detalle_txt(d):
        import json
        try:
            return json.loads(d).get("texto") or "Acción registrada"
        except (ValueError, TypeError, AttributeError):
            return d or "Acción registrada"
    app.jinja_env.filters["detalle_txt"] = detalle_txt
    app.jinja_env.filters["hora_ms"] = lambda s: datetime.fromtimestamp(s, zona()).strftime("%H:%M:%S")
    app.jinja_env.filters["fecha_ms"] = lambda s: (lambda d: f"{d.day} {MESES_LARGOS[d.month - 1][:3]}")(datetime.fromtimestamp(s, zona()))
    app.jinja_env.filters["precio_f"] = lambda v: dinero.fmt_precio(Decimal(str(v))) if v is not None else "—"
    app.jinja_env.filters["cantidad_f"] = lambda v: (f"{float(v):,.6f}".rstrip("0").rstrip(".")).replace(",", "X").replace(".", ",").replace("X", ".")

    def en_gs(cent):
        """Equivalente en guaraníes de un importe en dólares, o None si no hay tipo de cambio cargado."""
        ref = guarani.referencia()
        return guarani.fmt(guarani.de_usd_cent(cent or 0, ref)) if ref else None
    from .transferencias import ocultar
    app.jinja_env.globals.update(en_gs=en_gs, cambios_pyg=guarani.cambios, ocultar=ocultar,
                                 ahora_local=lambda: datetime.now(zona()), idem=_idem)
    app.jinja_env.globals.update(ROLES=ROLES, ESTADOS=ESTADOS, KYC=KYC, PERFILES=PERFILES, TIPOS_OP=TIPOS_OP,
                                 iniciales=iniciales, icono=icono, navegacion=navegacion, avisos_no_leidos=avisos_no_leidos, cinta=cinta,
                                 VERSION=VERSION, ahora=tiempo.ahora)
