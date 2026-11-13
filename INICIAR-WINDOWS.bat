@echo off
rem Financiera Cripto - demostracion en Windows. Doble clic para iniciar.
chcp 65001 >nul
cd /d "%~dp0"
title Financiera Cripto

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto sinpython

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  Preparando la financiera por primera vez. Puede tardar un par de minutos...
  echo.
  %PY% -m venv .venv
  if errorlevel 1 goto sinpython
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 goto error
)

set "FINANCIERA_ENTORNO=desarrollo"
if not exist "instance\financiera.db" (
  ".venv\Scripts\python.exe" -m flask --app financiera sembrar-demo
  if errorlevel 1 goto error
)

echo.
echo  ==========================================================
echo   Financiera Cripto - demostracion
echo  ----------------------------------------------------------
echo   Se abre sola en el navegador: http://127.0.0.1:5000
echo.
echo   Contrasena de todas las cuentas:  Demo-2026!
echo     admin@demo.local          Administracion
echo     operaciones@demo.local    Operaciones
echo     cumplimiento@demo.local   Cumplimiento
echo     lucia@demo.local          Cliente
echo.
echo   Para apagarla, cierra esta ventana.
echo  ==========================================================
echo.
start "" "http://127.0.0.1:5000"
".venv\Scripts\python.exe" -m flask --app financiera run --port 5000
goto fin

:sinpython
echo.
echo  No encontre Python 3.11 o mas nuevo en esta computadora.
echo  Se abre la pagina de descarga: instala Python y, en la primera
echo  pantalla del instalador, marca la casilla "Add python.exe to PATH".
echo  Despues vuelve a abrir este archivo.
echo.
start "" "https://www.python.org/downloads/"
goto fin

:error
echo.
echo  Algo fallo. Saca una captura de esta ventana y enviala.
echo.

:fin
pause
