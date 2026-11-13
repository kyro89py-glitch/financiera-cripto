# Cambios

Este proyecto sigue [versionado semántico](https://semver.org/lang/es/). Las fechas son de Paraguay.

## [0.3.0] - 2026-11-13

### Nuevo
- **Ejecución real en Binance** (red de pruebas por defecto): órdenes de mercado contra USDT con la API REST firmada; el libro se asienta con cantidades, precios promedio y comisiones reales, y guarda el número de orden de Binance.
- **Motor de ejecución en dos fases** con tramos por activo, id de orden fijo y consulta antes de reenviar: un corte de red o una respuesta perdida nunca duplica una orden. Ejecuciones parciales, comisiones en el activo, en USDT o en BNB, importes mínimos e incrementos de cantidad del par.
- Verificación de USDT libre antes de aprobar un aporte; los tramos menores al mínimo quedan en dólares y, en retiros, se juntan en la venta más grande.
- Operaciones **En ejecución** con detalle de cada tramo, alerta alta y botón de reintento.
- **Ajustes → Ejecución:** ejecutor y modo, prueba de conexión y de permisos de la clave (retiros deshabilitados, IP restringida), saldos del exchange contra el libro, últimas órdenes y **pausa de emergencia** (Cumplimiento puede activarla; solo Administración la levanta).
- **Precios desde Binance** (`FUENTE_PRECIOS`), y conciliación con los saldos traídos de Binance.
- Migración 0002 que reconstruye la tabla de operaciones conservando los datos; el migrador verifica las claves foráneas antes de confirmar.

### Pruebas
- 79 pruebas automáticas, con una imitación de la API de Binance que verifica la firma HMAC, los filtros del par, las comisiones y las fallas de red.

## [0.2.0] - 2026-11-13

### Nuevo
- **Legajo documental.** Clientes y equipo suben documentos (PDF, JPG o PNG validados por contenido); Cumplimiento los acepta o rechaza con motivo. La identidad solo se verifica con los documentos obligatorios aceptados. Ver un documento desde el panel queda en la bitácora.
- **Condiciones del servicio y aviso de riesgos** versionados: el cliente debe aceptarlos antes de usar su cuenta.
- **Idoneidad:** elegir una cartera con más riesgo que el perfil exige confirmación expresa y marca la operación para el equipo.
- **Comisión de gestión** mensual (por defecto 1,5 % anual) sobre el valor de la cartera al cierre del mes, proporcional a los días invertidos en el primer mes, solo para meses cerrados e idempotente por cliente y mes; desde la pantalla de Administración o con `flask cobrar-comisiones`.
- **Conciliación de custodia:** compara el libro con los saldos reales del banco y de cada criptomoneda; registros inmutables y alertas por diferencias o por conciliación vencida.
- **Estados de cuenta mensuales** imprimibles o guardables como PDF, con valor inicial, aportes, retiros, comisiones, resultado de mercado, posiciones y órdenes.
- **Avisos** en el portal con campana y contador, y por correo con SMTP opcional (`flask enviar-correos`). El equipo recibe aviso de cada nueva solicitud.
- **Migraciones numeradas** de la base de datos, aplicadas al arrancar.
- Integración continua en GitHub Actions (pruebas en Python 3.11 y 3.13, demostración completa y construcción de la imagen).

### Mejorado
- Rediseño completo de la interfaz: nuevo sistema visual, ingreso con vista 3D, tablas que se adaptan al celular, gráficos SVG de evolución y de flujo de dinero, ficha de cliente y panel de control con indicadores.
- Gráficos con ejes de valores redondos que nunca repiten etiquetas.
- Las tareas de fondo de Docker también envían correos y cobran la comisión el día 1 de cada mes.

### Pruebas
- 56 pruebas automáticas (eran 42).

## [0.1.0] - 2026-11-11

Primera versión: portal de clientes, panel del equipo, libro contable de solo inserción, bitácora encadenada, verificación en dos pasos, doble firma, precios de CoinGecko y despliegue con Docker y HTTPS.
