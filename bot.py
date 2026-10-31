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


def save_state(news):
    state = {
        "last_news_id": news["id"],
        "last_title": news["title"],
        "last_published": news["published"],
    }

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def generate_spanish_content(news):
    api_key = os.environ["GEMINI_API_KEY"]
    encoded_key = urllib.parse.quote(api_key, safe="")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={encoded_key}"
    )

    prompt = f"""
Analizá únicamente este comunicado oficial y devolvé un JSON válido.

Título original:
{news["title"]}

Fecha:
{news["published"]}

Fuente:
Federal Reserve

Enlace:
{news["link"]}

El JSON debe contener exactamente estos campos:
{{
  "title_es": "título traducido al español",
  "summary_es": "resumen formal y breve en español",
  "impact_es": "impacto potencial en el mercado"
}}

Reglas:
- Escribí en español formal y natural.
- No inventes datos.
- No agregues información que no figure en el comunicado.
- Si el hecho no tiene un impacto directo sobre criptomonedas, indicá claramente que no se observa un impacto directo con la información disponible.
- No uses frases como "por qué importa".
- No incluyas emojis dentro del JSON.
- Devolvé únicamente el JSON, sin Markdown ni explicaciones adicionales.
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

    required_fields = {"title_es", "summary_es", "impact_es"}

    if not required_fields.issubset(content):
        raise RuntimeError("La respuesta de Gemini no tiene el formato esperado.")

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
        print("La noticia más reciente ya fue enviada.")
        return

    translated = generate_spanish_content(news)

    message = (
        "🔴 COMUNICADO OFICIAL\n\n"
        "📰 Resumen del acontecimiento\n\n"
        f"{translated['title_es']}\n\n"
        "📝 Síntesis\n\n"
        f"{translated['summary_es']}\n\n"
        "📊 Impacto potencial en el mercado\n\n"
        f"{translated['impact_es']}\n\n"
        "🕐 Fecha de publicación\n\n"
        f"{news['published']}\n\n"
        "🏛️ Fuente\n\n"
        "Federal Reserve\n\n"
        "🔗 Documento oficial\n\n"
        f"{news['link']}"
    )

    send_message(message)
    save_state(news)
    print("Nueva noticia traducida y enviada.")


if __name__ == "__main__":
    main()
