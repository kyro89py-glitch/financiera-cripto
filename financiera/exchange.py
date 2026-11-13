"""Conexión con el exchange donde se ejecutan las órdenes.

Hay tres ejecutores con la misma interfaz:

- ``Binance``: órdenes de mercado reales contra USDT por la API REST de Binance Spot (o su red de pruebas).
- ``Simulado``: ejecuta al precio vigente registrado, sin salir del sistema. Es el modo por defecto.
- ``Interno``: lo usa el motor para lo que no se negocia en el exchange (en modo Binance, el USDT, que es la
  moneda contra la que se opera).

Unidades: los dólares en centavos y las criptomonedas en unidades de 1e-8, siempre enteros.
"""
import hashlib
import hmac
import json
import time
import urllib.parse
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal

import requests
from flask import current_app

from .dinero import CRIPTO, unidades_por, valor_cent

U = Decimal(CRIPTO)
CENT = Decimal(100)
URL_BINANCE = "https://api.binance.com"
URL_BINANCE_PRUEBAS = "https://testnet.binance.vision"
MONEDA_COTIZACION = "USDT"


class ErrorExchange(Exception):
    """definitivo=True: el exchange rechazó la orden y seguro no se creó.
    definitivo=False: no se sabe si se creó (sin respuesta, error 5xx): hay que consultarla antes de reenviar."""

    def __init__(self, mensaje, definitivo=True, codigo=None):
        super().__init__(mensaje)
        self.definitivo = definitivo
        self.codigo = codigo


@dataclass
class Reglas:
    minimo_cent: int = 0      # importe mínimo de una orden (filtro NOTIONAL)
    paso: int = 1             # incremento de cantidad, en unidades de 1e-8 (filtro LOT_SIZE)
    minimo_unidades: int = 1  # cantidad mínima, en unidades de 1e-8


@dataclass
class Relleno:
    """Resultado de una orden ejecutada, ya traducido a lo que se asienta en el libro del cliente."""
    cantidad_bruta: int           # unidades negociadas en el exchange (venta: incluye la comisión cobrada en el activo)
    cantidad: int                 # compra: unidades que recibe el cliente; venta: unidades que salen del cliente
    importe_cent: int             # compra: dólares que paga el cliente; venta: dólares netos que recibe
    precio: Decimal               # precio promedio de ejecución
    comision: Decimal = Decimal(0)
    comision_activo: str | None = None
    ref: str | None = None
    parcial: bool = False
    respuesta: dict = field(default_factory=dict)


def _dec(x):
    return Decimal(str(x))


def _texto_cantidad(unidades):
    q = (Decimal(unidades) / U).quantize(Decimal("0.00000001"))
    s = format(q, "f").rstrip("0").rstrip(".")
    return s or "0"


def traducir(activo, lado, ejecutada, cotizada, comisiones, precio=None, ref=None, parcial=False, respuesta=None):
    """Convierte cantidades del exchange (Decimal) en un Relleno para el libro.

    Compra: el cliente recibe lo ejecutado menos la comisión cobrada en el mismo activo y paga lo cotizado
    (más la comisión si se cobró en USDT), redondeado hacia arriba al centavo.
    Venta: salen del cliente las unidades vendidas (más la comisión si se cobró en el activo) y recibe lo
    cotizado menos la comisión en USDT, redondeado hacia abajo. Una comisión en BNB de otro activo la paga la casa.
    """
    com_activo = comisiones.get(activo, Decimal(0))
    com_cot = comisiones.get(MONEDA_COTIZACION, Decimal(0))
    bruto = int((ejecutada * U).to_integral_value(ROUND_DOWN))
    com_u = int((com_activo * U).to_integral_value(ROUND_CEILING))
    if lado == "compra":
        cantidad = bruto - com_u
        importe = int(((cotizada + com_cot) * CENT).to_integral_value(ROUND_CEILING))
    else:
        cantidad = bruto + com_u
        importe = int(((cotizada - com_cot) * CENT).to_integral_value(ROUND_DOWN))
    if precio is None:
        precio = (cotizada / ejecutada) if ejecutada else Decimal(0)
    principal = max(comisiones.items(), key=lambda kv: kv[1], default=(None, Decimal(0)))
    return Relleno(cantidad_bruta=bruto, cantidad=cantidad, importe_cent=importe,
                   precio=precio.quantize(Decimal("0.00000001")), comision=principal[1], comision_activo=principal[0],
                   ref=ref, parcial=parcial, respuesta=respuesta or {})


# ---------------------------------------------------------------------------------------------------------------
class Simulado:
    """Ejecuta al precio registrado en el sistema. Sirve para operar sin exchange y para pruebas."""
    nombre = "simulado"
    etiqueta = "Simulador interno"
    real = False

    def __init__(self, precios, comision_pct=Decimal(0), minimo_cent=0):
        self._precios = precios
        self.comision = Decimal(comision_pct) / 100
        self.minimo_cent = minimo_cent
        self.margen_venta = self.comision

    def opera(self, activo):
        return activo != "USD"

    def reglas(self, activo):
        return Reglas(minimo_cent=self.minimo_cent)

    def _precio(self, activo):
        p = self._precios.get(activo)
        if not p:
            raise ErrorExchange(f"No hay precio para {activo}.")
        return Decimal(p["precio"])

    def comprar(self, activo, importe_cent, id_orden):
        precio = self._precio(activo)
        bruto = unidades_por(importe_cent, precio)
        if bruto <= 0:
            raise ErrorExchange(f"El monto no alcanza para comprar {activo}.")
        com = int((Decimal(bruto) * self.comision).to_integral_value(ROUND_CEILING))
        return Relleno(cantidad_bruta=bruto, cantidad=bruto - com, importe_cent=importe_cent, precio=precio,
                       comision=Decimal(com) / U, comision_activo=activo if com else None, ref=id_orden)

    def vender(self, activo, cantidad, id_orden):
        precio = self._precio(activo)
        ingreso = valor_cent(activo, cantidad, precio)
        com = int((Decimal(ingreso) * self.comision).to_integral_value(ROUND_CEILING))
        return Relleno(cantidad_bruta=cantidad, cantidad=cantidad, importe_cent=ingreso - com, precio=precio,
                       comision=Decimal(com) / CENT, comision_activo=MONEDA_COTIZACION if com else None, ref=id_orden)

    def consultar(self, activo, id_orden):
        return None  # no guarda estado: una orden que quedó "enviada" se vuelve a ejecutar

    def saldos(self):
        return None

    def disponible(self, activo):
        return None

    def verificar(self):
        return [(True, "Las órdenes se ejecutan dentro del sistema, al precio vigente registrado.")]


class Interno(Simulado):
    nombre = "interno"
    etiqueta = "Conversión interna"


# ---------------------------------------------------------------------------------------------------------------
class Binance:
    """Cliente mínimo de la API REST de Binance Spot (órdenes de mercado contra USDT)."""
    nombre = "binance"
    margen_venta = Decimal("0.004")   # colchón para comisión y deslizamiento al calcular cuánto vender
    _cache_reglas = {}

    def __init__(self, clave, secreto, url=URL_BINANCE_PRUEBAS, recv_window=5000, sesion=None, timeout=10):
        self.clave, self.secreto = clave or "", secreto or ""
        self.url = url.rstrip("/")
        self.recv_window = recv_window
        self.sesion = sesion or requests.Session()
        self.timeout = timeout
        self._desfase = 0

    @property
    def real(self):
        return "testnet" not in self.url

    @property
    def etiqueta(self):
        return "Binance" if self.real else "Binance (red de pruebas)"

    @staticmethod
    def simbolo(activo):
        return f"{activo}{MONEDA_COTIZACION}"

    def opera(self, activo):
        return activo not in ("USD", MONEDA_COTIZACION)

    # ---- transporte ----
    def _pedir(self, metodo, ruta, params=None, firmado=False, _reintento=True):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        cabeceras = {}
        if firmado:
            if not (self.clave and self.secreto):
                raise ErrorExchange("Faltan BINANCE_API_KEY y BINANCE_API_SECRET en la configuración.")
            params["recvWindow"] = self.recv_window
            params["timestamp"] = int(time.time() * 1000) + self._desfase
            consulta = urllib.parse.urlencode(params)
            firma = hmac.new(self.secreto.encode(), consulta.encode(), hashlib.sha256).hexdigest()
            consulta += "&signature=" + firma
            cabeceras["X-MBX-APIKEY"] = self.clave
        else:
            consulta = urllib.parse.urlencode(params)
        url = self.url + ruta + ("?" + consulta if consulta else "")
        try:
            r = self.sesion.request(metodo, url, headers=cabeceras, timeout=self.timeout)
        except requests.RequestException as e:
            raise ErrorExchange(f"Binance no respondió ({e.__class__.__name__}).", definitivo=False) from None
        try:
            datos = r.json()
        except ValueError:
            datos = None
        if r.status_code >= 500 or (isinstance(datos, dict) and datos.get("code") in (-1006, -1007)):
            raise ErrorExchange(f"Binance respondió con un error interno ({r.status_code}); el resultado es desconocido.",
                                definitivo=False, codigo=(datos or {}).get("code") if isinstance(datos, dict) else None)
        if r.status_code >= 400:
            codigo = datos.get("code") if isinstance(datos, dict) else None
            mensaje = datos.get("msg") if isinstance(datos, dict) else r.text[:200]
            if codigo == -1021 and firmado and _reintento:  # reloj desfasado: sincronizar y reintentar una vez
                self.sincronizar()
                return self._pedir(metodo, ruta, {k: v for k, v in params.items()
                                                 if k not in ("timestamp", "recvWindow")}, firmado, False)
            raise ErrorExchange(f"Binance rechazó la solicitud ({codigo}): {mensaje}", definitivo=True, codigo=codigo)
        if datos is None:
            raise ErrorExchange("Binance devolvió una respuesta ilegible.", definitivo=False)
        return datos

    def sincronizar(self):
        servidor = self._pedir("GET", "/api/v3/time")["serverTime"]
        self._desfase = int(servidor) - int(time.time() * 1000)
        return self._desfase

    # ---- reglas del par ----
    def reglas(self, activo):
        sim = self.simbolo(activo)
        clave = (self.url, sim)
        cache = self._cache_reglas.get(clave)
        if cache and time.time() - cache[0] < 3600:
            return cache[1]
        info = self._pedir("GET", "/api/v3/exchangeInfo", {"symbol": sim})
        simbolos = info.get("symbols") or []
        if not simbolos:
            raise ErrorExchange(f"Binance no tiene el par {sim}.")
        s = simbolos[0]
        if s.get("status") != "TRADING":
            raise ErrorExchange(f"El par {sim} no está habilitado para operar en Binance ({s.get('status')}).")
        filtros = {f["filterType"]: f for f in s.get("filters", [])}
        lote = filtros.get("LOT_SIZE", {})
        mercado = filtros.get("MARKET_LOT_SIZE", {})
        paso = _dec(mercado.get("stepSize", "0"))
        minimo_q = _dec(mercado.get("minQty", "0"))
        if paso <= 0:
            paso = _dec(lote.get("stepSize", "0.00000001"))
            minimo_q = _dec(lote.get("minQty", "0"))
        nocional = filtros.get("NOTIONAL") or filtros.get("MIN_NOTIONAL") or {}
        minimo = _dec(nocional.get("minNotional", "0"))
        if nocional.get("applyMinToMarket") is False or nocional.get("applyToMarket") is False:
            minimo = Decimal(0)
        reglas = Reglas(minimo_cent=int((minimo * CENT).to_integral_value(ROUND_CEILING)),
                        paso=max(1, int((paso * U).to_integral_value(ROUND_DOWN))),
                        minimo_unidades=max(1, int((minimo_q * U).to_integral_value(ROUND_CEILING))))
        self._cache_reglas[clave] = (time.time(), reglas)
        return reglas

    # ---- órdenes ----
    def _relleno(self, activo, lado, datos):
        ejecutada = _dec(datos.get("executedQty", "0"))
        estado = datos.get("status")
        if ejecutada <= 0:
            raise ErrorExchange(f"La orden no se ejecutó en Binance (estado {estado}).", definitivo=True)
        comisiones = {}
        for f in datos.get("fills") or []:
            a = f.get("commissionAsset")
            if a:
                comisiones[a] = comisiones.get(a, Decimal(0)) + _dec(f.get("commission", "0"))
        cotizada = _dec(datos.get("cummulativeQuoteQty", "0"))
        return traducir(activo, lado, ejecutada, cotizada, comisiones, ref=str(datos.get("orderId")),
                        parcial=estado != "FILLED", respuesta=datos)

    def _orden(self, activo, params):
        try:
            return self._pedir("POST", "/api/v3/order", params, firmado=True)
        except ErrorExchange as e:
            if e.codigo == -1013:  # filtro del par: las reglas pueden haber cambiado, se vuelven a leer
                self._cache_reglas.pop((self.url, self.simbolo(activo)), None)
            raise

    def comprar(self, activo, importe_cent, id_orden):
        datos = self._orden(activo, {
            "symbol": self.simbolo(activo), "side": "BUY", "type": "MARKET",
            "quoteOrderQty": format((Decimal(importe_cent) / CENT).quantize(Decimal("0.01")), "f"),
            "newClientOrderId": id_orden, "newOrderRespType": "FULL"})
        return self._relleno(activo, "compra", datos)

    def vender(self, activo, cantidad, id_orden):
        datos = self._orden(activo, {
            "symbol": self.simbolo(activo), "side": "SELL", "type": "MARKET", "quantity": _texto_cantidad(cantidad),
            "newClientOrderId": id_orden, "newOrderRespType": "FULL"})
        return self._relleno(activo, "venta", datos)

    def consultar(self, activo, id_orden):
        """Busca una orden por su id propio. None si Binance no la tiene (nunca llegó)."""
        sim = self.simbolo(activo)
        try:
            orden = self._pedir("GET", "/api/v3/order", {"symbol": sim, "origClientOrderId": id_orden}, firmado=True)
        except ErrorExchange as e:
            if e.codigo == -2013:
                return None
            raise
        if orden.get("status") in ("NEW", "PARTIALLY_FILLED", "PENDING_NEW"):
            raise ErrorExchange("La orden sigue abierta en Binance; vuelve a intentarlo en unos segundos.", definitivo=False)
        lado = "compra" if orden.get("side") == "BUY" else "venta"
        if _dec(orden.get("executedQty", "0")) <= 0:
            raise ErrorExchange(f"La orden no se ejecutó en Binance (estado {orden.get('status')}).", definitivo=True)
        trades = self._pedir("GET", "/api/v3/myTrades", {"symbol": sim, "orderId": orden["orderId"]}, firmado=True)
        orden = dict(orden, fills=[{"price": t["price"], "qty": t["qty"], "commission": t["commission"],
                                    "commissionAsset": t["commissionAsset"]} for t in trades])
        return self._relleno(activo, lado, orden)

    # ---- cuenta y precios ----
    def saldos(self):
        cuenta = self._pedir("GET", "/api/v3/account", {"omitZeroBalances": "true"}, firmado=True)
        out = {}
        for b in cuenta.get("balances", []):
            total = _dec(b.get("free", "0")) + _dec(b.get("locked", "0"))
            if total:
                out[b["asset"]] = int((total * U).to_integral_value(ROUND_DOWN))
        return out

    def disponible(self, activo):
        """Unidades libres (no bloqueadas en órdenes) de un activo en la cuenta."""
        cuenta = self._pedir("GET", "/api/v3/account", {"omitZeroBalances": "true"}, firmado=True)
        for b in cuenta.get("balances", []):
            if b["asset"] == activo:
                return int((_dec(b.get("free", "0")) * U).to_integral_value(ROUND_DOWN))
        return 0

    def precios(self, activos):
        simbolos = [self.simbolo(a) for a in activos if self.opera(a)]
        datos = self._pedir("GET", "/api/v3/ticker/24hr", {"symbols": json.dumps(simbolos, separators=(",", ":"))})
        por_simbolo = {d["symbol"]: d for d in datos}
        out = {}
        for a in activos:
            if a == MONEDA_COTIZACION:
                out[a] = (Decimal(1), Decimal(0))
                continue
            d = por_simbolo.get(self.simbolo(a))
            if d and _dec(d.get("lastPrice", "0")) > 0:
                out[a] = (_dec(d["lastPrice"]), _dec(d.get("priceChangePercent", "0")))
        return out

    def verificar(self):
        """Controles de la conexión y de la clave. Devuelve [(ok, texto)]; ok=None es una advertencia."""
        out = []
        desfase = self.sincronizar()
        out.append((abs(desfase) < 1000, f"Conexión con {self.etiqueta}: reloj del servidor con {abs(desfase)} ms de diferencia."))
        cuenta = self._pedir("GET", "/api/v3/account", {"omitZeroBalances": "true"}, firmado=True)
        out.append((bool(cuenta.get("canTrade")), "La clave puede operar en Spot." if cuenta.get("canTrade")
                    else "La clave no tiene permiso para operar en Spot."))
        if self.real:
            try:
                r = self._pedir("GET", "/sapi/v1/account/apiRestrictions", firmado=True)
            except ErrorExchange as e:
                out.append((None, f"No se pudieron leer las restricciones de la clave: {e}"))
            else:
                out.append((not r.get("enableWithdrawals"), "Los retiros están deshabilitados en la clave."
                            if not r.get("enableWithdrawals") else "La clave permite RETIROS: deshabilítalos en Binance."))
                out.append((bool(r.get("ipRestrict")), "La clave solo funciona desde IP autorizadas."
                            if r.get("ipRestrict") else "La clave funciona desde cualquier IP: restríngela a la del servidor."))
        else:
            out.append((None, "Red de pruebas: el dinero no es real. Cambia BINANCE_URL para operar en producción."))
        return out


# ---------------------------------------------------------------------------------------------------------------
def modo():
    return current_app.config.get("EJECUCION", "simulado")


def cliente_binance():
    """Cliente de Binance con la configuración de la aplicación (en las pruebas, el que se haya inyectado)."""
    prueba = current_app.extensions.get("broker_pruebas")
    if isinstance(prueba, Binance):
        return prueba
    cfg = current_app.config
    return Binance(cfg.get("BINANCE_API_KEY"), cfg.get("BINANCE_API_SECRET"), cfg.get("BINANCE_URL") or URL_BINANCE_PRUEBAS,
                   cfg.get("BINANCE_RECV_WINDOW", 5000))


def broker(precios=None):
    """Ejecutor configurado. precios: los vigentes a usar en el simulador y en la conversión interna."""
    prueba = current_app.extensions.get("broker_pruebas")
    if prueba is not None:
        return prueba
    cfg = current_app.config
    if modo() == "binance":
        return cliente_binance()
    return Simulado(precios if precios is not None else {}, cfg.get("SIMULADOR_COMISION_PCT", Decimal(0)),
                    cfg.get("SIMULADOR_MINIMO_CENT", 0))
