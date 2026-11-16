-- v0.20 · centro de ayuda: consultas con seguimiento entre el cliente y el equipo.
CREATE TABLE IF NOT EXISTS consultas (
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
  cliente_id INTEGER REFERENCES clientes(id),
  categoria TEXT NOT NULL,
  asunto TEXT NOT NULL,
  estado TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'respondida', 'cerrada')),
  creada TEXT NOT NULL,
  actualizada TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_consultas_usuario ON consultas(usuario_id, actualizada);
CREATE INDEX IF NOT EXISTS ix_consultas_estado ON consultas(estado, actualizada);
CREATE TABLE IF NOT EXISTS consulta_mensajes (
  id INTEGER PRIMARY KEY,
  consulta_id INTEGER NOT NULL REFERENCES consultas(id),
  autor_id INTEGER NOT NULL REFERENCES usuarios(id),
  del_equipo INTEGER NOT NULL DEFAULT 0,
  texto TEXT NOT NULL,
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_consulta_mensajes ON consulta_mensajes(consulta_id, id);
