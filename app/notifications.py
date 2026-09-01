"""Notificaciones push FCM para eventos operativos del APK beta."""
from __future__ import annotations

import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from .config import config
from .storage import storage

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aurum-push")
_credentials = None
_credentials_lock = Lock()
_ALLOWED_CATEGORIES = {"order", "mode", "risk", "engine", "reconciliation"}


def _service_info() -> dict | None:
    raw = config.fcm_service_account_json
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(base64.b64decode(raw).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.error("FCM_SERVICE_ACCOUNT_JSON no es JSON ni Base64 valido: %s", exc)
            return None


def configured() -> bool:
    info = _service_info()
    return bool(info and info.get("project_id") and info.get("private_key"))


def _access_token(info: dict) -> str:
    global _credentials
    with _credentials_lock:
        if _credentials is None:
            _credentials = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/firebase.messaging"]
            )
        if not _credentials.valid or _credentials.expired:
            _credentials.refresh(Request())
        return str(_credentials.token)


def _send(title: str, body: str, category: str) -> None:
    info = _service_info()
    tokens = storage.push_tokens()
    if not info or not tokens:
        return
    project_id = info["project_id"]
    try:
        access_token = _access_token(info)
    except Exception:
        logger.exception("No se pudo autenticar el envio FCM")
        return
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    headers = {"Authorization": f"Bearer {access_token}"}
    for token in tokens:
        payload = {"message": {
            "token": token,
            "notification": {"title": title[:120], "body": body[:300]},
            "data": {"category": category, "environment": "TESTNET"},
            "android": {"priority": "high", "notification": {
                "channel_id": "aurum_trading", "sound": "default",
            }},
        }}
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=8)
            if response.status_code in {404, 410} or "UNREGISTERED" in response.text:
                storage.unregister_push_device(token)
            elif response.status_code >= 300:
                logger.warning("FCM rechazo notificacion (%s): %s", response.status_code, response.text[:200])
        except (httpx.HTTPError, OSError):
            logger.exception("Fallo de red enviando notificacion FCM")


def notify_event(level: str, category: str, message: str) -> None:
    if category not in _ALLOWED_CATEGORIES or not configured():
        return
    titles = {
        "order": "Orden ejecutada · Testnet",
        "mode": "Modo de Aurum actualizado",
        "risk": "Alerta de riesgo · Testnet",
        "engine": "Estado del motor",
        "reconciliation": "Reconciliación requerida",
    }
    if level.upper() == "ERROR":
        title = "Aurum requiere atención"
    else:
        title = titles.get(category, "Aurum · Testnet")
    _executor.submit(_send, title, message, category)
