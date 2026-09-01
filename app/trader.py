"""
Ejecucion de ordenes y gestion de la posicion (Fase 3).

Reglas de operacion (todas configurables desde el .env):
  ENTRADA (cuando NO tenemos posicion):
    - Comprar si el precio ha caido COMPRAR_CAIDA_PCT % desde el maximo reciente
      (compra "en el dip"), o si la estrategia da señal de COMPRAR.
  SALIDA (cuando SI tenemos posicion):
    - TAKE PROFIT: vender si el precio sube TAKE_PROFIT_PCT % sobre la entrada.
    - STOP LOSS:   vender si el precio baja STOP_LOSS_PCT % bajo la entrada.
    - o si la estrategia da señal de VENDER.

La posicion se guarda en data/posicion.json para no perderla si se reinicia.
Todo ocurre en la cuenta configurada (TESTNET mientras USE_TESTNET=true).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .binance_client import cliente, BinanceError
from .bot import estado
from .config import config

_DATA = Path(__file__).resolve().parent.parent / "data"
_ARCHIVO = _DATA / "posicion.json"
_lock = Lock()


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _posicion_vacia() -> dict:
    return {"en_posicion": False, "cantidad": 0.0, "precio_entrada": 0.0,
            "hora": None, "symbol": config.symbol}


def cargar_posicion() -> dict:
    try:
        return json.loads(_ARCHIVO.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return _posicion_vacia()


def guardar_posicion(pos: dict) -> None:
    _DATA.mkdir(exist_ok=True)
    _ARCHIVO.write_text(json.dumps(pos, indent=2), encoding="utf-8")


def _precio_medio(orden: dict) -> float:
    """Precio medio de ejecucion a partir de la respuesta de Binance."""
    ejecutado = float(orden.get("executedQty", 0) or 0)
    gastado = float(orden.get("cummulativeQuoteQty", 0) or 0)
    if ejecutado > 0 and gastado > 0:
        return gastado / ejecutado
    fills = orden.get("fills", [])
    if fills:
        return float(fills[0]["price"])
    return 0.0


# ---------------------------------------------------------------- acciones
def comprar(motivo: str = "orden manual") -> dict:
    """Compra a mercado gastando ORDEN_USDT. Devuelve {ok, mensaje}."""
    with _lock:
        pos = cargar_posicion()
        if pos["en_posicion"]:
            return {"ok": False, "mensaje": "Ya hay una posicion abierta."}
        try:
            usdt_libre = cliente.saldo_libre(_quote())
            if usdt_libre < config.orden_usdt:
                return {"ok": False, "mensaje": f"Saldo insuficiente: {usdt_libre:.2f} USDT."}
            orden = cliente.comprar_mercado(config.orden_usdt)
        except BinanceError as e:
            estado._log(f"Error al COMPRAR: {e}")
            return {"ok": False, "mensaje": str(e)}

        cantidad = float(orden.get("executedQty", 0) or 0)
        precio = _precio_medio(orden)
        pos = {"en_posicion": True, "cantidad": cantidad, "precio_entrada": precio,
               "hora": _ahora(), "symbol": config.symbol}
        guardar_posicion(pos)
        estado._log(f"COMPRA ejecutada: {cantidad:.6f} @ {precio:.2f} USDT ({motivo})")
        return {"ok": True, "mensaje": f"Compra ejecutada @ {precio:.2f}", "posicion": pos}


def vender(motivo: str = "orden manual") -> dict:
    """Vende a mercado toda la posicion. Devuelve {ok, mensaje}."""
    with _lock:
        pos = cargar_posicion()
        if not pos["en_posicion"]:
            return {"ok": False, "mensaje": "No hay posicion que vender."}
        try:
            # Vendemos el saldo real disponible del activo base (mas fiable que la cantidad guardada)
            libre = cliente.saldo_libre(_base())
            cantidad = min(libre, pos["cantidad"]) if libre > 0 else pos["cantidad"]
            orden = cliente.vender_mercado(cantidad)
        except BinanceError as e:
            estado._log(f"Error al VENDER: {e}")
            return {"ok": False, "mensaje": str(e)}

        precio = _precio_medio(orden)
        entrada = pos["precio_entrada"] or precio
        ganancia_pct = (precio - entrada) / entrada * 100 if entrada else 0.0
        guardar_posicion(_posicion_vacia())
        estado._log(f"VENTA ejecutada @ {precio:.2f} USDT | Resultado: {ganancia_pct:+.2f}% ({motivo})")
        return {"ok": True, "mensaje": f"Venta ejecutada @ {precio:.2f} ({ganancia_pct:+.2f}%)"}


# ---------------------------------------------------------------- helpers
def _base() -> str:
    return cliente.info_simbolo()["base"]


def _quote() -> str:
    return cliente.info_simbolo()["quote"]


def estado_posicion(precio_actual: float | None = None) -> dict:
    """Datos de la posicion para el panel, con P&L en vivo y niveles TP/SL."""
    pos = cargar_posicion()
    salida = dict(pos)
    if pos["en_posicion"] and pos["precio_entrada"]:
        e = pos["precio_entrada"]
        salida["take_profit"] = round(e * (1 + config.take_profit_pct / 100), 2)
        salida["stop_loss"] = round(e * (1 - config.stop_loss_pct / 100), 2)
        if precio_actual:
            salida["pnl_pct"] = round((precio_actual - e) / e * 100, 2)
            salida["valor_actual"] = round(pos["cantidad"] * precio_actual, 2)
    return salida


# ---------------------------------------------------------------- modo AUTO
def gestionar_auto(analisis: dict, klines: list[list]) -> None:
    """
    Se llama en cada ciclo del motor cuando el modo es AUTO.
    Decide y ejecuta segun las reglas de porcentaje + la estrategia.
    """
    precio = analisis.get("precio") or 0.0
    if precio <= 0:
        return
    pos = cargar_posicion()

    if not pos["en_posicion"]:
        # Maximo reciente para medir la caida
        ventana = klines[-config.caida_ventana:] if len(klines) >= config.caida_ventana else klines
        max_reciente = max(float(k[2]) for k in ventana) if ventana else precio
        caida_pct = (max_reciente - precio) / max_reciente * 100 if max_reciente else 0.0

        if caida_pct >= config.comprar_caida_pct:
            comprar(f"caida de {caida_pct:.2f}% desde {max_reciente:.2f}")
        elif analisis.get("señal") == "COMPRAR":
            comprar("señal de la estrategia")
    else:
        entrada = pos["precio_entrada"] or precio
        subida_pct = (precio - entrada) / entrada * 100
        if subida_pct >= config.take_profit_pct:
            vender(f"take-profit +{subida_pct:.2f}%")
        elif subida_pct <= -config.stop_loss_pct:
            vender(f"stop-loss {subida_pct:.2f}%")
        elif analisis.get("señal") == "VENDER":
            vender("señal de la estrategia")
