-- v0.30: dibujos sobre el gráfico (niveles, líneas de tendencia) y anotaciones de análisis, por persona y por moneda.
CREATE TABLE IF NOT EXISTS dibujos (
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
  activo TEXT NOT NULL REFERENCES activos(codigo),
  tipo TEXT NOT NULL CHECK (tipo IN ('nivel', 'tendencia', 'nota')),
  datos TEXT NOT NULL,              -- JSON validado en el servidor
  creado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_dibujos_usuario ON dibujos(usuario_id, activo, id);
