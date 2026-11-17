-- v0.30: noticias y acontecimientos del mercado. Cada registro tiene fuente identificable, enlace y fecha verificable.
-- Los carga el equipo a mano o se importan de un canal RSS/Atom; los importados quedan en revisión hasta que alguien los publique.
CREATE TABLE IF NOT EXISTS noticias (
  id INTEGER PRIMARY KEY,
  tipo TEXT NOT NULL CHECK (tipo IN ('noticia', 'evento')),
  titulo TEXT NOT NULL,
  resumen TEXT NOT NULL DEFAULT '',
  fuente TEXT NOT NULL,
  url TEXT NOT NULL,
  fecha TEXT NOT NULL,                   -- publicación (noticia) o día y hora del acontecimiento (evento), ISO 8601 UTC
  activos TEXT NOT NULL DEFAULT '',      -- códigos separados por coma
  importancia TEXT NOT NULL DEFAULT 'media' CHECK (importancia IN ('alta', 'media', 'baja')),
  estado TEXT NOT NULL DEFAULT 'publicada' CHECK (estado IN ('publicada', 'revision', 'oculta')),
  origen TEXT NOT NULL DEFAULT 'manual',  -- manual | rss
  guid TEXT,                              -- identificador del canal, para no importar dos veces
  creado TEXT NOT NULL,
  creado_por INTEGER REFERENCES usuarios(id),
  revisado_por INTEGER REFERENCES usuarios(id),
  revisado TEXT
);
CREATE INDEX IF NOT EXISTS ix_noticias_estado ON noticias(estado, tipo, fecha);
CREATE UNIQUE INDEX IF NOT EXISTS ux_noticias_guid ON noticias(guid) WHERE guid IS NOT NULL;
