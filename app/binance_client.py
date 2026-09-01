"""
Cliente minimo de Binance (Spot).

Hace solo lo que necesitamos, sin librerias pesadas:
  - precio_actual()  -> endpoint publico, no necesita clave
  - cuenta()         -> endpoint firmado, necesita API key + secret
  - klines()         -> velas historicas (para la estrategia, Fase 2)

Las peticiones "firmadas" llevan una firma HMAC-SHA256 para que Binance
sepa que de verdad eres tu. Nunca se envia el secret por la red.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import httpx

from .config import config


class BinanceError(Exception):
    """Error devuelto por Binance o por la conexion."""


class BinanceClient:
    def __init__(self) -> None:
        self.base_url = config.base_url
        self.api_key = config.api_key
        self.api_secret = config.api_secret
        self._http = httpx.Client(timeout=10.0)

    # ----- utilidades internas -----
    def _headers(self) -> dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key}

    def _firmar(self, params: dict[str, Any]) -> dict[str, Any]:
        """Anade timestamp y la firma HMAC a los parametros."""
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000
        query = "&".join(f"{k}={v}" for k, v in params.items())
        firma = hmac.new(
            self.api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = firma
        return params

    def _get(self, path: str, params: dict | None = None, firmado: bool = False) -> Any:
        url = f"{self.base_url}{path}"
        try:
            if firmado:
                r = self._http.get(url, params=self._firmar(params or {}), headers=self._headers())
            else:
                r = self._http.get(url, params=params or {})
        except httpx.HTTPError as e:
            raise BinanceError(f"No se pudo conectar con Binance: {e}") from e

        if r.status_code != 200:
            raise BinanceError(f"Binance respondio {r.status_code}: {r.text}")
        return r.json()

    def _post(self, path: str, params: dict) -> Any:
        """POST siempre firmado (para crear ordenes)."""
        url = f"{self.base_url}{path}"
        try:
            r = self._http.post(url, params=self._firmar(params), headers=self._headers())
        except httpx.HTTPError as e:
            raise BinanceError(f"No se pudo conectar con Binance: {e}") from e
        if r.status_code != 200:
            raise BinanceError(f"Binance respondio {r.status_code}: {r.text}")
        return r.json()

    # ----- endpoints publicos -----
    def ping(self) -> bool:
        self._get("/api/v3/ping")
        return True

    def precio_actual(self, symbol: str | None = None) -> float:
        symbol = symbol or config.symbol
        data = self._get("/api/v3/ticker/price", {"symbol": symbol})
        return float(data["price"])

    def klines(self, symbol: str | None = None, interval: str = "1h", limit: int = 100) -> list[list]:
        """Velas historicas. Cada vela: [open_time, open, high, low, close, volume, ...]."""
        symbol = symbol or config.symbol
        return self._get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})

    # ----- endpoints firmados (necesitan clave) -----
    def cuenta(self) -> dict:
        """Datos de la cuenta, incluidos los saldos."""
        return self._get("/api/v3/account", firmado=True)

    def saldos(self, solo_con_fondos: bool = True) -> list[dict]:
        data = self.cuenta()
        balances = data.get("balances", [])
        if solo_con_fondos:
            balances = [b for b in balances if float(b["free"]) > 0 or float(b["locked"]) > 0]
        return balances

    def saldo_libre(self, asset: str) -> float:
        """Cantidad disponible (no bloqueada) de una moneda concreta."""
        for b in self.cuenta().get("balances", []):
            if b["asset"] == asset:
                return float(b["free"])
        return 0.0

    # ----- reglas del simbolo (cacheadas) -----
    _info_cache: dict[str, dict] = {}

    def info_simbolo(self, symbol: str | None = None) -> dict:
        """
        Devuelve base, quote y el 'stepSize' (minimo incremento de cantidad).
        Se necesita para que las ordenes tengan una cantidad valida.
        """
        symbol = symbol or config.symbol
        if symbol in self._info_cache:
            return self._info_cache[symbol]
        data = self._get("/api/v3/exchangeInfo", {"symbol": symbol})
        s = data["symbols"][0]
        step = "1"
        for f in s["filters"]:
            if f["filterType"] == "LOT_SIZE":
                step = f["stepSize"]
                break
        info = {"base": s["baseAsset"], "quote": s["quoteAsset"], "step": step}
        self._info_cache[symbol] = info
        return info

    def _ajustar_cantidad(self, cantidad: float, step: str) -> str:
        """Recorta la cantidad al 'stepSize' permitido (redondeo hacia abajo)."""
        from decimal import Decimal, ROUND_DOWN
        paso = Decimal(step)
        c = (Decimal(str(cantidad)) / paso).to_integral_value(rounding=ROUND_DOWN) * paso
        # Formatea sin exponente y sin ceros sobrantes problematicos
        return format(c.normalize(), "f")

    # ----- creacion de ordenes (MARKET) -----
    def comprar_mercado(self, usdt: float, symbol: str | None = None) -> dict:
        """Compra a mercado gastando una cantidad fija en USDT (quoteOrderQty)."""
        symbol = symbol or config.symbol
        return self._post("/api/v3/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quoteOrderQty": f"{usdt:.2f}",
        })

    def vender_mercado(self, cantidad: float, symbol: str | None = None) -> dict:
        """Vende a mercado una cantidad del activo base, ajustada al stepSize."""
        symbol = symbol or config.symbol
        step = self.info_simbolo(symbol)["step"]
        qty = self._ajustar_cantidad(cantidad, step)
        return self._post("/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET",
            "quantity": qty,
        })


# Instancia unica reutilizable
cliente = BinanceClient()
