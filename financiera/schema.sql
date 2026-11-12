-- Esquema de Financiera Cripto.
-- Unidades: los montos en dólares se guardan en centavos (enteros) y las criptomonedas en
-- unidades de 1e-8 (enteros), para no perder precisión con números decimales.
-- El libro contable, las órdenes y la bitácora solo admiten inserciones: los disparadores
-- impiden modificar o borrar filas.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS usuarios (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  nombre TEXT NOT NULL,
  rol TEXT NOT NULL CHECK (rol IN ('cliente', 'operador', 'cumplimiento', 'admin')),
  clave_hash TEXT NOT NULL,
  debe_cambiar_clave INTEGER NOT NULL DEFAULT 0,
  totp_secreto TEXT,
  totp_pendiente TEXT,
  totp_ultimo INTEGER,
  activo INTEGER NOT NULL DEFAULT 1,
  fallos INTEGER NOT NULL DEFAULT 0,
  bloqueado_hasta TEXT,
  sesion_ver INTEGER NOT NULL DEFAULT 1,
  ultimo_ingreso TEXT,
  creado TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activos (
  codigo TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  coingecko_id TEXT,
  color TEXT NOT NULL,
  estable INTEGER NOT NULL DEFAULT 0,
  orden INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS modelos (
  codigo TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  riesgo INTEGER NOT NULL CHECK (riesgo BETWEEN 1 AND 5),
  color TEXT NOT NULL,
  descripcion TEXT NOT NULL,
  activo INTEGER NOT NULL DEFAULT 1,
  orden INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS modelo_pesos (
  modelo TEXT NOT NULL REFERENCES modelos(codigo),
  activo TEXT NOT NULL REFERENCES activos(codigo),
  peso_pb INTEGER NOT NULL CHECK (peso_pb > 0 AND peso_pb <= 10000),
  PRIMARY KEY (modelo, activo)
);

CREATE TABLE IF NOT EXISTS clientes (
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER UNIQUE REFERENCES usuarios(id),
  nombre TEXT NOT NULL,
  documento TEXT NOT NULL UNIQUE,
  tipo TEXT NOT NULL CHECK (tipo IN ('persona', 'empresa')),
  telefono TEXT,
  perfil_riesgo TEXT NOT NULL CHECK (perfil_riesgo IN ('conservador', 'moderado', 'arriesgado')),
  modelo TEXT NOT NULL REFERENCES modelos(codigo),
  kyc_estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (kyc_estado IN ('pendiente', 'verificado', 'observado')),
  kyc_nota TEXT,
  kyc_fecha TEXT,
  kyc_por INTEGER REFERENCES usuarios(id),
  origen_fondos TEXT,
  origen_fondos_fecha TEXT,
  origen_fondos_por INTEGER REFERENCES usuarios(id),
  creado TEXT NOT NULL,
  creado_por INTEGER REFERENCES usuarios(id)
);

CREATE TABLE IF NOT EXISTS precios (
  activo TEXT PRIMARY KEY REFERENCES activos(codigo),
  precio TEXT NOT NULL,
  cambio_24h TEXT,
  fuente TEXT NOT NULL,
  ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS precios_historial (
  id INTEGER PRIMARY KEY,
  activo TEXT NOT NULL REFERENCES activos(codigo),
  precio TEXT NOT NULL,
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_precios_historial ON precios_historial(activo, ts);

CREATE TABLE IF NOT EXISTS operaciones (
  id INTEGER PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  tipo TEXT NOT NULL CHECK (tipo IN ('aporte', 'retiro')),
  monto_cent INTEGER NOT NULL CHECK (monto_cent > 0),
  modelo TEXT REFERENCES modelos(codigo),
  referencia TEXT,
  estado TEXT NOT NULL DEFAULT 'pendiente'
    CHECK (estado IN ('pendiente', 'primera_firma', 'liquidada', 'rechazada', 'cancelada')),
  creado TEXT NOT NULL,
  creado_por INTEGER REFERENCES usuarios(id),
  firma1_por INTEGER REFERENCES usuarios(id),
  firma1_ts TEXT,
  firma2_por INTEGER REFERENCES usuarios(id),
  firma2_ts TEXT,
  resuelto_ts TEXT,
  resuelto_por INTEGER REFERENCES usuarios(id),
  motivo TEXT,
  liquidado_cent INTEGER
);
CREATE INDEX IF NOT EXISTS ix_operaciones_estado ON operaciones(estado, creado);
CREATE INDEX IF NOT EXISTS ix_operaciones_cliente ON operaciones(cliente_id, creado);

CREATE TABLE IF NOT EXISTS libro (
  id INTEGER PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  activo TEXT NOT NULL,
  cantidad INTEGER NOT NULL,
  concepto TEXT NOT NULL CHECK (concepto IN ('deposito', 'compra', 'venta', 'pago_retiro')),
  operacion_id INTEGER REFERENCES operaciones(id),
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_libro_cliente ON libro(cliente_id, activo);

CREATE TABLE IF NOT EXISTS ordenes (
  id INTEGER PRIMARY KEY,
  operacion_id INTEGER NOT NULL REFERENCES operaciones(id),
  cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  activo TEXT NOT NULL REFERENCES activos(codigo),
  lado TEXT NOT NULL CHECK (lado IN ('compra', 'venta')),
  cantidad INTEGER NOT NULL CHECK (cantidad > 0),
  precio TEXT NOT NULL,
  importe_cent INTEGER NOT NULL,
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ordenes_operacion ON ordenes(operacion_id);

CREATE TABLE IF NOT EXISTS bitacora (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  usuario_id INTEGER,
  actor TEXT NOT NULL,
  accion TEXT NOT NULL,
  objeto TEXT,
  detalle TEXT NOT NULL,
  ip TEXT,
  hash_prev TEXT NOT NULL,
  hash TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS libro_no_modificable BEFORE UPDATE ON libro
BEGIN SELECT RAISE(ABORT, 'El libro contable no se puede modificar'); END;
CREATE TRIGGER IF NOT EXISTS libro_no_borrable BEFORE DELETE ON libro
BEGIN SELECT RAISE(ABORT, 'El libro contable no se puede borrar'); END;
CREATE TRIGGER IF NOT EXISTS ordenes_no_modificables BEFORE UPDATE ON ordenes
BEGIN SELECT RAISE(ABORT, 'Las órdenes ejecutadas no se pueden modificar'); END;
CREATE TRIGGER IF NOT EXISTS ordenes_no_borrables BEFORE DELETE ON ordenes
BEGIN SELECT RAISE(ABORT, 'Las órdenes ejecutadas no se pueden borrar'); END;
CREATE TRIGGER IF NOT EXISTS bitacora_no_modificable BEFORE UPDATE ON bitacora
BEGIN SELECT RAISE(ABORT, 'La bitácora no se puede modificar'); END;
CREATE TRIGGER IF NOT EXISTS bitacora_no_borrable BEFORE DELETE ON bitacora
BEGIN SELECT RAISE(ABORT, 'La bitácora no se puede borrar'); END;

-- Datos base: activos disponibles y carteras modelo. Se pueden ajustar antes de operar.
INSERT OR IGNORE INTO activos (codigo, nombre, coingecko_id, color, estable, orden) VALUES
  ('BTC', 'Bitcoin', 'bitcoin', '#F5A524', 0, 1),
  ('ETH', 'Ethereum', 'ethereum', '#7B8FF7', 0, 2),
  ('USDT', 'Dólar digital (USDT)', 'tether', '#22B8A0', 1, 3),
  ('SOL', 'Solana', 'solana', '#A66BFA', 0, 4),
  ('BNB', 'BNB', 'binancecoin', '#E3B81F', 0, 5),
  ('XRP', 'XRP', 'ripple', '#7F93B0', 0, 6),
  ('LINK', 'Chainlink', 'chainlink', '#2F6BFF', 0, 7);

INSERT OR IGNORE INTO modelos (codigo, nombre, riesgo, color, descripcion, orden) VALUES
  ('reserva', 'Reserva', 2, '#22B8A0', 'Prioriza la estabilidad: la mayor parte queda en dólares digitales.', 1),
  ('equilibrio', 'Equilibrio', 3, '#7B8FF7', 'Mitad en Bitcoin, con Ethereum, Solana y una reserva en dólares digitales.', 2),
  ('impulso', 'Impulso', 5, '#F5A524', 'Seis criptomonedas y sin reserva: es la que más puede subir y la que más puede bajar.', 3);

INSERT OR IGNORE INTO modelo_pesos (modelo, activo, peso_pb) VALUES
  ('reserva', 'USDT', 6000), ('reserva', 'BTC', 3000), ('reserva', 'ETH', 1000),
  ('equilibrio', 'BTC', 5000), ('equilibrio', 'ETH', 2500), ('equilibrio', 'USDT', 1500), ('equilibrio', 'SOL', 1000),
  ('impulso', 'BTC', 3500), ('impulso', 'ETH', 2500), ('impulso', 'SOL', 1500), ('impulso', 'BNB', 1000),
  ('impulso', 'XRP', 800), ('impulso', 'LINK', 700);
