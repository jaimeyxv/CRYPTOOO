"""Configuracion tipada y validada de Aurum."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class ConfigError(ValueError):
    """Configuracion incoherente o insegura."""


def _bool(nombre: str, defecto: bool) -> bool:
    valor = os.getenv(nombre)
    if valor is None:
        return defecto
    normalizado = valor.strip().lower()
    if normalizado in {"1", "true", "si", "sí", "yes", "on"}:
        return True
    if normalizado in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{nombre} debe ser true o false")


def _int(nombre: str, defecto: int) -> int:
    try:
        return int(os.getenv(nombre, str(defecto)))
    except ValueError as exc:
        raise ConfigError(f"{nombre} debe ser un numero entero") from exc


def _float(nombre: str, defecto: float) -> float:
    try:
        return float(os.getenv(nombre, str(defecto)))
    except ValueError as exc:
        raise ConfigError(f"{nombre} debe ser un numero") from exc


@dataclass(frozen=True)
class Config:
    api_key: str
    api_secret: str
    use_testnet: bool
    beta_only: bool
    enable_live_trading: bool
    symbol: str
    panel_password: str
    session_secret: str
    cookie_secure: bool
    allowed_hosts: tuple[str, ...]
    environment: str
    data_dir: Path
    log_level: str
    interval: str
    sma_rapida: int
    sma_lenta: int
    rsi_periodo: int
    rsi_sobrecompra: int
    rsi_sobreventa: int
    analisis_seg: int
    orden_usdt: float
    comprar_caida_pct: float
    take_profit_pct: float
    stop_loss_pct: float
    caida_ventana: int
    max_operaciones_dia: int
    perdida_max_diaria_usdt: float
    cooldown_seg: int
    http_timeout_seg: float
    fcm_service_account_json: str

    @property
    def base_url(self) -> str:
        return "https://testnet.binance.vision" if self.use_testnet else "https://api.binance.com"

    @property
    def modo_texto(self) -> str:
        return "TESTNET (dinero falso)" if self.use_testnet else "REAL (dinero real)"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "aurum.db"

    def validar(self) -> list[str]:
        """Devuelve avisos y bloquea configuraciones incoherentes."""
        errores: list[str] = []
        avisos: list[str] = []
        if not self.symbol.isalnum():
            errores.append("SYMBOL solo puede contener letras y numeros")
        if not self.allowed_hosts:
            errores.append("ALLOWED_HOSTS debe contener al menos un host")
        if self.sma_rapida < 1 or self.sma_lenta <= self.sma_rapida:
            errores.append("SMA_LENTA debe ser mayor que SMA_RAPIDA")
        if self.rsi_periodo < 2:
            errores.append("RSI_PERIODO debe ser al menos 2")
        if not 1 <= self.rsi_sobreventa < self.rsi_sobrecompra <= 99:
            errores.append("los umbrales RSI son invalidos")
        if self.analisis_seg < 5:
            errores.append("ANALISIS_SEG debe ser al menos 5")
        positivos = (self.orden_usdt, self.comprar_caida_pct, self.take_profit_pct,
                     self.stop_loss_pct, self.perdida_max_diaria_usdt)
        if any(valor <= 0 for valor in positivos):
            errores.append("importe y limites de riesgo deben ser positivos")
        if self.caida_ventana < 2 or self.max_operaciones_dia < 1 or self.cooldown_seg < 0:
            errores.append("ventana, maximo diario o cooldown invalidos")
        if not self.api_key or not self.api_secret:
            (errores if self.environment == "production" else avisos).append(
                "faltan credenciales de Binance; solo funcionaran endpoints publicos"
            )
        if self.panel_password == "cambia_esto" or len(self.panel_password) < 8:
            (errores if self.environment == "production" else avisos).append(
                "PANEL_PASSWORD es debil o conserva el valor inicial"
            )
        if len(self.session_secret) < 32:
            (errores if self.environment == "production" else avisos).append(
                "SESSION_SECRET deberia tener al menos 32 caracteres aleatorios"
            )
        if self.environment == "production" and not self.cookie_secure:
            errores.append("COOKIE_SECURE debe ser true en produccion")
        if self.environment == "production" and "*" in self.allowed_hosts:
            errores.append("ALLOWED_HOSTS no puede ser * en produccion")
        if not self.use_testnet and not self.enable_live_trading:
            avisos.append("Mainnet esta configurado, pero ENABLE_LIVE_TRADING=false bloquea ordenes")
        if self.beta_only and not self.use_testnet:
            errores.append("BETA_ONLY=true exige USE_TESTNET=true; Mainnet esta bloqueado en esta version")
        if errores:
            raise ConfigError("Configuracion invalida: " + "; ".join(errores))
        return avisos


def cargar_config() -> Config:
    raiz = Path(__file__).resolve().parent.parent
    password = os.getenv("PANEL_PASSWORD", "cambia_esto").strip()
    return Config(
        api_key=os.getenv("BINANCE_API_KEY", "").strip(),
        api_secret=os.getenv("BINANCE_API_SECRET", "").strip(),
        use_testnet=_bool("USE_TESTNET", True),
        beta_only=_bool("BETA_ONLY", True),
        enable_live_trading=_bool("ENABLE_LIVE_TRADING", False),
        symbol=os.getenv("SYMBOL", "BTCUSDT").strip().upper(),
        panel_password=password,
        session_secret=os.getenv("SESSION_SECRET", password).strip(),
        cookie_secure=_bool("COOKIE_SECURE", False),
        allowed_hosts=tuple(host.strip() for host in os.getenv("ALLOWED_HOSTS", "*").split(",") if host.strip()),
        environment=os.getenv("ENVIRONMENT", "development").strip().lower(),
        data_dir=Path(os.getenv("DATA_DIR", str(raiz / "data"))).expanduser(),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        interval=os.getenv("INTERVAL", "1h").strip(),
        sma_rapida=_int("SMA_RAPIDA", 9),
        sma_lenta=_int("SMA_LENTA", 21),
        rsi_periodo=_int("RSI_PERIODO", 14),
        rsi_sobrecompra=_int("RSI_SOBRECOMPRA", 70),
        rsi_sobreventa=_int("RSI_SOBREVENTA", 30),
        analisis_seg=_int("ANALISIS_SEG", 30),
        orden_usdt=_float("ORDEN_USDT", 100),
        comprar_caida_pct=_float("COMPRAR_CAIDA_PCT", 1.0),
        take_profit_pct=_float("TAKE_PROFIT_PCT", 2.0),
        stop_loss_pct=_float("STOP_LOSS_PCT", 1.0),
        caida_ventana=_int("CAIDA_VENTANA", 24),
        max_operaciones_dia=_int("MAX_OPERACIONES_DIA", 10),
        perdida_max_diaria_usdt=_float("PERDIDA_MAX_DIARIA_USDT", 50),
        cooldown_seg=_int("COOLDOWN_SEG", 300),
        http_timeout_seg=_float("HTTP_TIMEOUT_SEG", 10),
        fcm_service_account_json=os.getenv("FCM_SERVICE_ACCOUNT_JSON", "").strip(),
    )


config = cargar_config()
