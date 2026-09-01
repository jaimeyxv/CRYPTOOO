"""Ejecucion Spot, limites de riesgo y registro de operaciones."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

from .binance_client import BinanceError, cliente
from .bot import estado
from .config import config
from .storage import storage, utc_now

_lock = Lock()


def cargar_posicion() -> dict:
    return storage.position()


def guardar_posicion(pos: dict) -> None:
    """Compatibilidad para herramientas existentes; SQLite es la fuente de verdad."""
    if pos.get("en_posicion"):
        storage.set_position(pos)
    else:
        storage.clear_position()


def _precio_medio(orden: dict) -> float:
    ejecutado = float(orden.get("executedQty", 0) or 0)
    quote = float(orden.get("cummulativeQuoteQty", 0) or 0)
    if ejecutado > 0 and quote > 0:
        return quote / ejecutado
    fills = orden.get("fills") or []
    total_qty = sum(float(fill.get("qty", 0)) for fill in fills)
    if total_qty:
        return sum(float(fill["price"]) * float(fill["qty"]) for fill in fills) / total_qty
    return 0.0


def _quote_ejecutado(orden: dict, cantidad: float, precio: float) -> float:
    return float(orden.get("cummulativeQuoteQty", 0) or 0) or cantidad * precio


def _order_id(orden: dict) -> str | None:
    value = orden.get("orderId") or orden.get("clientOrderId")
    return str(value) if value is not None else None


def _base_quote() -> tuple[str, str]:
    info = cliente.info_simbolo()
    return info["base"], info["quote"]


def estado_riesgo() -> dict:
    actividad = storage.daily_activity()
    cooldown_restante = 0
    if actividad["ultima_compra"]:
        try:
            ultima = datetime.fromisoformat(actividad["ultima_compra"])
            cooldown_restante = max(0, config.cooldown_seg - int((datetime.now(timezone.utc) - ultima).total_seconds()))
        except ValueError:
            cooldown_restante = 0
    razones = []
    if actividad["compras"] >= config.max_operaciones_dia:
        razones.append("limite diario de compras alcanzado")
    if actividad["pnl"] <= -config.perdida_max_diaria_usdt:
        razones.append("perdida maxima diaria alcanzada")
    if cooldown_restante:
        razones.append(f"cooldown activo ({cooldown_restante}s)")
    if not config.use_testnet and not config.enable_live_trading:
        razones.append("trading real bloqueado por ENABLE_LIVE_TRADING")
    return {
        "permite_compra": not razones,
        "bloqueos": razones,
        "compras_hoy": actividad["compras"],
        "max_compras": config.max_operaciones_dia,
        "pnl_hoy": round(actividad["pnl"], 4),
        "perdida_max_diaria": config.perdida_max_diaria_usdt,
        "cooldown_restante": cooldown_restante,
        "live_trading_habilitado": config.use_testnet or config.enable_live_trading,
    }


def comprar(motivo: str = "orden manual") -> dict:
    with _lock:
        pos = cargar_posicion()
        riesgo = estado_riesgo()
        if not riesgo["permite_compra"]:
            mensaje = "Compra bloqueada: " + ", ".join(riesgo["bloqueos"])
            estado.registrar_evento(mensaje, "WARNING", "risk")
            return {"ok": False, "mensaje": mensaje, "riesgo": riesgo}
        try:
            _, quote_asset = _base_quote()
            saldo = cliente.saldo_libre(quote_asset)
            if saldo < config.orden_usdt:
                return {"ok": False, "mensaje": f"Saldo insuficiente: {saldo:.2f} {quote_asset}."}
            orden = cliente.comprar_mercado(config.orden_usdt)
        except BinanceError as exc:
            estado.registrar_evento(f"Error al comprar: {exc}", "ERROR", "order")
            return {"ok": False, "mensaje": str(exc)}

        cantidad = float(orden.get("executedQty", 0) or 0)
        precio = _precio_medio(orden)
        if cantidad <= 0 or precio <= 0:
            mensaje = "Binance acepto la orden, pero no devolvio una ejecucion completa; revisa la cuenta"
            estado.registrar_evento(mensaje, "ERROR", "reconciliation")
            return {"ok": False, "mensaje": mensaje}
        quote_qty = _quote_ejecutado(orden, cantidad, precio)
        ahora = utc_now()
        order_id = _order_id(orden)
        es_adicional = bool(pos["en_posicion"])
        if es_adicional:
            cantidad_total = float(pos["cantidad"]) + cantidad
            coste_total = float(pos.get("quote_spent") or 0) + quote_qty
            pos = {
                "en_posicion": True, "cantidad": cantidad_total,
                "precio_entrada": coste_total / cantidad_total,
                "quote_spent": coste_total, "hora": pos.get("hora") or ahora,
                "symbol": config.symbol, "order_id": order_id,
            }
        else:
            pos = {
                "en_posicion": True, "cantidad": cantidad, "precio_entrada": precio,
                "quote_spent": quote_qty, "hora": ahora, "symbol": config.symbol,
                "order_id": order_id,
            }
        trade = {
            "symbol": config.symbol, "side": "BUY", "quantity": cantidad,
            "price": precio, "quote_quantity": quote_qty, "reason": motivo,
            "order_id": order_id, "mode": estado.modo.value, "created_at": ahora,
        }
        storage.record_buy(pos, trade)
        detalle = (
            f" | posicion {pos['cantidad']:.8f} @ media {pos['precio_entrada']:.2f}"
            if es_adicional else ""
        )
        estado.registrar_evento(
            f"COMPRA ejecutada: {cantidad:.8f} @ {precio:.2f}{detalle} ({motivo})", "INFO", "order"
        )
        mensaje = "Entrada adicional" if es_adicional else "Compra"
        return {"ok": True, "mensaje": f"{mensaje} ejecutada @ {precio:.2f}", "posicion": pos}


def vender(motivo: str = "orden manual") -> dict:
    with _lock:
        pos = cargar_posicion()
        if not pos["en_posicion"]:
            return {"ok": False, "mensaje": "No existe una posicion abierta."}
        try:
            base_asset, _ = _base_quote()
            libre = cliente.saldo_libre(base_asset)
            if libre <= 0:
                mensaje = f"No hay saldo libre de {base_asset}; es necesario reconciliar la posicion"
                estado.registrar_evento(mensaje, "ERROR", "reconciliation")
                return {"ok": False, "mensaje": mensaje}
            cantidad = min(libre, float(pos["cantidad"]))
            orden = cliente.vender_mercado(cantidad)
        except BinanceError as exc:
            estado.registrar_evento(f"Error al vender: {exc}", "ERROR", "order")
            return {"ok": False, "mensaje": str(exc)}

        ejecutado = float(orden.get("executedQty", 0) or 0)
        precio = _precio_medio(orden)
        if ejecutado <= 0 or precio <= 0:
            mensaje = "Venta aceptada sin detalle de ejecucion; revisa Binance antes de reintentar"
            estado.registrar_evento(mensaje, "ERROR", "reconciliation")
            return {"ok": False, "mensaje": mensaje}
        quote_qty = _quote_ejecutado(orden, ejecutado, precio)
        coste = float(pos.get("quote_spent") or (pos["cantidad"] * pos["precio_entrada"]))
        coste_vendido = coste * min(1.0, ejecutado / float(pos["cantidad"]))
        pnl = quote_qty - coste_vendido
        pnl_pct = pnl / coste_vendido * 100 if coste_vendido else 0.0
        restante = max(0.0, float(pos["cantidad"]) - ejecutado)
        posicion_restante = None
        if restante > float(pos["cantidad"]) * 0.01:
            posicion_restante = dict(pos)
            posicion_restante["cantidad"] = restante
            posicion_restante["quote_spent"] = max(0.0, coste - coste_vendido)
        trade = {
            "symbol": config.symbol, "side": "SELL", "quantity": ejecutado,
            "price": precio, "quote_quantity": quote_qty, "realized_pnl": pnl,
            "realized_pnl_pct": pnl_pct, "reason": motivo, "order_id": _order_id(orden),
            "mode": estado.modo.value, "created_at": utc_now(),
        }
        storage.record_sell(trade, posicion_restante)
        estado.registrar_evento(
            f"VENTA ejecutada @ {precio:.2f} | Resultado {pnl:+.2f} ({pnl_pct:+.2f}%) ({motivo})",
            "INFO", "order",
        )
        detalle = " (salida parcial)" if posicion_restante else ""
        return {"ok": True, "mensaje": f"Venta ejecutada @ {precio:.2f} ({pnl_pct:+.2f}%){detalle}",
                "trade": trade, "posicion": posicion_restante}


def estado_posicion(precio_actual: float | None = None) -> dict:
    pos = cargar_posicion()
    salida = dict(pos)
    if pos["en_posicion"] and pos["precio_entrada"]:
        entrada = float(pos["precio_entrada"])
        salida["take_profit"] = round(entrada * (1 + config.take_profit_pct / 100), 8)
        salida["stop_loss"] = round(entrada * (1 - config.stop_loss_pct / 100), 8)
        if precio_actual and precio_actual > 0:
            salida["pnl_pct"] = round((precio_actual - entrada) / entrada * 100, 3)
            salida["pnl_no_realizado"] = round(float(pos["cantidad"]) * precio_actual - float(pos["quote_spent"]), 4)
            salida["valor_actual"] = round(float(pos["cantidad"]) * precio_actual, 4)
    return salida


def gestionar_auto(analisis: dict, klines: list[list]) -> None:
    precio = float(analisis.get("precio") or 0)
    if precio <= 0:
        return
    pos = cargar_posicion()
    ventana = klines[-config.caida_ventana:] if klines else []
    max_reciente = max((float(k[2]) for k in ventana), default=precio)
    caida_pct = (max_reciente - precio) / max_reciente * 100 if max_reciente else 0
    if not pos["en_posicion"]:
        if caida_pct >= config.comprar_caida_pct:
            comprar(f"caida de {caida_pct:.2f}% desde {max_reciente:.2f}")
        elif analisis.get("señal") == "COMPRAR":
            comprar("señal de estrategia")
        return
    entrada = float(pos["precio_entrada"] or precio)
    variacion = (precio - entrada) / entrada * 100
    if variacion >= config.take_profit_pct:
        vender(f"take-profit +{variacion:.2f}%")
    elif variacion <= -config.stop_loss_pct:
        vender(f"stop-loss {variacion:.2f}%")
    elif analisis.get("señal") == "VENDER":
        vender("señal de estrategia")
    elif caida_pct >= config.comprar_caida_pct:
        comprar(f"entrada adicional por caida de {caida_pct:.2f}% desde {max_reciente:.2f}")
    elif analisis.get("señal") == "COMPRAR":
        comprar("entrada adicional por señal de estrategia")
