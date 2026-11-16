"""Observabilidad y recuperación ante fallos.

- Cada solicitud recibe un identificador (cabecera X-Request-ID) que aparece en los registros y en las páginas de
  error, para que soporte encuentre el problema exacto.
- Registro estructurado de cada solicitud: método, ruta, estado, duración y usuario (nunca datos personales).
- /salud: estado de la base, frescura de precios, ejecución, respaldos y correos, para monitores externos.
- /metricas: métricas en formato Prometheus, solo con METRICAS_TOKEN.
- `flask recuperar`: retoma las ejecuciones que quedaron a medias si el proceso se cortó.
"""
import json
import logging
import re
import secrets
import threading
import time
from datetime import datetime, timezone

import click
from flask import current_app, g, request
from flask.cli import with_appcontext

from . import db

BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5)
_lock = threading.Lock()
log = logging.getLogger("financiera.solicitudes")


def _metricas():
    return current_app.extensions.setdefault("metricas", {"solicitudes": {}, "duracion": [0] * (len(BUCKETS) + 1),
                                                          "suma": 0.0, "total": 0, "inicio": time.time()})


def _edad_minutos(ts_texto):
    try:
        t = datetime.fromisoformat(ts_texto)
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 60


def chequeos():
    """Devuelve (estado, detalle). estado: 'ok', 'degradado' o 'falla'."""
    from . import ejecucion
    det, estado = {}, "ok"
    try:
        db.uno("SELECT 1 AS x")
        det["base"] = "ok"
    except Exception as e:  # noqa: BLE001 - el monitor necesita saber cualquier falla
        return "falla", {"base": f"error: {e.__class__.__name__}"}
    ult = db.uno("SELECT MAX(ts) AS ts FROM precios")
    edad = _edad_minutos(ult["ts"]) if ult and ult["ts"] else None
    det["precios_min"] = round(edad, 1) if edad is not None else None
    if edad is None or edad > current_app.config["PRECIO_MAX_MINUTOS"]:
        estado = "degradado"
        det["precios"] = "desactualizados: no se ejecutan operaciones hasta que vuelvan"
    det["ejecucion"] = "pausada" if ejecucion.pausada() else "activa"
    det["ejecuciones_incompletas"] = len(ejecucion.incompletas())
    r = db.uno("SELECT creado, prueba_ok FROM respaldos ORDER BY id DESC LIMIT 1")
    det["ultimo_respaldo_h"] = round(_edad_minutos(r["creado"]) / 60, 1) if r and _edad_minutos(r["creado"]) is not None else None
    if current_app.config["ENTORNO"] == "produccion" and (det["ultimo_respaldo_h"] is None or det["ultimo_respaldo_h"] > 26):
        estado = "degradado"
        det["respaldos"] = "sin respaldo en las últimas 26 horas"
    det["correos_pendientes"] = db.uno("SELECT COUNT(*) AS n FROM correos WHERE estado = 'pendiente'")["n"]
    return estado, det


def init_app(app):
    log.setLevel(logging.INFO)

    @app.before_request
    def _rid():
        entrante = request.headers.get("X-Request-ID", "")
        g.rid = entrante if re.fullmatch(r"[A-Za-z0-9._-]{8,64}", entrante) else secrets.token_hex(8)
        g.t0 = time.perf_counter()

    @app.after_request
    def _registrar(resp):
        dur = time.perf_counter() - g.get("t0", time.perf_counter())
        resp.headers["X-Request-ID"] = g.get("rid", "")
        m = _metricas()
        clase = f"{resp.status_code // 100}xx"
        with _lock:
            m["solicitudes"][clase] = m["solicitudes"].get(clase, 0) + 1
            m["total"] += 1
            m["suma"] += dur
            i = next((k for k, b in enumerate(BUCKETS) if dur <= b), len(BUCKETS))
            m["duracion"][i] += 1
        if not request.path.startswith("/static/") and current_app.config["ENTORNO"] != "pruebas":
            u = g.get("usuario")
            log.info(json.dumps({"rid": g.get("rid"), "metodo": request.method, "ruta": request.path, "estado": resp.status_code,
                                 "ms": round(dur * 1000, 1), "usuario": u["id"] if u else None}, ensure_ascii=False))
        return resp

    @app.teardown_request
    def _excepcion(exc):
        if exc is not None:
            log.error(json.dumps({"rid": g.get("rid"), "ruta": request.path, "error": exc.__class__.__name__}))

    @app.get("/salud")
    def salud():
        estado, det = chequeos()
        from .version import VERSION
        return {"estado": estado, "version": VERSION, **det}, (503 if estado == "falla" else 200), \
            {"Cache-Control": "no-store"}

    @app.get("/metricas")
    def metricas():
        token = current_app.config.get("METRICAS_TOKEN") or ""
        enviado = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if not token or not secrets.compare_digest(token, enviado):
            return "No encontrado", 404
        m = _metricas()
        estado, det = chequeos()
        lineas = ["# TYPE fc_solicitudes_total counter"]
        lineas += [f'fc_solicitudes_total{{clase="{k}"}} {v}' for k, v in sorted(m["solicitudes"].items())]
        lineas.append("# TYPE fc_solicitud_segundos histogram")
        acum = 0
        for b, n in zip(BUCKETS + ("+Inf",), m["duracion"]):
            acum += n
            lineas.append(f'fc_solicitud_segundos_bucket{{le="{b}"}} {acum}')
        lineas += [f"fc_solicitud_segundos_sum {m['suma']:.4f}", f"fc_solicitud_segundos_count {m['total']}"]
        ops = db.todos("SELECT estado, COUNT(*) AS n FROM operaciones GROUP BY estado")
        lineas.append("# TYPE fc_operaciones gauge")
        lineas += [f'fc_operaciones{{estado="{o["estado"]}"}} {o["n"]}' for o in ops]
        lineas.append("# TYPE fc_precios_edad_minutos gauge")
        lineas.append(f"fc_precios_edad_minutos {det.get('precios_min') if det.get('precios_min') is not None else -1}")
        lineas.append("# TYPE fc_alertas_aml_abiertas gauge")
        aml = db.uno("SELECT COUNT(*) AS n FROM alertas_aml WHERE estado = 'abierta'")["n"]
        lineas.append(f"fc_alertas_aml_abiertas {aml}")
        lineas.append("# TYPE fc_salud gauge")
        lineas.append(f"fc_salud {dict(ok=2, degradado=1).get(estado, 0)}")
        lineas.append(f"fc_proceso_segundos {time.time() - m['inicio']:.0f}")
        return "\n".join(lineas) + "\n", 200, {"Content-Type": "text/plain; version=0.0.4"}


def recuperar(antiguedad_seg=60):
    """Retoma las ejecuciones 'ejecutando' más viejas que antiguedad_seg. Devuelve [(id, resultado)]."""
    from . import ejecucion
    out = []
    for op in ejecucion.incompletas():
        edad = _edad_minutos(op["ejecucion_inicio"])
        if edad is not None and edad * 60 < antiguedad_seg:
            continue
        try:
            out.append((op["id"], ejecucion.continuar(op["id"])))
        except ejecucion.ErrorEjecucion as e:
            out.append((op["id"], f"sigue pendiente: {e}"))
    return out


@click.command("recuperar")
@click.option("--antiguedad", default=60, help="Segundos mínimos desde que empezó la ejecución.")
@with_appcontext
def cmd_recuperar(antiguedad):
    """Retoma las ejecuciones que quedaron a medias (por ejemplo, tras un corte del servidor)."""
    res = recuperar(antiguedad)
    if not res:
        click.echo("No hay ejecuciones a medias.")
    for opid, r in res:
        click.echo(f"Operación #{opid}: {r}")
