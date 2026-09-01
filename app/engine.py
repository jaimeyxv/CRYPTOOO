"""
Motor de analisis en segundo plano (Fase 2).

Un hilo que, mientras el bot no este en OFF, cada cierto tiempo:
  1. descarga las velas recientes de Binance,
  2. calcula la señal con la estrategia,
  3. la guarda en el estado del bot (para que el panel la muestre).

La EJECUCION real de ordenes llega en la Fase 3. Aqui solo se detecta y avisa.
"""
from __future__ import annotations

import threading
import time

from .binance_client import cliente, BinanceError
from .bot import estado, Modo
from .config import config
from .strategy import analizar
from . import trader

_hilo: threading.Thread | None = None
_parar = threading.Event()


def _cierres_desde_klines(klines: list[list]) -> list[float]:
    # En cada vela, el indice 4 es el precio de cierre
    return [float(k[4]) for k in klines]


def _ciclo() -> None:
    while not _parar.is_set():
        try:
            if estado.modo != Modo.OFF:
                klines = cliente.klines(interval=config.interval, limit=150)
                cierres = _cierres_desde_klines(klines)
                analisis = analizar(cierres, config)
                estado.registrar_analisis(analisis.dict())
                # En AUTO, ademas de detectar, ejecutamos segun las reglas
                if estado.modo == Modo.AUTO:
                    trader.gestionar_auto(analisis.dict(), klines)
        except BinanceError:
            # Fallo de red puntual: no tumbamos el hilo, reintenta al siguiente ciclo
            pass
        except Exception:
            pass
        # Espera troceada para poder parar rapido
        for _ in range(config.analisis_seg):
            if _parar.is_set():
                break
            time.sleep(1)


def iniciar() -> None:
    global _hilo
    if _hilo and _hilo.is_alive():
        return
    _parar.clear()
    _hilo = threading.Thread(target=_ciclo, name="motor-analisis", daemon=True)
    _hilo.start()


def detener() -> None:
    _parar.set()
