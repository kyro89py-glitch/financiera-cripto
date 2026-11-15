-- Órdenes programadas por precio: límite (comprar si baja a, vender si sube a) y stop (vender si baja a, comprar si sube a).

CREATE TABLE programadas (
  id INTEGER PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  activo TEXT NOT NULL REFERENCES activos(codigo),
  lado TEXT NOT NULL CHECK (lado IN ('compra', 'venta')),
  condicion TEXT NOT NULL CHECK (condicion IN ('menor', 'mayor')),
  precio TEXT NOT NULL,
  monto_cent INTEGER NOT NULL CHECK (monto_cent >= 0),
  todo INTEGER NOT NULL DEFAULT 0,
  estado TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'ejecutada', 'cancelada', 'fallida')),
  creado TEXT NOT NULL,
  resuelta_ts TEXT,
  operacion_id INTEGER REFERENCES operaciones(id),
  nota TEXT
);
CREATE INDEX ix_programadas_abiertas ON programadas(activo) WHERE estado = 'abierta';
CREATE INDEX ix_programadas_cliente ON programadas(cliente_id, estado);
