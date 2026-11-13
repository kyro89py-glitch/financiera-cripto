#!/bin/bash
# Financiera Cripto - demostración en Mac. Doble clic para iniciar.
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo ""
  echo "  No encontré Python 3.11 o más nuevo en esta Mac."
  echo "  Se abre la página de descarga: instala Python y vuelve a abrir este archivo."
  echo ""
  open "https://www.python.org/downloads/"
  read -r -p "  Presiona Enter para cerrar." _
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo ""
  echo "  Preparando la financiera por primera vez. Puede tardar un par de minutos..."
  echo ""
  "$PY" -m venv .venv && .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt || {
    echo "  Algo falló. Saca una captura de esta ventana y envíala."; read -r -p "  Enter para cerrar." _; exit 1; }
fi

export FINANCIERA_ENTORNO=desarrollo
if [ ! -f instance/financiera.db ]; then
  .venv/bin/python -m flask --app financiera sembrar-demo || { echo "  Algo falló."; read -r -p "  Enter para cerrar." _; exit 1; }
fi

cat <<'TEXTO'

  ==========================================================
   Financiera Cripto - demostración
  ----------------------------------------------------------
   Se abre sola en el navegador: http://127.0.0.1:5000

   Contraseña de todas las cuentas:  Demo-2026!
     admin@demo.local          Administración
     operaciones@demo.local    Operaciones
     cumplimiento@demo.local   Cumplimiento
     lucia@demo.local          Cliente

   Para apagarla, cierra esta ventana.
  ==========================================================

TEXTO
(sleep 2; open "http://127.0.0.1:5000") &
exec .venv/bin/python -m flask --app financiera run --port 5000
