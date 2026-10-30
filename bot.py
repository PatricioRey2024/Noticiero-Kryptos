import json
import os
import urllib.request


def send_message(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    topic_id = os.environ["TELEGRAM_TOPIC_ID"]

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "message_thread_id": int(topic_id),
        "text": text,
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
    send_message(
        "✅ NotiKrypto está conectado correctamente.\n\n"
        "Este mensaje fue enviado al tema «Info diaria».\n\n"
        "La próxima etapa será conectar las fuentes de noticias."
    )


if __name__ == "__main__":
    main()
