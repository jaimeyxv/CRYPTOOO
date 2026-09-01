"""Motor observable de analisis y ejecucion en segundo plano."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from . import trader
from .binance_client import BinanceError, cliente
from .bot import Modo, estado
from .config import config
from .strategy import analizar

logger = logging.getLogger(__name__)
_hilo: threading.Thread | None = None
_parar = threading.Event()
_lock = threading.RLock()
_telemetry = {
    "started_at": None,
    "last_cycle": None,
    "last_success": None,
    "last_error": None,
    "consecutive_errors": 0,
    "cycle_duration_ms": None,
    "cycles": 0,
    "phase": "stopped",
}
_last_klines: list[list] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _set(**values) -> None:
    with _lock:
        _telemetry.update(values)


def estado_motor() -> dict:
    with _lock:
        data = dict(_telemetry)
        data["thread_alive"] = bool(_hilo and _hilo.is_alive())
        data["interval_seconds"] = config.analisis_seg
        return data


def klines_cache() -> list[list]:
    with _lock:
        return [list(item) for item in _last_klines]


def _ciclo() -> None:
    global _last_klines
    _set(started_at=_now(), phase="idle")
    while not _parar.is_set():
        inicio = time.monotonic()
        if estado.modo == Modo.OFF:
            _set(phase="idle", last_cycle=_now())
            _parar.wait(min(config.analisis_seg, 5))
            continue
        try:
            _set(phase="analyzing", last_cycle=_now())
            klines = cliente.klines(interval=config.interval, limit=200)
            cierres = [float(k[4]) for k in klines]
            resultado = analizar(cierres, config).dict()
            with _lock:
                _last_klines = klines
            estado.registrar_analisis(resultado)
            if estado.modo == Modo.AUTO:
                _set(phase="executing")
                trader.gestionar_auto(resultado, klines)
            duracion = round((time.monotonic() - inicio) * 1000, 1)
            with _lock:
                _telemetry.update({
                    "phase": "waiting", "last_success": _now(), "last_error": None,
                    "consecutive_errors": 0, "cycle_duration_ms": duracion,
                    "cycles": int(_telemetry["cycles"]) + 1,
                })
        except BinanceError as exc:
            _record_error(f"Binance: {exc}")
        except Exception as exc:  # el hilo debe sobrevivir, pero el fallo queda visible
            logger.exception("Fallo no controlado en el motor")
            _record_error(f"Error interno: {type(exc).__name__}: {exc}")
        _parar.wait(config.analisis_seg)
    _set(phase="stopped")


def _record_error(message: str) -> None:
    with _lock:
        count = int(_telemetry["consecutive_errors"]) + 1
        _telemetry.update({"phase": "error", "last_error": message, "consecutive_errors": count})
    logger.error("Ciclo de motor fallido (%s): %s", count, message)
    if count == 1 or count % 10 == 0:
        estado.registrar_evento(message, "ERROR", "engine")


def iniciar() -> None:
    global _hilo
    if _hilo and _hilo.is_alive():
        return
    _parar.clear()
    _hilo = threading.Thread(target=_ciclo, name="aurum-engine", daemon=True)
    _hilo.start()
    logger.info("Motor de analisis iniciado")


def detener() -> None:
    _parar.set()
    if _hilo and _hilo.is_alive():
        _hilo.join(timeout=min(config.analisis_seg + 2, 15))
    logger.info("Motor de analisis detenido")
