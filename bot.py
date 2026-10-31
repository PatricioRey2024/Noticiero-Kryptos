import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime


RSS_URL = "https://www.federalreserve.gov/feeds/press_all.xml"
STATE_FILE = "state.json"


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

    message = (
        "COMUNICADO OFICIAL\n\n"
        "Resumen del acontecimiento\n\n"
        f"{news['title']}\n\n"
        "Fuente y fecha de publicación\n\n"
        f"Federal Reserve — {news['published']}\n\n"
        "Documento oficial\n\n"
        f"{news['link']}"
    )

    send_message(message)
    save_state(news)
    print("Nueva noticia enviada y registrada.")


if __name__ == "__main__":
    main()
