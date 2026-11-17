"""Incidencias del equipo: problemas técnicos, de seguridad, de operaciones, de cumplimiento o de un cliente, con responsable,
severidad, estado y una línea de tiempo de notas. Todo cambio queda también en la bitácora."""
from . import auditoria, db, notificaciones
from .tiempo import ahora

CATEGORIAS = {"tecnica": "Técnica", "seguridad": "Seguridad", "operaciones": "Operaciones", "cumplimiento": "Cumplimiento", "cliente": "Cliente"}
SEVERIDADES = {"baja": ("", "Baja"), "media": ("info", "Media"), "alta": ("warn", "Alta"), "critica": ("bad", "Crítica")}
ESTADOS = {"abierta": ("warn", "Abierta"), "en_curso": ("info", "En curso"), "resuelta": ("ok", "Resuelta"), "cerrada": ("", "Cerrada")}


class ErrorIncidencia(Exception):
    pass


def _equipo(uid):
    return db.uno("SELECT * FROM usuarios WHERE id = ? AND rol != 'cliente' AND activo = 1", (uid,)) if uid else None


def _nota(c, iid, uid, texto, ts):
    c.execute("INSERT INTO incidencias_notas (incidencia_id, usuario_id, texto, ts) VALUES (?, ?, ?, ?)", (iid, uid, texto, ts))


def crear(datos, usuario):
    titulo = " ".join((datos.get("titulo") or "").split())
    desc = (datos.get("descripcion") or "").strip()
    if not 5 <= len(titulo) <= 140:
        raise ErrorIncidencia("El título tiene que tener entre 5 y 140 caracteres.")
    if len(desc) < 10:
        raise ErrorIncidencia("Describe qué pasó (al menos 10 caracteres).")
    cat, sev = datos.get("categoria"), datos.get("severidad")
    if cat not in CATEGORIAS or sev not in SEVERIDADES:
        raise ErrorIncidencia("Elige categoría y severidad.")
    cliente_id = None
    if (datos.get("cliente") or "").strip():
        from . import transferencias
        c = transferencias.buscar(datos["cliente"])
        if not c:
            raise ErrorIncidencia("No encontramos a ese cliente (usa su correo, cédula, @usuario o identificador).")
        cliente_id = c["id"]
    asignada = _equipo(int(datos["asignada_a"])) if str(datos.get("asignada_a") or "").isdigit() else None
    ts = ahora()
    with db.transaccion() as c:
        iid = c.execute("INSERT INTO incidencias (titulo, descripcion, categoria, severidad, cliente_id, asignada_a, creada_por, creada, actualizada)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (titulo, desc[:4000], cat, sev, cliente_id, asignada["id"] if asignada else None,
                                                                usuario["id"], ts, ts)).lastrowid
        _nota(c, iid, usuario["id"], "Registró la incidencia" + (f" y la asignó a {asignada['nombre']}" if asignada else "") + ".", ts)
        auditoria.registrar("incidencia.creada", f"incidencia:{iid}", {"texto": f"Incidencia {SEVERIDADES[sev][1].lower()} ({CATEGORIAS[cat]}): {titulo}"},
                            usuario=usuario, ts=ts)
    if sev in ("alta", "critica"):
        notificaciones.notificar_rol(("admin", "cumplimiento"), f"Incidencia {SEVERIDADES[sev][1].lower()}: {titulo}", f"/equipo/incidencias/{iid}",
                                     excepto=usuario["id"])
    if asignada and asignada["id"] != usuario["id"]:
        notificaciones.notificar(asignada["id"], f"Te asignaron la incidencia «{titulo}».", f"/equipo/incidencias/{iid}", categoria="cuenta")
    return iid


def actualizar(iid, datos, usuario):
    i = db.uno("SELECT * FROM incidencias WHERE id = ?", (iid,))
    if not i:
        raise ErrorIncidencia("No existe.")
    cambios = []
    nuevo = {}
    if datos.get("estado") in ESTADOS and datos["estado"] != i["estado"]:
        if i["estado"] == "cerrada":
            raise ErrorIncidencia("La incidencia está cerrada. Abre una nueva si el problema volvió.")
        nuevo["estado"] = datos["estado"]
        cambios.append(f"estado: {ESTADOS[i['estado']][1]} → {ESTADOS[datos['estado']][1]}")
    if datos.get("severidad") in SEVERIDADES and datos["severidad"] != i["severidad"]:
        nuevo["severidad"] = datos["severidad"]
        cambios.append(f"severidad: {SEVERIDADES[i['severidad']][1]} → {SEVERIDADES[datos['severidad']][1]}")
    if "asignada_a" in datos:
        a = _equipo(int(datos["asignada_a"])) if str(datos.get("asignada_a") or "").isdigit() else None
        if (a["id"] if a else None) != i["asignada_a"]:
            nuevo["asignada_a"] = a["id"] if a else None
            cambios.append("asignada a " + (a["nombre"] if a else "nadie"))
    texto = (datos.get("nota") or "").strip()[:2000]
    if nuevo.get("estado") in ("resuelta", "cerrada") and not texto and not db.uno(
            "SELECT 1 FROM incidencias_notas WHERE incidencia_id = ? AND texto NOT LIKE 'Registró%' AND texto NOT LIKE 'Cambió%'", (iid,)):
        raise ErrorIncidencia("Para resolver o cerrar, deja una nota con lo que se hizo.")
    if not cambios and not texto:
        raise ErrorIncidencia("No hay cambios.")
    ts = ahora()
    with db.transaccion() as c:
        if nuevo:
            sets = ", ".join(f"{k} = ?" for k in nuevo)
            extra = ", resuelta = ?" if nuevo.get("estado") in ("resuelta", "cerrada") and not i["resuelta"] else ""
            vals = list(nuevo.values()) + ([ts] if extra else [])
            c.execute(f"UPDATE incidencias SET {sets}{extra}, actualizada = ? WHERE id = ?", (*vals, ts, iid))
        else:
            c.execute("UPDATE incidencias SET actualizada = ? WHERE id = ?", (ts, iid))
        if cambios:
            _nota(c, iid, usuario["id"], "Cambió " + "; ".join(cambios) + ".", ts)
        if texto:
            _nota(c, iid, usuario["id"], texto, ts)
        auditoria.registrar("incidencia.actualizada", f"incidencia:{iid}",
                            {"texto": f"«{i['titulo'][:60]}»: " + ("; ".join(cambios) if cambios else "agregó una nota") + "."}, usuario=usuario, ts=ts)
    if nuevo.get("asignada_a") and nuevo["asignada_a"] != usuario["id"]:
        notificaciones.notificar(nuevo["asignada_a"], f"Te asignaron la incidencia «{i['titulo']}».", f"/equipo/incidencias/{iid}", categoria="cuenta")


def listar(estado=None, severidad=None, cliente_id=None, limite=200):
    sql = ("SELECT i.*, a.nombre AS asignado, c.nombre AS cliente, (SELECT COUNT(*) FROM incidencias_notas n WHERE n.incidencia_id = i.id) AS notas"
           " FROM incidencias i LEFT JOIN usuarios a ON a.id = i.asignada_a LEFT JOIN clientes c ON c.id = i.cliente_id WHERE 1 = 1")
    args = []
    if estado == "activas":
        sql += " AND i.estado IN ('abierta', 'en_curso')"
    elif estado in ESTADOS:
        sql += " AND i.estado = ?"
        args.append(estado)
    if severidad in SEVERIDADES:
        sql += " AND i.severidad = ?"
        args.append(severidad)
    if cliente_id:
        sql += " AND i.cliente_id = ?"
        args.append(cliente_id)
    orden = " ORDER BY i.estado IN ('resuelta', 'cerrada'), CASE i.severidad WHEN 'critica' THEN 0 WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, i.actualizada DESC"
    return db.todos(sql + orden + " LIMIT ?", (*args, limite))


def detalle(iid):
    i = db.uno("SELECT i.*, a.nombre AS asignado, c.nombre AS cliente, u.nombre AS autor FROM incidencias i LEFT JOIN usuarios a ON a.id = i.asignada_a"
               " LEFT JOIN clientes c ON c.id = i.cliente_id JOIN usuarios u ON u.id = i.creada_por WHERE i.id = ?", (iid,))
    notas = db.todos("SELECT n.*, u.nombre FROM incidencias_notas n LEFT JOIN usuarios u ON u.id = n.usuario_id WHERE n.incidencia_id = ? ORDER BY n.id", (iid,))
    return i, notas
