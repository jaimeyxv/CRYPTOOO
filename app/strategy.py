"""
Estrategia de trading (Fase 2): Cruce de medias moviles + filtro RSI.

Idea, en palabras sencillas:
  - Media RAPIDA (ej. 9 velas) y media LENTA (ej. 21 velas).
  - Cuando la rapida CRUZA hacia ARRIBA a la lenta -> el precio coge fuerza -> COMPRAR.
  - Cuando la rapida CRUZA hacia ABAJO a la lenta -> pierde fuerza -> VENDER.
  - El RSI actua de filtro: no compramos si ya esta "sobrecomprado" (caro),
    y damos aviso de venta si esta muy sobrecomprado.

Todo se calcula con matematica basica (sin librerias pesadas).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import sqrt


@dataclass
class Analisis:
    señal: str            # "COMPRAR" | "VENDER" | "MANTENER"
    razon: str            # explicacion legible para el panel
    precio: float
    rsi: float | None
    sma_rapida: float | None
    sma_lenta: float | None
    tendencia: str        # "alcista" | "bajista" | "lateral"
    confianza: int        # 0-100, intensidad heuristica; no probabilidad
    volatilidad_pct: float | None

    def dict(self) -> dict:
        return asdict(self)


def sma_serie(valores: list[float], n: int) -> list[float | None]:
    """Media movil simple como serie (None hasta tener n datos)."""
    salida: list[float | None] = []
    acum = 0.0
    for i, v in enumerate(valores):
        acum += v
        if i >= n:
            acum -= valores[i - n]
        salida.append(acum / n if i >= n - 1 else None)
    return salida


def rsi(valores: list[float], periodo: int = 14) -> float | None:
    """Indice de Fuerza Relativa (0-100). Mide si algo esta sobre/infravalorado."""
    if len(valores) <= periodo:
        return None
    ganancias, perdidas = 0.0, 0.0
    # Primera media de ganancias/perdidas
    for i in range(1, periodo + 1):
        cambio = valores[i] - valores[i - 1]
        if cambio >= 0:
            ganancias += cambio
        else:
            perdidas -= cambio
    media_g = ganancias / periodo
    media_p = perdidas / periodo
    # Suavizado de Wilder para el resto
    for i in range(periodo + 1, len(valores)):
        cambio = valores[i] - valores[i - 1]
        subida = max(cambio, 0.0)
        bajada = max(-cambio, 0.0)
        media_g = (media_g * (periodo - 1) + subida) / periodo
        media_p = (media_p * (periodo - 1) + bajada) / periodo
    if media_p == 0:
        return 100.0
    rs = media_g / media_p
    return round(100 - (100 / (1 + rs)), 2)


def rsi_serie(valores: list[float], periodo: int = 14) -> list[float | None]:
    """Serie RSI de Wilder alineada con los precios de entrada."""
    salida: list[float | None] = [None] * len(valores)
    if len(valores) <= periodo:
        return salida
    cambios = [valores[i] - valores[i - 1] for i in range(1, len(valores))]
    media_g = sum(max(c, 0) for c in cambios[:periodo]) / periodo
    media_p = sum(max(-c, 0) for c in cambios[:periodo]) / periodo
    salida[periodo] = 100.0 if media_p == 0 else round(100 - 100 / (1 + media_g / media_p), 2)
    for indice in range(periodo, len(cambios)):
        cambio = cambios[indice]
        media_g = (media_g * (periodo - 1) + max(cambio, 0)) / periodo
        media_p = (media_p * (periodo - 1) + max(-cambio, 0)) / periodo
        salida[indice + 1] = 100.0 if media_p == 0 else round(100 - 100 / (1 + media_g / media_p), 2)
    return salida


def volatilidad_pct(valores: list[float], ventana: int = 20) -> float | None:
    """Desviacion estandar de retornos simples, expresada en porcentaje."""
    muestra = valores[-(ventana + 1):]
    if len(muestra) < 3:
        return None
    retornos = [(muestra[i] / muestra[i - 1] - 1) * 100 for i in range(1, len(muestra)) if muestra[i - 1]]
    if len(retornos) < 2:
        return None
    media = sum(retornos) / len(retornos)
    varianza = sum((valor - media) ** 2 for valor in retornos) / (len(retornos) - 1)
    return round(sqrt(varianza), 3)


def analizar(cierres: list[float], cfg) -> Analisis:
    """
    Recibe la lista de precios de cierre (mas reciente al final) y la config,
    y devuelve la señal actual con su explicacion.
    """
    precio = cierres[-1] if cierres else 0.0
    if not cierres:
        return Analisis("MANTENER", "No hay velas disponibles.", 0.0, None, None, None,
                        "lateral", 0, None)
    sr = sma_serie(cierres, cfg.sma_rapida)
    sl = sma_serie(cierres, cfg.sma_lenta)
    valor_rsi = rsi(cierres, cfg.rsi_periodo)

    rapida_ahora, rapida_antes = sr[-1], sr[-2] if len(sr) >= 2 else None
    lenta_ahora, lenta_antes = sl[-1], sl[-2] if len(sl) >= 2 else None

    # Sin datos suficientes todavia
    if None in (rapida_ahora, rapida_antes, lenta_ahora, lenta_antes):
        return Analisis(
            señal="MANTENER",
            razon="Aun no hay suficientes velas para analizar.",
            precio=precio, rsi=valor_rsi,
            sma_rapida=rapida_ahora, sma_lenta=lenta_ahora,
            tendencia="lateral", confianza=0, volatilidad_pct=volatilidad_pct(cierres),
        )

    tendencia = "alcista" if rapida_ahora >= lenta_ahora else "bajista"

    # Deteccion de cruces
    cruce_arriba = rapida_antes <= lenta_antes and rapida_ahora > lenta_ahora
    cruce_abajo = rapida_antes >= lenta_antes and rapida_ahora < lenta_ahora

    señal = "MANTENER"
    razon = "Sin cambios relevantes; mantener posicion."

    if cruce_arriba:
        if valor_rsi is not None and valor_rsi >= cfg.rsi_sobrecompra:
            señal = "MANTENER"
            razon = f"Cruce alcista pero RSI alto ({valor_rsi}): posible sobrecompra, esperar."
        else:
            señal = "COMPRAR"
            razon = f"Cruce alcista de medias (RSI {valor_rsi}). Momento de entrada."
    elif cruce_abajo:
        señal = "VENDER"
        razon = f"Cruce bajista de medias (RSI {valor_rsi}). Momento de salida."
    elif valor_rsi is not None and valor_rsi >= cfg.rsi_sobrecompra:
        señal = "VENDER"
        razon = f"RSI muy alto ({valor_rsi}): sobrecompra, considerar tomar ganancias."
    elif valor_rsi is not None and valor_rsi <= cfg.rsi_sobreventa:
        señal = "COMPRAR"
        razon = f"RSI muy bajo ({valor_rsi}): sobreventa, posible rebote."

    separacion = abs(rapida_ahora - lenta_ahora) / precio * 100 if precio else 0
    confianza = min(100, round(35 + separacion * 20)) if señal != "MANTENER" else min(60, round(separacion * 15))
    return Analisis(
        señal=señal, razon=razon, precio=precio, rsi=valor_rsi,
        sma_rapida=round(rapida_ahora, 2), sma_lenta=round(lenta_ahora, 2),
        tendencia=tendencia, confianza=confianza, volatilidad_pct=volatilidad_pct(cierres),
    )
