"""Imitación de la API REST de Binance Spot para las pruebas: firma, filtros, comisiones, saldos y fallas de red.

Se comporta como el exchange en lo que usa el sistema: órdenes de mercado por importe (quoteOrderQty) o por cantidad,
consulta por id propio (-2013 si no existe), myTrades, account, exchangeInfo, ticker/24hr, time y apiRestrictions.
"""
import hashlib
import hmac
import json
import urllib.parse
from decimal import ROUND_DOWN, Decimal

import requests

CLAVE, SECRETO = "clave-prueba", "secreto-prueba"


class Respuesta:
    def __init__(self, codigo, datos):
        self.status_code = codigo
        self._datos = datos
        self.text = json.dumps(datos)

    def json(self):
        return self._datos


class BinanceFalso:
    def __init__(self, precios, saldos=None):
        self.precios = {k: Decimal(v) for k, v in precios.items()}
        self.saldos = {k: Decimal(v) for k, v in (saldos or {"USDT": "1000000"}).items()}
        self.paso = {}            # símbolo -> stepSize
        self.minimo = {}          # símbolo -> minNotional
        self.comision_bnb = False
        self.fallas = {}          # símbolo -> lista de fallas para las próximas órdenes
        self.ordenes = {}         # clientOrderId -> orden
        self.trades = {}          # orderId -> trades
        self.envios = []          # (símbolo, lado, clientOrderId) de cada POST que llegó al "motor"
        self.restricciones = {"enableWithdrawals": False, "ipRestrict": True, "enableSpotAndMarginTrading": True}
        self.parcial = {}         # símbolo -> fracción ejecutada
        self._id = 1000

    # ---- utilidades ----
    def _paso(self, sim):
        return Decimal(self.paso.get(sim, "0.00001"))

    def _error(self, codigo, msg, http=400):
        return Respuesta(http, {"code": codigo, "msg": msg})

    def _verificar_firma(self, consulta, cabeceras):
        assert cabeceras.get("X-MBX-APIKEY") == CLAVE, "falta la clave en la cabecera"
        cuerpo, _, firma = consulta.rpartition("&signature=")
        esperado = hmac.new(SECRETO.encode(), cuerpo.encode(), hashlib.sha256).hexdigest()
        assert firma == esperado, "firma HMAC incorrecta"

    # ---- transporte ----
    def request(self, metodo, url, headers=None, timeout=None):
        partes = urllib.parse.urlparse(url)
        ruta, consulta = partes.path, partes.query
        p = dict(urllib.parse.parse_qsl(consulta))
        if "signature" in p:
            self._verificar_firma(consulta, headers or {})
        if ruta == "/api/v3/time":
            import time
            return Respuesta(200, {"serverTime": int(time.time() * 1000)})
        if ruta == "/api/v3/exchangeInfo":
            sim = p["symbol"]
            if sim[:-4] not in self.precios:
                return self._error(-1121, "Invalid symbol.")
            return Respuesta(200, {"symbols": [{"symbol": sim, "status": "TRADING", "filters": [
                {"filterType": "LOT_SIZE", "minQty": str(self._paso(sim)), "maxQty": "9000", "stepSize": str(self._paso(sim))},
                {"filterType": "MARKET_LOT_SIZE", "minQty": "0.00000000", "maxQty": "100", "stepSize": "0.00000000"},
                {"filterType": "NOTIONAL", "minNotional": str(self.minimo.get(sim, "5")), "applyMinToMarket": True,
                 "maxNotional": "9000000", "applyMaxToMarket": False, "avgPriceMins": 5}]}]})
        if ruta == "/api/v3/ticker/24hr":
            sims = json.loads(p["symbols"])
            return Respuesta(200, [{"symbol": s, "lastPrice": str(self.precios[s[:-4]]), "priceChangePercent": "-1.250"}
                                   for s in sims if s[:-4] in self.precios])
        if ruta == "/api/v3/account":
            return Respuesta(200, {"canTrade": True, "balances": [
                {"asset": a, "free": str(v), "locked": "0.00000000"} for a, v in self.saldos.items() if v]})
        if ruta == "/sapi/v1/account/apiRestrictions":
            return Respuesta(200, self.restricciones)
        if ruta == "/api/v3/order" and metodo == "POST":
            return self._nueva_orden(p)
        if ruta == "/api/v3/order" and metodo == "GET":
            o = self.ordenes.get(p["origClientOrderId"])
            if not o:
                return self._error(-2013, "Order does not exist.")
            return Respuesta(200, {k: v for k, v in o.items() if k != "fills"})
        if ruta == "/api/v3/myTrades":
            return Respuesta(200, self.trades.get(int(p["orderId"]), []))
        return self._error(-1, f"ruta no imitada: {metodo} {ruta}", 404)

    def _nueva_orden(self, p):
        sim, lado, cid = p["symbol"], p["side"], p["newClientOrderId"]
        assert p["type"] == "MARKET" and p["newOrderRespType"] == "FULL"
        falla = (self.fallas.get(sim) or [None]).pop(0) if self.fallas.get(sim) else None
        if falla == "red":                       # no llegó al exchange
            raise requests.ConnectionError("conexión rechazada")
        if falla == "rechazo":
            return self._error(-2010, "Account has insufficient balance for requested action.")
        if falla == "error_500":
            return Respuesta(503, {"code": -1007, "msg": "Timeout waiting for response from backend server."})
        activo = sim[:-4]
        precio = self.precios[activo]
        paso = self._paso(sim)
        if lado == "BUY":
            importe = Decimal(p["quoteOrderQty"])
            cantidad = (importe / precio / paso).to_integral_value(ROUND_DOWN) * paso
        else:
            cantidad = Decimal(p["quantity"])
            if (cantidad / paso) != (cantidad / paso).to_integral_value():
                return self._error(-1013, "Filter failure: LOT_SIZE")
        fr = Decimal(self.parcial.get(sim, "1"))
        ejecutada = (cantidad * fr / paso).to_integral_value(ROUND_DOWN) * paso
        cotizada = (ejecutada * precio).quantize(Decimal("0.00000001"))
        if cantidad * precio < Decimal(self.minimo.get(sim, "5")):
            return self._error(-1013, "Filter failure: NOTIONAL")
        if lado == "BUY" and self.saldos.get("USDT", 0) < cotizada:
            return self._error(-2010, "Account has insufficient balance for requested action.")
        if lado == "SELL" and self.saldos.get(activo, 0) < cantidad:
            return self._error(-2010, "Account has insufficient balance for requested action.")
        if self.comision_bnb:
            com, com_a = (cotizada * Decimal("0.00075") / self.precios["BNB"]).quantize(Decimal("0.00000001")), "BNB"
        elif lado == "BUY":
            com, com_a = (ejecutada * Decimal("0.001")).quantize(Decimal("0.00000001")), activo
        else:
            com, com_a = (cotizada * Decimal("0.001")).quantize(Decimal("0.00000001")), "USDT"
        if lado == "BUY":
            self.saldos["USDT"] = self.saldos.get("USDT", 0) - cotizada
            self.saldos[activo] = self.saldos.get(activo, 0) + ejecutada
        else:
            self.saldos[activo] = self.saldos.get(activo, 0) - ejecutada
            self.saldos["USDT"] = self.saldos.get("USDT", 0) + cotizada
        self.saldos[com_a] = self.saldos.get(com_a, 0) - com
        self._id += 1
        estado = "FILLED" if ejecutada == cantidad else "EXPIRED"
        fills = [{"price": str(precio), "qty": str(ejecutada), "commission": str(com), "commissionAsset": com_a, "tradeId": self._id}]
        orden = {"symbol": sim, "orderId": self._id, "clientOrderId": cid, "side": lado, "type": "MARKET", "status": estado,
                 "executedQty": format(ejecutada, "f"), "cummulativeQuoteQty": format(cotizada, "f"),
                 "origQty": format(cantidad, "f"), "fills": fills}
        self.ordenes[cid] = orden
        self.trades[self._id] = fills
        self.envios.append((sim, lado, cid))
        if falla == "procesada_sin_respuesta":   # el exchange la ejecutó pero la respuesta se perdió
            raise requests.ReadTimeout("tiempo de espera agotado")
        return Respuesta(200, orden)
