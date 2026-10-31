import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime


RSS_URL = "https://www.federalreserve.gov/feeds/press_all.xml"
STATE_FILE = "state.json"
GEMINI_MODEL = "gemini-3.1-flash-lite"


def read_latest_news():
    request = urllib.request.Request(
        RSS_URL,
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
        raise RuntimeError("El RSS no devolvió ninguna noticia.")

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

    news_id = link or f"{title}|{published}"

    return {
        "id": news_id,
        "title": title,
        "link": link,
        "published": published,
    }


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    with open(STATE_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_state(news, relevance):
    state = {
        "last_news_id": news["id"],
        "last_title": news["title"],
        "last_published": news["published"],
        "last_relevance": relevance,
    }

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
Analizá este comunicado oficial para un noticiero financiero y cripto.

Título original:
{news["title"]}

Fecha:
{news["published"]}

Fuente:
Federal Reserve

Enlace:
{news["link"]}

Devolvé únicamente un JSON válido con estos campos:
{{
  "relevance": "ALTA, MEDIA, BAJA o DESCARTAR",
  "title_es": "título traducido al español",
  "summary_es": "resumen formal y breve en español",
  "impact_es": "impacto potencial en el mercado"
}}

Criterios de relevancia:

ALTA:
- decisión de tasas de interés;
- inflación o empleo con efecto sobre política monetaria;
- crisis de liquidez;
- quiebra o rescate bancario;
- riesgo para la estabilidad financiera;
- regulación importante;
- medida con posible impacto amplio en mercados financieros o criptomonedas.

MEDIA:
- medida relevante para un sector financiero;
- cambio regulatorio de alcance limitado;
- acontecimiento que pueda afectar a una entidad o grupo de activos;
- información que merezca seguimiento del mercado.

BAJA:
- decisión administrativa puntual;
- aprobación rutinaria de una entidad;
- anuncio institucional sin efecto amplio;
- publicación de interés limitado.

DESCARTAR:
- información educativa;
- eventos menores;
- comunicados rutinarios;
- publicaciones sin impacto financiero identificable.

Reglas:
- No clasifiques una noticia como relevante solo porque mencione a un banco o a la Reserva Federal.
- No inventes datos.
- Si no existe un impacto directo sobre criptomonedas, indicá esa limitación claramente.
- Usá español formal y natural.
- No uses la frase "por qué importa".
- No incluyas emojis dentro del JSON.
- Devolvé únicamente el JSON, sin Markdown ni explicaciones.
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

    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))

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


def main():
    news = read_latest_news()
    state = load_state()

    if state.get("last_news_id") == news["id"]:
        print("La noticia más reciente ya fue procesada.")
        return

    analysis = analyze_news(news)
    relevance = analysis["relevance"]

    if relevance in {"BAJA", "DESCARTAR"}:
        save_state(news, relevance)
        print(f"Noticia no publicada. Nivel de relevancia: {relevance}.")
        return

    message = (
        "🔴 COMUNICADO OFICIAL\n\n"
        "📰 Resumen del acontecimiento\n\n"
        f"{analysis['title_es']}\n\n"
        "📝 Síntesis\n\n"
        f"{analysis['summary_es']}\n\n"
        "📊 Impacto potencial en el mercado\n\n"
        f"{analysis['impact_es']}\n\n"
        "🕐 Fecha de publicación\n\n"
        f"{news['published']}\n\n"
        "🏛️ Fuente\n\n"
        "Federal Reserve\n\n"
        "🔗 Documento oficial\n\n"
        f"{news['link']}"
    )

    send_message(message)
    save_state(news, relevance)
    print(f"Nueva noticia publicada. Nivel de relevancia: {relevance}.")


if __name__ == "__main__":
    main()
