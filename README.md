# 🤖 Bot Financiero (Binance)

Bot de trading para Binance **Spot** con panel de control para tablet.
Tú decides cuándo activarlo y en qué modo. Empieza en **Testnet** (dinero falso).

> ⚠️ Esto es una herramienta educativa. El trading tiene riesgo real de
> pérdida. No inviertas dinero que no puedas permitirte perder.

---

## 🧭 Modos del bot

| Modo | Qué hace |
|------|----------|
| 🔴 **OFF** | Dormido, no hace nada |
| 🟡 **SEÑALES** | Detecta oportunidades y te avisa, pero **NO opera** — tú aprietas el botón |
| 🟢 **AUTO** | Detecta y ejecuta las órdenes solo |

---

## 🚀 Puesta en marcha (en tu PC primero)

### 1. Consigue las claves de Testnet (gratis, dinero falso)
1. Entra en <https://testnet.binance.vision/>
2. Inicia sesión con tu cuenta de **GitHub**
3. Pulsa **"Generate HMAC_SHA256 Key"**
4. Copia la **API Key** y el **Secret Key** (el secret solo se muestra una vez)

### 2. Configura el proyecto
```powershell
# Crea tu archivo de configuración a partir del ejemplo
copy .env.example .env
# Abre .env y pega tus claves de testnet
```

### 3. Instala las dependencias
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. Arranca el bot
```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 5. Abre el panel
- En el **mismo PC**: <http://localhost:8000>
- En la **tablet** (misma red WiFi): `http://IP_DEL_PC:8000`
  (mira la IP del PC con `ipconfig`)

---

## 📁 Estructura

```
app/
  config.py          # lee el .env
  binance_client.py  # habla con Binance (precios, saldo, órdenes)
  bot.py             # el interruptor OFF / SEÑALES / AUTO
  main.py            # el servidor web y el panel
  templates/
    index.html       # el panel que ves en la tablet
```

---

## 🧠 La estrategia (Fase 2)

Cruce de **medias móviles** con filtro de **RSI**:

- Media **rápida** (9 velas) y **lenta** (21 velas) sobre velas de 1 hora.
- Cruce rápida ↑ lenta → **COMPRAR** · cruce rápida ↓ lenta → **VENDER**.
- El **RSI (14)** filtra: evita comprar sobrecomprado y avisa de tomar ganancias.

Todo es configurable desde el `.env` (`SMA_RAPIDA`, `SMA_LENTA`, `RSI_PERIODO`,
`INTERVAL`, `ANALISIS_SEG`…). El bot re-analiza cada 30 s en segundo plano.

---

## 💸 Reglas de operación (Fase 3)

El bot ejecuta órdenes reales (en la cuenta configurada) con gestión de riesgo:

| Regla | Variable `.env` | Por defecto |
|-------|-----------------|-------------|
| Cuánto gastar por compra | `ORDEN_USDT` | 100 USDT |
| **Comprar** si el precio cae X% desde el máximo reciente | `COMPRAR_CAIDA_PCT` | 1.0 % |
| **Vender** (take-profit) si sube Y% sobre la entrada | `TAKE_PROFIT_PCT` | 2.0 % |
| **Stop-loss**: vender si pierde Z% | `STOP_LOSS_PCT` | 1.0 % |

- En modo **🟡 SEÑALES**: tú aprietas **Comprar/Vender** (con confirmación).
- En modo **🟢 AUTO**: el bot compra en las caídas y vende solo al llegar al
  take-profit o al stop-loss.
- Solo mantiene **una posición a la vez** y guarda la entrada en `data/posicion.json`.

> 🔒 Antes de pasar a dinero real: en la API Key de Binance **desactiva los retiros**
> (deja solo *Enable Spot Trading*).

---

## 🗺️ Hoja de ruta

- [x] **Fase 1** — Esqueleto: panel + conexión a Testnet + interruptor de modo
- [x] **Fase 2** — Dashboard profesional + estrategia (RSI + medias móviles) + motor de señales
- [x] **Fase 3** — Ejecución real (manual y AUTO) con reglas de %: compra en caída, take-profit y stop-loss
- [ ] **Fase 4** — Desplegar 24/7 en Oracle Cloud (gratis)
- [ ] **Fase 5** — Pasar a dinero real (con retiros desactivados en la API)
