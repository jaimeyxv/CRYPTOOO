"""Estado concurrente del motor y bitacora operativa."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from enum import Enum
from threading import RLock

from .storage import storage

logger = logging.getLogger(__name__)


class Modo(str, Enum):
    OFF = "OFF"
    SENALES = "SENALES"
    AUTO = "AUTO"


class EstadoBot:
    def __init__(self) -> None:
        self._modo = Modo.OFF
        self._lock = RLock()
        self._ultimo_cambio = datetime.now(timezone.utc)
        self._eventos: list[dict] = []
        self._ultima_senal: dict | None = None
        self._senal_previa: str | None = None
        self._append_event("INFO", "system", "Bot iniciado en modo OFF", persistir=False)

    @staticmethod
    def _ahora() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _append_event(self, level: str, category: str, mensaje: str, persistir: bool = True) -> None:
        evento = {"hora": self._ahora(), "level": level, "category": category, "mensaje": mensaje}
        self._eventos.append(evento)
        self._eventos = self._eventos[-200:]
        if persistir:
            try:
                storage.add_event(level, category, mensaje)
            except sqlite3.Error:
                logger.exception("No se pudo persistir un evento")

    def registrar_evento(self, mensaje: str, level: str = "INFO", category: str = "trading") -> None:
        with self._lock:
            self._append_event(level.upper(), category, mensaje)
        getattr(logger, level.lower(), logger.info)(mensaje)

    def registrar_analisis(self, analisis: dict) -> None:
        with self._lock:
            self._ultima_senal = dict(analisis)
            nueva = analisis.get("señal")
            if nueva in {"COMPRAR", "VENDER"} and nueva != self._senal_previa:
                sufijo = "esperando confirmacion" if self._modo == Modo.SENALES else "evaluando ejecucion"
                if self._modo != Modo.OFF:
                    self._append_event("INFO", "signal", f"Señal {nueva}: {analisis.get('razon', '')} ({sufijo})")
            self._senal_previa = nueva

    @property
    def ultima_senal(self) -> dict | None:
        with self._lock:
            return dict(self._ultima_senal) if self._ultima_senal else None

    @property
    def modo(self) -> Modo:
        with self._lock:
            return self._modo

    def cambiar_modo(self, nuevo: Modo) -> None:
        with self._lock:
            if nuevo == self._modo:
                return
            anterior = self._modo
            self._modo = nuevo
            self._ultimo_cambio = datetime.now(timezone.utc)
            self._append_event("WARNING" if nuevo == Modo.AUTO else "INFO", "mode",
                               f"Modo cambiado: {anterior.value} -> {nuevo.value}")

    def parada_emergencia(self) -> None:
        with self._lock:
            anterior = self._modo
            self._modo = Modo.OFF
            self._ultimo_cambio = datetime.now(timezone.utc)
            self._append_event("WARNING", "risk", f"Parada de emergencia activada desde {anterior.value}")

    def eventos_recientes(self, n: int = 30) -> list[dict]:
        with self._lock:
            return [dict(item) for item in reversed(self._eventos[-n:])]

    def resumen(self) -> dict:
        with self._lock:
            return {
                "modo": self._modo.value,
                "ultimo_cambio": self._ultimo_cambio.isoformat(timespec="seconds"),
                "eventos": [dict(item) for item in reversed(self._eventos[-30:])],
                "senal": dict(self._ultima_senal) if self._ultima_senal else None,
            }


estado = EstadoBot()
