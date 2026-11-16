"""Monitoreo antilavado (hallazgo S-06): reglas automáticas, personas expuestas políticamente y listas de sanciones.

Las reglas no bloquean ni deciden nada por sí solas: generan alertas en una cola para el oficial de cumplimiento,
que las descarta con una nota o las marca como reportadas (ROS a la SEPRELAD). La única excepción es una
coincidencia con una lista de sanciones: mientras esa alerta siga abierta, no se aprueban operaciones del cliente.

Las listas (ONU, OFAC u otras) se cargan desde un CSV con `flask antilavado importar-lista`, porque la plataforma
no descarga nada por su cuenta. Columnas: nombre, documento, pais, referencia.
"""
import csv
import difflib
import unicodedata
from datetime import timedelta

import click
from flask import current_app
from flask.cli import with_appcontext

from . import auditoria, db, notificaciones
from .tiempo import ahora, ahora_dt, iso, leer

NIVELES = {"media": "Media", "alta": "Alta", "critica": "Crítica"}
REGLAS = {
    "monto_alto": "Operación igual o mayor al umbral",
    "fraccionamiento": "Depósitos fraccionados bajo el umbral",
    "entrada_salida": "Entrada y salida rápida de fondos",
    "envios_multiples": "Envíos a muchos destinatarios",
    "pep": "Persona expuesta políticamente",
    "sancion": "Coincidencia con lista de sanciones",
}


def normalizar(nombre):
    t = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower()
    t = "".join(ch if ch.isalnum() else " " for ch in t)
    return " ".join(sorted(p for p in t.split() if len(p) > 1))


def _doc(d):
    return "".join(ch for ch in (d or "").upper() if ch.isalnum())


def alertar(c, cliente_id, regla, nivel, detalle, ref):
    """Inserta una alerta si no existía la misma (regla, ref). Devuelve True si es nueva. c: conexión en transacción."""
    cur = c.execute("INSERT OR IGNORE INTO alertas_aml (cliente_id, regla, nivel, detalle, ref, creada) VALUES (?, ?, ?, ?, ?, ?)",
                    (cliente_id, regla, nivel, detalle, ref, ahora()))
    return cur.rowcount == 1


def coincidencias(nombre, documento):
    """Busca a una persona en las listas cargadas. Devuelve [(fila, motivo)]."""
    out = []
    doc = _doc(documento)
    if doc:
        for f in db.todos("SELECT * FROM listas_sanciones WHERE documento = ?", (doc,)):
            out.append((f, "documento idéntico"))
    norm = normalizar(nombre)
    if norm:
        primera = norm.split()[0]
        for f in db.todos("SELECT * FROM listas_sanciones WHERE nombre_norm LIKE ?", (f"%{primera}%",)):
            if any(f["id"] == x["id"] for x, _ in out):
                continue
            r = difflib.SequenceMatcher(None, norm, f["nombre_norm"]).ratio()
            if r >= 0.88:
                out.append((f, f"nombre similar ({r:.0%})"))
    return out


def evaluar(cliente_id):
    """Corre todas las reglas para un cliente. Devuelve la cantidad de alertas nuevas."""
    cli = db.uno("SELECT * FROM clientes WHERE id = ?", (cliente_id,))
    if not cli:
        return 0
    from . import niveles
    umbral = niveles.cent("UMBRAL_AML_USD")
    nuevas = []
    ops = db.todos("SELECT * FROM operaciones WHERE cliente_id = ? AND estado NOT IN ('rechazada', 'cancelada')"
                   " AND creado >= ? ORDER BY creado", (cliente_id, iso(ahora_dt() - timedelta(days=30))))
    envios = db.todos("SELECT * FROM transferencias WHERE de_cliente = ? AND ts >= ? ORDER BY ts",
                      (cliente_id, iso(ahora_dt() - timedelta(days=7))))
    with db.transaccion() as c:
        for o in ops:
            if o["tipo"] in ("aporte", "retiro") and o["monto_cent"] >= umbral:
                if alertar(c, cliente_id, "monto_alto", "alta",
                           f"{'Depósito' if o['tipo'] == 'aporte' else 'Retiro'} #{o['id']} de US$ {o['monto_cent'] / 100:,.2f}.", f"op:{o['id']}"):
                    nuevas.append("monto_alto")
        aportes = [o for o in ops if o["tipo"] == "aporte"]
        for i, o in enumerate(aportes):
            t0 = leer(o["creado"])
            ventana = [a for a in aportes[i:] if leer(a["creado"]) - t0 <= timedelta(days=7)]
            if len(ventana) >= 3 and all(a["monto_cent"] < umbral for a in ventana) and sum(a["monto_cent"] for a in ventana) >= umbral:
                if alertar(c, cliente_id, "fraccionamiento", "alta",
                           f"{len(ventana)} depósitos en 7 días que suman US$ {sum(a['monto_cent'] for a in ventana) / 100:,.2f},"
                           " cada uno por debajo del umbral.", f"frac:{o['id']}"):
                    nuevas.append("fraccionamiento")
                break
        salidas = [(o["creado"], o["monto_cent"], f"retiro #{o['id']}") for o in ops if o["tipo"] == "retiro"]
        salidas += [(e["ts"], e["valor_cent"], f"envío #{e['id']}") for e in envios]
        for a in aportes:
            ta = leer(a["creado"])
            sale = sum(m for ts, m, _ in salidas if timedelta(0) <= leer(ts) - ta <= timedelta(hours=72))
            if a["monto_cent"] >= 100000 and sale >= a["monto_cent"] * 0.8:
                if alertar(c, cliente_id, "entrada_salida", "media",
                           f"Salió el {sale / a['monto_cent']:.0%} del depósito #{a['id']} en menos de 72 horas.", f"es:{a['id']}"):
                    nuevas.append("entrada_salida")
        destinos = {e["a_cliente"] for e in envios if leer(e["ts"]) >= ahora_dt() - timedelta(hours=24)}
        if len(destinos) >= 5:
            if alertar(c, cliente_id, "envios_multiples", "media", f"Envíos a {len(destinos)} clientes distintos en 24 horas.",
                       f"env:{cliente_id}:{ahora()[:10]}"):
                nuevas.append("envios_multiples")
        if cli["pep"]:
            if alertar(c, cliente_id, "pep", "media", "Cliente declarado como persona expuesta políticamente"
                       + (f" ({cli['pep_cargo']})" if cli["pep_cargo"] else "") + ": requiere debida diligencia reforzada.",
                       f"pep:{cliente_id}"):
                nuevas.append("pep")
    for fila, motivo in coincidencias(cli["nombre"], cli["documento"]):
        with db.transaccion() as c:
            if alertar(c, cliente_id, "sancion", "critica", f"Posible coincidencia con «{fila['nombre']}» de la lista {fila['lista']}"
                       f" ({motivo}). No se aprueban operaciones hasta que Cumplimiento lo resuelva.", f"san:{cliente_id}:{fila['id']}"):
                nuevas.append("sancion")
    if nuevas:
        if "sancion" in nuevas or "monto_alto" in nuevas:
            db.ejecutar("UPDATE clientes SET riesgo_aml = 'alto' WHERE id = ?", (cliente_id,))
        notificaciones.notificar_rol(("cumplimiento", "admin"), f"Antilavado: {len(nuevas)} alerta(s) nueva(s) sobre {cli['nombre']}.",
                                     "/equipo/antilavado")
    return len(nuevas)


def bloqueado(cliente_id):
    """True si hay una coincidencia con listas de sanciones sin resolver."""
    return bool(db.uno("SELECT 1 FROM alertas_aml WHERE cliente_id = ? AND regla = 'sancion' AND estado = 'abierta'", (cliente_id,)))


def resolver(alerta_id, estado, nota, usuario):
    if estado not in ("descartada", "reportada"):
        raise ValueError("Estado inválido.")
    nota = (nota or "").strip()[:500]
    if len(nota) < 5:
        raise ValueError("Escribe por qué tomas esta decisión: queda en la bitácora.")
    a = db.uno("SELECT * FROM alertas_aml WHERE id = ?", (alerta_id,))
    if not a or a["estado"] != "abierta":
        raise ValueError("La alerta ya fue resuelta.")
    ts = ahora()
    db.ejecutar("UPDATE alertas_aml SET estado = ?, nota = ?, resuelta = ?, resuelta_por = ? WHERE id = ?",
                (estado, nota, ts, usuario["id"], alerta_id))
    auditoria.registrar(f"aml.{estado}", f"cliente:{a['cliente_id']}",
                        {"texto": f"Alerta antilavado #{alerta_id} ({REGLAS.get(a['regla'], a['regla'])}) {estado}: {nota}"},
                        usuario=usuario, ts=ts)


def abiertas(limite=200):
    return db.todos("SELECT a.*, c.nombre, c.documento FROM alertas_aml a JOIN clientes c ON c.id = a.cliente_id"
                    " WHERE a.estado = 'abierta' ORDER BY CASE a.nivel WHEN 'critica' THEN 0 WHEN 'alta' THEN 1 ELSE 2 END, a.creada DESC"
                    " LIMIT ?", (limite,))


def resueltas(limite=100):
    return db.todos("SELECT a.*, c.nombre, u.nombre AS por FROM alertas_aml a JOIN clientes c ON c.id = a.cliente_id"
                    " LEFT JOIN usuarios u ON u.id = a.resuelta_por WHERE a.estado != 'abierta' ORDER BY a.resuelta DESC LIMIT ?", (limite,))


def importar_lista(ruta, lista):
    n = 0
    ts = ahora()
    with open(ruta, encoding="utf-8-sig", newline="") as f, db.transaccion() as c:
        c.execute("DELETE FROM listas_sanciones WHERE lista = ?", (lista,))
        for fila in csv.DictReader(f):
            nombre = (fila.get("nombre") or "").strip()
            if not nombre:
                continue
            c.execute("INSERT INTO listas_sanciones (lista, nombre, nombre_norm, documento, pais, referencia, cargada)"
                      " VALUES (?, ?, ?, ?, ?, ?, ?)", (lista, nombre, normalizar(nombre), _doc(fila.get("documento")) or None,
                                                         (fila.get("pais") or "").strip() or None,
                                                         (fila.get("referencia") or "").strip() or None, ts))
            n += 1
    auditoria.registrar("aml.lista", None, {"texto": f"Lista de sanciones {lista} cargada con {n} registros."})
    return n


def revisar_todos():
    return sum(evaluar(c["id"]) for c in db.todos("SELECT id FROM clientes"))


@click.group("antilavado")
def cmd_antilavado():
    """Monitoreo antilavado: listas y reglas."""


@cmd_antilavado.command("importar-lista")
@click.argument("archivo")
@click.option("--lista", required=True, help="Nombre de la lista, por ejemplo ONU u OFAC.")
@with_appcontext
def cmd_importar(archivo, lista):
    """Carga una lista de sanciones desde un CSV (nombre, documento, pais, referencia) y revisa a todos los clientes."""
    n = importar_lista(archivo, lista.upper())
    click.echo(f"{n} registros cargados en la lista {lista.upper()}. Revisando clientes…")
    click.echo(f"{revisar_todos()} alertas nuevas.")


@cmd_antilavado.command("revisar")
@with_appcontext
def cmd_revisar():
    """Corre las reglas sobre todos los clientes (conviene programarlo cada hora)."""
    click.echo(f"{revisar_todos()} alertas nuevas.")
