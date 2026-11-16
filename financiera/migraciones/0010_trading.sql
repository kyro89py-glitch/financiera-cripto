-- v0.20 · trading: órdenes OCO, salidas por cantidad (toma de ganancia y corte de pérdida de una compra) y preferencias.

-- Las órdenes con el mismo grupo forman una OCO: cuando una se ejecuta, las demás se cancelan solas.
ALTER TABLE programadas ADD COLUMN grupo TEXT;
-- Venta por cantidad de unidades (para proteger exactamente lo que se compró); si es NULL se usa monto_cent.
ALTER TABLE programadas ADD COLUMN cantidad INTEGER;
-- Cómo nació la orden: 'tp' (toma de ganancia), 'sl' (corte de pérdida), 'oco' o NULL (límite o stop simple).
ALTER TABLE programadas ADD COLUMN origen TEXT;
CREATE INDEX IF NOT EXISTS ix_programadas_grupo ON programadas(grupo) WHERE grupo IS NOT NULL;

-- Preferencias de cada persona (panel de inicio, indicadores, moneda, notificaciones). JSON validado en el servidor.
CREATE TABLE IF NOT EXISTS preferencias (
  usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id),
  datos TEXT NOT NULL DEFAULT '{}',
  actualizado TEXT
);
