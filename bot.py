import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime


FED_RSS_URL = "https://www.federalreserve.gov/feeds/press_all.xml"
COINBASE_INCIDENTS_URL = (
    "https://status.coinbase.com/api/v2/incidents/unresolved.json"
)
BLS_FEEDS = [
    (
        "BLS - Inflación CPI",
        "https://www.bls.gov/feed/cpi.rss",
    ),
    (
        "BLS - Empleo",
        "https://www.bls.gov/feed/empsit.rss",
    ),
]
STATE_FILE = "state.json"
GEMINI_MODEL = "gemini-3.5-flash-lite"
MAX_PROCESSED_IDS = 200


def http_get_json(url, headers=None):
    request = urllib.request.Request(
        url,
        headers=headers or {},
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def read_federal_reserve_news():
    request = urllib.request.Request(
        FED_RSS_URL,
        headers={
            "User-Agent": os.environ["SEC_USER_AGENT"],
            "Accept": "application/rss+xml, application/xml",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read()

    root = ET.fromstring(content)
    item = root.find("./channel/item")

    if item is None:
        return []

    title = item.findtext("title", default="Sin título").strip()
    link = item.findtext("link", default="").strip()
    published = item.findtext("pubDate", default="").strip()

    if published:
        try:
            published = parsedate_to_datetime(published).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
        except ValueError:
            pass

    news_id = f"federal_reserve:{link or title}"

    return [
        {
            "id": news_id,
            "source": "Federal Reserve",
            "title": title,
            "link": link,
            "published": published,
            "details": "",
        }
    ]


def read_coinbase_incidents():
    data = http_get_json(COINBASE_INCIDENTS_URL)
    incidents = []

    for incident in data.get("incidents", []):
        incident_id = incident.get("id", "")
        incident_name = incident.get("name", "Incidente en Coinbase")
        incident_status = incident.get("status", "")
        incident_impact = incident.get("impact", "")
        updates = incident.get("incident_updates", [])

        if not incident_id or not updates:
            continue

        latest_update = updates[0]
        update_id = latest_update.get("id", "")
        update_body = latest_update.get("body", "")
        updated_at = latest_update.get("updated_at", "")
        shortlink = incident.get("shortlink", "")

        news_id = f"coinbase:{incident_id}:{update_id}"

        details = (
            f"Estado: {incident_status}\n"
            f"Impacto declarado: {incident_impact}\n"
            f"Actualización: {update_body}"
        )

        print(
            f"Coinbase detectado: {incident_name} | "
            f"Estado: {incident_status} | "
            f"Impacto: {incident_impact}"
        )

        incidents.append(
            {
                "id": news_id,
                "source": "Coinbase Status",
                "title": incident_name,
                "link": shortlink or "https://status.coinbase.com/",
                "published": updated_at,
                "details": details,
            }
        )

    print(
        f"Coinbase Status: {len(incidents)} incidentes abiertos encontrados."
    )

    return incidents

    
    def read_bls_news():
        news = []
    
        headers = {
            "User-Agent": os.environ["SEC_USER_AGENT"],
            "Accept": "application/rss+xml, application/xml",
        }
    
        for source_name, feed_url in BLS_FEEDS:
            request = urllib.request.Request(
                feed_url,
                headers=headers,
            )
    
            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read()
    
            root = ET.fromstring(content)
            item = root.find("./channel/item")
    
            if item is None:
                continue
    
            title = item.findtext("title", default="Sin título").strip()
            link = item.findtext("link", default="").strip()
            published = item.findtext("pubDate", default="").strip()
            details = item.findtext("description", default="").strip()
    
            if published:
                try:
                    published = parsedate_to_datetime(published).strftime(
                        "%Y-%m-%d %H:%M UTC"
                    )
                except ValueError:
                    pass
    
            news_id = f"bls:{link or title}"
    
            news.append(
                {
                    "id": news_id,
                    "source": source_name,
                    "title": title,
                    "link": link,
                    "published": published,
                    "details": details,
                }
            )
    
        print(f"BLS: {len(news)} comunicados encontrados.")
    
        return news


def collect_news():
    news = []

    try:
        news.extend(read_federal_reserve_news())
    except urllib.error.HTTPError as error:
        print(
            f"Federal Reserve no disponible temporalmente: "
            f"HTTP {error.code}"
        )
    except Exception as error:
        print(f"Error consultando Federal Reserve: {error}")

    try:
        news.extend(read_coinbase_incidents())
    except urllib.error.HTTPError as error:
        print(
            f"Coinbase Status no disponible temporalmente: "
            f"HTTP {error.code}"
        )
    except Exception as error:
        print(f"Error consultando Coinbase Status: {error}")

    try:
        news.extend(read_bls_news())
    except urllib.error.HTTPError as error:
        print(
            f"BLS no disponible temporalmente: "
            f"HTTP {error.code}"
        )
    except Exception as error:
        print(f"Error consultando BLS: {error}")

    return news


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"processed_ids": []}

    with open(STATE_FILE, "r", encoding="utf-8") as file:
        state = json.load(file)

    state.setdefault("processed_ids", [])
    return state


def save_state(state):
    state["processed_ids"] = state["processed_ids"][-MAX_PROCESSED_IDS:]

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def analyze_news(news):
    api_key = os.environ["GEMINI_API_KEY"]
    encoded_key = urllib.parse.quote(api_key, safe="")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={encoded_key}"
    )

    prompt = f"""
Analizá esta información para un noticiero financiero y cripto.

Fuente:
{news["source"]}

Título:
{news["title"]}

Fecha:
{news["published"]}

Detalles:
{news["details"]}

Enlace:
{news["link"]}

Devolvé únicamente un JSON válido con estos campos:
{{
  "relevance": "ALTA, MEDIA, BAJA o DESCARTAR",
  "title_es": "título formal en español",
  "summary_es": "resumen formal y breve en español",
  "impact_es": "impacto potencial en el mercado"
}}

Criterios:

ALTA:
- interrupción grave;
- retiros o depósitos suspendidos;
- hackeo o incidente de seguridad;
- crisis de liquidez;
- decisión importante de tasas;
- sanción relevante;
- riesgo financiero amplio;
- hecho con posible impacto significativo en criptomonedas o mercados.

MEDIA:
- incidente operativo relevante;
- cambio regulatorio sectorial;
- problema que afecte a una parte importante de los usuarios;
- hecho que merezca seguimiento del mercado.

BAJA:
- mantenimiento menor;
- incidente limitado;
- decisión administrativa puntual;
- comunicado sin efecto amplio.

DESCARTAR:
- información rutinaria;
- promociones;
- eventos menores;
- información sin impacto financiero identificable.

Reglas editoriales:
- Escribí en español formal y natural.
- No uses la frase "por qué importa".
- Usá el encabezado conceptual "Impacto potencial en el mercado".
- No inventes datos.
- No presentes una declaración de una empresa como una confirmación independiente.
- Si la fuente es una empresa involucrada, indicá que se trata de un comunicado oficial de esa entidad.
- Si no hay impacto directo sobre criptomonedas, indicá esa limitación.
- No incluyas emojis dentro del JSON.
- Devolvé únicamente el JSON.
"""

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt,
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    result = None

    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            if error.code != 503 or attempt == 2:
                raise

            wait_seconds = 5 * (attempt + 1)
            print(
                "Gemini no está disponible temporalmente. "
                f"Reintento en {wait_seconds} segundos."
            )
            time.sleep(wait_seconds)

    if result is None:
        raise RuntimeError("Gemini no devolvió una respuesta.")

    candidates = result.get("candidates", [])

    if not candidates:
        raise RuntimeError("Gemini no devolvió una respuesta.")

    generated_text = candidates[0]["content"]["parts"][0]["text"].strip()
    content = json.loads(generated_text)

    required_fields = {
        "relevance",
        "title_es",
        "summary_es",
        "impact_es",
    }

    if not required_fields.issubset(content):
        raise RuntimeError("La respuesta de Gemini no tiene el formato esperado.")

    content["relevance"] = content["relevance"].upper().strip()

    if content["relevance"] not in {"ALTA", "MEDIA", "BAJA", "DESCARTAR"}:
        raise RuntimeError("Gemini devolvió una clasificación no válida.")

    return content


def send_message(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    topic_id = os.environ["TELEGRAM_TOPIC_ID"]

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "message_thread_id": int(topic_id),
        "text": text,
        "disable_web_page_preview": False,
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(result)


def build_message(news, analysis):
    company_notice = ""

    if news["source"] == "Coinbase Status":
        company_notice = (
            "⚖️ Estado de la información\n\n"
            "Comunicado oficial de Coinbase Status.\n\n"
        )

    return (
        "🔴 COMUNICADO OFICIAL\n\n"
        "📰 Resumen del acontecimiento\n\n"
        f"{analysis['title_es']}\n\n"
        "📝 Síntesis\n\n"
        f"{analysis['summary_es']}\n\n"
        "📊 Impacto potencial en el mercado\n\n"
        f"{analysis['impact_es']}\n\n"
        f"{company_notice}"
        "🕐 Fecha de publicación\n\n"
        f"{news['published']}\n\n"
        "🏛️ Fuente\n\n"
        f"{news['source']}\n\n"
        "🔗 Documento oficial\n\n"
        f"{news['link']}"
    )


def main():
    state = load_state()
    news_items = collect_news()

    if not news_items:
        print("No se encontraron noticias o incidentes nuevos.")
        return

    processed_any = False

    for news in news_items:
        if news["id"] in state["processed_ids"]:
            continue

        try:
            analysis = analyze_news(news)
        except urllib.error.HTTPError as error:
            if error.code == 503:
                print(
                    "Gemini no está disponible. "
                    "La noticia queda pendiente para otra ejecución."
                )
                return
            raise

        relevance = analysis["relevance"]

        state["processed_ids"].append(news["id"])
        save_state(state)
        processed_any = True

        if relevance in {"BAJA", "DESCARTAR"}:
            print(
                f"{news['source']}: noticia no publicada. "
                f"Nivel de relevancia: {relevance}."
            )
            continue

        message = build_message(news, analysis)
        send_message(message)

        print(
            f"{news['source']}: noticia publicada. "
            f"Nivel de relevancia: {relevance}."
        )

    if not processed_any:
        print("No hay noticias nuevas para procesar.")


if __name__ == "__main__":
    main()
