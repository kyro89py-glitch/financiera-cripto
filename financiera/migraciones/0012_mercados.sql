-- v0.20 · mercados: alertas por variación porcentual en 24 horas, además de las alertas por precio.
ALTER TABLE alertas_precio ADD COLUMN tipo TEXT NOT NULL DEFAULT 'precio';
ALTER TABLE alertas_precio ADD COLUMN umbral REAL;
