"""Información de referencia de cada moneda: qué es, quién la creó y cómo funciona.

Es texto descriptivo y estable (no son datos de mercado: precios, volumen y capitalización salen de la fuente de
precios configurada, con su hora). Si una moneda no tiene ficha, la pantalla lo dice en lugar de inventarla.
"""
INFO = {
    "BTC": ("2009", "Prueba de trabajo", "La primera criptomoneda, creada por Satoshi Nakamoto. Su emisión está limitada a 21 millones de unidades y la red la mantienen mineros que validan bloques cada diez minutos aproximadamente."),
    "ETH": ("2015", "Prueba de participación (desde 2022)", "La moneda de Ethereum, la red de contratos inteligentes más usada. Se paga en ETH el costo de usar la red, y sobre ella funcionan muchas aplicaciones de finanzas descentralizadas y estables."),
    "USDT": ("2014", "Moneda estable", "Tether, una moneda estable que busca valer un dólar estadounidense, respaldada por reservas que declara la empresa emisora. Circula en varias redes, como TRON y Ethereum."),
    "BNB": ("2017", "Prueba de participación", "La moneda del ecosistema de Binance. Se usa para pagar comisiones en el exchange y en BNB Chain, la red asociada."),
    "SOL": ("2020", "Prueba de participación", "La moneda de Solana, una red pensada para muchas transacciones por segundo con costos bajos. Tuvo varias interrupciones de servicio en sus primeros años."),
    "XRP": ("2012", "Consenso propio (XRP Ledger)", "La moneda del XRP Ledger, vinculada a la empresa Ripple, orientada a pagos y transferencias internacionales rápidas."),
    "LINK": ("2017", "Token en Ethereum", "El token de Chainlink, una red de oráculos que lleva datos externos (como precios) a los contratos inteligentes."),
    "USDC": ("2018", "Moneda estable", "USD Coin, emitida por Circle, una moneda estable que busca valer un dólar con reservas en efectivo y títulos de corto plazo que se auditan periódicamente."),
    "DOGE": ("2013", "Prueba de trabajo", "Dogecoin nació como una broma basada en un meme y se volvió una de las monedas más conocidas. No tiene un límite máximo de emisión."),
    "ADA": ("2017", "Prueba de participación", "La moneda de Cardano, una red de contratos inteligentes desarrollada con un enfoque académico y de revisión formal."),
    "TRX": ("2017", "Prueba de participación delegada", "La moneda de TRON, una red muy usada para transferir monedas estables como USDT por su bajo costo."),
    "AVAX": ("2020", "Prueba de participación", "La moneda de Avalanche, una plataforma de contratos inteligentes que permite crear redes propias (subredes)."),
    "SHIB": ("2020", "Token en Ethereum", "Shiba Inu, una moneda meme creada como token de Ethereum. Su precio depende sobre todo del interés especulativo."),
    "DOT": ("2020", "Prueba de participación nominada", "La moneda de Polkadot, una red que conecta cadenas especializadas y comparte su seguridad entre ellas."),
    "BCH": ("2017", "Prueba de trabajo", "Bitcoin Cash surgió de una división de Bitcoin en 2017 para permitir bloques más grandes y pagos más baratos."),
    "LTC": ("2011", "Prueba de trabajo", "Litecoin, una de las monedas más antiguas, creada por Charlie Lee a partir del código de Bitcoin con bloques más rápidos."),
    "SUI": ("2023", "Prueba de participación delegada", "La moneda de Sui, una red de contratos inteligentes desarrollada por Mysten Labs, enfocada en velocidad y procesamiento en paralelo."),
    "XLM": ("2014", "Protocolo de consenso de Stellar", "Lumens, la moneda de Stellar, una red para pagos y emisión de activos digitales entre instituciones financieras y personas."),
    "NEAR": ("2020", "Prueba de participación", "La moneda de NEAR Protocol, una red de contratos inteligentes que divide el trabajo en fragmentos para escalar."),
    "APT": ("2022", "Prueba de participación", "La moneda de Aptos, una red de contratos inteligentes creada por exintegrantes del proyecto de Meta para monedas digitales."),
    "ATOM": ("2019", "Prueba de participación", "La moneda del Cosmos Hub, en el centro de un ecosistema de cadenas independientes que se comunican entre sí."),
    "UNI": ("2020", "Token en Ethereum", "El token de gobierno de Uniswap, uno de los exchanges descentralizados más grandes. Da voto sobre cambios del protocolo."),
    "AAVE": ("2020", "Token en Ethereum", "El token de gobierno de Aave, un protocolo descentralizado de préstamos con garantía en criptomonedas."),
    "POL": ("2024", "Token de Polygon", "POL reemplazó a MATIC como moneda de Polygon, un conjunto de redes que buscan abaratar y acelerar transacciones compatibles con Ethereum."),
    "ARB": ("2023", "Token de gobierno", "El token de gobierno de Arbitrum, una red de segunda capa sobre Ethereum que agrupa transacciones para reducir costos."),
    "OP": ("2022", "Token de gobierno", "El token de gobierno de Optimism, una red de segunda capa sobre Ethereum basada en rollups optimistas."),
    "PEPE": ("2023", "Token en Ethereum", "Pepe, una moneda meme lanzada como token de Ethereum. No tiene utilidad más allá de la especulación y su precio es muy volátil."),
}


def ficha(codigo):
    f = INFO.get(codigo)
    if not f:
        return None
    return {"lanzamiento": f[0], "consenso": f[1], "descripcion": f[2]}
