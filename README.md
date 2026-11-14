# Financiera Cripto

Plataforma de inversión en criptomonedas para operar con clientes reales, con dos espacios:

- **Portal del cliente:** su cartera (también en 3D), aportes y retiros, movimientos, estados de cuenta mensuales para imprimir, su legajo de documentos y avisos.
- **Compra y venta tipo exchange:** además de las carteras armadas por la casa, el cliente puede depositar en su saldo y comprar o vender cada moneda por su cuenta, con mercado en vivo, página por moneda, favoritas y billetera.
- **Panel del equipo:** aprobación de operaciones con controles de cumplimiento y doble firma, fichas de clientes con legajo, revisión de documentos, conciliación de custodia, comisiones de gestión, bitácora inalterable, precios y usuarios.
- **Ejecución en Binance:** al aprobar, las compras y ventas se envían como órdenes de mercado a Binance (o a su red de pruebas) y el libro se asienta con las cantidades, precios y comisiones reales. Sin Binance configurado, un simulador ejecuta al precio vigente.

Es un sistema propio e independiente: corre en tu servidor y guarda todo en tu base de datos. Los únicos servicios externos son opcionales: Binance para ejecutar y cotizar, CoinGecko para los precios cuando no se usa Binance (también se cargan a mano) y un servidor de correo para los avisos por email.

> **Estado:** versión 0.5, lista para pruebas internas con el equipo y para operar en la red de pruebas de Binance. Antes de recibir dinero de clientes lee [Antes de operar con dinero real](#antes-de-operar-con-dinero-real).

---

## Probarlo sin instalar nada

Con una cuenta de GitHub, abre [este enlace](https://codespaces.new/kyro89py-glitch/financiera-cripto?quickstart=1) y toca **Create codespace**. En unos minutos se instala, carga la demostración y se abre en el navegador. Las cuentas y la contraseña están más abajo. Los Codespaces son gratis hasta 60 horas por mes en una cuenta personal.

## Probarlo en tu computadora

**La forma fácil:** instala Python desde https://www.python.org/downloads/ (en Windows, marca *Add python.exe to PATH*), descarga este proyecto (botón verde **Code → Download ZIP**), descomprímelo y haz doble clic en `INICIAR-WINDOWS.bat` o en `INICIAR-MAC.command`. La primera vez instala lo necesario y carga la demostración; después se abre sola en el navegador. En Mac, si aparece un aviso de seguridad, haz clic derecho sobre el archivo → **Abrir**.

**A mano**, con Python 3.11 o superior:

```bash
python -m venv .venv
source .venv/bin/activate            # en Windows: .venv\Scripts\activate
pip install -r requirements.txt

export FINANCIERA_ENTORNO=desarrollo  # en Windows: set FINANCIERA_ENTORNO=desarrollo
flask --app financiera sembrar-demo   # carga datos de demostración
flask --app financiera run
```

Abre http://127.0.0.1:5000. Todas las cuentas de demostración usan la contraseña `Demo-2026!`.

| Cuenta | Rol | Para ver |
|---|---|---|
| `lucia@demo.local` | Cliente | Portal con cartera, estados de cuenta, legajo completo y un retiro rechazado |
| `patricia@demo.local` | Cliente | Aporte pendiente en una cartera con más riesgo que su perfil |
| `hugo@demo.local` | Cliente | Identidad sin verificar; todavía tiene que aceptar las condiciones |
| `operaciones@demo.local` | Operaciones | Cola de aprobaciones y alta de clientes |
| `cumplimiento@demo.local` | Cumplimiento | Segunda firma, documentos por revisar, conciliación, bitácora y reportes |
| `admin@demo.local` | Administración | Todo lo anterior, precios, comisiones y usuarios del equipo |

---

## Qué hace

### Roles

| Rol | Puede |
|---|---|
| Cliente | Ver su cartera, pedir aportes y retiros, cancelar solicitudes pendientes, subir sus documentos, ver e imprimir sus estados de cuenta |
| Operaciones | Aprobar o rechazar operaciones (primera firma), dar de alta clientes, subir documentos al legajo, generar contraseñas temporales |
| Cumplimiento | Lo anterior más la segunda firma, revisar documentos, verificar identidades, registrar el origen de los fondos, conciliar la custodia, ver la bitácora y exportar reportes |
| Administración | Todo lo anterior, cargar precios, cobrar comisiones y gestionar los usuarios del equipo |

### Cómo fluye el dinero

1. El cliente elige una cartera modelo (Reserva, Equilibrio o Impulso), transfiere y pide el aporte con el número de comprobante.
2. El equipo confirma la recepción y aprueba. El sistema compra cada activo según los pesos del modelo **al precio de ese momento**.
3. Para retirar, el sistema usa primero el saldo en dólares y vende el resto en proporción a cada tenencia.
4. Cada mes cerrado se cobra la comisión de gestión (por defecto 1,5 % anual, la doceava parte por mes) sobre el valor de la cartera al cierre del mes; el primer mes se cobra en proporción a los días invertidos. Es idempotente: un cliente nunca paga dos veces el mismo mes.
5. El cliente recibe un aviso en el portal (y por correo, si está configurado) cuando se aprueba o rechaza algo, y tiene un estado de cuenta por mes con valor inicial, aportes, retiros, comisiones, resultado de mercado y valor final.

### Alta y debida diligencia

1. Operaciones da de alta al cliente con su perfil de riesgo (conservador, moderado o arriesgado) y le entrega una contraseña temporal.
2. En su primer ingreso el cliente cambia la contraseña y **acepta las condiciones del servicio y el aviso de riesgos**; queda registrado con la versión y la fecha.
3. El cliente (o el equipo) sube los documentos obligatorios: identidad y domicilio para personas; estatutos y representante para empresas. Solo se aceptan PDF, JPG o PNG verificados por su contenido, no por la extensión.
4. Cumplimiento revisa cada documento. La identidad solo se puede marcar como verificada cuando todos los obligatorios están aceptados.

### Controles automáticos

Al aprobar, el sistema verifica:

- **Identidad verificada:** nada se aprueba si Cumplimiento no la verificó.
- **Origen de los fondos:** los aportes desde US$ 10.000 lo necesitan registrado.
- **Doble firma:** las operaciones desde US$ 25.000 necesitan dos personas distintas, y la segunda tiene que ser de Cumplimiento o de Administración.
- **Precios vigentes:** no se ejecuta con precios de más de 60 minutos.
- **Saldo suficiente:** un retiro no puede superar el valor de la cartera menos los retiros ya pedidos.
- **Idoneidad:** si el cliente elige una cartera con más riesgo que su perfil, tiene que confirmarlo de forma expresa, y la operación queda marcada para el equipo.

### Conciliación de custodia

Cumplimiento registra los saldos reales del banco y de cada criptomoneda en custodia; el sistema los compara con el libro contable y guarda el resultado sin posibilidad de modificarlo. Si hay diferencias, o si pasa más de un día sin conciliar, aparece una alerta en el panel. Con Binance conectado, el botón **Traer saldos de Binance** completa el formulario con los saldos de la cuenta; el saldo bancario en dólares se sigue cargando a mano.

### Ejecución de órdenes

Cada operación aprobada se divide en **tramos**, uno por activo, y pasa por estos pasos:

1. **Plan:** con los precios vigentes y las reglas del par en Binance (importe mínimo por orden, incremento de cantidad). En un aporte, si un tramo no llega al mínimo del exchange, ese dinero queda en dólares. En un retiro, los tramos chicos se juntan en la venta de la tenencia más grande. Antes de aprobar un aporte se verifica que haya USDT libre suficiente en la cuenta.
2. **Envío:** cada tramo tiene un id de orden propio y fijo (`fc-<operación>-<C|V>-<activo>`). Antes de enviarlo se marca como *enviado*; si la respuesta se pierde, al reintentar primero se consulta a Binance. **Nunca se compra ni se vende dos veces lo mismo.**
3. **Liquidación:** cuando todos los tramos terminaron, se asientan en el libro las cantidades netas de comisión, el precio promedio y el número de orden de Binance. Una comisión cobrada en BNB la absorbe la casa.

Si Binance rechaza un tramo (saldo insuficiente, filtro del par, mantenimiento), la operación queda **En ejecución** con una alerta alta, y se reintenta desde su pantalla sin repetir lo ya ejecutado. Desde **Ajustes → Ejecución**, Administración y Cumplimiento pueden activar una **pausa de emergencia** que detiene todo envío; solo Administración la levanta.

El USDT es la moneda contra la que se opera en Binance: el tramo de USDT de una cartera es una conversión interna 1:1, sin orden. El dinero que llega al banco en dólares se convierte a USDT y se deposita en Binance antes de aprobar los aportes; al pagar retiros, el USDT de las ventas se convierte y se transfiere desde el banco. Esa tesorería es manual.

Los umbrales se cambian en la configuración.

---

## Cómo está construido

- **Python + Flask + SQLite.** Sin dependencias de interfaz: las pantallas y los gráficos (SVG) se generan en el servidor y el JavaScript solo agrega la vista 3D, la vista previa del aporte y pequeñas ayudas.
- **Migraciones numeradas** en `financiera/migraciones/`: al arrancar se aplican las que falten, cada una en su transacción.
- **Montos exactos:** los dólares se guardan en centavos y las criptomonedas en unidades de 0,00000001, siempre como enteros. Nunca se usan decimales de coma flotante.
- **Libro contable de solo inserción:** cada depósito, compra, venta y pago es un asiento. Los saldos se calculan sumando asientos. La base de datos impide modificar o borrar asientos y órdenes.
- **Bitácora inalterable:** cada acción queda registrada con autor, hora e IP. Cada registro guarda la huella SHA-256 del anterior, así que cualquier alteración directa en la base se detecta. La pantalla de Cumplimiento la verifica en cada visita, y también se puede verificar con `flask --app financiera verificar-bitacora`.

```
financiera/
  __init__.py        configuración, cabeceras de seguridad y arranque
  migraciones/       esquema de la base en pasos numerados (tablas, disparadores, datos base)
  seguridad.py       contraseñas (scrypt), sesiones, CSRF, dos pasos, permisos, condiciones
  auditoria.py       bitácora encadenada
  operaciones.py     reglas de aportes y retiros, idoneidad, doble firma, alertas
  ejecucion.py       motor de ejecución en dos fases: plan, envío idempotente, liquidación, pausa
  exchange.py        conexión con Binance (API REST firmada) y simulador con la misma interfaz
  cartera.py         tenencias, valuación, estados de cuenta mensuales
  comisiones.py      comisión de gestión mensual
  conciliacion.py    conciliación del libro con los saldos reales
  documentos.py      legajo: validación de archivos, revisión, faltantes
  notificaciones.py  avisos en el portal y cola de correos
  graficos.py        geometría de los gráficos SVG
  precios.py         precios manuales, desde Binance o desde CoinGecko, historial y antigüedad
  cuentas.py         alta de usuarios y clientes, verificaciones
  demo.py            datos de demostración
  rutas_*.py         pantallas de acceso, cliente, equipo, administración y documentos
  templates/         pantallas
  static/            estilos y JavaScript (sin recursos externos)
tests/               88 pruebas automáticas (incluye una imitación completa de la API de Binance)
```

### Seguridad incluida

- Contraseñas con scrypt y sal individual, mínimo 10 caracteres con letras y números.
- Verificación en dos pasos (TOTP, compatible con Google Authenticator y similares). Es obligatoria para el equipo en producción y opcional para clientes. Los códigos no se pueden reutilizar.
- Bloqueo de la cuenta por 15 minutos tras 5 intentos fallidos. El mensaje de error es el mismo exista o no el correo.
- Cierre de sesión por 30 minutos de inactividad. Cambiar la contraseña o restablecer un acceso cierra las demás sesiones.
- Protección CSRF en todos los formularios.
- Cookies `HttpOnly`, `SameSite=Lax` y `Secure` en producción.
- Política de seguridad de contenido estricta: solo scripts propios y ninguna carga externa. También HSTS, `X-Frame-Options` y `nosniff`.
- Contraseñas temporales que se muestran una sola vez y obligan a elegir una propia.

---

## Poner en producción

### Opción recomendada: Docker con HTTPS automático

En un servidor con Docker y un dominio que apunte a él:

```bash
cp .env.example .env        # completa DOMINIO, SECRET_KEY y los datos bancarios
docker compose up -d --build
docker compose exec app flask --app financiera crear-admin
```

Esto levanta tres servicios:

- **La aplicación**, con 3 procesos.
- **Las tareas de fondo:** actualiza precios y envía los correos pendientes cada 5 minutos, y el día 1 de cada mes cobra la comisión del mes anterior.
- **Caddy**, que obtiene y renueva el certificado HTTPS solo.

El primer administrador crea al resto del equipo desde Ajustes → Usuarios del equipo.

### Respaldos

```bash
docker compose exec app flask --app financiera respaldar /datos/respaldo-$(date +%F).db
```

Programa este comando todos los días y copia el archivo fuera del servidor (otro proveedor o almacenamiento externo), junto con la carpeta `/datos/documentos` del legajo. Prueba restaurar un respaldo al menos una vez por mes.

### Comandos útiles

| Comando | Qué hace |
|---|---|
| `flask --app financiera crear-admin` | Crea el primer usuario de Administración |
| `flask --app financiera migrar` | Aplica las migraciones pendientes (también se hace al arrancar) |
| `flask --app financiera actualizar-precios` | Trae los precios de CoinGecko |
| `flask --app financiera cobrar-comisiones [--periodo AAAA-MM]` | Cobra la comisión del mes (por defecto, el anterior) |
| `flask --app financiera enviar-correos` | Envía los avisos por correo pendientes |
| `flask --app financiera verificar-bitacora` | Comprueba que nadie alteró la bitácora |
| `flask --app financiera respaldar destino.db` | Copia consistente de la base en caliente |

### Conectar Binance

Empieza siempre por la **red de pruebas** (dinero ficticio):

1. Entra en https://testnet.binance.vision con tu cuenta de GitHub y genera una clave de API (HMAC).
2. En el `.env`: `EJECUCION=binance`, `BINANCE_API_KEY=…`, `BINANCE_API_SECRET=…`. `BINANCE_URL` ya apunta a la red de pruebas por defecto.
3. Reinicia y entra en **Ajustes → Ejecución → Probar ahora**. Haz aportes y retiros de prueba y revisa los tramos.

Para operar con dinero real, en Binance crea una clave **solo con permiso de Spot**, con los **retiros deshabilitados** y **restringida a la IP del servidor**, y cambia `BINANCE_URL=https://api.binance.com`. La pantalla de Ejecución verifica esas tres condiciones y marca en rojo la que falte. Usa una cuenta de empresa verificada y dedicada solo a la financiera.

### Configuración

Todas las opciones están comentadas en `.env.example`. Las principales:

| Variable | Para qué |
|---|---|
| `SECRET_KEY` | Firma las sesiones. Obligatoria en producción. |
| `EXIGIR_2FA_EQUIPO` | Obliga al equipo a usar la verificación en dos pasos (por defecto sí en producción). |
| `UMBRAL_ORIGEN_FONDOS_USD`, `UMBRAL_DOBLE_FIRMA_USD` | Montos a partir de los cuales se exige el origen de los fondos y la doble firma. |
| `PRECIO_MAX_MINUTOS` | Antigüedad máxima de un precio para ejecutar operaciones. |
| `INSTRUCCIONES_DEPOSITO` | Datos bancarios que ve el cliente al aportar. |
| `ORDEN_MAXIMA_USD` | Monto máximo de cada compra o venta que hace el cliente por su cuenta. |
| `EJECUCION` | `simulado` (por defecto) o `binance`. |
| `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `BINANCE_URL` | Clave de API y dirección (red de pruebas por defecto; `https://api.binance.com` para operar en real). |
| `FUENTE_PRECIOS` | `binance` o `coingecko`. Por defecto, Binance si se ejecuta en Binance. |
| `COMISION_ANUAL_PCT` | Comisión de gestión anual en porcentaje (0 la desactiva). |
| `SMTP_HOST`, `SMTP_USUARIO`, `SMTP_CLAVE`, `SMTP_REMITENTE` | Servidor de correo para los avisos. Sin `SMTP_HOST` los avisos solo se ven en el portal. |
| `URL_PUBLICA` | Dirección del sistema, para los enlaces de los correos y el pie de los estados de cuenta. |
| `DOCUMENTO_MAX_MB` | Tamaño máximo de cada documento del legajo. |

### Pruebas

```bash
pip install pytest
python -m pytest
```

---

## Antes de operar con dinero real

El sistema registra y controla las operaciones, pero hay piezas del negocio que no puede resolver el software:

1. **Figura legal y autorizaciones.** Recibir dinero del público para invertirlo puede requerir autorización de la Superintendencia de Valores del BCP. Además rigen las obligaciones antilavado de Seprelad y el reporte de operaciones con criptoactivos a la DNIT (RG 47/2026). Confírmalo con un abogado local antes de abrir al público.
2. **Custodia en Binance.** Las órdenes se ejecutan en Binance y el dinero de todos los clientes queda en una sola cuenta de la empresa (cuenta ómnibus); el detalle por cliente vive en el libro. Eso exige conciliar a diario, proteger la cuenta (2FA, clave sin retiros, IP restringida) y evaluar con un abogado el riesgo de custodiar en un exchange extranjero sin regulación local específica.
3. **Banco.** La conciliación incluye el saldo en dólares, pero se carga a mano desde el extracto; no hay conexión con el banco.
4. **Verificación de identidad.** El legajo y la revisión son manuales. Para volumen conviene integrar un proveedor de verificación con prueba de vida.
5. **Contrato y textos legales.** El texto de condiciones y el aviso de riesgos del portal es un punto de partida: un abogado tiene que adaptarlo a tu figura legal antes de usarlo.
6. **Escala.** SQLite rinde bien con un solo servidor y miles de clientes. Para más servidores conviene migrar a PostgreSQL.
7. **Revisión externa.** Antes de lanzar, una auditoría de seguridad hecha por terceros, como una prueba de penetración.
