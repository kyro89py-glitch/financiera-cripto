-- v0.30: control dual de acciones críticas e incidencias del equipo.
CREATE TABLE IF NOT EXISTS autorizaciones (
  id INTEGER PRIMARY KEY,
  accion TEXT NOT NULL,
  detalle TEXT NOT NULL,                 -- JSON con lo que se va a ejecutar
  resumen TEXT NOT NULL,                 -- descripción legible de lo pedido
  motivo TEXT NOT NULL,
  estado TEXT NOT NULL DEFAULT 'pendiente'
    CHECK (estado IN ('pendiente', 'ejecutada', 'rechazada', 'cancelada', 'vencida', 'fallida')),
  solicitada_por INTEGER NOT NULL REFERENCES usuarios(id),
  solicitada TEXT NOT NULL,
  vence TEXT NOT NULL,
  resuelta_por INTEGER REFERENCES usuarios(id),
  resuelta TEXT,
  nota TEXT,
  resultado TEXT
);
CREATE INDEX IF NOT EXISTS ix_autorizaciones_estado ON autorizaciones(estado, solicitada);

CREATE TABLE IF NOT EXISTS incidencias (
  id INTEGER PRIMARY KEY,
  titulo TEXT NOT NULL,
  descripcion TEXT NOT NULL,
  categoria TEXT NOT NULL CHECK (categoria IN ('tecnica', 'seguridad', 'operaciones', 'cumplimiento', 'cliente')),
  severidad TEXT NOT NULL CHECK (severidad IN ('baja', 'media', 'alta', 'critica')),
  estado TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'en_curso', 'resuelta', 'cerrada')),
  cliente_id INTEGER REFERENCES clientes(id),
  asignada_a INTEGER REFERENCES usuarios(id),
  creada_por INTEGER NOT NULL REFERENCES usuarios(id),
  creada TEXT NOT NULL,
  actualizada TEXT NOT NULL,
  resuelta TEXT
);
CREATE INDEX IF NOT EXISTS ix_incidencias_estado ON incidencias(estado, severidad);

CREATE TABLE IF NOT EXISTS incidencias_notas (
  id INTEGER PRIMARY KEY,
  incidencia_id INTEGER NOT NULL REFERENCES incidencias(id),
  usuario_id INTEGER REFERENCES usuarios(id),
  texto TEXT NOT NULL,
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_incidencias_notas ON incidencias_notas(incidencia_id, id);
