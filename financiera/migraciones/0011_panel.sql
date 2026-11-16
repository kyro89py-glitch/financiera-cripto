-- v0.20 · inicio inteligente: categoría de cada aviso para filtrar y para decidir qué se envía por correo.
ALTER TABLE notificaciones ADD COLUMN categoria TEXT NOT NULL DEFAULT 'cuenta';
UPDATE notificaciones SET categoria = CASE
  WHEN enlace LIKE '/cuenta/sesiones%' OR enlace LIKE '/cuenta/seguridad%' OR texto LIKE '%sesi%' OR texto LIKE '%contraseña%' THEN 'seguridad'
  WHEN enlace LIKE '/mercado/%' OR enlace LIKE '/trading/%' OR texto LIKE '%alerta de precio%' THEN 'precios'
  WHEN enlace LIKE '/cliente/movimientos%' OR enlace LIKE '/cliente/envios%' OR enlace LIKE '/equipo/operaciones%' THEN 'operaciones'
  ELSE 'cuenta' END;
CREATE INDEX IF NOT EXISTS ix_notificaciones_categoria ON notificaciones(usuario_id, categoria, ts);
