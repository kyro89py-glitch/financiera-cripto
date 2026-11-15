-- Guaraníes en depósitos y retiros, compras automáticas (ahorro programado) y alertas de precio.

ALTER TABLE operaciones ADD COLUMN monto_pyg INTEGER;   -- guaraníes que entrega o recibe el cliente
ALTER TABLE operaciones ADD COLUMN cambio_pyg INTEGER;  -- guaraníes por dólar aplicados

CREATE TABLE planes (
  id INTEGER PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  activo TEXT NOT NULL REFERENCES activos(codigo),
  monto_cent INTEGER NOT NULL CHECK (monto_cent > 0),
  frecuencia TEXT NOT NULL CHECK (frecuencia IN ('semanal', 'quincenal', 'mensual')),
  estado TEXT NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo', 'cancelado')),
  proxima TEXT NOT NULL,
  creado TEXT NOT NULL,
  ultima_ts TEXT,
  ultima_nota TEXT,
  ejecuciones INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_planes_proxima ON planes(estado, proxima);

CREATE TABLE alertas_precio (
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
  activo TEXT NOT NULL REFERENCES activos(codigo),
  sentido TEXT NOT NULL CHECK (sentido IN ('sube', 'baja')),
  precio TEXT NOT NULL,
  creado TEXT NOT NULL,
  disparada_ts TEXT
);
CREATE INDEX ix_alertas_abiertas ON alertas_precio(activo) WHERE disparada_ts IS NULL;
