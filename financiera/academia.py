"""Academia: lecciones breves sobre criptomonedas, trading, seguridad y finanzas. Contenido educativo, no asesoramiento."""
CATEGORIAS = {"basico": "Primeros pasos", "trading": "Trading", "seguridad": "Seguridad", "finanzas": "Finanzas personales"}

# slug: (categoría, título, minutos, resumen, [(subtítulo, párrafo)], [puntos clave], enlace práctico (ruta, texto) o None)
LECCIONES = {
    "que-es-una-criptomoneda": ("basico", "Qué es una criptomoneda", 4,
        "Dinero digital que funciona sin un banco central, registrado en una red pública.", [
        ("Un registro compartido", "Una criptomoneda es un registro de quién tiene cuánto, mantenido por miles de computadoras en lugar de un solo banco. Ese registro se llama cadena de bloques: cada bloque agrupa transacciones y se enlaza con el anterior, de modo que cambiar el pasado es prácticamente imposible."),
        ("Por qué tienen precio", "Su precio surge de la oferta y la demanda. Bitcoin tiene una emisión limitada a 21 millones; otras monedas tienen reglas distintas. No hay un Estado ni una empresa que garantice su valor, y por eso el precio puede moverse mucho en poco tiempo."),
        ("Monedas estables", "Las monedas estables, como USDT o USDC, buscan valer siempre un dólar y se respaldan con reservas de la empresa que las emite. Sirven para moverse entre monedas sin salir del mundo cripto, pero dependen de la solvencia del emisor."),
        ], ["No hay garantía de depósitos: el riesgo es tuyo.", "El precio puede subir o bajar con fuerza.", "Entiende qué compras antes de comprarlo."],
        ("/mercado", "Ver las monedas disponibles")),
    "como-leer-un-precio": ("basico", "Cómo leer un precio y su variación", 3,
        "Qué significan el precio, la variación de 24 horas, el volumen y la capitalización.", [
        ("Precio y par", "El precio BTC/USD dice cuántos dólares vale un bitcoin. Siempre es un par: una moneda expresada en otra."),
        ("Variación de 24 horas", "Compara el precio de ahora con el de hace 24 horas. Un +3 % no dice nada del mes ni del año: mira también 7 y 30 días antes de sacar conclusiones."),
        ("Volumen y capitalización", "El volumen es cuánto se negoció en 24 horas: a más volumen, más fácil comprar o vender sin mover el precio. La capitalización es el precio por la cantidad en circulación, y permite comparar el tamaño de las monedas."),
        ], ["Un precio bajo por unidad no significa que sea barata.", "Poco volumen implica más diferencia entre compra y venta.", "Compara períodos, no solo el día."],
        ("/mercado/comparar", "Comparar monedas")),
    "tu-primera-compra": ("basico", "Tu primera compra, paso a paso", 4,
        "Del depósito a la compra, y qué revisar antes de confirmar.", [
        ("Depositar", "Primero se verifica tu identidad. Después pides un depósito en Billetera, transfieres y el equipo lo acredita cuando confirma que el dinero llegó."),
        ("Comprar", "En Trading eliges la moneda y el monto en dólares. Antes de confirmar ves el precio de referencia, la comisión y cuánto recibirías. El precio final puede variar un poco porque el mercado se mueve."),
        ("Después de comprar", "Tu moneda aparece en la billetera con su costo promedio. Desde ahí ves cuánto ganas o pierdes y puedes vender, convertir o enviar."),
        ], ["Empieza con un monto que puedas permitirte perder.", "Revisa siempre el resumen antes de confirmar.", "Comprar de a poco reduce el efecto de un mal momento."],
        ("/trading", "Ir a Trading")),
    "tipos-de-ordenes": ("trading", "Mercado, límite, stop y OCO", 5,
        "Los cuatro tipos de orden y cuándo conviene cada uno.", [
        ("Orden de mercado", "Se ejecuta ahora, al mejor precio disponible. Es la más simple; a cambio, aceptas el precio del momento."),
        ("Orden límite", "Tú fijas el precio. Una compra límite espera a que el precio baje hasta tu nivel; una venta límite, a que suba. Puede no ejecutarse nunca si el precio no llega."),
        ("Stop", "Una venta stop se activa si el precio cae hasta un nivel. Sirve para limitar una pérdida sin estar mirando la pantalla. Se ejecuta a precio de mercado, así que en caídas bruscas puede salir algo peor."),
        ("OCO", "Son dos órdenes enlazadas: una toma la ganancia si sube y otra corta la pérdida si baja. Cuando una se ejecuta, la otra se cancela sola. Es la forma ordenada de definir de antemano cuánto quieres ganar y cuánto aceptas perder."),
        ], ["Decide tu salida antes de entrar.", "Un stop limita la pérdida, no la elimina.", "Lo reservado en órdenes abiertas no se puede usar para otra cosa."],
        ("/trading", "Probar los tipos de orden")),
    "velas-e-indicadores": ("trading", "Velas e indicadores sin misterio", 6,
        "Cómo leer una vela y qué dicen las medias, el RSI, el MACD y Bollinger.", [
        ("La vela", "Cada vela resume un período: dónde abrió, dónde cerró, el máximo y el mínimo. Verde si cerró arriba de donde abrió, roja si cerró abajo."),
        ("Medias móviles", "Promedian el precio de las últimas velas y suavizan el ruido. Cuando el precio está sobre su media, la tendencia reciente es de suba. La EMA da más peso a lo más nuevo."),
        ("RSI y MACD", "El RSI va de 0 a 100: sobre 70 suele decirse que está sobrecomprado y bajo 30, sobrevendido. El MACD compara dos medias para mostrar si el impulso gana o pierde fuerza."),
        ("Bandas de Bollinger", "Dibujan un canal alrededor de la media según la volatilidad. Bandas anchas indican un mercado agitado; angostas, uno calmo."),
        ], ["Ningún indicador predice el futuro: describen el pasado.", "Úsalos para ordenar tus decisiones, no para justificarlas.", "Varias señales juntas valen más que una sola."],
        ("/trading", "Ver el gráfico con indicadores")),
    "gestion-del-riesgo": ("trading", "Gestión del riesgo", 5,
        "Cuánto arriesgar en cada operación y por qué diversificar.", [
        ("Tamaño de la posición", "Una regla común es no arriesgar más del 1 o 2 % de tu capital en una sola operación. Si tu stop está 5 % abajo, eso define cuánto puedes comprar."),
        ("Concentración", "Si una sola moneda es más de la mitad de tu cartera, tu resultado depende casi por completo de ella. Repartir reduce ese riesgo, a costa de no aprovechar tanto sus subas."),
        ("Volatilidad", "Mide cuánto se mueve el precio. Una cartera con volatilidad alta puede perder una parte importante de su valor en días. Que coincida con lo que estás dispuesto a soportar es más importante que acertar el momento."),
        ], ["Define la pérdida máxima antes de operar.", "Diversificar no elimina el riesgo de mercado.", "Revisa tu exposición en Análisis de cartera."],
        ("/cliente/analisis", "Ver el análisis de mi cartera")),
    "proteger-tu-cuenta": ("seguridad", "Cómo proteger tu cuenta", 4,
        "Contraseña, verificación en dos pasos y sesiones.", [
        ("Contraseña única", "Usa una contraseña larga que no uses en ningún otro sitio. Un gestor de contraseñas te la recuerda."),
        ("Verificación en dos pasos", "Además de la contraseña, te pide un código que cambia cada 30 segundos en una aplicación de tu teléfono. Aunque alguien robe tu contraseña, no puede entrar."),
        ("Sesiones", "En el Centro de seguridad ves en qué dispositivos está abierta tu cuenta y puedes cerrarlos a distancia."),
        ], ["Activa la verificación en dos pasos hoy.", "Guarda los códigos de respaldo en un lugar seguro.", "Si ves una sesión que no reconoces, ciérrala y cambia la contraseña."],
        ("/cuenta/centro-seguridad", "Abrir el Centro de seguridad")),
    "estafas-comunes": ("seguridad", "Estafas comunes y cómo reconocerlas", 4,
        "Suplantación, rentabilidades garantizadas y falsos soportes.", [
        ("Suplantación", "Mensajes o páginas que imitan a la plataforma para robarte la contraseña. Entra siempre escribiendo la dirección o desde la aplicación instalada, nunca desde un enlace que te llegó."),
        ("Rentabilidad garantizada", "Nadie puede garantizar ganancias con criptomonedas. Si te prometen un porcentaje fijo sin riesgo, es una estafa o un riesgo que no te están contando."),
        ("Falso soporte", "El equipo nunca te pide tu contraseña, tus códigos ni que instales programas de acceso remoto. Las consultas se atienden desde Ayuda, dentro de la plataforma."),
        ], ["Desconfía de la urgencia.", "Nunca compartas contraseña ni códigos.", "Un envío a otro cliente no se puede deshacer."],
        ("/cliente/ayuda", "Ir al centro de ayuda")),
    "presupuesto-e-inversion": ("finanzas", "Antes de invertir: tu presupuesto", 4,
        "Fondo de emergencia, deudas y cuánto destinar a activos de riesgo.", [
        ("Primero lo primero", "Antes de invertir en activos de riesgo conviene tener un fondo de emergencia de varios meses de gastos y sin deudas caras, como tarjetas."),
        ("Cuánto destinar", "Destina a criptomonedas solo dinero que no vas a necesitar en el corto plazo y cuya pérdida no cambie tu vida. Para muchas personas es una parte pequeña de sus ahorros."),
        ("Constancia", "Aportar un monto fijo cada mes promedia los precios de compra y evita decidir por impulso."),
        ], ["No inviertas dinero que necesitas pronto.", "El horizonte largo tolera mejor la volatilidad.", "Un plan simple y constante suele rendir más que adivinar el momento."],
        ("/cliente/invertir", "Programar un aporte")),
    "impuestos-en-paraguay": ("finanzas", "Criptomonedas e impuestos en Paraguay", 4,
        "Qué informar y por qué conviene guardar tus comprobantes.", [
        ("Obligación de informar", "Desde 2026 la autoridad tributaria (DNIT) exige a ciertos contribuyentes una declaración informativa de sus operaciones con criptoactivos. Las reglas pueden cambiar: confirma tu caso con tu contador."),
        ("Tus registros", "Guarda el detalle de cada operación: fecha, cantidad, valor en dólares y comisiones. Desde Billetera › Historial puedes exportarlo completo."),
        ("Ganancias", "El tratamiento de las ganancias depende de tu situación y de las normas vigentes. Esta lección es informativa y no reemplaza el asesoramiento profesional."),
        ], ["Exporta tu historial una vez al año.", "Consulta con un contador matriculado.", "Guarda los comprobantes de cada movimiento."],
        ("/cliente/movimientos", "Ver y exportar mi historial")),
}


def lista():
    return [{"slug": s, "categoria": v[0], "titulo": v[1], "minutos": v[2], "resumen": v[3]} for s, v in LECCIONES.items()]


def leccion(slug):
    v = LECCIONES.get(slug)
    if not v:
        return None
    slugs = list(LECCIONES)
    i = slugs.index(slug)
    return {"slug": slug, "categoria": v[0], "titulo": v[1], "minutos": v[2], "resumen": v[3], "secciones": v[4], "claves": v[5],
            "practica": v[6], "siguiente": slugs[i + 1] if i + 1 < len(slugs) else None}
