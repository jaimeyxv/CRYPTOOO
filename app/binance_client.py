"""Cliente REST robusto y ligero para Binance Spot."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from decimal import Decimal, ROUND_DOWN
from threading import Lock
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import config

logger = logging.getLogger(__name__)
INTERVALOS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"}


class BinanceError(Exception):
    """Error controlado de Binance o de conectividad."""


class BinanceClient:
    def __init__(self) -> None:
        self.base_url = config.base_url
        self.api_key = config.api_key
        self.api_secret = config.api_secret
        timeout = httpx.Timeout(config.http_timeout_seg, connect=min(config.http_timeout_seg, 5))
        self._http = httpx.Client(timeout=timeout, limits=httpx.Limits(max_connections=10, max_keepalive_connections=5))
        self._time_offset_ms = 0
        self._last_time_sync = 0.0
        self._sync_lock = Lock()
        self._info_cache: dict[str, dict] = {}
        self._account_cache: tuple[float, dict] | None = None

    def _headers(self) -> dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key}

    def _require_credentials(self) -> None:
        if not self.api_key or not self.api_secret:
            raise BinanceError("Faltan BINANCE_API_KEY y BINANCE_API_SECRET")

    def _message(self, response: httpx.Response) -> str:
        try:
            data = response.json()
            message = data.get("msg") or str(data)
            code = data.get("code")
            return f"{code}: {message}" if code is not None else message
        except ValueError:
            return response.text[:300] or "respuesta sin detalle"

    def _request(self, method: str, path: str, params: dict | None = None,
                 signed: bool = False, retries: int = 2) -> Any:
        if signed:
            self._require_credentials()
        url = f"{self.base_url}{path}"
        for attempt in range(retries + 1):
            request_params = self._signed(params or {}) if signed else (params or {})
            try:
                response = self._http.request(method, url, params=request_params,
                                              headers=self._headers() if signed else None)
            except httpx.HTTPError as exc:
                if attempt < retries and method == "GET":
                    time.sleep(0.25 * (2 ** attempt))
                    continue
                raise BinanceError(f"No se pudo conectar con Binance: {exc}") from exc
            if response.status_code in {418, 429}:
                retry_after = response.headers.get("Retry-After", "1")
                raise BinanceError(f"Limite de Binance alcanzado; reintenta en {retry_after}s")
            if response.status_code >= 500 and attempt < retries and method == "GET":
                time.sleep(0.25 * (2 ** attempt))
                continue
            if signed and response.status_code == 400 and attempt < retries:
                try:
                    if response.json().get("code") == -1021:
                        self._last_time_sync = 0
                        continue
                except ValueError:
                    pass
            if response.status_code < 200 or response.status_code >= 300:
                raise BinanceError(f"Binance respondio {response.status_code}: {self._message(response)}")
            try:
                return response.json()
            except ValueError as exc:
                raise BinanceError("Binance devolvio una respuesta no valida") from exc
        raise BinanceError("No se pudo completar la peticion")

    def _sync_time(self) -> None:
        if time.monotonic() - self._last_time_sync < 1800:
            return
        with self._sync_lock:
            if time.monotonic() - self._last_time_sync < 1800:
                return
            inicio = int(time.time() * 1000)
            data = self._request("GET", "/api/v3/time", retries=1)
            fin = int(time.time() * 1000)
            self._time_offset_ms = int(data["serverTime"]) - ((inicio + fin) // 2)
            self._last_time_sync = time.monotonic()

    def _signed(self, params: dict[str, Any]) -> dict[str, Any]:
        self._sync_time()
        signed = dict(params)
        signed["timestamp"] = int(time.time() * 1000) + self._time_offset_ms
        signed["recvWindow"] = 5000
        query = urlencode(signed, doseq=True)
        signed["signature"] = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return signed

    def ping(self) -> bool:
        self._request("GET", "/api/v3/ping", retries=1)
        return True

    def precio_actual(self, symbol: str | None = None) -> float:
        data = self._request("GET", "/api/v3/ticker/price", {"symbol": symbol or config.symbol})
        return float(data["price"])

    def ticker_24h(self, symbol: str | None = None) -> dict:
        data = self._request("GET", "/api/v3/ticker/24hr", {"symbol": symbol or config.symbol})
        return {
            "price": float(data["lastPrice"]),
            "change_pct": float(data["priceChangePercent"]),
            "high": float(data["highPrice"]),
            "low": float(data["lowPrice"]),
            "volume": float(data["quoteVolume"]),
        }

    def klines(self, symbol: str | None = None, interval: str = "1h", limit: int = 150) -> list[list]:
        if interval not in INTERVALOS:
            raise BinanceError(f"Intervalo no permitido: {interval}")
        limit = max(20, min(int(limit), 500))
        return self._request("GET", "/api/v3/klines", {
            "symbol": symbol or config.symbol, "interval": interval, "limit": limit,
        })

    def cuenta(self, cache_seg: float = 2.0) -> dict:
        ahora = time.monotonic()
        if self._account_cache and ahora - self._account_cache[0] < cache_seg:
            return self._account_cache[1]
        data = self._request("GET", "/api/v3/account", signed=True)
        self._account_cache = (ahora, data)
        return data

    def saldos(self, solo_con_fondos: bool = True) -> list[dict]:
        balances = self.cuenta().get("balances", [])
        if solo_con_fondos:
            balances = [b for b in balances if float(b["free"]) > 0 or float(b["locked"]) > 0]
        return balances

    def saldo_libre(self, asset: str) -> float:
        for balance in self.cuenta(cache_seg=0).get("balances", []):
            if balance["asset"] == asset:
                return float(balance["free"])
        return 0.0

    def info_simbolo(self, symbol: str | None = None) -> dict:
        symbol = symbol or config.symbol
        if symbol in self._info_cache:
            return self._info_cache[symbol]
        data = self._request("GET", "/api/v3/exchangeInfo", {"symbol": symbol})
        if not data.get("symbols"):
            raise BinanceError(f"Simbolo desconocido: {symbol}")
        item = data["symbols"][0]
        filters = {f["filterType"]: f for f in item["filters"]}
        market_lot = filters.get("MARKET_LOT_SIZE") or {}
        regular_lot = filters.get("LOT_SIZE") or {}
        # Testnet puede publicar MARKET_LOT_SIZE con stepSize=0. Usarlo causaria
        # una division por cero al cuantizar una venta; LOT_SIZE sigue siendo valido.
        try:
            market_step_valid = Decimal(str(market_lot.get("stepSize", "0"))) > 0
        except (ValueError, ArithmeticError):
            market_step_valid = False
        lot = market_lot if market_step_valid else regular_lot
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL", {})
        info = {
            "base": item["baseAsset"], "quote": item["quoteAsset"],
            "step": lot.get("stepSize", "1"), "min_qty": float(lot.get("minQty", 0)),
            "max_qty": float(lot.get("maxQty", 0)),
            "min_notional": float(notional.get("minNotional", 0)),
        }
        self._info_cache[symbol] = info
        return info

    @staticmethod
    def _ajustar_cantidad(cantidad: float, step: str) -> str:
        paso = Decimal(step)
        if paso <= 0:
            raise BinanceError("Binance devolvio un stepSize invalido para la cantidad")
        ajustada = (Decimal(str(cantidad)) / paso).to_integral_value(rounding=ROUND_DOWN) * paso
        return format(ajustada.normalize(), "f")

    def _create_order(self, params: dict) -> dict:
        """No reintenta POST: ante timeout consulta la orden por su id de cliente."""
        client_id = f"aurum_{uuid.uuid4().hex[:20]}"
        params = {**params, "newClientOrderId": client_id, "newOrderRespType": "FULL"}
        try:
            result = self._request("POST", "/api/v3/order", params, signed=True, retries=1)
            self._account_cache = None
            return result
        except BinanceError as original:
            if "No se pudo conectar" not in str(original):
                raise
            try:
                return self._request("GET", "/api/v3/order", {
                    "symbol": params["symbol"], "origClientOrderId": client_id,
                }, signed=True, retries=1)
            except BinanceError:
                raise BinanceError(
                    f"Resultado de orden incierto ({client_id}); revisa Binance antes de reintentar"
                ) from original

    def comprar_mercado(self, importe_quote: float, symbol: str | None = None) -> dict:
        symbol = symbol or config.symbol
        info = self.info_simbolo(symbol)
        if importe_quote < info["min_notional"]:
            raise BinanceError(f"La orden debe ser al menos {info['min_notional']} {info['quote']}")
        return self._create_order({
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quoteOrderQty": format(Decimal(str(importe_quote)), "f"),
        })

    def vender_mercado(self, cantidad: float, symbol: str | None = None) -> dict:
        symbol = symbol or config.symbol
        info = self.info_simbolo(symbol)
        qty = self._ajustar_cantidad(cantidad, info["step"])
        qty_float = float(qty)
        if qty_float <= 0 or qty_float < info["min_qty"]:
            raise BinanceError(f"Cantidad inferior al minimo de {info['min_qty']} {info['base']}")
        if info["max_qty"] and qty_float > info["max_qty"]:
            raise BinanceError(f"Cantidad superior al maximo de {info['max_qty']} {info['base']}")
        return self._create_order({"symbol": symbol, "side": "SELL", "type": "MARKET", "quantity": qty})

    def cerrar(self) -> None:
        self._http.close()


cliente = BinanceClient()
