-- Envíos entre clientes y apertura de cuenta en línea.
-- Se reconstruye el libro para admitir los conceptos 'envio' y 'recepcion' y vincular cada asiento a su transferencia.
-- Los datos se copian tal cual y se vuelven a crear los disparadores que impiden modificar o borrar asientos.

CREATE TABLE transferencias (
  id INTEGER PRIMARY KEY,
  de_cliente INTEGER NOT NULL REFERENCES clientes(id),
  a_cliente INTEGER NOT NULL REFERENCES clientes(id),
  activo TEXT NOT NULL,  -- 'USD' o el código de una moneda
  cantidad INTEGER NOT NULL CHECK (cantidad > 0),
  valor_cent INTEGER NOT NULL,
  nota TEXT,
  ts TEXT NOT NULL,
  por INTEGER REFERENCES usuarios(id),
  CHECK (de_cliente != a_cliente)
);
CREATE INDEX ix_transferencias_de ON transferencias(de_cliente, ts);
CREATE INDEX ix_transferencias_a ON transferencias(a_cliente, ts);
CREATE TRIGGER transferencias_no_modificables BEFORE UPDATE ON transferencias
BEGIN SELECT RAISE(ABORT, 'Las transferencias no se pueden modificar'); END;
CREATE TRIGGER transferencias_no_borrables BEFORE DELETE ON transferencias
BEGIN SELECT RAISE(ABORT, 'Las transferencias no se pueden borrar'); END;

CREATE TABLE libro_nuevo (
  id INTEGER PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  activo TEXT NOT NULL,
  cantidad INTEGER NOT NULL,
  concepto TEXT NOT NULL CHECK (concepto IN ('deposito', 'compra', 'venta', 'pago_retiro', 'comision', 'envio', 'recepcion')),
  operacion_id INTEGER REFERENCES operaciones(id),
  ts TEXT NOT NULL,
  transferencia_id INTEGER REFERENCES transferencias(id)
);
INSERT INTO libro_nuevo (id, cliente_id, activo, cantidad, concepto, operacion_id, ts)
  SELECT id, cliente_id, activo, cantidad, concepto, operacion_id, ts FROM libro;
DROP TABLE libro;
ALTER TABLE libro_nuevo RENAME TO libro;
CREATE INDEX ix_libro_cliente ON libro(cliente_id, activo);
CREATE TRIGGER libro_no_modificable BEFORE UPDATE ON libro
BEGIN SELECT RAISE(ABORT, 'El libro contable no se puede modificar'); END;
CREATE TRIGGER libro_no_borrable BEFORE DELETE ON libro
BEGIN SELECT RAISE(ABORT, 'El libro contable no se puede borrar'); END;

ALTER TABLE clientes ADD COLUMN origen TEXT NOT NULL DEFAULT 'equipo';
