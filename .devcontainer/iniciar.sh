#!/bin/sh
# Se ejecuta cada vez que abres el Codespace: inicia la financiera en el puerto 5000.
cat <<'TEXTO'

  ==========================================================
   Financiera Cripto - demostración
  ----------------------------------------------------------
   Se abre sola en una pestaña nueva del navegador.
   Si no se abre: pestaña PUERTOS (PORTS) > puerto 5000 >
   ícono del globo.

   Contraseña de todas las cuentas:  Demo-2026!
     admin@demo.local          Administración
     operaciones@demo.local    Operaciones
     cumplimiento@demo.local   Cumplimiento
     lucia@demo.local          Cliente

   Para detenerla: Ctrl + C en esta ventana.
  ==========================================================

TEXTO
exec python -m flask --app financiera run --host 0.0.0.0 --port 5000
