"""
Configuracion central del bot.
Lee las variables del archivo .env y las deja disponibles para el resto
de la aplicacion. Si algo falta, avisa con un mensaje claro.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Carga las variables del archivo .env (si existe)
load_dotenv()


def _as_bool(valor: str | None, por_defecto: bool = True) -> bool:
    if valor is None:
        return por_defecto
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes", "on")


@dataclass
class Config:
    api_key: str
    api_secret: str
    use_testnet: bool
    symbol: str
    panel_password: str
    # --- Parametros de la estrategia (Fase 2) ---
    interval: str          # temporalidad de las velas (1m, 5m, 1h, ...)
    sma_rapida: int        # media movil rapida
    sma_lenta: int         # media movil lenta
    rsi_periodo: int       # periodo del RSI
    rsi_sobrecompra: int   # umbral de sobrecompra (evita comprar caro)
    rsi_sobreventa: int    # umbral de sobreventa (oportunidad de compra)
    analisis_seg: int      # cada cuantos segundos analiza el mercado
    # --- Reglas de operacion / gestion de riesgo (Fase 3) ---
    orden_usdt: float          # cuanto USDT gastar en cada compra
    comprar_caida_pct: float   # comprar si el precio cae este % desde el maximo reciente
    take_profit_pct: float     # vender si sube este % sobre el precio de entrada (ganancia)
    stop_loss_pct: float       # vender si baja este % bajo el precio de entrada (proteccion)
    caida_ventana: int         # nº de velas para calcular el "maximo reciente"

    @property
    def base_url(self) -> str:
        # URL de la API segun sea testnet (dinero falso) o real
        if self.use_testnet:
            return "https://testnet.binance.vision"
        return "https://api.binance.com"

    @property
    def modo_texto(self) -> str:
        return "TESTNET (dinero falso)" if self.use_testnet else "REAL (dinero de verdad)"


def cargar_config() -> Config:
    return Config(
        api_key=os.getenv("BINANCE_API_KEY", "").strip(),
        api_secret=os.getenv("BINANCE_API_SECRET", "").strip(),
        use_testnet=_as_bool(os.getenv("USE_TESTNET"), True),
        symbol=os.getenv("SYMBOL", "BTCUSDT").strip().upper(),
        panel_password=os.getenv("PANEL_PASSWORD", "cambia_esto").strip(),
        interval=os.getenv("INTERVAL", "1h").strip(),
        sma_rapida=int(os.getenv("SMA_RAPIDA", "9")),
        sma_lenta=int(os.getenv("SMA_LENTA", "21")),
        rsi_periodo=int(os.getenv("RSI_PERIODO", "14")),
        rsi_sobrecompra=int(os.getenv("RSI_SOBRECOMPRA", "70")),
        rsi_sobreventa=int(os.getenv("RSI_SOBREVENTA", "30")),
        analisis_seg=int(os.getenv("ANALISIS_SEG", "30")),
        orden_usdt=float(os.getenv("ORDEN_USDT", "100")),
        comprar_caida_pct=float(os.getenv("COMPRAR_CAIDA_PCT", "1.0")),
        take_profit_pct=float(os.getenv("TAKE_PROFIT_PCT", "2.0")),
        stop_loss_pct=float(os.getenv("STOP_LOSS_PCT", "1.0")),
        caida_ventana=int(os.getenv("CAIDA_VENTANA", "24")),
    )


# Instancia unica que usa toda la app
config = cargar_config()
