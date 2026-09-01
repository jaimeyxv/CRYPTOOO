"""Sesion firmada y proteccion basica contra fuerza bruta."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request

from .config import config

COOKIE = "aurum_sesion"
DURACION_SEG = 7 * 24 * 3600
VENTANA_LOGIN_SEG = 5 * 60
MAX_INTENTOS = 8
_intentos: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()


def _secreto() -> bytes:
    return hashlib.sha256(("aurum-session:" + config.session_secret).encode()).digest()


def crear_token() -> str:
    expira = str(int(time.time()) + DURACION_SEG)
    nonce = secrets.token_urlsafe(18)
    payload = f"{expira}.{nonce}"
    firma = hmac.new(_secreto(), payload.encode(), hashlib.sha256).digest()
    firma_b64 = base64.urlsafe_b64encode(firma).decode().rstrip("=")
    return f"{payload}.{firma_b64}"


def token_valido(token: str | None) -> bool:
    if not token or token.count(".") != 2:
        return False
    expira, nonce, firma_b64 = token.split(".", 2)
    try:
        if int(expira) < int(time.time()) or not nonce:
            return False
        recibida = base64.urlsafe_b64decode(firma_b64 + "=" * (-len(firma_b64) % 4))
    except (ValueError, TypeError):
        return False
    payload = f"{expira}.{nonce}"
    esperada = hmac.new(_secreto(), payload.encode(), hashlib.sha256).digest()
    return hmac.compare_digest(esperada, recibida)


def pin_correcto(pin: str) -> bool:
    return secrets.compare_digest(pin.strip(), config.panel_password)


def esta_autenticado(request: Request) -> bool:
    return token_valido(request.cookies.get(COOKIE))


def login_permitido(ip: str) -> bool:
    ahora = time.monotonic()
    with _lock:
        intentos = _intentos[ip]
        while intentos and ahora - intentos[0] > VENTANA_LOGIN_SEG:
            intentos.popleft()
        return len(intentos) < MAX_INTENTOS


def registrar_login(ip: str, correcto: bool) -> None:
    with _lock:
        if correcto:
            _intentos.pop(ip, None)
        else:
            _intentos[ip].append(time.monotonic())
