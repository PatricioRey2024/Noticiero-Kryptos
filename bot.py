import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime


SEC_RSS_URL = "https://www.sec.gov/rss/news/press.xml"


def read_latest_sec_news():
    request = urllib.request.Request(
        SEC_RSS_URL,
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
        raise RuntimeError("El RSS de la SEC no devolvió noticias.")

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

    return title, link, published


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
    title, link, published = read_latest_sec_news()

    message = (
        "🟠 COMUNICADO OFICIAL\n\n"
        f"📰 {title}\n\n"
        f"🕐 Publicado: {published}\n"
        f"🌐 Fuente: SEC\n"
        f"🔗 {link}"
    )

    send_message(message)


if __name__ == "__main__":
    main()
