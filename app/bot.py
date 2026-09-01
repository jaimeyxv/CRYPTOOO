"""
Estado del bot: el "interruptor" con 3 modos.

  OFF      -> dormido, no hace nada
  SENALES  -> detecta oportunidades y te avisa, pero NO opera (tu decides)
  AUTO     -> detecta y ejecuta las ordenes solo

En la Fase 1 solo gestionamos el estado (encender/apagar/cambiar modo).
La deteccion de senales y la ejecucion llegan en las Fases 2 y 3.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from threading import Lock


class Modo(str, Enum):
    OFF = "OFF"
    SENALES = "SENALES"
    AUTO = "AUTO"


class EstadoBot:
    def __init__(self) -> None:
        self._modo = Modo.OFF
        self._lock = Lock()
        self._ultimo_cambio = datetime.now(timezone.utc)
        self._eventos: list[dict] = []
        self._ultima_senal: dict | None = None
        self._senal_previa: str | None = None
        self._log("Bot iniciado en modo OFF")

    def registrar_analisis(self, analisis: dict) -> None:
        """Guarda el ultimo analisis y avisa si la señal cambio (COMPRAR/VENDER)."""
        with self._lock:
            self._ultima_senal = analisis
            nueva = analisis.get("señal")
            if nueva in ("COMPRAR", "VENDER") and nueva != self._senal_previa:
                if self._modo == Modo.SENALES:
                    self._log(f"Señal: {nueva} — {analisis.get('razon', '')} (esperando tu decision)")
                elif self._modo == Modo.AUTO:
                    self._log(f"Señal: {nueva} — {analisis.get('razon', '')} (ejecucion automatica)")
            self._senal_previa = nueva

    @property
    def ultima_senal(self) -> dict | None:
        return self._ultima_senal

    @property
    def modo(self) -> Modo:
        return self._modo

    def cambiar_modo(self, nuevo: Modo) -> None:
        with self._lock:
            if nuevo == self._modo:
                return
            anterior = self._modo
            self._modo = nuevo
            self._ultimo_cambio = datetime.now(timezone.utc)
            self._log(f"Modo cambiado: {anterior.value} -> {nuevo.value}")

    def _log(self, mensaje: str) -> None:
        self._eventos.append({
            "hora": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mensaje": mensaje,
        })
        # Mantener solo los ultimos 100 eventos en memoria
        self._eventos = self._eventos[-100:]

    def eventos_recientes(self, n: int = 20) -> list[dict]:
        return list(reversed(self._eventos[-n:]))

    def resumen(self) -> dict:
        return {
            "modo": self._modo.value,
            "ultimo_cambio": self._ultimo_cambio.isoformat(timespec="seconds"),
            "eventos": self.eventos_recientes(),
            "senal": self._ultima_senal,
        }


# Instancia unica del estado del bot
estado = EstadoBot()
