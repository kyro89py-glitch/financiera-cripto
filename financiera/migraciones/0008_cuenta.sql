-- Sesiones por dispositivo, privacidad y método de depósito o retiro.

CREATE TABLE IF NOT EXISTS sesiones (
  id TEXT PRIMARY KEY,                 -- identificador aleatorio que viaja en la cookie de sesión
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
  creada TEXT NOT NULL,
  ultima TEXT NOT NULL,
  ip TEXT,
  agente TEXT,
  dispositivo TEXT,                    -- descripción legible: «Chrome en Windows»
  cerrada TEXT,
  cierre TEXT                          -- salida | usuario | clave | equipo
);
CREATE INDEX IF NOT EXISTS ix_sesiones_usuario ON sesiones(usuario_id, creada);

ALTER TABLE usuarios ADD COLUMN ocultar_saldos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE clientes ADD COLUMN recibir_envios INTEGER NOT NULL DEFAULT 1;
ALTER TABLE operaciones ADD COLUMN metodo TEXT;
