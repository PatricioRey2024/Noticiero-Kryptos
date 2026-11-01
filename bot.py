import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


FED_RSS_URL = "https://www.federalreserve.gov/feeds/press_all.xml"
TREASURY_RSS_URL = "https://home.treasury.gov/rss.xml"
COINBASE_INCIDENTS_URL = "https://status.coinbase.com/api/v2/incidents/unresolved.json"
BINANCE_URL = (
    "https://www.binance.com/bapi/composite/v1/public/"
    "cms/article/catalog/list/query"
)
CMC_URL = "https://pro-api.coinmarketcap.com/v3/cryptocurrency/quotes/latest"

BLS_FEEDS = [
    ("BLS - Inflación CPI", "https://www.bls.gov/feed/cpi.rss"),
    ("BLS - Empleo", "https://www.bls.gov/feed/empsit.rss"),
]

TREASURY_KEYWORDS = (
    "sanctions sanction ofac debt liquidity financial finance "
    "terrorist financing money laundering north korea dprk iran russia "
    "cyber crypto digital asset virtual currency"
).split()

BINANCE_CATALOG_IDS = [49, 161]
BINANCE_KEYWORDS = (
    "security incident hack hacked unauthorized withdrawal withdrawals "
    "deposit deposits suspend suspended suspension security funds stolen "
    "breach exploit wallet retiro retiros depósito depósitos seguridad "
    "incidente hackeo"
).split()

STATE_FILE = "state.json"
GEMINI_MODEL = "gemini-3.5-flash-lite"
MAX_PROCESSED_IDS = 200
MAX_NEWS_AGE_HOURS = 48


def user_agent():
    return os.environ.get(
        "SEC_USER_AGENT",
        "NotiKryptos/1.0 contacto-not-configurado",
    )


def http_get_json(url, headers=None, timeout=30):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_news_datetime(value):
    if not value:
        return None
    value = str(value).strip()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            match = re.search(r"(20\d{2})[-/](\d{2})[-/](\d{2})", value)
            if not match:
                return None
            parsed = datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)),
                tzinfo=timezone.utc,
            )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_recent_news(value):
    parsed = parse_news_datetime(value)
    if parsed is None:
        return False
    age = datetime.now(timezone.utc) - parsed
    return timedelta(0) <= age <= timedelta(hours=MAX_NEWS_AGE_HOURS)


def format_published_date(value):
    parsed = parse_news_datetime(value)
    return (
        parsed.strftime("%Y-%m-%d %H:%M UTC")
        if parsed
        else (value or "Fecha no disponible")
    )


def rss_headers():
    return {
        "User-Agent": user_agent(),
        "Accept": "application/rss+xml, application/xml",
    }


def read_federal_reserve_news():
    request = urllib.request.Request(FED_RSS_URL, headers=rss_headers())
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())
    item = root.find("./channel/item")
    if item is None:
        return []
    title = item.findtext("title", "Sin título").strip()
    link = item.findtext("link", "").strip()
    published = item.findtext("pubDate", "").strip()
    return [{
        "id": f"federal_reserve:{link or title}",
        "source": "Federal Reserve",
        "title": title,
        "link": link,
        "published": published,
        "details": "",
    }]


def read_treasury_news():
    request = urllib.request.Request(TREASURY_RSS_URL, headers=rss_headers())
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())
    candidates = []
    for element in root.iter():
        if element.tag.split("}")[-1] != "item":
            continue
        title = element.findtext("title", "Sin título").strip()
        details = element.findtext("description", "").strip()
        text = f"{title} {details}".lower()
        if not any(keyword in text for keyword in TREASURY_KEYWORDS):
            continue
        link = element.findtext("link", "").strip() or TREASURY_RSS_URL
        published = element.findtext("pubDate", "").strip()
        candidates.append({
            "id": f"treasury:{link or title}",
            "source": "U.S. Treasury",
            "title": title,
            "link": link,
            "published": published,
            "details": details,
        })
    if not candidates:
        print("Treasury: no se encontró un comunicado relevante.")
        return []
    latest = max(
        candidates,
        key=lambda item: parse_news_datetime(item["published"])
        or datetime.min.replace(tzinfo=timezone.utc),
    )
    print(f"Treasury detectado: {latest['title']}")
    return [latest]


def read_coinbase_incidents():
    data = http_get_json(COINBASE_INCIDENTS_URL)
    incidents = []
    for incident in data.get("incidents", []):
        incident_id = incident.get("id", "")
        updates = incident.get("incident_updates", [])
        if not incident_id or not updates:
            continue
        latest = updates[0]
        name = incident.get("name", "Incidente en Coinbase")
        status = incident.get("status", "")
        impact = incident.get("impact", "")
        update_id = latest.get("id", "")
        details = (
            f"Estado: {status}\n"
            f"Impacto declarado: {impact}\n"
            f"Actualización: {latest.get('body', '')}"
        )
        print(
            f"Coinbase detectado: {name} | Estado: {status} | Impacto: {impact}"
        )
        incidents.append({
            "id": f"coinbase:{incident_id}:{update_id}",
            "source": "Coinbase Status",
            "title": name,
            "link": incident.get("shortlink", "https://status.coinbase.com/"),
            "published": latest.get("updated_at", ""),
            "details": details,
        })
    print(f"Coinbase Status: {len(incidents)} incidentes abiertos encontrados.")
    return incidents


def normalize_binance_title(title):
    value = unicodedata.normalize("NFKD", title)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def resolve_binance_url(url, headers):
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.geturl()
    except Exception:
        return url


def read_binance_news():
    news = []
    seen = set()
    headers = {
        "User-Agent": user_agent(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    for catalog_id in BINANCE_CATALOG_IDS:
        query = urllib.parse.urlencode({
            "catalogId": catalog_id, "pageNo": 1, "pageSize": 20,
        })
        data = http_get_json(f"{BINANCE_URL}?{query}", headers=headers)
        articles = (data.get("data") or {}).get("articles") or []
        for article in articles:
            title = (article.get("title") or "Anuncio de Binance").strip()
            if not any(word in title.lower() for word in BINANCE_KEYWORDS):
                continue
            code = article.get("code", "")
            link = article.get("shortLink", "")
            if not link and code:
                link = f"https://www.binance.com/en/support/announcement/{code}"
            link = resolve_binance_url(
                link or "https://www.binance.com/en/support/announcement",
                headers,
            )
            canonical = f"binance:{link}|{normalize_binance_title(title)}"
            if canonical in seen:
                continue
            seen.add(canonical)
            published = article.get("releaseDate") or article.get("publishDate") or ""
            if isinstance(published, (int, float)):
                published = datetime.fromtimestamp(
                    published / 1000, tz=timezone.utc
                ).isoformat()
            if not published:
                match = re.search(r"(20\d{2})[-/](\d{2})[-/](\d{2})", title)
                if match:
                    published = "-".join(match.groups())
            if not published:
                print(f"Binance: anuncio sin fecha omitido: {title}")
                continue
            news.append({
                "id": canonical,
                "legacy_ids": [f"binance:{article.get('id', '')}"],
                "source": "Binance",
                "title": title,
                "link": link,
                "published": published,
                "details": "Comunicado oficial publicado por Binance.",
            })
            print(f"Binance detectado: {title}")
    security = [item for item in news if "security incident" in item["title"].lower()]
    if len(security) > 1:
        latest = max(
            security,
            key=lambda item: parse_news_datetime(item["published"])
            or datetime.min.replace(tzinfo=timezone.utc),
        )
        news = [item for item in news if item not in security] + [latest]
        print("Binance: se conserva únicamente la actualización más reciente del incidente.")
    print(f"Binance: {len(news)} anuncios relevantes encontrados.")
    return news


def read_coinmarketcap_market():
    api_key = os.environ["CMC_API_KEY"]
    query = urllib.parse.urlencode({
        "slug": "bitcoin,ethereum,solana,near-protocol",
        "convert": "USD",
    })
    request = urllib.request.Request(
        f"{CMC_URL}?{query}",
        headers={"Accept": "application/json", "X-CMC_PRO_API_KEY": api_key},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    data = result.get("data") or {}
    if not data:
        raise RuntimeError("CoinMarketCap no devolvió datos de mercado.")
    print(f"CoinMarketCap: cotizaciones actuales recibidas para {len(data)} activos.")
    return {"quotes": data}


def format_coinmarketcap_snapshot(market_data):
    lines = ["📊 Estado actual del mercado cripto", ""]
    names = {"1": "BTC", "1027": "ETH", "5426": "SOL", "6535": "NEAR"}
    for asset_id, asset in market_data.get("quotes", {}).items():
        quote = asset.get("quote", {})
        if isinstance(quote, list):
            quote = quote[0] if quote else {}
        usd = quote.get("USD", {})
        symbol = names.get(str(asset_id), asset.get("symbol", "ACTIVO"))
        price = usd.get("price", "N/D")
        lines.append(f"{symbol}: ${price}")
        lines.append(
            f"1 h: {usd.get('percent_change_1h', 'N/D')}% · "
            f"24 h: {usd.get('percent_change_24h', 'N/D')}% · "
            f"7 d: {usd.get('percent_change_7d', 'N/D')}% · "
            f"30 d: {usd.get('percent_change_30d', 'N/D')}%"
        )
        lines.append("")
    return "\n".join(lines)


def read_bls_news():
    news = []
    for source_name, feed_url in BLS_FEEDS:
        request = urllib.request.Request(feed_url, headers=rss_headers())
        with urllib.request.urlopen(request, timeout=30) as response:
            root = ET.fromstring(response.read())
        entries = [
            element for element in root.iter()
            if element.tag.split("}")[-1] in {"item", "entry"}
        ]
        if not entries:
            print(f"{source_name}: no se encontró ningún comunicado.")
            continue
        item = entries[0]
        values = {}
        link = ""
        for child in item:
            name = child.tag.split("}")[-1]
            if name in {"title", "pubDate", "published", "updated", "date", "description", "summary", "content"}:
                values.setdefault(name, (child.text or "").strip())
            if name == "link":
                link = (child.attrib.get("href", "") or child.text or "").strip()
        title = values.get("title") or "Sin título"
        published = next((values.get(k) for k in ("pubDate", "published", "updated", "date") if values.get(k)), "")
        details = values.get("description") or values.get("summary") or values.get("content") or ""
        news.append({
            "id": f"bls:{link or title}", "source": source_name, "title": title,
            "link": link or feed_url, "published": published, "details": details,
        })
        print(f"{source_name}: comunicado encontrado.")
    print(f"BLS: {len(news)} comunicados encontrados.")
    return news


def collect_news():
    news = []
    sources = [
        ("Federal Reserve", read_federal_reserve_news),
        ("Treasury", read_treasury_news),
        ("Coinbase Status", read_coinbase_incidents),
        ("Binance", read_binance_news),
        ("BLS", read_bls_news),
    ]
    for label, reader in sources:
        try:
            news.extend(reader())
        except urllib.error.HTTPError as error:
            print(f"{label} no disponible temporalmente: HTTP {error.code}")
        except Exception as error:
            print(f"Error consultando {label}: {error}")
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
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={urllib.parse.quote(api_key, safe='')}"
    )
    prompt = f"""Analizá esta noticia para un noticiero financiero y cripto.
Fuente: {news['source']}
Título: {news['title']}
Fecha: {news['published']}
Detalles: {news['details']}
Enlace: {news['link']}

Devolvé únicamente JSON válido con relevance (ALTA, MEDIA, BAJA o DESCARTAR),
title_es, summary_es e impact_es. Escribí en español formal y natural.
Usá el concepto 'Impacto potencial en el mercado'. No inventes datos.
ALTA: hackeo, retiros suspendidos, crisis de liquidez, sanción relevante,
decisión fuerte de tasas o riesgo financiero amplio.
MEDIA: incidente operativo relevante, regulación sectorial o hecho que merezca seguimiento.
BAJA: mantenimiento menor o comunicado administrativo puntual.
DESCARTAR: promoción, listado, airdrop o información sin impacto identificable.
"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
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
            wait = 5 * (attempt + 1)
            print(f"Gemini no está disponible temporalmente. Reintento en {wait} segundos.")
            time.sleep(wait)
    if not result or not result.get("candidates"):
        raise RuntimeError("Gemini no devolvió una respuesta.")
    text = result["candidates"][0]["content"]["parts"][0]["text"].strip()
    content = json.loads(text)
    required = {"relevance", "title_es", "summary_es", "impact_es"}
    if not required.issubset(content):
        raise RuntimeError("La respuesta de Gemini no tiene el formato esperado.")
    content["relevance"] = content["relevance"].upper().strip()
    if content["relevance"] not in {"ALTA", "MEDIA", "BAJA", "DESCARTAR"}:
        raise RuntimeError("Gemini devolvió una clasificación no válida.")
    return content


def send_message(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    payload = {
        "chat_id": os.environ["TELEGRAM_CHAT_ID"],
        "message_thread_id": int(os.environ["TELEGRAM_TOPIC_ID"]),
        "text": text,
        "disable_web_page_preview": False,
    }
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result)


def build_message(news, analysis):
    notice = ""
    if news["source"] in {"Coinbase Status", "Binance"}:
        notice = (
            "⚖️ Estado de la información\n\n"
            f"Comunicado oficial de {news['source']}.\n\n"
        )
    return (
        "🔴 COMUNICADO OFICIAL\n\n"
        "📰 Resumen del acontecimiento\n\n"
        f"{analysis['title_es']}\n\n"
        "📝 Síntesis\n\n"
        f"{analysis['summary_es']}\n\n"
        "📊 Impacto potencial en el mercado\n\n"
        f"{analysis['impact_es']}\n\n"
        f"{notice}"
        "🕐 Fecha de publicación\n\n"
        f"{format_published_date(news['published'])}\n\n"
        "🏛️ Fuente\n\n"
        f"{news['source']}\n\n"
        "🔗 Documento oficial\n\n"
        f"{news['link']}"
    )


def main():
    state = load_state()

    try:
        market_data = read_coinmarketcap_market()
        print(format_coinmarketcap_snapshot(market_data))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(f"CoinMarketCap no disponible: HTTP {error.code} — {body}")
    except Exception as error:
        print(f"Error consultando CoinMarketCap: {error}")

    news_items = collect_news()
    if not news_items:
        print("No se encontraron noticias o incidentes nuevos.")
        return

    processed_any = False
    for news in news_items:
        news_id = news["id"]
        legacy_ids = news.get("legacy_ids", [])
        if news_id in state["processed_ids"] or any(
            old_id in state["processed_ids"] for old_id in legacy_ids
        ):
            continue
        if not is_recent_news(news["published"]):
            print(
                f"{news['source']}: comunicado antiguo o sin fecha válida omitido. "
                f"Fecha: {news['published']}"
            )
            state["processed_ids"].append(news_id)
            save_state(state)
            processed_any = True
            continue
        try:
            analysis = analyze_news(news)
        except urllib.error.HTTPError as error:
            if error.code == 503:
                print("Gemini no está disponible. La noticia queda pendiente para otra ejecución.")
                return
            raise
        relevance = analysis["relevance"]
        state["processed_ids"].append(news_id)
        save_state(state)
        processed_any = True
        if relevance in {"BAJA", "DESCARTAR"}:
            print(f"{news['source']}: noticia no publicada. Nivel de relevancia: {relevance}.")
            continue
        send_message(build_message(news, analysis))
        print(f"{news['source']}: noticia publicada. Nivel de relevancia: {relevance}.")
    if not processed_any:
        print("No hay noticias nuevas para procesar.")


if __name__ == "__main__":
    main()
