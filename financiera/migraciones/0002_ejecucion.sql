-- Ejecución real en un exchange: estado 'ejecutando', tramos de ejecución, datos del exchange en las órdenes
-- y ajustes operativos (pausa de emergencia).
-- SQLite no permite cambiar un CHECK: se reconstruye la tabla de operaciones conservando ids y datos.
-- El migrador desactiva las claves foráneas durante la migración y las verifica antes de confirmarla.

CREATE TABLE operaciones_nueva (
  id INTEGER PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  tipo TEXT NOT NULL CHECK (tipo IN ('aporte', 'retiro', 'comision')),
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
  ejecucion_por INTEGER REFERENCES usuarios(id)
);
INSERT INTO operaciones_nueva (id, cliente_id, tipo, monto_cent, periodo, fuera_perfil, modelo, referencia, estado, creado,
                               creado_por, firma1_por, firma1_ts, firma2_por, firma2_ts, resuelto_ts, resuelto_por, motivo,
                               liquidado_cent)
  SELECT id, cliente_id, tipo, monto_cent, periodo, fuera_perfil, modelo, referencia, estado, creado,
         creado_por, firma1_por, firma1_ts, firma2_por, firma2_ts, resuelto_ts, resuelto_por, motivo, liquidado_cent
  FROM operaciones;
DROP TABLE operaciones;
ALTER TABLE operaciones_nueva RENAME TO operaciones;
CREATE INDEX ix_operaciones_estado ON operaciones(estado, creado);
CREATE INDEX ix_operaciones_cliente ON operaciones(cliente_id, creado);
CREATE UNIQUE INDEX ux_comision_periodo ON operaciones(cliente_id, periodo) WHERE tipo = 'comision';

-- Dónde se ejecutó cada orden y cuánto cobró el exchange. Las órdenes anteriores quedan como 'interno'.
ALTER TABLE ordenes ADD COLUMN venue TEXT NOT NULL DEFAULT 'interno';
ALTER TABLE ordenes ADD COLUMN comision TEXT;
ALTER TABLE ordenes ADD COLUMN comision_activo TEXT;
ALTER TABLE ordenes ADD COLUMN ref_exchange TEXT;

-- Un tramo por activo y operación. Es la tabla de trabajo del motor: guarda lo pedido y lo que respondió
-- el exchange, para poder reintentar sin duplicar órdenes (cada tramo tiene un id de orden propio y fijo).
CREATE TABLE ejecuciones (
  id INTEGER PRIMARY KEY,
  operacion_id INTEGER NOT NULL REFERENCES operaciones(id),
  activo TEXT NOT NULL REFERENCES activos(codigo),
  lado TEXT NOT NULL CHECK (lado IN ('compra', 'venta')),
  venue TEXT NOT NULL,
  id_orden TEXT NOT NULL UNIQUE,
  importe_pedido_cent INTEGER,
  cantidad_pedida INTEGER,
  estado TEXT NOT NULL DEFAULT 'pendiente'
    CHECK (estado IN ('pendiente', 'enviada', 'ejecutada', 'omitida', 'fallida')),
  cantidad_bruta INTEGER,
  cantidad INTEGER,
  precio TEXT,
  importe_cent INTEGER,
  comision TEXT,
  comision_activo TEXT,
  ref_exchange TEXT,
  intentos INTEGER NOT NULL DEFAULT 0,
  nota TEXT,
  respuesta TEXT,
  creado TEXT NOT NULL,
  actualizado TEXT NOT NULL
);
CREATE INDEX ix_ejecuciones_operacion ON ejecuciones(operacion_id);
CREATE INDEX ix_ejecuciones_estado ON ejecuciones(estado);

CREATE TABLE ajustes (
  clave TEXT PRIMARY KEY,
  valor TEXT NOT NULL,
  ts TEXT NOT NULL,
  por INTEGER REFERENCES usuarios(id)
);
