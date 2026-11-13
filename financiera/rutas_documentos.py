"""Descarga de documentos del legajo: solo el propio cliente o el equipo."""
from flask import Blueprint, abort, g, send_file

from . import auditoria, db, documentos, seguridad

bp = Blueprint("documentos", __name__)


@bp.get("/documentos/<int:did>")
def ver(did):
    r = seguridad.exigir_sesion()
    if r:
        return r
    d = db.uno("SELECT d.*, c.usuario_id, c.nombre, c.tipo AS tipo_cliente FROM documentos d"
               " JOIN clientes c ON c.id = d.cliente_id WHERE d.id = ?", (did,))
    if not d:
        abort(404)
    propio = g.usuario["rol"] == "cliente" and d["usuario_id"] == g.usuario["id"]
    if not propio and not seguridad.puede("equipo.ver"):
        abort(404)
    if not propio:
        auditoria.registrar("documento.consultado", f"documento:{did}",
                            {"texto": f"Abrió «{documentos.nombre_tipo(d['tipo_cliente'], d['tipo'])}» de {d['nombre']}."})
    resp = send_file(documentos.ruta(d), mimetype=d["mime"], download_name=d["nombre_original"], as_attachment=False,
                     max_age=0, conditional=False)
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'"
    resp.headers["Cache-Control"] = "private, no-store"
    return resp
