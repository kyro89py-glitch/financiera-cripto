# Financiera Cripto

Plataforma de inversión en criptomonedas con dos espacios:

- **Portal del cliente:** ve su cartera (también en 3D), pide aportes y retiros, sigue sus movimientos y descarga su estado de cuenta.
- **Panel del equipo:** aprueba operaciones con controles de cumplimiento, gestiona clientes y verificaciones, revisa la bitácora y administra precios y usuarios.

Es un sistema propio e independiente: corre en tu servidor y guarda todo en tu base de datos. No depende de Claude ni de servicios externos, salvo CoinGecko para los precios, y eso es opcional porque los precios también se cargan a mano.

> **Estado:** base técnica lista para pruebas internas. Antes de recibir dinero de clientes lee [Antes de operar con dinero real](#antes-de-operar-con-dinero-real).

---

## Probarlo en tu computadora

Necesitas Python 3.11 o superior.

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
| `lucia@demo.local` | Cliente | Portal con cartera, aportes y un retiro rechazado |
| `hugo@demo.local` | Cliente | Cliente con la identidad sin verificar |
| `operaciones@demo.local` | Operaciones | Cola de aprobaciones y alta de clientes |
| `cumplimiento@demo.local` | Cumplimiento | Segunda firma, verificaciones, bitácora y reportes |
| `admin@demo.local` | Administración | Todo lo anterior, precios y usuarios del equipo |

---

## Qué hace

### Roles

| Rol | Puede |
|---|---|
| Cliente | Ver su cartera, pedir aportes y retiros, cancelar solicitudes pendientes, descargar su estado de cuenta |
| Operaciones | Aprobar o rechazar operaciones (primera firma), dar de alta clientes, generar contraseñas temporales |
| Cumplimiento | Aprobar operaciones y dar la segunda firma, verificar identidades, registrar el origen de los fondos, ver la bitácora y exportar reportes |
| Administración | Todo lo anterior, cargar precios y gestionar los usuarios del equipo |

### Cómo fluye el dinero

1. El cliente elige una cartera modelo (Reserva, Equilibrio o Impulso), transfiere y pide el aporte con el número de comprobante.
2. El equipo confirma la recepción y aprueba. El sistema compra cada activo según los pesos del modelo **al precio de ese momento**.
3. Para retirar, el sistema usa primero el saldo en dólares y vende el resto en proporción a cada tenencia.

### Controles automáticos

Al aprobar, el sistema verifica:

- **Identidad verificada:** nada se aprueba si Cumplimiento no la verificó.
- **Origen de los fondos:** los aportes desde US$ 10.000 lo necesitan registrado.
- **Doble firma:** las operaciones desde US$ 25.000 necesitan dos personas distintas, y la segunda tiene que ser de Cumplimiento o de Administración.
- **Precios vigentes:** no se ejecuta con precios de más de 60 minutos.
- **Saldo suficiente:** un retiro no puede superar el valor de la cartera menos los retiros ya pedidos.

Los umbrales se cambian en la configuración.

---

## Cómo está construido

- **Python + Flask + SQLite.** Sin dependencias de interfaz: las pantallas se generan en el servidor y el JavaScript solo agrega la vista 3D y la vista previa del aporte.
- **Montos exactos:** los dólares se guardan en centavos y las criptomonedas en unidades de 0,00000001, siempre como enteros. Nunca se usan decimales de coma flotante.
- **Libro contable de solo inserción:** cada depósito, compra, venta y pago es un asiento. Los saldos se calculan sumando asientos. La base de datos impide modificar o borrar asientos y órdenes.
- **Bitácora inalterable:** cada acción queda registrada con autor, hora e IP. Cada registro guarda la huella SHA-256 del anterior, así que cualquier alteración directa en la base se detecta. La pantalla de Cumplimiento la verifica en cada visita, y también se puede verificar con `flask --app financiera verificar-bitacora`.

```
financiera/
  __init__.py      configuración, cabeceras de seguridad y arranque
  schema.sql       tablas, disparadores de inmutabilidad, activos y carteras modelo
  seguridad.py     contraseñas (scrypt), sesiones, CSRF, verificación en dos pasos, permisos
  auditoria.py     bitácora encadenada
  operaciones.py   reglas de aportes y retiros, doble firma, alertas
  cartera.py       tenencias, valuación, ejecución de compras y ventas
  precios.py       precios manuales o desde CoinGecko, historial y antigüedad
  cuentas.py       alta de usuarios y clientes, verificaciones
  demo.py          datos de demostración
  rutas_*.py       pantallas de acceso, cliente, equipo y administración
  templates/       pantallas
  static/          estilos y JavaScript (sin recursos externos)
tests/             42 pruebas automáticas
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
- **Una tarea** que actualiza los precios desde CoinGecko cada 5 minutos.
- **Caddy**, que obtiene y renueva el certificado HTTPS solo.

El primer administrador crea al resto del equipo desde Ajustes → Usuarios del equipo.

### Respaldos

```bash
docker compose exec app flask --app financiera respaldar /datos/respaldo-$(date +%F).db
```

Programa este comando todos los días y copia el archivo fuera del servidor (otro proveedor o almacenamiento externo). Prueba restaurar un respaldo al menos una vez por mes.

### Configuración

Todas las opciones están comentadas en `.env.example`. Las principales:

| Variable | Para qué |
|---|---|
| `SECRET_KEY` | Firma las sesiones. Obligatoria en producción. |
| `EXIGIR_2FA_EQUIPO` | Obliga al equipo a usar la verificación en dos pasos (por defecto sí en producción). |
| `UMBRAL_ORIGEN_FONDOS_USD`, `UMBRAL_DOBLE_FIRMA_USD` | Montos a partir de los cuales se exige el origen de los fondos y la doble firma. |
| `PRECIO_MAX_MINUTOS` | Antigüedad máxima de un precio para ejecutar operaciones. |
| `INSTRUCCIONES_DEPOSITO` | Datos bancarios que ve el cliente al aportar. |

### Pruebas

```bash
pip install pytest
python -m pytest
```

---

## Antes de operar con dinero real

El sistema registra y controla las operaciones, pero hay piezas del negocio que no puede resolver el software:

1. **Figura legal y autorizaciones.** Recibir dinero del público para invertirlo puede requerir autorización de la Superintendencia de Valores del BCP. Además rigen las obligaciones antilavado de Seprelad y el reporte de operaciones con criptoactivos a la DNIT (RG 47/2026). Confírmalo con un abogado local antes de abrir al público.
2. **Custodia real de las criptomonedas.** Hoy el sistema registra compras y ventas en su libro, pero no las ejecuta en un exchange. Falta decidir:
   - con qué exchange o custodio regulado se opera;
   - cómo se concilia todos los días el libro con los saldos reales.
3. **Banco.** Falta conciliar los depósitos y pagos con los extractos bancarios.
4. **Verificación de identidad.** Hoy Cumplimiento la marca a mano. Para volumen conviene integrar un proveedor de verificación con prueba de vida.
5. **Comisiones, avisos por correo y contratos.** No están implementados.
6. **Escala.** SQLite rinde bien con un solo servidor y miles de clientes. Para más servidores conviene migrar a PostgreSQL.
7. **Revisión externa.** Antes de lanzar, una auditoría de seguridad hecha por terceros, como una prueba de penetración.
