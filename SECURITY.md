# Seguridad

## Cómo reportar una vulnerabilidad

No abras un issue público. Escribe al responsable del proyecto por un canal privado con:

- qué encontraste y en qué pantalla o archivo;
- los pasos para reproducirlo;
- el impacto que crees que tiene.

Respondemos en un plazo de 3 días hábiles y avisamos cuando esté corregido.

## Qué protege el sistema

- Contraseñas con scrypt y sal individual; bloqueo tras intentos fallidos; verificación en dos pasos (TOTP) obligatoria para el equipo en producción.
- Sesiones con cierre por inactividad, invalidación al cambiar la clave y cookies `HttpOnly`, `SameSite=Lax` y `Secure`.
- Protección CSRF en todos los formularios y política de contenido estricta (solo scripts propios, sin recursos externos).
- Permisos por rol en el servidor para cada acción.
- Libro contable, órdenes, conciliaciones y bitácora de solo inserción, protegidos por disparadores de la base de datos; bitácora encadenada con SHA-256.
- Documentos del legajo validados por su contenido, guardados fuera de la carpeta pública con nombres aleatorios, servidos solo a su titular y al equipo, con cabeceras que impiden ejecutar contenido.

## Clave de API de Binance

- Crea la clave **solo con permiso de Spot**. **Nunca** habilites retiros: con ellos, quien robe la clave puede vaciar la cuenta.
- Restringe la clave a la IP pública del servidor.
- Guárdala solo en el `.env` del servidor (permisos 600) y rótala si alguien del equipo con acceso se va.
- Usa la pausa de emergencia de Ajustes → Ejecución ante cualquier sospecha, y revoca la clave desde Binance.

## Recomendaciones de operación

- Usa una `SECRET_KEY` larga y aleatoria, y no subas el archivo `.env` al repositorio.
- Mantén el servidor actualizado y limita el acceso SSH.
- Respalda a diario la base y la carpeta de documentos, cifrados y fuera del servidor.
- Revisa la bitácora y la conciliación todas las semanas.
- Antes de operar con dinero real, contrata una prueba de penetración externa.
