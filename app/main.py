"""Aplicacion web, API privada y ciclo de vida de Aurum."""
from __future__ import annotations

import logging
import time
import uuid
import csv
import io
from bisect import bisect_right
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import auth, engine, trader
from .binance_client import BinanceError, INTERVALOS, cliente
from .bot import Modo, estado
from .config import config
from .storage import storage
from .process_lock import ProcessLock
from .strategy import rsi_serie, sma_serie

logging.basicConfig(
    level=getattr(logging, config.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
process_lock = ProcessLock(config.data_dir / "aurum.lock")


@asynccontextmanager
async def lifespan(_: FastAPI):
    process_lock.acquire()
    try:
        storage.initialize()
        for warning in config.validar():
            logger.warning("Configuracion: %s", warning)
            storage.add_event("WARNING", "config", warning)
        engine.iniciar()
        yield
    finally:
        engine.detener()
        cliente.cerrar()
        process_lock.release()


app = FastAPI(
    title="Aurum Trading Console", version="2.0.0",
    docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan,
)
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts))


@app.middleware("http")
async def security_and_observability(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:16])
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc.lower() != request.headers.get("host", "").lower():
            return JSONResponse({"detail": "Origen no permitido"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'"
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Response-Time"] = f"{(time.perf_counter() - started) * 1000:.1f}ms"
    return response


def requerir_auth(request: Request) -> None:
    if not auth.esta_autenticado(request):
        raise HTTPException(status_code=401, detail="No autenticado")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if auth.esta_autenticado(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/api/login")
def api_login(request: Request, pin: str = Form(...)):
    ip = request.client.host if request.client else "unknown"
    if not auth.login_permitido(ip):
        raise HTTPException(status_code=429, detail="Demasiados intentos; espera cinco minutos")
    correcto = auth.pin_correcto(pin)
    auth.registrar_login(ip, correcto)
    if not correcto:
        return JSONResponse({"ok": False}, status_code=401)
    response = JSONResponse({"ok": True})
    response.set_cookie(
        auth.COOKIE, auth.crear_token(), max_age=auth.DURACION_SEG,
        httponly=True, secure=config.cookie_secure, samesite="strict", path="/",
    )
    return response


@app.post("/api/logout")
def api_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.COOKIE, path="/")
    return response


@app.get("/", response_class=HTMLResponse)
def panel(request: Request):
    if not auth.esta_autenticado(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("index.html", {
        "request": request, "symbol": config.symbol, "modo_conexion": config.modo_texto,
        "interval": config.interval,
    })


@app.get("/api/estado", dependencies=[Depends(requerir_auth)])
def api_estado():
    bot_summary = estado.resumen()
    persisted_events = storage.events(30)
    if persisted_events:
        bot_summary["eventos"] = [
            {"hora": item["created_at"], "level": item["level"],
             "category": item["category"], "mensaje": item["message"]}
            for item in persisted_events
        ]
    result: dict = {
        "conexion": config.modo_texto, "symbol": config.symbol,
        "bot": bot_summary, "motor": engine.estado_motor(),
        "precio": None, "mercado_24h": None, "saldos": [],
        "posicion": None, "rendimiento": storage.performance(),
        "riesgo": trader.estado_riesgo(),
        "reglas": {
            "orden_usdt": config.orden_usdt,
            "comprar_caida_pct": config.comprar_caida_pct,
            "take_profit_pct": config.take_profit_pct,
            "stop_loss_pct": config.stop_loss_pct,
        },
        "error": None,
    }
    try:
        ticker = cliente.ticker_24h()
        result["mercado_24h"] = ticker
        result["precio"] = ticker["price"]
    except BinanceError as exc:
        result["error"] = str(exc)
    result["posicion"] = trader.estado_posicion(result["precio"])
    try:
        result["saldos"] = cliente.saldos()
    except BinanceError as exc:
        if result["error"] is None:
            result["error"] = f"Saldo no disponible: {exc}"
    return result


@app.post("/api/modo", dependencies=[Depends(requerir_auth)])
def api_cambiar_modo(modo: str = Form(...)):
    try:
        nuevo = Modo(modo.strip().upper())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Modo invalido: {modo}") from exc
    if nuevo == Modo.AUTO and not config.use_testnet and not config.enable_live_trading:
        raise HTTPException(status_code=403, detail="AUTO en Mainnet requiere ENABLE_LIVE_TRADING=true")
    estado.cambiar_modo(nuevo)
    return {"ok": True, "modo": nuevo.value}


@app.post("/api/parada", dependencies=[Depends(requerir_auth)])
def api_parada():
    estado.parada_emergencia()
    return {"ok": True, "modo": Modo.OFF.value, "mensaje": "Motor detenido; la posicion no fue liquidada"}


@app.post("/api/orden", dependencies=[Depends(requerir_auth)])
def api_orden(tipo: str = Form(...)):
    if estado.modo == Modo.OFF:
        raise HTTPException(status_code=400, detail="Activa SENALES o AUTO antes de operar")
    tipo = tipo.strip().upper()
    if tipo == "COMPRAR":
        return trader.comprar("orden manual")
    if tipo == "VENDER":
        return trader.vender("orden manual")
    raise HTTPException(status_code=400, detail=f"Tipo invalido: {tipo}")


@app.get("/api/velas", dependencies=[Depends(requerir_auth)])
def api_velas(
    interval: str = Query(default=config.interval),
    limit: int = Query(default=200, ge=50, le=500),
):
    if interval not in INTERVALOS:
        raise HTTPException(status_code=400, detail="Intervalo no permitido")
    try:
        klines = cliente.klines(interval=interval, limit=limit)
    except BinanceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    cierres = [float(k[4]) for k in klines]
    rapida = sma_serie(cierres, config.sma_rapida)
    lenta = sma_serie(cierres, config.sma_lenta)
    rsis = rsi_serie(cierres, config.rsi_periodo)
    candles, fast, slow, volume, rsi_data = [], [], [], [], []
    for index, kline in enumerate(klines):
        epoch = int(kline[0]) // 1000
        opening, high, low, close = map(float, kline[1:5])
        candles.append({"time": epoch, "open": opening, "high": high, "low": low, "close": close})
        volume.append({"time": epoch, "value": float(kline[5]), "color": "#22c55e55" if close >= opening else "#ef444455"})
        if rapida[index] is not None:
            fast.append({"time": epoch, "value": round(rapida[index], 8)})
        if lenta[index] is not None:
            slow.append({"time": epoch, "value": round(lenta[index], 8)})
        if rsis[index] is not None:
            rsi_data.append({"time": epoch, "value": rsis[index]})
    markers = []
    candle_times = [item["time"] for item in candles]
    for trade in reversed(storage.trades(200)):
        try:
            timestamp = int(datetime.fromisoformat(trade["created_at"]).timestamp())
        except (ValueError, TypeError):
            continue
        marker_index = bisect_right(candle_times, timestamp) - 1
        if marker_index < 0:
            continue
        markers.append({
            "time": candle_times[marker_index], "position": "belowBar" if trade["side"] == "BUY" else "aboveBar",
            "color": "#22c55e" if trade["side"] == "BUY" else "#ef4444",
            "shape": "arrowUp" if trade["side"] == "BUY" else "arrowDown",
            "text": f"{trade['side']} {trade['price']:.2f}",
        })
    return {
        "velas": candles, "sma_rapida": fast, "sma_lenta": slow,
        "volumen": volume, "rsi": rsi_data, "marcadores": markers,
        "config": {"interval": interval, "sma_rapida": config.sma_rapida,
                   "sma_lenta": config.sma_lenta, "rsi_periodo": config.rsi_periodo},
    }


@app.get("/api/historial", dependencies=[Depends(requerir_auth)])
def api_historial(limit: int = Query(default=50, ge=1, le=500)):
    return {"operaciones": storage.trades(limit), "rendimiento": storage.performance()}


@app.get("/api/historial.csv", dependencies=[Depends(requerir_auth)])
def exportar_historial():
    fields = ["created_at", "symbol", "side", "quantity", "price", "quote_quantity",
              "realized_pnl", "realized_pnl_pct", "mode", "reason", "order_id"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for trade in reversed(storage.trades(500)):
        safe = dict(trade)
        for key, value in safe.items():
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                safe[key] = "'" + value
        writer.writerow(safe)
    return Response(
        output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=aurum-trades.csv"},
    )


@app.get("/api/configuracion", dependencies=[Depends(requerir_auth)])
def api_configuracion():
    return {
        "symbol": config.symbol, "testnet": config.use_testnet,
        "live_trading": config.enable_live_trading, "interval": config.interval,
        "sma_rapida": config.sma_rapida, "sma_lenta": config.sma_lenta,
        "rsi_periodo": config.rsi_periodo, "analisis_seg": config.analisis_seg,
        "max_operaciones_dia": config.max_operaciones_dia,
        "perdida_max_diaria_usdt": config.perdida_max_diaria_usdt,
        "cooldown_seg": config.cooldown_seg,
    }


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "aurum", "version": app.version}


@app.get("/readyz")
def readyz():
    motor = engine.estado_motor()
    database_ok = storage.healthy()
    ok = database_ok and motor["thread_alive"]
    public_engine = {"thread_alive": motor["thread_alive"], "phase": motor["phase"]}
    return JSONResponse({"ok": ok, "database": database_ok, "engine": public_engine}, status_code=200 if ok else 503)


@app.get("/api/salud")
def salud_binance():
    try:
        cliente.ping()
        return {"ok": True, "binance": True}
    except BinanceError as exc:
        return JSONResponse({"ok": False, "binance": False, "error": str(exc)}, status_code=503)
