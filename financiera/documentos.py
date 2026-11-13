"""Legajo del cliente: documentos subidos, revisión y requisitos para verificar la identidad."""
import hashlib
import os
import re
import uuid

from flask import current_app

from . import auditoria, db, notificaciones
from .tiempo import ahora

TIPOS = {
    "persona": [("identidad", "Documento de identidad (frente y dorso)"),
                ("domicilio", "Comprobante de domicilio"),
                ("ingresos", "Respaldo de ingresos u origen de los fondos")],
    "empresa": [("estatutos", "Estatutos y constancia de RUC"),
                ("representante", "Documento del representante legal"),
                ("ingresos", "Balance o respaldo del origen de los fondos")],
}
REQUERIDOS = {"persona": ("identidad", "domicilio"), "empresa": ("estatutos", "representante")}
FIRMAS = [(b"%PDF-", "application/pdf", "pdf"), (b"\x89PNG\r\n\x1a\n", "image/png", "png"), (b"\xff\xd8\xff", "image/jpeg", "jpg")]
ESTADOS = {"pendiente": ("warn", "En revisión"), "aceptado": ("ok", "Aceptado"), "rechazado": ("bad", "Rechazado")}


class ErrorDocumento(Exception):
    pass


def nombre_tipo(tipo_cliente, tipo):
    return dict(TIPOS.get(tipo_cliente, [])).get(tipo, tipo)


def carpeta():
    d = current_app.config["DOCUMENTOS_DIR"]
    os.makedirs(d, exist_ok=True)
    return d


def ruta(doc):
    return os.path.join(carpeta(), doc["archivo"])


def guardar(cliente, tipo, nombre, datos, usuario, ts=None):
    """Guarda un archivo del legajo. Solo acepta PDF, JPG o PNG reales (se revisa el contenido, no la extensión)."""
    if tipo not in dict(TIPOS[cliente["tipo"]]):
        raise ErrorDocumento("Elige qué documento estás subiendo.")
    maximo = current_app.config["DOCUMENTO_MAX_MB"] * 1024 * 1024
    if not datos:
        raise ErrorDocumento("El archivo está vacío.")
    if len(datos) > maximo:
        raise ErrorDocumento(f"El archivo supera los {current_app.config['DOCUMENTO_MAX_MB']} MB.")
    tipo_archivo = next(((m, ext) for firma, m, ext in FIRMAS if datos.startswith(firma)), None)
    if not tipo_archivo:
        raise ErrorDocumento("Solo se aceptan archivos PDF, JPG o PNG.")
    mime, ext = tipo_archivo
    original = re.sub(r"[^\w.\- ()áéíóúñÁÉÍÓÚÑ]", "_", os.path.basename(nombre or "documento"))[:120] or "documento"
    archivo = f"{uuid.uuid4().hex}.{ext}"
    destino = os.path.join(carpeta(), archivo)
    with open(destino, "xb") as f:
        f.write(datos)
    ts = ts or ahora()
    try:
        with db.transaccion() as c:
            cur = c.execute(
                "INSERT INTO documentos (cliente_id, tipo, nombre_original, archivo, mime, tamano, sha256, subido_por, subido_ts)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cliente["id"], tipo, original, archivo, mime, len(datos), hashlib.sha256(datos).hexdigest(),
                 usuario["id"] if usuario else None, ts))
            did = cur.lastrowid
            auditoria.registrar("documento.subido", f"documento:{did}",
                                {"texto": f"Subió «{nombre_tipo(cliente['tipo'], tipo)}» al legajo de {cliente['nombre']}.",
                                 "sha256": hashlib.sha256(datos).hexdigest()}, usuario=usuario, ts=ts)
    except BaseException:
        os.remove(destino)
        raise
    return did


def revisar(doc_id, estado, nota, usuario, ts=None):
    if estado not in ("aceptado", "rechazado"):
        raise ErrorDocumento("Elige si aceptas o rechazas el documento.")
    nota = (nota or "").strip()[:300]
    if estado == "rechazado" and len(nota) < 5:
        raise ErrorDocumento("Escribe por qué se rechaza; el cliente lo verá.")
    ts = ts or ahora()
    with db.transaccion() as c:
        d = c.execute("SELECT d.*, c.nombre, c.tipo AS tipo_cliente, c.usuario_id FROM documentos d"
                      " JOIN clientes c ON c.id = d.cliente_id WHERE d.id = ?", (doc_id,)).fetchone()
        if not d:
            raise ErrorDocumento("El documento no existe.")
        c.execute("UPDATE documentos SET estado = ?, nota = ?, revisado_por = ?, revisado_ts = ? WHERE id = ?",
                  (estado, nota or None, usuario["id"], ts, doc_id))
        tipo = nombre_tipo(d["tipo_cliente"], d["tipo"])
        auditoria.registrar("documento.revisado", f"documento:{doc_id}",
                            {"texto": f"{'Aceptó' if estado == 'aceptado' else 'Rechazó'} «{tipo}» de {d['nombre']}."
                             + (f" Nota: {nota}" if nota else ""), "estado": estado}, usuario=usuario, ts=ts)
        if d["usuario_id"]:
            texto = (f"Revisamos tu documento «{tipo}» y fue aceptado." if estado == "aceptado" else
                     f"Tu documento «{tipo}» fue rechazado: {nota}. Sube uno nuevo desde Mi perfil.")
            notificaciones.notificar(d["usuario_id"], texto, "/cliente/perfil", ts=ts)


def legajo(cliente):
    docs = db.todos("SELECT * FROM documentos WHERE cliente_id = ? ORDER BY subido_ts DESC, id DESC", (cliente["id"],))
    requeridos = REQUERIDOS[cliente["tipo"]]
    out = []
    for tipo, nombre in TIPOS[cliente["tipo"]]:
        lista = [d for d in docs if d["tipo"] == tipo]
        aceptado = any(d["estado"] == "aceptado" for d in lista)
        estado = "aceptado" if aceptado else (lista[0]["estado"] if lista else "falta")
        out.append({"tipo": tipo, "nombre": nombre, "requerido": tipo in requeridos, "docs": lista, "estado": estado})
    return out


def faltantes(cliente):
    """Documentos requeridos para verificar la identidad que todavía no tienen una versión aceptada."""
    return [x["nombre"] for x in legajo(cliente) if x["requerido"] and x["estado"] != "aceptado"]


def pendientes_revision():
    return db.todos("SELECT d.*, c.nombre, c.tipo AS tipo_cliente FROM documentos d JOIN clientes c ON c.id = d.cliente_id"
                    " WHERE d.estado = 'pendiente' ORDER BY d.subido_ts")


def pdf_ejemplo(texto):
    """PDF mínimo y válido, usado por los datos de demostración."""
    contenido = f"BT /F1 20 Tf 72 760 Td ({texto}) Tj 0 -30 Td /F1 12 Tf (Documento de ejemplo generado para la demostracion.) Tj ET".encode("latin-1")
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            b"<</Length " + str(len(contenido)).encode() + b">>stream\n" + contenido + b"\nendstream",
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    salida = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(salida))
        salida += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    salida += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    salida += f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return salida
