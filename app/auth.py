"""
Autenticacion sencilla del panel mediante un PIN (PANEL_PASSWORD del .env).

No usamos base de datos ni librerias extra: firmamos una cookie con HMAC
(SHA-256) usando la propia contrasena como secreto. Asi la sesion sigue
siendo valida aunque se reinicie el servidor, y nadie puede falsificarla
sin conocer el PIN.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from fastapi import Request

from .config import config

COOKIE = "aurum_sesion"
DURACION_SEG = 7 * 24 * 3600  # la sesion dura 7 dias


def _secreto() -> bytes:
    """Clave de firma derivada del PIN (estable entre reinicios)."""
    return hashlib.sha256(("aurum:" + config.panel_password).encode()).digest()


def crear_token() -> str:
    """Genera el valor de cookie: 'expira.firma'."""
    expira = str(int(time.time()) + DURACION_SEG)
    firma = hmac.new(_secreto(), expira.encode(), hashlib.sha256).digest()
    firma_b64 = base64.urlsafe_b64encode(firma).decode().rstrip("=")
    return f"{expira}.{firma_b64}"


def token_valido(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expira_str, firma_b64 = token.rsplit(".", 1)
    try:
        if int(expira_str) < int(time.time()):
            return False  # caducada
    except ValueError:
        return False
    esperada = hmac.new(_secreto(), expira_str.encode(), hashlib.sha256).digest()
    recibida = base64.urlsafe_b64decode(firma_b64 + "=" * (-len(firma_b64) % 4))
    return hmac.compare_digest(esperada, recibida)


def pin_correcto(pin: str) -> bool:
    """Compara el PIN introducido con el del .env (tiempo constante)."""
    return secrets.compare_digest(pin.strip(), config.panel_password)


def esta_autenticado(request: Request) -> bool:
    return token_valido(request.cookies.get(COOKIE))
