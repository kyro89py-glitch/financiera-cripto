# Cambios

Este proyecto sigue [versionado semántico](https://semver.org/lang/es/). Las fechas son de Paraguay.

## [0.30.0] - 2026-11-17

Personalización e identidad. Los servicios financieros reales siguen deshabilitados; lo que se ejecuta en simulador se indica como tal.

### Módulo 1 · Mi cuenta e identidad
- **Mi cuenta:** nueva sección con cabecera de identidad (foto, nombre, usuario, identificador, nivel, estado, antigüedad y protección) y pestañas Resumen, Datos y fotografía, Verificación y límites, Seguridad, Dispositivos, Preferencias, Actividad y Solicitudes y cierre. El resumen muestra qué falta para completar la cuenta.
- **Fotografía:** subir, tomar con la cámara (teléfono), recortar, acercar y girar antes de guardar, cambiar y quitar; seis avatares predeterminados. El servidor acepta solo JPG, PNG o WebP reales de hasta 6 MB, los vuelve a codificar a 512×512 sin metadatos (ubicación, cámara), guarda con nombre aleatorio fuera de la carpeta pública y limita los intentos. La foto vive en la cuenta: aparece en cualquier dispositivo.
- **Nombre de usuario único:** disponibilidad en tiempo real, unicidad garantizada por la base (sin distinguir mayúsculas), nombres reservados y un cambio cada 30 días. **Identificador de cuenta** «FC» + 8 dígitos con dígito verificador.
- **Perfil público** `/u/usuario`: la persona elige qué se ve (foto, presentación, ciudad, antigüedad, identidad verificada) o lo apaga. Nunca muestra saldos, movimientos, correo, teléfono, documento ni dirección; solo lo ven usuarios con sesión.
- **Datos editables y datos verificados:** nombre público, presentación, teléfono, país, ciudad, dirección y avatar se cambian al instante. Nombre legal, documento y fecha de nacimiento se corrigen con una **solicitud** que revisa Cumplimiento (persona distinta, nota obligatoria, bitácora); si cambia nombre o documento, la identidad vuelve a quedar pendiente de verificación.
- **Cambio de correo con verificación:** pide la contraseña, envía un enlace de un solo uso (1 hora) a la dirección nueva, avisa a la anterior y cierra todas las sesiones al aplicarse. No revela si una dirección ya está registrada.
- **Cierre de cuenta:** pedido con contraseña; no se puede con saldo, órdenes o trámites abiertos; lo aprueba el equipo y los registros se conservan el plazo legal.
- **Preferencias en la cuenta:** tema, moneda principal, zona horaria, ocultar saldos y recepción de envíos se guardan en el servidor y se aplican en todos los dispositivos. Idioma: solo español por ahora (guaraní, portugués e inglés pendientes).
- **Actividad:** línea de tiempo propia con inicios de sesión, seguridad, perfil, configuración, compras y ventas, depósitos, retiros, transferencias y órdenes; filtros por categoría y fechas, estado de cada registro y exportación CSV.
- **Envíos:** el destinatario se puede buscar por @usuario o identificador de cuenta, además de correo y cédula.
- **Equipo:** Cumplimiento › Solicitudes, con permiso propio (`cuenta.solicitudes`).
- Dependencias declaradas: `Pillow` y `cryptography` (esta última faltaba en requirements desde la 0.20).

### Módulo 2 · Centro de actividad y notificaciones
- **Notificaciones:** marcar una o todas como leídas (también por categoría), volver a marcar como no leída, eliminar una o todas las leídas, y filtros por tipo y «sin leer». Ver la lista ya no las marca solas: lo decide la persona. Abrir un aviso lo marca como leído.
- **Preferencias por tipo y canal**, guardadas en la cuenta: plataforma, correo y push para operaciones, alertas de precio, seguridad, cuenta, mercado y comunicados. Seguridad no se puede silenciar. **Push queda preparado pero no se envía** (pendiente de integración); el correo depende de que la plataforma tenga servidor de correo configurado.
- **Inicios de sesión:** aviso al entrar desde un dispositivo nuevo o, si la persona lo elige, en cada inicio.
- Nueva categoría «Comunicaciones de la plataforma» y función de comunicados del equipo a todos los clientes.

### Módulo 3 · Inicio personalizable
- **Tus favoritos:** módulo nuevo con las monedas marcadas con estrella, su precio en vivo, variación y mini gráfico.
- **Accesos rápidos a elección:** hasta 8 entre depositar, comprar, vender, convertir, enviar, retirar, mercados, movimientos, análisis, comparar, actividad, academia, herramientas y ayuda.
- **Período del gráfico:** se elige con cuál abre el gráfico de patrimonio.
- **Vistas guardadas:** hasta 5 configuraciones con nombre (módulos, orden, accesos y período) que se aplican con un toque. Todo queda en la cuenta, no en el dispositivo.
- Acceso directo al Centro de actividad desde el módulo de actividad reciente.

### Módulo 4 · Trading
- **Configuración del gráfico en la cuenta:** indicadores, parámetros y moneda de comparación se guardan en el servidor y se ven igual en cualquier dispositivo (antes vivían en el navegador; se migran solos la primera vez).
- **Indicadores nuevos:** VWAP (se desactiva si la fuente no informa volumen), oscilador estocástico %K/%D con parámetros, y **soportes y resistencias** detectados en las velas visibles (dos de cada lado, con la cantidad de toques).
- **Plantillas:** hasta 6 combinaciones de indicadores y parámetros con nombre, para aplicar con un toque.
- **Dibujos:** líneas horizontales de precio y líneas de tendencia entre dos velas (con prolongación), guardadas por moneda en la cuenta; se borran de a una o todas. Validadas en el servidor (precio, fechas, límites por moneda).
- **Comparar con otra moneda:** la segunda serie se dibuja escalada al precio de la primera vela visible y la leyenda muestra la variación de ambas.
- **Profundidad del libro:** gráfico de compras y ventas acumuladas bajo el libro de órdenes.
- **Anotaciones (historial de análisis):** notas por moneda con el precio del momento —lo pone el servidor, no el navegador— y la variación desde entonces. Solo las ve su autor.
- **Estadísticas de operaciones:** resultado acumulado de las ventas (costo promedio), porcentaje de ventas positivas, resultado promedio, mejor y peor venta, volumen, comisiones de operación y de gestión, rendimiento por moneda y períodos de 30 días, 90 días, 1 año o todo. **Si las órdenes salieron del simulador, la pantalla lo dice en cada cifra: no son ganancias ni pérdidas reales.**
- Acceso a alertas de precio desde la cabecera del par.

### Módulo 5 · Mercados
- **Noticias y acontecimientos** (`/mercado/noticias`, en Mercados y en la ficha de cada moneda): cada registro muestra la fuente, la fecha y el enlace al medio, y se filtra por moneda. Los acontecimientos (próximos y pasados) se ven como calendario con su importancia.
- **Carga y revisión por el equipo** (Equipo › Noticias, permiso `contenido.publicar`): carga manual con validación de enlace, fuente y fecha (una noticia no puede tener fecha futura) y **importación de canales RSS/Atom** (botón o `flask noticias-importar`), que guarda solo título, enlace y fecha —no copia el texto del medio— y deja todo **en revisión** hasta que una persona lo publica. XML protegido contra entidades maliciosas; solo canales https. Cada alta y cambio de estado queda en la bitácora.
- **No hay noticias de ejemplo:** la plataforma no inventa contenido; la sección aparece cuando el equipo publica.
- **Mapa de calor interactivo:** tamaño por capitalización o por volumen y panel de detalle (precio, 24 h, 7 días, capitalización, volumen, accesos al gráfico y a la ficha) al pasar el cursor o enfocar; en el teléfono el primer toque muestra el detalle y el segundo abre el gráfico.

### Módulo 6 · Centro de transferencias
- **Centro de transferencias** (`/cliente/transferencias`): uso del límite diario, enviado y recibido en el mes, personas a las que envías seguido (con acceso a «enviar de nuevo»), historial filtrable con estado y código EN-, y acceso a cada comprobante.
- **Envío en tres pasos:** datos → **revisión** (destinatario con nombre abreviado, @usuario e identificador de cuenta, importe, moneda, cantidad, concepto, comisión, lo que se descuenta y lo que queda del límite) → confirmación con contraseña y código de dos pasos. Nada se mueve antes de confirmar; el envío se vuelve a validar al confirmar y no se duplica si el formulario se reenvía.
- **Transferencias a bancos o billeteras externas en modo demostración:** se recorre el formulario y el resumen, pero no se descuenta saldo, no se envía dinero y no se registra ningún movimiento; el resultado lo dice expresamente («No enviada»). Se habilitará solo con un proveedor de pagos autorizado (`TRANSFERENCIAS_REALES`, apagado por defecto).
- El detalle de cada envío muestra tipo, estado y concepto.

### Módulo 7 · Servicios financieros
- **Herramientas** (`/herramientas`, en el menú): **conversor** entre dólar, guaraní (tipo de cambio de la plataforma, si está cargado) y cada moneda; **calculadora de comisiones** con las comisiones configuradas (compra o venta, conversión, envío interno, gestión anual); **rentabilidad de una operación** (cantidad, comisiones, resultado y precio para no perder); **riesgo y tamaño de posición** (pérdida máxima, cantidad a comprar según el stop, relación riesgo/beneficio y aviso si se necesita más capital).
- **Simulador con precios históricos:** compras periódicas (semanal, quincenal o mensual) desde hace 3, 6 o 12 meses, cada una al precio real registrado en esa fecha; muestra invertido, valor hoy, resultado, precio promedio, comparación con invertir todo el primer día y gráfico. Si no hay historial suficiente lo dice; nunca rellena datos. Rendimientos pasados no garantizan futuros.
- **Calendario de acontecimientos** con los eventos publicados por el equipo (módulo 5) y accesos al comparador, análisis de cartera, estadísticas y academia.

### Módulo 8 · Administración
- **Control dual de acciones críticas** (`CONTROL_DUAL`, encendido por defecto): cambiar límites de operación, dar de baja o reactivar a un usuario del equipo y cobrar la comisión de gestión ya no se ejecutan al pedirlo. Se crea un pedido con motivo obligatorio que otra persona de Administración o Cumplimiento aprueba (y entonces se ejecuta) o rechaza con nota. Quien pide no puede aprobar, los pedidos vencen a las 48 horas, no se aceptan duplicados y cada paso queda en la bitácora y se notifica (Equipo › Autorizaciones).
- **Incidencias** (Equipo › Incidencias): registro con categoría, severidad, cliente relacionado y responsable; línea de tiempo de notas; cambios de estado, severidad y responsable; para resolver o cerrar hace falta una nota. Las altas y críticas avisan a Administración y Cumplimiento y aparecen en las alertas del panel.
- **Perfil completo del cliente** para el equipo: identidad y cuenta (identificador, @usuario, alta, último ingreso, sesiones, dos pasos, nivel), solicitudes, incidencias y actividad de la cuenta. Teléfono, dirección y nacimiento se muestran **enmascarados**; solo Cumplimiento y Administración pueden verlos completos indicando un motivo, y esa consulta queda registrada con nombre y motivo.
- **Reporte de indicadores** (CSV agregado sin datos personales: clientes, volumen, órdenes del simulador marcadas como tales, depósitos, retiros, transferencias, comisiones, alertas, incidencias y autorizaciones), con su exportación registrada.
- Nuevos permisos: `autorizaciones.resolver`, `incidencias.gestionar`, `clientes.datos_sensibles`. En el celular, las secciones secundarias del equipo están en el menú de la cuenta, con contador.

## [0.20.0] - 2026-11-16

Evolución completa de la plataforma, trabajada por módulos. Los servicios financieros reales siguen deshabilitados.

### Módulo 1 · Seguridad y arquitectura (hallazgos S-03 a S-10 de la auditoría)
- **S-03 límites de tasa:** ingreso (20 por IP y 10 por correo cada 10 min), registro, búsqueda de destinatarios (20 por usuario cada 10 min), recuperación de contraseña, descarga de datos y consultas de mercado (240 por minuto por IP). Responden 429 con «Retry-After» y un mensaje claro.
- **S-04 cifrado en reposo:** secretos de verificación en dos pasos y documentos de identidad cifrados con Fernet y una clave fuera de la base (`CLAVE_CIFRADO`). Comandos `flask cifrado generar-clave`, `migrar` y `rotar` (rotación sin cortar el servicio).
- **S-05 respaldos:** `flask respaldo crear` hace una copia en caliente de la base y los documentos, la cifra, conserva las últimas 14 y la copia afuera con `RESPALDO_COMANDO`. Cada respaldo se restaura en una carpeta temporal y se verifica (integridad, cadena de la bitácora, conteos, saldos y documentos). Pantalla Ajustes › Respaldos y servicio diario en docker-compose.
- **S-06 antilavado:** reglas de monto alto, fraccionamiento, entrada y salida rápida, envíos múltiples y PEP; importación de listas de sanciones (ONU, OFAC) con coincidencia por documento y por nombre; cola de alertas para Cumplimiento con resolución justificada; una coincidencia con sanciones bloquea operaciones hasta resolverla. Ficha de debida diligencia (PEP, cargo, nacionalidad, domicilio fiscal).
- **S-07 recuperación de contraseña:** enlace de un solo uso por correo con vencimiento de 30 minutos, que no saltea la verificación en dos pasos, cierra todas las sesiones y avisa al titular. La respuesta no revela si el correo es cliente.
- **S-08 contraseñas:** scrypt con N=2^15, r=8, p=3 (equivalente al mínimo de OWASP) y actualización automática del hash al próximo ingreso.
- **S-09 secretos:** cualquier secreto se puede leer de un archivo (`*_FILE`), y en producción el arranque exige `SECRET_KEY` de 32 caracteres o más y `CLAVE_CIFRADO`.
- **S-10 escala:** los precios en vivo responden 304 cuando no cambiaron (ETag), así el sondeo cada 3 segundos casi no cuesta.
- **Idempotencia:** cada formulario que mueve dinero lleva una clave única; un doble clic o un reenvío del navegador no duplica la operación.
- **Observabilidad y recuperación:** identificador por solicitud (X-Request-ID) visible en las páginas de error, registro estructurado, `/salud` para monitores, `/metricas` para Prometheus con token y `flask recuperar` para retomar ejecuciones cortadas.

### Módulo 2 · Terminal de trading
- **Órdenes OCO:** dos órdenes enlazadas (toma de ganancia arriba y corte de pérdida abajo, o compra si baja y si sube); al ejecutarse una, la otra se cancela sola. Reserva el saldo una sola vez y cancelar una pata cancela el grupo.
- **Proteger una compra:** al comprar a mercado se puede fijar toma de ganancia y corte de pérdida; se validan en el servidor antes de comprar, se programan por la cantidad exacta comprada y forman una OCO si van las dos.
- **Gráfico:** zoom con rueda, botones o pellizco; desplazamiento arrastrando hacia el pasado; doble toque para volver; hasta 365 velas diarias y 300 intradiarias. Parámetros configurables de MA, EMA, Bollinger, RSI y MACD, guardados en el dispositivo.
- **Órdenes:** pestañas Abiertas, Ejecutadas y Canceladas (con el motivo, por ejemplo «OCO: se activó la orden #12»).
- **Confirmación:** muestra cómo cambiaría tu exposición a la moneda, advierte si pasaría del 50 % de tu cartera y aclara cuando la orden va al simulador.
- **Análisis del activo:** rendimiento a 7, 30 y 90 días y 1 año, volatilidad anual, máximo y distancia al máximo, RSI diario y tendencia respecto de sus medias de 20 y 50 días, con la aclaración de que no son recomendaciones. **Tu posición y riesgo:** cantidad, valor, peso, costo promedio, resultado sin realizar y lo reservado.
- **Validación en el servidor:** toda orden revisa identidad, revisión de cumplimiento, moneda habilitada, pausa de seguridad, precio vigente y saldo disponible.

### Módulo 3 · Inicio inteligente y centro de avisos
- **Panel personalizable:** cada persona elige qué módulos ver y en qué orden (con botones accesibles para subir y bajar); se guarda en su cuenta y se valida en el servidor.
- **Patrimonio animado:** cuenta hasta el valor al abrir y se actualiza suavemente con cada precio en vivo. El gráfico muestra el cambio del período elegido y, al tocar un punto, cuánto cambió desde el inicio. Corregido: el gráfico abría en «1 año» aunque estuviera marcado «7D».
- **Rendimiento por período** (24 horas, 7 días, 30 días, 1 año): cambio del patrimonio y rentabilidad ponderada por tiempo comparada con Bitcoin y con el promedio de las 10 monedas de mayor capitalización.
- **Riesgo de tu cartera:** nivel según la volatilidad comparado con el perfil declarado, diversificación efectiva, peso en dólares y estables y mayor posición. **Mejores y peores** de la cartera según el resultado sobre el costo.
- **Alertas importantes** (órdenes a punto de activarse, retiros en revisión, concentración, avisos de seguridad sin leer, precios sin actualizar) y **Para considerar**: observaciones automáticas con su porqué, aclarando que no son asesoramiento.
- **Resumen del mercado en palabras** con números calculados: variación ponderada por capitalización, cuántas suben, mayor suba y baja, dominancia de Bitcoin.
- **Centro de avisos:** categorías (operaciones, precios y órdenes, seguridad, cuenta, mercado), filtro de no leídos, agrupación por día y elección de qué categorías llegan por correo (seguridad siempre llega).

### Módulo 4 · Mercados y ficha de cada moneda
- **Listado:** ranking por capitalización, fuente y hora de la última actualización visibles, tarjetas de tendencia de 7 días y de las más negociadas respecto de su tamaño, orden por tendencia.
- **Mapa de calor:** período de 24 horas o 7 días, leyenda de colores y detalle al pasar el cursor (precio, variación y capitalización).
- **Comparar monedas:** hasta cuatro en la misma escala (todas parten de 0 %) en 7, 30 o 90 días o 1 año, con tabla lado a lado de precio, variaciones, volatilidad, RSI, distancia al máximo, capitalización, volumen y ranking.
- **Alertas por variación:** además de las de precio, avisan cuando una moneda sube o baja un porcentaje en 24 horas. Cada alerta avisa una vez.
- **Ficha de cada moneda:** qué es, año de lanzamiento, cómo funciona y categoría (texto descriptivo, no datos de mercado), ranking, estadísticas con su fuente y hora, rendimientos a 7, 30 y 90 días y 1 año, volatilidad y RSI, actividad del mercado (mejor compra y venta, diferencia y últimas operaciones, marcadas como simuladas cuando lo son), cotizaciones diarias y exportación del último año a CSV con fuente y zona horaria. Rangos nuevos de 90 días y 1 año.
- **Gráficos de línea en tiempo real:** el eje horizontal ahora respeta las fechas; antes, las últimas horas (que tienen más puntos) se estiraban y deformaban la curva.

### Módulo 5 · Billetera, historial y comprobantes
- **Identificador único** de cada movimiento (OP-000123 para operaciones, EN-000045 para envíos), visible en el detalle, el historial exportado y el comprobante.
- **Comprobantes** imprimibles o guardables en PDF, con una huella de verificación (HMAC-SHA256 de los datos del movimiento) y el rastro de la bitácora encadenada. El equipo comprueba que no fue alterado en Cumplimiento › Verificar comprobante; cada verificación queda registrada.
- **Historial:** filtros por fecha, moneda y tipo combinables con el buscador, y exportación a CSV con los mismos filtros, código y huella de cada movimiento.
- **Saldo pendiente de acreditar** (depósitos en revisión), además de disponible, reservado y en retiros.
- **Vista en dólares o guaraníes:** se elige en la billetera y se guarda en la cuenta. Indica el tipo de cambio usado, de dónde sale y cuándo se cargó, y aclara que los saldos se llevan en dólares.

### Módulo 6 · Perfil y centro de seguridad
- **Nivel de verificación** (0 cuenta abierta, 1 identidad verificada, 2 reforzada) con lo que permite cada uno y qué falta para el siguiente.
- **Límites de operación** visibles con lo usado hoy: máximo por orden, envíos por día y **retiros por día** (límite nuevo, US$ 50.000 por defecto).
- **Centro de seguridad:** puntaje de protección de 0 a 100 con controles (dos pasos, contraseña, identidad, sesiones abiertas, intentos fallidos, avisos sin leer), dispositivos con sesión y actividad reciente.
- **Preferencias:** moneda de la billetera, apariencia, avisos por correo e inicio. **Historial de actividad** con las últimas acciones del usuario tomadas de la bitácora.
- Las claves de API para clientes no se ofrecen todavía; el perfil lo indica.

### Módulo 7 · Ayuda, Academia, Earn y Análisis de cartera
- **Centro de ayuda:** preguntas frecuentes con buscador y consultas con seguimiento. El equipo las atiende en una pantalla nueva de Soporte y el cliente recibe un aviso con cada respuesta.
- **Academia:** 10 lecciones sobre primeros pasos, trading, seguridad y finanzas personales, con progreso guardado y enlace para practicar.
- **Earn (solo informativo):** explica staking, ahorro en estables y préstamos con sus riesgos. Ningún producto está habilitado ni se promete rendimiento; solo se puede anotar interés.
- **Análisis de cartera:** peso, volatilidad, aporte al riesgo y resultado de cada activo, diversificación efectiva y rendimiento por período frente a Bitcoin y al Top 10.
- Navegación: Análisis, Academia, Earn y Ayuda en la barra lateral de escritorio y en el perfil en el celular.

### Módulo 8 · Panel administrativo
- **Panel de administración:** clientes (altas, verificados, con dos pasos, activos), volumen operado en 24 horas, 7 y 30 días, depósitos, retiros y envíos, activos más utilizados, alertas de riesgo (sanciones, antilavado, ejecución, precios, respaldos, cuentas bloqueadas, consultas), mayores órdenes y últimas acciones del equipo.
- **Límites editables** por Administración (máximo por orden, envíos y retiros por día, doble firma, umbral antilavado), con rangos válidos y registro en la bitácora.
- **Roles y permisos:** matriz completa de qué puede cada rol y estado de dos pasos del equipo. Cumplimiento ve el panel y la matriz en solo lectura; solo Administración cambia ajustes.

### Módulo 9 · Experiencia visual y móvil
- Transiciones suaves entre pantallas, entrada animada de avisos y diálogos con fondo desenfocado; todo se desactiva con «reducir movimiento».
- **Confirmaciones propias:** un diálogo de la aplicación reemplaza al del navegador en todas las acciones que piden confirmar.
- **Estado de carga:** al enviar un formulario, el botón muestra un giro y no se puede tocar dos veces.
- **Celular:** barra inferior translúcida con indicador de la sección activa y respuesta al toque, botones de 44 px, campos que no disparan el zoom al escribir, pestañas que se deslizan y dejan a la vista la activa. En el equipo, Mercados y Trading pasan a la barra lateral para no apretar la barra inferior.
- Recorrido automático de 57 pantallas en 340 px, 390 px y 1440 px: sin desbordes horizontales, sin textos cortados y sin errores de consola.

## [0.10.0] - 2026-11-15

Etapa 2 del plan (rediseño visual) más las dos correcciones críticas de la auditoría técnica.

### Seguridad y exactitud
- **Compras simultáneas (S-01, crítico):** dos compras pedidas al mismo tiempo podían aprobarse con el mismo saldo. Ahora, dentro de la transacción que registra el plan, se descuenta lo que otras compras en curso y las órdenes abiertas ya comprometieron; si no alcanza, la segunda se rechaza con un mensaje claro. Nueva prueba de concurrencia con hilos que falla sin la corrección.
- **Frescura de precios (S-02):** en producción una operación o un envío de cripto exige un precio de hace 2 minutos como máximo (antes 60). Configurable con `PRECIO_MAX_MINUTOS`.

### Diseño
- Identidad nueva: tipografía Inter e Inter Display incluida en la aplicación (sin depender de servicios externos, licencia OFL), cifras tabulares, marca propia en SVG (también como ícono de la pestaña), paleta oscura más profunda con un solo acento cobalto y un detalle dorado, paneles separados por líneas finas, entrada suave del contenido y respuesta al tocar botones. Respeta «reducir movimiento» del sistema.
- **Inicio** rehecho como panel financiero: patrimonio total con resultado de las últimas 24 h, disponible, reservado en órdenes, en retiros y aportado neto; **gráfico interactivo de la evolución del patrimonio** (7 días, 1 mes, 3 meses, 1 año y todo) calculado con tus tenencias reales y los precios de cada momento; accesos rápidos (depositar, comprar, vender, convertir, enviar, retirar); indicadores (rentabilidad frente a Bitcoin, resultado realizado y no realizado, exposición a cripto, mayor posición, volatilidad anual de 30 días); tabla de activos con precio en vivo, variación y peso; composición 3D; resumen del mercado con ganadoras y perdedoras; actividad reciente y movimientos del mes.
- **Trading:** indicadores técnicos que se prenden y apagan y se recuerdan en el dispositivo: medias móviles 7 y 25, media exponencial 20, bandas de Bollinger (20, 2), volumen, RSI 14 y MACD (12, 26, 9) en paneles propios. Barra de liquidez con la profundidad de compra y venta a ±1 % del precio medio.
- **Mercados:** filtros por variación (suben o bajan) y por capitalización (grande, mediana, chica), combinables con categoría, buscador y orden.
- **Billetera:** totales completos (patrimonio, disponible, reservado, en retiros, resultado realizado y no realizado, rentabilidad), pestañas Activos, Historial, Depósitos, Retiros, Transferencias y Compras y ventas, y tabla por activo con total, disponible, reservado, precio, valor, resultado con costo promedio y acciones.

## [0.9.0] - 2026-11-15

### Nuevo
- **27 criptomonedas** (antes 7): se suman USDC, Dogecoin, Cardano, TRON, Avalanche, Shiba Inu, Polkadot, Bitcoin Cash, Litecoin, Sui, Stellar, NEAR, Aptos, Cosmos, Uniswap, Aave, Polygon, Arbitrum, Optimism y Pepe, con categorías (principales, estables, capa 1, capa 2, DeFi y memes). Administración puede suspender las compras de una moneda sin impedir que quien la tiene la venda.
- **Precios en tiempo real:** nuevo servicio `flask precios-en-vivo` que actualiza cada `VIVO_SEGUNDOS` (3 por defecto) desde Binance o CoinGecko, y revisa en cada actualización las órdenes límite, los stops y las alertas. Las pantallas se refrescan cada 3 segundos con destello verde o rojo en cada cambio e indicador «En vivo». Para demostraciones, `FUENTE_PRECIOS=simulada` mueve los precios solos (no se permite en producción). El historial se guarda cada minuto y se poda solo (5 minutos después de un día, 1 hora después de tres, 1 día después de dos meses).
- **Trading:** pantalla nueva con selector de pares con buscador, gráfico de velas interactivo en 1m, 15m, 1h, 4h, 1D y 1S (medias móviles de 7 y 25, volumen, cruz con apertura, máximo, mínimo y cierre), libro de órdenes con profundidad, operaciones del mercado, panel de compra y venta con órdenes de mercado, límite y stop, porcentajes del disponible y resumen antes de confirmar, y pestañas de órdenes abiertas e historial. Con Binance, velas, libro y operaciones son reales; si no, se arman con el historial propio o se simulan y la pantalla lo indica.
- **Mercados:** volumen y capitalización de 24 h, máximo y mínimo, resumen del mercado (capitalización, volumen, dominancia de Bitcoin), monedas que más suben, bajan y se negocian, mapa de calor, buscador, categorías y orden por capitalización, volumen, variación o nombre.
- **Saldo disponible y bloqueado:** las órdenes límite y stop por un monto fijo reservan el saldo mientras están abiertas; la billetera muestra disponible, en órdenes y en retiros.
- **Depósitos y retiros:** método (transferencia; efectivo en la oficina y USDT solo si están configurados con `OFICINA_DIRECCION` y `DEPOSITO_USDT_DIRECCION`), tabla de comisiones, pantalla de revisión antes de confirmar y página de retiro propia.
- **Movimientos:** una sola lista con operaciones y envíos, buscador, filtros por tipo y detalle de cada movimiento con línea de estado, órdenes ejecutadas y asientos.
- **Seguridad del perfil:** dispositivos conectados, historial de sesiones, cerrar una sesión o todas las demás, aviso al ingresar desde un dispositivo nuevo y al cambiar la contraseña o activar dos pasos, y registro de eventos de seguridad.
- **Privacidad:** ocultar saldos (también con el ojo de la barra superior), elegir si otros clientes pueden encontrarte para enviarte dinero y descargar una copia de tus datos.
- **Inicio:** saldo disponible, accesos a comprar, vender, depositar, retirar y enviar, movimientos recientes, actividad del mes y mercados destacados.
- **Navegación de cinco secciones:** Inicio, Mercados, Trading, Billetera y Perfil, abajo en el celular y al costado en la computadora.
- Migraciones 0007 (monedas, categorías y datos de mercado) y 0008 (sesiones, privacidad y método).

### Cambios
- Los datos de demostración usan el corte de CoinGecko del 15 de noviembre de 2026 y un año de historia de precios.
- `/mercado/precios.json` devuelve `{precios, vivo, seg, fuente}`.

### Pruebas
- 120 pruebas automáticas.

## [0.8.0] - 2026-11-15

### Nuevo
- **Envíos entre clientes:** dólares o monedas a otro cliente por correo o número de cédula, al instante y sin comisión. Confirmación del destinatario con nombre parcial, contraseña (y código de dos pasos si está activo) en cada envío, límite diario configurable (`ENVIO_MAX_DIA_USD`) y aviso a Cumplimiento en envíos altos (`ENVIO_AVISO_USD`). Registros inmutables y reflejados en el libro, el estado de cuenta, la rentabilidad y el CSV.
- **Apertura de cuenta en línea** con cuestionario de perfil de inversor, aceptación de condiciones, protección contra robots y límite de registros por conexión. La cuenta queda sin verificar hasta que Cumplimiento acepte los documentos.
- **Resultado por moneda:** costo promedio, ganancia sin realizar y ganancia realizada en la billetera.
- **App instalable** en el celular (manifiesto, íconos y página sin conexión). No guarda datos de la cuenta en el teléfono.
- Condiciones del servicio públicas en `/condiciones`.
- Migración 0006 (transferencias y libro con los conceptos de envío y recepción).

### Pruebas
- 103 pruebas automáticas.

## [0.7.0] - 2026-11-14

### Nuevo
- **Órdenes por precio:** compra límite, venta límite, stop (venta si baja) y compra si sube. Quedan abiertas y se ejecutan solas, a precio de mercado, cuando el precio llega al nivel elegido; no reservan saldo y avisan si no se pudieron ejecutar.
- **Convertir:** cambio directo de una moneda por otra en un solo paso.
- **Gráfico de velas** en la página de cada moneda, además del de línea.
- **Portada pública** con escena 3D, mercado, funciones, pasos para abrir una cuenta y aviso de riesgo.
- Migración 0005.

### Pruebas
- 96 pruebas automáticas.

## [0.6.0] - 2026-11-14

### Nuevo: pensado para Paraguay
- **Guaraníes:** Administración carga el tipo de cambio de la casa (depósitos y retiros, con margen máximo configurable). El cliente puede depositar y cobrar retiros en guaraníes; cada operación guarda los guaraníes y el tipo de cambio aplicado. Los valores principales muestran su equivalente en guaraníes.
- **Compra automática (ahorro programado):** compra de una moneda por un monto fijo cada semana, cada 15 días o cada mes (`flask ejecutar-planes`, incluido en las tareas de Docker). Si no hay saldo, avisa y pasa a la fecha siguiente.
- **Alertas de precio:** aviso único cuando una moneda sube o baja hasta el precio elegido.
- **Resumen anual de criptoactivos** por cliente (compras, ventas, depósitos, retiros y tenencia al cierre), como base para las declaraciones informativas.
- Migración 0004.

### Pruebas
- 92 pruebas automáticas.

## [0.5.0] - 2026-11-14

### Nuevo
- **Compra y venta libre de cada moneda:** el cliente opera por su cuenta contra su saldo en dólares, a precio de mercado y en el momento, con el mismo motor de ejecución (simulador o Binance). Controles: identidad verificada, precio vigente, saldo suficiente, mínimo del exchange, máximo por orden (`ORDEN_MAXIMA_USD`) y pausa de emergencia.
- **Depósito a saldo:** un aporte puede quedar en dólares, sin invertirse en una cartera, para comprar monedas después.
- **Página de cada moneda:** precio en grande con escena 3D, gráfico de 24 horas, 7 y 30 días, máximo y mínimo, tenencia, precio promedio de compra, panel de órdenes y últimas órdenes.
- **Mercado tipo exchange:** favoritas, filtros (todas, favoritas, en mi billetera), orden por las que más suben o bajan, y **precios que se actualizan solos**.
- **Cinta de precios** en todas las pantallas y **billetera** con saldo por moneda y accesos para comprar y vender.
- **Tema oscuro por defecto**, con opción de tema claro desde el menú de la cuenta.
- Migración 0003 (tipos de operación `compra` y `venta`, activo negociado y favoritos).

### Pruebas
- 88 pruebas automáticas.

## [0.4.0] - 2026-11-13

### Nuevo
- **El 3D como protagonista:** el inicio del cliente, su cartera, el resumen del equipo y el mercado abren con una escena 3D a todo el ancho, con las cifras principales encima.
- **Motor 3D:** nueva forma **Órbitas** (el activo mayor al centro y los demás girando en anillos), entrada animada desde una nube de puntos, más brillo y recorrido automático por las cuatro formas en la pantalla de ingreso.
- **Rentabilidad ponderada por tiempo** de cada cliente, comparada con Bitcoin en el mismo período.
- **Composición frente a la cartera modelo:** peso actual y objetivo de cada activo, con aviso cuando la cartera se desvía 5 puntos o más.
- **Mercado:** precios, variación de 24 horas y de 7 días con minigráficos, para clientes y equipo.

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
