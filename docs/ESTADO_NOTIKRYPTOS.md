# Estado completo de Krypto Noticias / NotiKryptos

Última actualización: 2026-11-03

Este archivo resume el estado del bot de noticias cripto para la comunidad Kryptos Club, dónde están los códigos, cómo funciona, qué está activo y qué falta completar.

## 1. Repositorio principal

- Repositorio: [PatricioRey2024/Noticiero-Kryptos](https://github.com/PatricioRey2024/Noticiero-Kryptos)
- Rama productiva: `main`
- Pull Request productivo fusionado: [PR #1](https://github.com/PatricioRey2024/Noticiero-Kryptos/pull/1)
- Pull Request de ampliación macroeconómica: [PR #2](https://github.com/PatricioRey2024/Noticiero-Kryptos/pull/2)
- Rama de desarrollo actual del PR #2: `codex/macro-bea-datos-estructurados`

El PR #1 contiene la versión que ya está funcionando en `main`. El PR #2 todavía está en borrador y no debe considerarse producción hasta completar y validar la integración macroeconómica.

## 2. Ubicación local del proyecto

La copia local utilizada durante el desarrollo se encuentra en:

`<CARPETA_LOCAL_DEL_PROYECTO>`

El archivo de este resumen está guardado en:

`<CARPETA_LOCAL_DEL_PROYECTO>\ESTADO_NOTIKRYPTOS.md`

Si se pierde la copia local, todo el código principal también está respaldado en GitHub.

## 3. Archivos principales del repositorio

### `bot.py`

Archivo principal del bot. Contiene:

- lectura de fuentes RSS y APIs;
- filtro de noticias recientes;
- clasificación con Gemini;
- selección de relevancia `ALTA`, `MEDIA`, `BAJA` o `DESCARTAR`;
- mensajes de alertas;
- informe diario;
- informe semanal;
- lectura de mercados cripto;
- lectura de mercados tradicionales;
- calendario FOMC;
- calendario BLS;
- calendario BEA en el PR #2;
- estructura macroeconómica `previous`, `expected`, `actual` y campos `core` en el PR #2;
- envío a Telegram;
- reintentos ante errores temporales;
- registro de `message_id` y `chat_id`;
- control de noticias procesadas;
- corroboración básica entre fuentes.

En GitHub:

- [bot.py en main](https://github.com/PatricioRey2024/Noticiero-Kryptos/blob/main/bot.py)
- [bot.py del PR #2](https://github.com/PatricioRey2024/Noticiero-Kryptos/blob/codex/macro-bea-datos-estructurados/bot.py)

### `state.json`

Archivo de estado generado y actualizado por GitHub Actions. Guarda:

- identificadores ya procesados;
- noticias publicadas;
- `telegram_message_id`;
- `telegram_chat_id`;
- fecha del envío;
- alertas ya revisadas.

En GitHub:

- [state.json en main](https://github.com/PatricioRey2024/Noticiero-Kryptos/blob/main/state.json)

No se debe borrar ni modificar manualmente sin revisar primero el historial, porque se podrían repetir noticias o perder el registro de entregas.

### `tests/test_bot.py`

Pruebas unitarias del bot. Verifican principalmente:

- compatibilidad con estados antiguos;
- límites del registro de mensajes;
- preservación de fuentes y enlaces;
- formato de los mensajes;
- agenda BEA;
- estados macroeconómicos incompletos en el PR #2.

En GitHub:

- [tests/test_bot.py del PR #2](https://github.com/PatricioRey2024/Noticiero-Kryptos/blob/codex/macro-bea-datos-estructurados/tests/test_bot.py)

### `requirements.txt`

El bot utiliza principalmente la biblioteca estándar de Python y no depende de un paquete externo para sus consultas principales.

### `.github/workflows/`

Contiene los workflows que ejecutan el bot en GitHub Actions.

## 4. Workflows activos

### Alertas

Archivo:

`.github/workflows/notikryptos-alerts.yml`

Funciones:

- ejecución manual;
- ejecución automática cada 15 minutos;
- publica únicamente noticias clasificadas como `ALTA`;
- utiliza el encabezado `NOTIKRYPTOS ALERT`;
- guarda el estado después del envío;
- evita conflictos entre ejecuciones mediante `concurrency` y sincronización de `main`.

En GitHub:

- [Workflow de alertas](https://github.com/PatricioRey2024/Noticiero-Kryptos/actions/workflows/notikryptos-alerts.yml)

### Informe diario

Archivo:

`.github/workflows/notikryptos-daily.yml`

Funciones:

- ejecución manual;
- ejecución automática a las 07:30 de Argentina;
- publica el resumen de mercado cripto;
- publica DXY, oro, WTI, Nasdaq y S&P 500;
- publica Fear & Greed y Altcoin Season cuando están disponibles;
- guarda el estado.

Horario configurado:

`30 10 * * *` UTC = 07:30 ART.

En GitHub:

- [Workflow diario](https://github.com/PatricioRey2024/Noticiero-Kryptos/actions/workflows/notikryptos-daily.yml)

### Informe semanal

Archivo:

`.github/workflows/notikryptos-weekly.yml`

Funciones:

- ejecución manual;
- ejecución automática los lunes a las 08:00 de Argentina;
- resumen de publicaciones de los últimos siete días;
- agenda FOMC;
- agenda BLS;
- agenda BEA en el PR #2;
- campos macroeconómicos estructurados en el PR #2.

Horario configurado:

`0 11 * * 1` UTC = lunes a las 08:00 ART.

En GitHub:

- [Workflow semanal](https://github.com/PatricioRey2024/Noticiero-Kryptos/actions/workflows/notikryptos-weekly.yml)

### Pruebas automáticas del PR #2

Archivo:

`.github/workflows/notikryptos-tests.yml`

Funciones:

- valida sintaxis de `bot.py`;
- ejecuta pruebas unitarias;
- ejecuta `git diff --check`;
- se ejecuta sobre el PR #2.

Última ejecución validada antes de la última ampliación:

- [Workflow de pruebas](https://github.com/PatricioRey2024/Noticiero-Kryptos/actions/runs/41703525925)
- Resultado: `success`.

## 5. Fuentes incorporadas

### Fuentes oficiales y operativas

- Federal Reserve RSS:
  `https://www.federalreserve.gov/feeds/press_all.xml`
- U.S. Treasury RSS:
  `https://home.treasury.gov/rss.xml`
- Coinbase Status API:
  `https://status.coinbase.com/api/v2/incidents/unresolved.json`
- Binance announcements API pública.
- BLS CPI RSS:
  `https://www.bls.gov/feed/cpi.rss`
- BLS Employment RSS:
  `https://www.bls.gov/feed/empsit.rss`
- BLS release calendar:
  `https://www.bls.gov/schedule/{year}/`
- BLS Public Data API:
  `https://api.bls.gov/publicAPI/v1/timeseries/data/`
- Federal Reserve FOMC calendar:
  `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm`
- BEA release schedule:
  `https://www.bea.gov/news/schedule/`
- CoinMarketCap API:
  cotizaciones, Fear & Greed y Altcoin Season.
- Alternative.me:
  fallback de Fear & Greed.
- Yahoo Finance Chart:
  DXY, oro, petróleo WTI, Nasdaq y S&P 500.
- OpenAI News RSS.
- Google AI RSS.
- Microsoft AI RSS.

### Fuente descartada

Stooq fue probado, pero respondió con una página de verificación HTML en lugar de datos CSV. No forma parte del bot.

## 6. Datos de mercado integrados

### Cripto

- BTC.
- ETH.
- SOL.
- NEAR.
- Variación de 1 hora.
- Variación de 24 horas.
- Variación de 7 días.
- Variación de 30 días.

### Mercados tradicionales

- DXY.
- Oro.
- Petróleo WTI.
- Nasdaq.
- S&P 500.

### Sentimiento

- Fear & Greed.
- Altcoin Season Index.

Los datos de mercado son informativos y no constituyen pronósticos.

## 7. Estados editoriales y de verificación

Los mensajes pueden mostrar:

- `✅ CONFIRMADO · fuente oficial`
- `✅ CONFIRMADO · corroborado por más de una fuente`
- `⚖️ COMUNICADO OFICIAL · requiere contexto independiente`
- `🟡 EN VERIFICACIÓN`

El bot no debería presentar como confirmado un consenso de mercado o una interpretación.

## 8. Confirmación de entregas a Telegram

El envío se considera confirmado sólo cuando Telegram responde correctamente al método `sendMessage`.

Se guardan:

- `telegram_message_id`;
- `telegram_chat_id`;
- fecha del mensaje;
- noticia asociada;
- nivel de relevancia.

Pruebas reales ya realizadas:

- alerta Binance: `message_id 675`;
- informe diario: `message_id 677`;
- informe semanal: `message_id 679`.

El informe semanal llegó a Telegram, aunque una ejecución antigua quedó marcada como fallida al intentar hacer `push` de `state.json` después de que otro workflow actualizara `main`. Esa condición fue corregida en los tres workflows mediante sincronización previa de `main`.

## 9. Secretos de GitHub Actions

Los valores reales nunca deben pegarse en el chat ni en el repositorio. Deben estar en:

`GitHub → Settings → Secrets and variables → Actions`

Nombres utilizados:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_TOPIC_ID`
- `SEC_USER_AGENT`
- `GEMINI_API_KEY`
- `CMC_API_KEY`

Si se pierde un secreto, hay que regenerarlo en el proveedor correspondiente y actualizarlo en GitHub. Este archivo no contiene ningún valor secreto.

## 10. Estado productivo actual

La rama `main` contiene la versión operativa del bot con:

- alertas cada 15 minutos;
- informe diario;
- informe semanal;
- fuentes gratuitas configuradas;
- entrega confirmada en Telegram;
- estado persistente en `state.json`.

El PR #2 todavía no está fusionado. Su contenido no está activo en producción hasta que pase las pruebas y sea fusionado.

## 11. Trabajo pendiente del PR #2

- completar lectura del valor anterior por indicador;
- conectar el valor real con el período correcto;
- incorporar valores oficiales BEA;
- incorporar PCE core y deflactor del PIB;
- incorporar consenso externo gratuito y etiquetarlo como no oficial;
- enviar avisos 24 horas y 15 minutos antes;
- enviar actualización al momento de la publicación;
- calcular sorpresa sólo cuando las unidades sean comparables;
- probar la ejecución completa en GitHub Actions;
- revisar el contenido del informe semanal;
- fusionar a `main` sólo después de validar todo.

## 12. Cómo recuperar el proyecto si se pierde la sesión

1. Abrir el repositorio:
   [Noticiero-Kryptos en GitHub](https://github.com/PatricioRey2024/Noticiero-Kryptos)

2. Revisar `main` para la versión productiva.

3. Revisar el [PR #2](https://github.com/PatricioRey2024/Noticiero-Kryptos/pull/2) para la ampliación macroeconómica.

4. Consultar este archivo:
   `ESTADO_NOTIKRYPTOS.md`

5. Revisar los workflows en la pestaña [Actions](https://github.com/PatricioRey2024/Noticiero-Kryptos/actions).

6. No eliminar `state.json` sin revisar antes los registros de mensajes enviados.

7. No copiar secretos al código ni al archivo Markdown.

## 13. Nota sobre la PC local

El bot productivo se ejecuta en GitHub Actions. La computadora puede estar apagada. La PC sólo es necesaria para editar, revisar o administrar el proyecto; no para que los workflows programados se ejecuten.


