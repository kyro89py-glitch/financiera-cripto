#!/bin/sh
# Se ejecuta una sola vez, al crear el Codespace: instala las dependencias y carga la demostración.
set -e
pip install --no-cache-dir -r requirements.txt pytest
if [ ! -f instance/financiera.db ]; then
  python -m flask --app financiera sembrar-demo
fi
