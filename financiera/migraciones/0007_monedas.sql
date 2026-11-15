-- Más monedas, categorías para el mercado y habilitación por moneda.
-- habilitado = 0: la moneda deja de listarse y de comprarse; quien la tiene la sigue viendo y la puede vender.

ALTER TABLE activos ADD COLUMN categoria TEXT NOT NULL DEFAULT 'capa1';
ALTER TABLE activos ADD COLUMN habilitado INTEGER NOT NULL DEFAULT 1;
ALTER TABLE activos ADD COLUMN alta TEXT;

UPDATE activos SET categoria = 'principal' WHERE codigo IN ('BTC', 'ETH');
UPDATE activos SET categoria = 'estable' WHERE codigo = 'USDT';
UPDATE activos SET categoria = 'defi' WHERE codigo = 'LINK';

INSERT OR IGNORE INTO activos (codigo, nombre, coingecko_id, color, estable, orden, categoria, alta) VALUES
  ('USDC', 'USD Coin', 'usd-coin', '#2775CA', 1, 8, 'estable', '2026-11-15'),
  ('DOGE', 'Dogecoin', 'dogecoin', '#C2A633', 0, 9, 'memes', '2026-11-15'),
  ('ADA', 'Cardano', 'cardano', '#3468D1', 0, 10, 'capa1', '2026-11-15'),
  ('TRX', 'TRON', 'tron', '#EF0027', 0, 11, 'capa1', '2026-11-15'),
  ('AVAX', 'Avalanche', 'avalanche-2', '#E84142', 0, 13, 'capa1', '2026-11-15'),
  ('SHIB', 'Shiba Inu', 'shiba-inu', '#FFA409', 0, 14, 'memes', '2026-11-15'),
  ('DOT', 'Polkadot', 'polkadot', '#E6007A', 0, 15, 'capa1', '2026-11-15'),
  ('BCH', 'Bitcoin Cash', 'bitcoin-cash', '#8DC351', 0, 16, 'capa1', '2026-11-15'),
  ('LTC', 'Litecoin', 'litecoin', '#5C88C9', 0, 17, 'capa1', '2026-11-15'),
  ('SUI', 'Sui', 'sui', '#4DA2FF', 0, 18, 'capa1', '2026-11-15'),
  ('XLM', 'Stellar', 'stellar', '#8C9BB4', 0, 19, 'capa1', '2026-11-15'),
  ('NEAR', 'NEAR Protocol', 'near', '#00C08B', 0, 20, 'capa1', '2026-11-15'),
  ('APT', 'Aptos', 'aptos', '#4FD1C5', 0, 21, 'capa1', '2026-11-15'),
  ('ATOM', 'Cosmos', 'cosmos', '#7C7FB8', 0, 22, 'capa1', '2026-11-15'),
  ('UNI', 'Uniswap', 'uniswap', '#FF007A', 0, 23, 'defi', '2026-11-15'),
  ('AAVE', 'Aave', 'aave', '#B6509E', 0, 24, 'defi', '2026-11-15'),
  ('POL', 'Polygon', 'polygon-ecosystem-token', '#8247E5', 0, 25, 'capa2', '2026-11-15'),
  ('ARB', 'Arbitrum', 'arbitrum', '#28A0F0', 0, 26, 'capa2', '2026-11-15'),
  ('OP', 'Optimism', 'optimism', '#FF0420', 0, 27, 'capa2', '2026-11-15'),
  ('PEPE', 'Pepe', 'pepe', '#4C9540', 0, 28, 'memes', '2026-11-15');

-- Orden por capitalización de mercado.
UPDATE activos SET orden = CASE codigo WHEN 'BTC' THEN 1 WHEN 'ETH' THEN 2 WHEN 'USDT' THEN 3 WHEN 'BNB' THEN 4
  WHEN 'USDC' THEN 5 WHEN 'XRP' THEN 6 WHEN 'SOL' THEN 7 WHEN 'TRX' THEN 8 WHEN 'DOGE' THEN 9 WHEN 'LINK' THEN 10
  WHEN 'ADA' THEN 11 WHEN 'XLM' THEN 12 WHEN 'BCH' THEN 13 WHEN 'NEAR' THEN 14 WHEN 'LTC' THEN 15 WHEN 'AVAX' THEN 16
  WHEN 'UNI' THEN 17 WHEN 'SUI' THEN 18 WHEN 'SHIB' THEN 19 WHEN 'AAVE' THEN 20 WHEN 'PEPE' THEN 21 WHEN 'DOT' THEN 22
  WHEN 'ARB' THEN 23 WHEN 'POL' THEN 24 WHEN 'ATOM' THEN 25 WHEN 'APT' THEN 26 WHEN 'OP' THEN 27 ELSE orden END;

-- Datos de mercado que acompañan al precio (solo informativos).
ALTER TABLE precios ADD COLUMN volumen_24h REAL;
ALTER TABLE precios ADD COLUMN cap_mercado REAL;
ALTER TABLE precios ADD COLUMN max_24h TEXT;
ALTER TABLE precios ADD COLUMN min_24h TEXT;

-- Precio en vivo: un registro por moneda que se actualiza cada pocos segundos. El historial guarda un punto cada
-- pocos minutos, para que la base no crezca con cada actualización.
CREATE INDEX IF NOT EXISTS ix_precios_historial_ts ON precios_historial(ts);
