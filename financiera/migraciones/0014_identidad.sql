-- v0.30 · identidad y personalización de la cuenta.
ALTER TABLE usuarios ADD COLUMN usuario TEXT;                 -- nombre de usuario único (sin @)
CREATE UNIQUE INDEX IF NOT EXISTS ux_usuarios_usuario ON usuarios(usuario COLLATE NOCASE) WHERE usuario IS NOT NULL;
ALTER TABLE usuarios ADD COLUMN usuario_ts TEXT;              -- último cambio de nombre de usuario
ALTER TABLE usuarios ADD COLUMN nombre_publico TEXT;
ALTER TABLE usuarios ADD COLUMN bio TEXT;
ALTER TABLE usuarios ADD COLUMN foto TEXT;                    -- archivo en FOTOS_DIR (siempre recodificado por el servidor)
ALTER TABLE usuarios ADD COLUMN foto_ts TEXT;
ALTER TABLE usuarios ADD COLUMN avatar INTEGER NOT NULL DEFAULT 0;   -- estilo del avatar predeterminado
ALTER TABLE usuarios ADD COLUMN telefono TEXT;
ALTER TABLE usuarios ADD COLUMN pais TEXT;
ALTER TABLE usuarios ADD COLUMN ciudad TEXT;
ALTER TABLE usuarios ADD COLUMN direccion TEXT;
ALTER TABLE usuarios ADD COLUMN nacimiento TEXT;              -- AAAA-MM-DD; una vez cargada solo cambia con revisión
ALTER TABLE usuarios ADD COLUMN estado_cuenta TEXT NOT NULL DEFAULT 'activa';  -- activa | cierre_solicitado | cerrada

-- Cambio de correo: el nuevo solo vale después de abrir el enlace que se envía a esa dirección.
CREATE TABLE IF NOT EXISTS cambios_email (
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
  nuevo TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  creada TEXT NOT NULL,
  vence TEXT NOT NULL,
  usada TEXT
);

-- Solicitudes que resuelve el equipo: corrección de datos verificados (KYC) y cierre de cuenta.
CREATE TABLE IF NOT EXISTS solicitudes_cuenta (
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
  tipo TEXT NOT NULL CHECK (tipo IN ('correccion', 'cierre')),
  detalle TEXT NOT NULL,            -- JSON: campos pedidos y motivo
  estado TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'aprobada', 'rechazada', 'cancelada')),
  creada TEXT NOT NULL,
  resuelta TEXT,
  resuelta_por INTEGER REFERENCES usuarios(id),
  nota TEXT
);
CREATE INDEX IF NOT EXISTS ix_solicitudes_cuenta ON solicitudes_cuenta(estado, creada);
