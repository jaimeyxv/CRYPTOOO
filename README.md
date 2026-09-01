# Aurum — Bot de trading para Binance Spot

Aurum es una aplicación web de trading educativo para **Binance Spot**. Reúne un panel responsive, análisis técnico y ejecución manual o automática de órdenes. Está diseñada para comenzar en **Spot Testnet**, validar el funcionamiento sin dinero real y solo después evaluar un uso controlado en Mainnet.

> [!WARNING]
> Este proyecto no ofrece asesoramiento financiero ni garantiza rentabilidad. Una estrategia automatizada puede generar pérdidas. Usa Testnet durante el desarrollo y nunca habilites retiros en una API key de trading.

## Estado actual

El proyecto ya dispone de:

- Panel web protegido por contraseña.
- Precio, velas y saldos de Binance Spot.
- Estrategia basada en medias móviles simples (SMA) y RSI.
- Modos `OFF`, `SENALES` y `AUTO`.
- Órdenes manuales de mercado desde el panel.
- Entrada automática por caída desde un máximo reciente.
- Salida por take-profit, stop-loss o señal de venta.
- Persistencia transaccional en SQLite con migración automática del JSON anterior.
- Historial auditable de compras, ventas, motivos y resultados.
- KPIs de P&L, win rate, profit factor y volumen operado.
- Límites de operaciones, pérdida diaria y cooldown entre compras.
- Sincronización horaria, filtros de símbolo e idempotencia defensiva con Binance.
- Gráficas de velas, volumen, SMA, RSI y marcadores de operaciones.
- Telemetría del motor, parada de emergencia, liveness y readiness.
- Contenedores, HTTPS con Caddy y CI mediante GitHub Actions.

La primera ejecución arranca en `OFF`. Después, el modo confirmado se conserva en SQLite y se restaura tras reinicios o despliegues; `AUTO` continúa operando aunque el navegador esté cerrado. Posiciones, operaciones y bitácora también se conservan. La última señal se recalcula al reanudar el motor.

## Modos de operación

| Modo | Analiza | Permite órdenes manuales | Opera automáticamente |
| --- | :---: | :---: | :---: |
| `OFF` | No | No | No |
| `SENALES` | Sí | Sí | No |
| `AUTO` | Sí | Sí | Sí |

## Arquitectura

```text
Navegador
   │ HTTP + cookie firmada
   ▼
FastAPI / Jinja2 (app/main.py)
   ├── autenticación (app/auth.py)
   ├── estado en memoria (app/bot.py)
   ├── motor periódico (app/engine.py)
   │      └── estrategia SMA + RSI (app/strategy.py)
   └── ejecución y riesgo (app/trader.py)
          ├── SQLite: posición, historial y eventos (app/storage.py)
          └── cliente REST (app/binance_client.py)
                       │
                       ▼
            Binance Spot Testnet / Mainnet
```

| Ruta | Responsabilidad |
| --- | --- |
| `app/main.py` | Aplicación FastAPI, ciclo de vida, vistas y API del panel. |
| `app/config.py` | Lectura centralizada de variables de entorno. |
| `app/auth.py` | Validación de contraseña y cookie de sesión firmada con HMAC. |
| `app/binance_client.py` | Peticiones públicas y firmadas a Binance REST. |
| `app/strategy.py` | Cálculo de SMA, RSI y señal de mercado. |
| `app/engine.py` | Hilo que ejecuta el análisis periódicamente. |
| `app/trader.py` | Órdenes, reglas de riesgo y persistencia de la posición. |
| `app/storage.py` | Repositorio SQLite transaccional, historial y métricas. |
| `app/bot.py` | Modo, última señal y eventos recientes en memoria. |
| `app/templates/` | Panel y pantalla de acceso. |
| `Procfile` | Comando de arranque para un servicio web. |
| `Dockerfile` / `compose*.yaml` | Ejecución reproducible y proxy HTTPS. |
| `tests/` | Pruebas unitarias y de integración. |

## Estrategia actual

El motor descarga 150 velas y analiza sus cierres:

1. Calcula una SMA rápida y una SMA lenta.
2. Detecta cruces alcistas y bajistas.
3. Calcula el RSI mediante suavizado de Wilder.
4. Filtra entradas cuando el RSI indica sobrecompra.
5. También genera señales por sobrecompra o sobreventa.
6. Expone volatilidad reciente y una puntuación heurística de confianza técnica.

En `AUTO`, compra cuando el precio cae `COMPRAR_CAIDA_PCT` desde el máximo de las últimas `CAIDA_VENTANA` velas o cuando la estrategia emite `COMPRAR`. Vende al alcanzar el take-profit, el stop-loss o una señal `VENDER`.

### Modelo cuantitativo del panel

El panel complementa la señal discreta con métricas calculadas sobre los últimos 50 retornos disponibles:

- Probabilidad alcista y bajista implícita mediante una función logística que combina separación SMA normalizada por volatilidad, momentum y RSI.
- Frecuencia alcista observada con suavizado de Laplace, evitando extremos artificiales en muestras pequeñas.
- Retorno medio por vela y momentum normalizado por desviación estándar.
- Incertidumbre mediante entropía binaria de Shannon: cerca de `100%` implica mayor ambigüedad entre ambos escenarios.
- Relación riesgo/beneficio configurada y tasa de aciertos de equilibrio `stop / (take-profit + stop)`.

La probabilidad implícita es un **score heurístico no calibrado**, no la frecuencia histórica de éxito de la estrategia. El panel muestra el tamaño de muestra y esta advertencia de forma permanente. Convertirla en una probabilidad calibrada requiere backtesting fuera de muestra, comisiones, slippage y validación temporal.

> [!IMPORTANT]
> El repositorio no incluye backtesting. Los valores predeterminados son ejemplos, no parámetros recomendados para operar dinero real.

## Requisitos

- Python 3.12.
- Credenciales de Binance Spot Testnet.
- Conexión HTTPS saliente hacia Binance.
- Para producción: una máquina Linux activa y almacenamiento persistente.

## Instalación local

### 1. Preparar Python

```powershell
git clone URL_DE_TU_REPOSITORIO
cd CRYPTOOO
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

En Linux o macOS activa el entorno con `source .venv/bin/activate`.

### 2. Obtener credenciales Testnet

1. Abre <https://testnet.binance.vision/>.
2. Inicia sesión y genera una clave `HMAC_SHA256`.
3. Guarda la API key y el secret; el secret solo se muestra una vez.

### 3. Configurar `.env`

Copia el ejemplo y edita `.env`:

```powershell
Copy-Item .env.example .env
```

Configuración mínima para desarrollo:

```dotenv
BINANCE_API_KEY=tu_api_key_de_testnet
BINANCE_API_SECRET=tu_secret_de_testnet
USE_TESTNET=true
SYMBOL=BTCUSDT
PANEL_PASSWORD=usa_una_contraseña_larga_y_unica
SESSION_SECRET=usa_un_valor_aleatorio_de_al_menos_32_caracteres
COOKIE_SECURE=false
ALLOWED_HOSTS=localhost,127.0.0.1

INTERVAL=1h
SMA_RAPIDA=9
SMA_LENTA=21
RSI_PERIODO=14
RSI_SOBRECOMPRA=70
RSI_SOBREVENTA=30
ANALISIS_SEG=30

ORDEN_USDT=100
COMPRAR_CAIDA_PCT=1.0
TAKE_PROFIT_PCT=2.0
STOP_LOSS_PCT=1.0
CAIDA_VENTANA=24
MAX_OPERACIONES_DIA=10
PERDIDA_MAX_DIARIA_USDT=50
COOLDOWN_SEG=300
```

`.env` está ignorado por Git. No publiques credenciales en código, commits, capturas o logs.

### 4. Iniciar

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abre <http://localhost:8000>. En otro dispositivo de la misma red usa `http://IP_DEL_EQUIPO:8000` y permite el puerto en el firewall local.

## Configuración

| Variable | Valor inicial | Descripción |
| --- | --- | --- |
| `BINANCE_API_KEY` | vacío | API key de Binance. |
| `BINANCE_API_SECRET` | vacío | Secret para firmar peticiones. |
| `USE_TESTNET` | `true` | `true` para Testnet; `false` para Mainnet. |
| `SYMBOL` | `BTCUSDT` | Par Spot analizado y operado. |
| `PANEL_PASSWORD` | `cambia_esto` | Contraseña del panel; debe reemplazarse. |
| `SESSION_SECRET` | contraseña del panel | Secreto independiente para firmar sesiones. |
| `COOKIE_SECURE` | `false` | Debe ser `true` detrás de HTTPS. |
| `ALLOWED_HOSTS` | `*` | Hosts HTTP admitidos, separados por coma. |
| `ENABLE_LIVE_TRADING` | `false` | Segunda confirmación para permitir compras en Mainnet. |
| `INTERVAL` | `1h` | Intervalo de velas aceptado por Binance. |
| `SMA_RAPIDA` / `SMA_LENTA` | `9` / `21` | Periodos de las medias. |
| `RSI_PERIODO` | `14` | Periodo del RSI. |
| `RSI_SOBRECOMPRA` / `RSI_SOBREVENTA` | `70` / `30` | Umbrales del RSI. |
| `ANALISIS_SEG` | `30` | Segundos entre ciclos. |
| `ORDEN_USDT` | `100` | Importe de cada compra. |
| `COMPRAR_CAIDA_PCT` | `1.0` | Caída porcentual que activa una entrada. |
| `TAKE_PROFIT_PCT` | `2.0` | Ganancia porcentual que activa una salida. |
| `STOP_LOSS_PCT` | `1.0` | Pérdida porcentual que activa una salida. |
| `CAIDA_VENTANA` | `24` | Velas usadas para el máximo reciente. |
| `MAX_OPERACIONES_DIA` | `10` | Máximo de compras nuevas por día UTC. |
| `PERDIDA_MAX_DIARIA_USDT` | `50` | Bloquea nuevas compras al alcanzar esta pérdida diaria. |
| `COOLDOWN_SEG` | `300` | Pausa mínima entre compras. |

## API interna

La documentación automática de FastAPI está desactivada. El panel utiliza estas rutas:

| Método | Ruta | Requiere sesión | Uso |
| --- | --- | :---: | --- |
| `GET` | `/login` | No | Pantalla de acceso. |
| `POST` | `/api/login` | No | Inicio de sesión. |
| `POST` | `/api/logout` | No | Cierre de sesión. |
| `GET` | `/` | Sí | Panel principal. |
| `GET` | `/api/estado` | Sí | Precio, saldos, modo, señal y posición. |
| `POST` | `/api/modo` | Sí | Cambia el modo del bot. |
| `POST` | `/api/orden` | Sí | Envía una orden manual. |
| `GET` | `/api/velas` | Sí | Datos del gráfico. |
| `GET` | `/api/historial` | Sí | Operaciones y rendimiento persistente. |
| `GET` | `/api/historial.csv` | Sí | Exportación CSV segura del historial. |
| `GET` | `/api/configuracion` | Sí | Configuración pública segura del motor. |
| `POST` | `/api/parada` | Sí | Pasa inmediatamente a `OFF` sin liquidar la posición. |
| `GET` | `/healthz` | No | Liveness local para contenedores. |
| `GET` | `/readyz` | No | Readiness de motor y base de datos. |
| `GET` | `/api/salud` | No | Comprueba la conexión con Binance. |

## Despliegue fácil en Railway

Railway es la opción más sencilla para que otra persona pruebe Aurum desde un navegador: no requiere instalar Docker, administrar una VM, configurar SSH ni comprar un dominio. Railway detecta el `Dockerfile`, construye la aplicación y proporciona una URL pública con HTTPS.

> [!IMPORTANT]
> El crédito gratuito sirve para una primera prueba, pero no garantiza operación gratuita e ininterrumpida todos los meses. Revisa el consumo en Railway. Mantén `USE_TESTNET=true` y `ENABLE_LIVE_TRADING=false`: el probador usará fondos ficticios de Binance Spot Testnet.

### 1. Preparar las cuentas

1. Sube este proyecto a un repositorio privado de GitHub.
2. Crea una cuenta en [Railway](https://railway.com/) y enlaza GitHub.
3. Crea o restablece una cuenta de [Binance Spot Testnet](https://testnet.binance.vision/) y genera una API key. Las credenciales de Testnet son distintas de las de Binance real.

El usuario que probará el panel no necesita descargar nada ni conocer las claves de Binance. Solo recibirá la URL de Railway y la contraseña del panel.

### 2. Crear el servicio

En Railway selecciona **New Project → Deploy from GitHub repo**, autoriza el repositorio y elígelo. No añadas una base de datos aparte: Aurum utiliza SQLite en un volumen persistente.

En **Variables → Raw Editor** añade:

```dotenv
ENVIRONMENT=production
LOG_LEVEL=INFO
DATA_DIR=/app/data
BINANCE_API_KEY=TU_API_KEY_DE_TESTNET
BINANCE_API_SECRET=TU_API_SECRET_DE_TESTNET
USE_TESTNET=true
BETA_ONLY=true
ENABLE_LIVE_TRADING=false
SYMBOL=BTCUSDT
PANEL_PASSWORD=UNA_CONTRASENA_LARGA_Y_UNICA
SESSION_SECRET=UNA_CADENA_ALEATORIA_DE_AL_MENOS_48_CARACTERES
COOKIE_SECURE=true
ALLOWED_HOSTS=127.0.0.1,healthcheck.railway.app
RAILWAY_RUN_UID=0
```

No compartas estas variables ni las guardes en Git. `RAILWAY_RUN_UID=0` permite escribir en el volumen que Railway monta como propietario `root`; el contenedor local continúa usando el usuario sin privilegios `aurum`.

### 3. Conservar el historial

En el lienzo del proyecto selecciona el servicio, añade un **Volume** y establece como punto de montaje:

```text
/app/data
```

Sin este volumen, el historial SQLite se perderá cuando Railway reemplace el contenedor.

### 4. Publicar la URL

1. En **Settings → Healthcheck Path** escribe `/healthz`.
2. Espera a que el primer despliegue finalice correctamente.
3. En **Settings → Networking → Public Networking** pulsa **Generate Domain**.
4. Copia el dominio asignado, por ejemplo `aurum-production.up.railway.app`.
5. Sustituye `ALLOWED_HOSTS` por `127.0.0.1,aurum-production.up.railway.app,healthcheck.railway.app`, usando tu dominio real. Railway volverá a desplegar el servicio.
6. Abre `https://TU-DOMINIO`, inicia sesión con `PANEL_PASSWORD` y confirma que la interfaz muestre **TESTNET** y **Mainnet bloqueado**.

Para la prueba comparte únicamente la URL y la contraseña del panel. La misma instancia, saldo ficticio e historial serán compartidos por todas las personas que accedan; no publiques esa información en canales abiertos.

## Aplicación Android beta sin anuncios

El repositorio incluye una aplicación Android ligera en `android/`. No incorpora publicidad, analítica ni compras. Utiliza Internet, estado de red y el permiso de notificaciones de Android. La aplicación abre el panel HTTPS de Railway en un WebView endurecido, mantiene la sesión, permite descargar el CSV y envía enlaces externos al navegador.

Las compras, ventas, cambios de modo, paradas de riesgo y fallos del motor llegan como notificaciones nativas incluso con la interfaz cerrada. La notificación no ejecuta órdenes: informa de un evento que el servidor ya persistió. El APK y el backend permanecen bloqueados en Binance Spot Testnet mediante `BETA_ONLY=true`.

La interfaz web cambia automáticamente según el dispositivo:

- Tablet horizontal: mercado y controles en dos columnas.
- Tablet vertical: mercado, modo, posición y señal aparecen primero; reportes e historial después.
- Móvil: una columna, controles táctiles de al menos 44 px, gráficas compactas y tablas desplazables.
- Se respetan rotación, áreas seguras, zoom del sistema y navegación atrás de Android.

### Activar las notificaciones nativas

1. Crea un proyecto en Firebase y registra una aplicación Android con el paquete `com.aurum.trading`. Google Analytics no es necesario.
2. Descarga `google-services.json`. No lo subas al repositorio. Conviértelo a base64 en PowerShell:

   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("google-services.json"))
   ```

3. En GitHub abre **Settings → Secrets and variables → Actions → Secrets** y crea `FIREBASE_GOOGLE_SERVICES_JSON_BASE64` con el resultado.
4. En Firebase abre **Project settings → Service accounts**, genera una clave privada y guárdala fuera del repositorio. Convierte ese segundo JSON a base64 con el mismo comando.
5. En Railway añade `FCM_SERVICE_ACCOUNT_JSON` con el segundo valor base64 y confirma `BETA_ONLY=true` y `USE_TESTNET=true`.
6. Redespliega Railway. Instala el APK nuevo, acepta el permiso de notificaciones e inicia sesión una vez para registrar el dispositivo.

Los dos archivos tienen propósitos distintos: `google-services.json` identifica la app durante la compilación; la cuenta de servicio autoriza a Railway para enviar mensajes. Nunca deben compartirse ni confirmarse en Git.

### Generar el APK sin instalar Android Studio

1. En GitHub abre **Settings → Secrets and variables → Actions → Variables**.
2. Crea `AURUM_URL` con la URL HTTPS de Railway. Si conservas `https://web-production-93f88c.up.railway.app`, el proyecto ya la usa como valor predeterminado.
3. Abre **Actions → Android APK → Run workflow**. Un cambio dentro de `android/` también inicia la compilación automáticamente.
4. Cuando finalice, abre la ejecución y descarga el artefacto `aurum-testnet-beta`.
5. Descomprime `app-debug.apk`, transfiérelo a la tablet y autoriza temporalmente **Instalar aplicaciones desconocidas** para el gestor de archivos utilizado.

El APK debug está firmado automáticamente por Android y es apropiado para pruebas privadas. Para distribuir en Google Play se debe generar un Android App Bundle firmado con un keystore privado y aplicar el proceso de publicación de Play Console.

### Coste y disponibilidad

- Railway ofrece una prueba inicial con crédito y después un plan Free con un crédito mensual reducido. La aplicación puede consumirlo antes de acabar el mes.
- Si necesitas continuidad predecible, el plan Hobby incluye una cuota mensual que se aplica al consumo.
- En una prueba limitada, Railway puede restringir conexiones externas; enlazar una cuenta de GitHub verificable o usar un plan de pago evita que esa restricción impida conectar con Binance.
- Los volúmenes del Trial/Free tienen capacidad limitada y los datos de una prueba vencida no deben considerarse una copia de seguridad.
- En Trial/Free no está disponible el reinicio ilimitado. Revisa los logs y configura **Restart Policy: On Failure**.

## Despliegue gratuito 24/7 en Oracle Cloud

Si el objetivo posterior es mantener el motor activo continuamente sin depender del pequeño crédito mensual de Railway, la alternativa es una VM **Oracle Cloud Always Free**. Requiere más administración, pero puede permanecer encendida dentro de los límites gratuitos. Oracle puede solicitar una tarjeta para verificar la identidad y puede existir falta temporal de capacidad en una región.

Documentación oficial: [recursos Always Free de Oracle Cloud](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

### Topología recomendada

```text
Internet
   │ HTTPS
   ▼
Caddy (HTTPS automático)
   │ red privada de Docker
   ▼
Aurum + Uvicorn (1 contenedor / 1 worker)
   ├── /opt/aurum/.env
   └── volumen aurum_data/aurum.db
```

### 1. Crear la VM

En Oracle Cloud crea una instancia marcada como **Always Free eligible**:

- Ubuntu 24.04 o 22.04.
- Forma `VM.Standard.A1.Flex` o una Always Free disponible.
- 1 OCPU y memoria suficiente para la aplicación.
- IP pública reservada si asociarás un dominio.
- Puerto 22 limitado a tu IP; 80/443 únicamente para HTTPS.

### 2. Instalar Docker y Aurum

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo mkdir -p /opt/aurum
sudo chown "$USER":"$USER" /opt/aurum
git clone URL_DE_TU_REPOSITORIO /opt/aurum
cd /opt/aurum
cp .env.example .env
nano .env
```

En producción configura como mínimo `ENVIRONMENT=production`, `COOKIE_SECURE=true`, `ALLOWED_HOSTS=tu-dominio`, las credenciales, una contraseña fuerte y un `SESSION_SECRET` aleatorio. Conserva `USE_TESTNET=true` y `ENABLE_LIVE_TRADING=false` durante la validación.

### 3. Arrancar con HTTPS y reinicio automático

Apunta tu dominio a la IP pública y añade `DOMAIN=tu-dominio` al `.env`. Después ejecuta:

```bash
docker compose -f compose.yaml -f compose.production.yaml up -d --build
docker compose -f compose.yaml -f compose.production.yaml ps
docker compose -f compose.yaml -f compose.production.yaml logs -f aurum
```

> [!CAUTION]
> Usa exactamente **un worker**. Cada proceso inicia su propio motor y varios workers podrían analizar y enviar órdenes duplicadas.

El `compose.production.yaml` incorpora Caddy, certificados TLS automáticos, cookies seguras, reinicio del proceso, health check y un volumen persistente. Si prefieres instalar Python directamente, se incluye una unidad preparada en `deploy/aurum.service`.

### 4. Verificar

No expongas Uvicorn directamente. Comprueba primero la salud de los contenedores y luego abre `https://tu-dominio`:

Comprueba el servicio desde la propia VM:

```bash
docker compose -f compose.yaml -f compose.production.yaml ps
curl https://tu-dominio/healthz
```

### Actualizaciones

```bash
cd /opt/aurum
git pull --ff-only
docker compose -f compose.yaml -f compose.production.yaml up -d --build
docker compose -f compose.yaml -f compose.production.yaml logs --tail=100 aurum
```

La base `aurum.db` permanece en el volumen `aurum_data`. Debes incluir ese volumen en tus copias de seguridad.

## Seguridad operativa

- Usa Testnet hasta validar completamente el flujo.
- Crea una API key exclusiva para Aurum.
- Habilita solo lectura y Spot Trading; **deshabilita retiros**.
- Restringe la API key por IP cuando sea posible.
- Usa una contraseña larga y única para el panel.
- Publica el panel solo mediante HTTPS o una red privada.
- Ejecuta una sola instancia y un solo worker.
- Revisa logs, posición y saldo después de reiniciar o actualizar.
- Haz copias de seguridad del volumen SQLite `aurum_data`.
- Añade alertas externas antes de considerar Mainnet.

## Limitaciones conocidas

- La posición local no se reconcilia automáticamente con Binance.
- Una orden ejecutada pero no guardada puede dejar estados divergentes.
- SQLite está diseñado para una sola instancia; no proporciona alta disponibilidad distribuida.
- El modo se restaura desde SQLite al reiniciar; una corrupción o pérdida del volumen puede impedir esa continuidad.
- No hay reconciliación periódica del saldo, órdenes abiertas e historial remoto.
- El P&L no modela por separado comisiones, slippage ni conversiones de fees.
- No existe todavía backtesting histórico ni validación estadística de la estrategia.
- No hay alertas por Telegram, correo o push.
- Las librerías visuales se cargan desde CDN y requieren acceso a Internet en el navegador.

Desplegar el proceso 24/7 mejora su disponibilidad, pero no convierte por sí solo el sistema en una plataforma de trading tolerante a fallos.

## Hoja de ruta

- [x] Panel, autenticación y conexión a Binance Testnet.
- [x] Estrategia SMA/RSI y motor periódico.
- [x] Órdenes manuales y modo automático con riesgo básico.
- [x] Validación estricta de producción y bloqueo adicional de Mainnet.
- [x] Logs, eventos persistentes y estado observable del motor.
- [x] SQLite transaccional, historial y métricas de rendimiento.
- [x] Pruebas unitarias, integración y CI.
- [x] Docker, health checks, volumen persistente y HTTPS con Caddy.
- [x] Rate limiting, cookies endurecidas y hosts permitidos.
- [ ] Reconciliación completa con Binance y recuperación de posiciones divergentes.
- [ ] Backtesting con comisiones, slippage y comparación de estrategias.
- [x] Exportación CSV del historial.
- [ ] Alertas externas.

## Descargo de responsabilidad

Aurum se distribuye con fines educativos. Tú eres responsable de revisar el código, proteger las credenciales, cumplir las reglas de Binance y la normativa aplicable, y asumir cualquier pérdida derivada de su uso.
