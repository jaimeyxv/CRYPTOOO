"""
Aplicacion web (panel de control) con FastAPI.

Arranca con:   uvicorn app.main:app --host 0.0.0.0 --port 8000
Luego abre en la tablet:   http://IP_DEL_EQUIPO:8000

Rutas:
  GET  /            -> el panel (HTML)
  GET  /api/estado  -> datos en vivo (precio, saldo, modo)  [JSON]
  POST /api/modo    -> cambiar OFF / SENALES / AUTO
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request

from contextlib import asynccontextmanager

from .binance_client import cliente, BinanceError
from .bot import estado, Modo
from .config import config
from . import auth
from . import engine
from . import trader
from .strategy import sma_serie


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine.iniciar()   # arranca el motor de analisis en segundo plano
    yield
    engine.detener()


app = FastAPI(title="Bot Financiero", docs_url=None, redoc_url=None, lifespan=lifespan)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def requerir_auth(request: Request):
    """Dependencia para las rutas /api: corta con 401 si no hay sesion valida."""
    if not auth.esta_autenticado(request):
        raise HTTPException(status_code=401, detail="No autenticado")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    # Si ya tiene sesion, no tiene sentido pedir el PIN otra vez
    if auth.esta_autenticado(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/api/login")
def api_login(pin: str = Form(...)):
    if not auth.pin_correcto(pin):
        return JSONResponse({"ok": False}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        auth.COOKIE, auth.crear_token(),
        max_age=auth.DURACION_SEG, httponly=True, samesite="lax",
    )
    return resp


@app.post("/api/logout")
def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/", response_class=HTMLResponse)
def panel(request: Request):
    if not auth.esta_autenticado(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "symbol": config.symbol,
            "modo_conexion": config.modo_texto,
        },
    )


@app.get("/api/estado", dependencies=[Depends(requerir_auth)])
def api_estado():
    """Todo lo que el panel necesita para refrescarse."""
    resultado: dict = {
        "conexion": config.modo_texto,
        "symbol": config.symbol,
        "bot": estado.resumen(),
        "precio": None,
        "saldos": [],
        "posicion": None,
        "reglas": {
            "orden_usdt": config.orden_usdt,
            "comprar_caida_pct": config.comprar_caida_pct,
            "take_profit_pct": config.take_profit_pct,
            "stop_loss_pct": config.stop_loss_pct,
        },
        "error": None,
    }

    # Precio (publico, no necesita clave)
    try:
        resultado["precio"] = cliente.precio_actual()
    except BinanceError as e:
        resultado["error"] = str(e)

    # Posicion actual con P&L en vivo
    try:
        resultado["posicion"] = trader.estado_posicion(resultado["precio"])
    except Exception:
        resultado["posicion"] = None

    # Saldos (necesita clave valida)
    try:
        resultado["saldos"] = cliente.saldos()
    except BinanceError as e:
        # No pisamos un error de precio si ya hubo uno
        if resultado["error"] is None:
            resultado["error"] = f"Saldo no disponible (revisa tus claves): {e}"

    return resultado


@app.post("/api/modo", dependencies=[Depends(requerir_auth)])
def api_cambiar_modo(modo: str = Form(...)):
    modo = modo.strip().upper()
    try:
        nuevo = Modo(modo)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Modo invalido: {modo}")
    estado.cambiar_modo(nuevo)
    return {"ok": True, "modo": nuevo.value}


@app.post("/api/orden", dependencies=[Depends(requerir_auth)])
def api_orden(tipo: str = Form(...)):
    """Orden manual desde el panel: COMPRAR o VENDER."""
    tipo = tipo.strip().upper()
    if estado.modo == Modo.OFF:
        raise HTTPException(status_code=400, detail="El bot esta en OFF. Activa SEÑALES o AUTO para operar.")
    if tipo == "COMPRAR":
        return trader.comprar("orden manual")
    if tipo == "VENDER":
        return trader.vender("orden manual")
    raise HTTPException(status_code=400, detail=f"Tipo invalido: {tipo}")


@app.get("/api/velas", dependencies=[Depends(requerir_auth)])
def api_velas():
    """Velas + medias moviles para el grafico del panel."""
    try:
        klines = cliente.klines(interval=config.interval, limit=150)
    except BinanceError as e:
        raise HTTPException(status_code=502, detail=str(e))

    cierres = [float(k[4]) for k in klines]
    sr = sma_serie(cierres, config.sma_rapida)
    sl = sma_serie(cierres, config.sma_lenta)

    velas, media_rapida, media_lenta = [], [], []
    for i, k in enumerate(klines):
        t = int(k[0]) // 1000  # segundos (lightweight-charts usa epoch en segundos)
        velas.append({
            "time": t,
            "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]),
        })
        if sr[i] is not None:
            media_rapida.append({"time": t, "value": round(sr[i], 2)})
        if sl[i] is not None:
            media_lenta.append({"time": t, "value": round(sl[i], 2)})

    return {
        "velas": velas,
        "sma_rapida": media_rapida,
        "sma_lenta": media_lenta,
        "config": {
            "interval": config.interval,
            "sma_rapida": config.sma_rapida,
            "sma_lenta": config.sma_lenta,
        },
    }


@app.get("/api/salud")
def salud():
    """Comprueba que Binance responde."""
    try:
        cliente.ping()
        return {"ok": True}
    except BinanceError as e:
        return {"ok": False, "error": str(e)}
