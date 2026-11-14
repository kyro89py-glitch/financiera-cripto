-- Compra y venta libre de cada moneda por parte del cliente (tipos 'compra' y 'venta'), y lista de favoritos.
-- Se reconstruye la tabla de operaciones para ampliar el CHECK de tipo y agregar el activo negociado.

CREATE TABLE operaciones_nueva (
  id INTEGER PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  tipo TEXT NOT NULL CHECK (tipo IN ('aporte', 'retiro', 'comision', 'compra', 'venta')),
  monto_cent INTEGER NOT NULL CHECK (monto_cent > 0),
  periodo TEXT,
  fuera_perfil INTEGER NOT NULL DEFAULT 0,
  modelo TEXT REFERENCES modelos(codigo),
  referencia TEXT,
  estado TEXT NOT NULL DEFAULT 'pendiente'
    CHECK (estado IN ('pendiente', 'primera_firma', 'ejecutando', 'liquidada', 'rechazada', 'cancelada')),
  creado TEXT NOT NULL,
  creado_por INTEGER REFERENCES usuarios(id),
  firma1_por INTEGER REFERENCES usuarios(id),
  firma1_ts TEXT,
  firma2_por INTEGER REFERENCES usuarios(id),
  firma2_ts TEXT,
  resuelto_ts TEXT,
  resuelto_por INTEGER REFERENCES usuarios(id),
  motivo TEXT,
  liquidado_cent INTEGER,
  ejecucion_inicio TEXT,
  ejecucion_por INTEGER REFERENCES usuarios(id),
  activo TEXT REFERENCES activos(codigo),
  cantidad_pedida INTEGER
);
INSERT INTO operaciones_nueva (id, cliente_id, tipo, monto_cent, periodo, fuera_perfil, modelo, referencia, estado, creado,
                               creado_por, firma1_por, firma1_ts, firma2_por, firma2_ts, resuelto_ts, resuelto_por, motivo,
                               liquidado_cent, ejecucion_inicio, ejecucion_por)
  SELECT id, cliente_id, tipo, monto_cent, periodo, fuera_perfil, modelo, referencia, estado, creado,
         creado_por, firma1_por, firma1_ts, firma2_por, firma2_ts, resuelto_ts, resuelto_por, motivo, liquidado_cent,
         ejecucion_inicio, ejecucion_por
  FROM operaciones;
DROP TABLE operaciones;
ALTER TABLE operaciones_nueva RENAME TO operaciones;
CREATE INDEX ix_operaciones_estado ON operaciones(estado, creado);
CREATE INDEX ix_operaciones_cliente ON operaciones(cliente_id, creado);
CREATE UNIQUE INDEX ux_comision_periodo ON operaciones(cliente_id, periodo) WHERE tipo = 'comision';
CREATE INDEX ix_operaciones_activo ON operaciones(cliente_id, activo, creado);

CREATE TABLE favoritos (
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
  activo TEXT NOT NULL REFERENCES activos(codigo),
  creado TEXT NOT NULL,
  PRIMARY KEY (usuario_id, activo)
);
