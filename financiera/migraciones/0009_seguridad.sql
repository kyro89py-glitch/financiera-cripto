-- v0.20 · seguridad: límites de tasa, recuperación de contraseña, idempotencia, antilavado y respaldos.

-- S-03: un registro por intento en reglas sensibles (ingreso, registro, búsquedas, descargas). La clave guarda
-- un hash de la IP, el correo o el usuario, nunca el dato en claro.
CREATE TABLE IF NOT EXISTS limites (
  regla TEXT NOT NULL,
  clave TEXT NOT NULL,
  ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_limites ON limites (regla, clave, ts);

-- S-07: enlaces de un solo uso para recuperar la contraseña. Solo se guarda el hash del enlace.
CREATE TABLE IF NOT EXISTS recuperaciones (
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
  token_hash TEXT NOT NULL UNIQUE,
  creada TEXT NOT NULL,
  vence TEXT NOT NULL,
  usada TEXT,
  ip TEXT
);

-- Idempotencia: cada formulario que mueve dinero lleva una clave única; si llega dos veces, se procesa una sola.
CREATE TABLE IF NOT EXISTS idempotencia (
  clave TEXT PRIMARY KEY,
  usuario_id INTEGER NOT NULL,
  ruta TEXT NOT NULL,
  creada TEXT NOT NULL,
  resultado TEXT
);

-- S-06: datos para debida diligencia (SEPRELAD) y para el informe por operación de la DNIT.
ALTER TABLE clientes ADD COLUMN pep INTEGER NOT NULL DEFAULT 0;
ALTER TABLE clientes ADD COLUMN pep_cargo TEXT;
ALTER TABLE clientes ADD COLUMN nacionalidad TEXT;
ALTER TABLE clientes ADD COLUMN domicilio_fiscal TEXT;
ALTER TABLE clientes ADD COLUMN riesgo_aml TEXT NOT NULL DEFAULT 'normal';

CREATE TABLE IF NOT EXISTS listas_sanciones (
  id INTEGER PRIMARY KEY,
  lista TEXT NOT NULL,
  nombre TEXT NOT NULL,
  nombre_norm TEXT NOT NULL,
  documento TEXT,
  pais TEXT,
  referencia TEXT,
  cargada TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sanciones_doc ON listas_sanciones (documento);

CREATE TABLE IF NOT EXISTS alertas_aml (
  id INTEGER PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  regla TEXT NOT NULL,
  nivel TEXT NOT NULL CHECK (nivel IN ('media', 'alta', 'critica')),
  detalle TEXT NOT NULL,
  ref TEXT NOT NULL,
  estado TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'descartada', 'reportada')),
  creada TEXT NOT NULL,
  resuelta TEXT,
  resuelta_por INTEGER REFERENCES usuarios(id),
  nota TEXT,
  UNIQUE (regla, ref)
);
CREATE INDEX IF NOT EXISTS ix_alertas_aml_estado ON alertas_aml (estado, creada);

-- S-05: registro de cada respaldo y de su prueba de restauración.
CREATE TABLE IF NOT EXISTS respaldos (
  id INTEGER PRIMARY KEY,
  archivo TEXT NOT NULL,
  creado TEXT NOT NULL,
  bytes INTEGER,
  sha256 TEXT,
  probado TEXT,
  prueba_ok INTEGER,
  detalle TEXT
);
