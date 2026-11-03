import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
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
CMC_FEAR_GREED_URL = "https://pro-api.coinmarketcap.com/v3/fear-and-greed/latest"
CMC_ALTCOIN_SEASON_URL = "https://pro-api.coinmarketcap.com/v1/altcoin-season-index/latest"
ALTERNATIVE_ME_FNG_URL = "https://api.alternative.me/fng/?limit=1"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_SCHEDULE_URL = "https://www.bls.gov/schedule/{year}/"

BLS_FEEDS = [
    ("BLS - Inflación CPI", "https://www.bls.gov/feed/cpi.rss"),
    ("BLS - Empleo", "https://www.bls.gov/feed/empsit.rss"),
]

OFFICIAL_TECH_FEEDS = [
    ("OpenAI News", "https://openai.com/news/rss.xml"),
    ("Google AI", "https://blog.google/technology/ai/rss/"),
    ("Microsoft AI", "https://www.microsoft.com/en-us/microsoft-cloud/blog/feed//"),
]

YAHOO_MARKET_SYMBOLS = {
    "DXY": "DX-Y.NYB",
    "Oro": "GC=F",
    "Petróleo WTI": "CL=F",
    "Nasdaq": "^IXIC",
    "S&P 500": "^GSPC",
}

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
TELEGRAM_MAX_ATTEMPTS = 3
TELEGRAM_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RUN_MODE = os.environ.get("RUN_MODE", "manual").strip().lower()


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
    quotes = market_data.get("quotes", {})
    if isinstance(quotes, list):
        assets = [(asset.get("id", ""), asset) for asset in quotes]
    else:
        assets = quotes.items()

    for asset_id, asset in assets:
        quote = asset.get("quote", {}) if isinstance(asset, dict) else {}
        if isinstance(quote, list):
            quote = quote[0] if quote else {}
        if isinstance(quote, dict) and "USD" in quote:
            usd = quote.get("USD", {})
        else:
            usd = quote
        if isinstance(usd, list):
            usd = usd[0] if usd else {}
        if not isinstance(usd, dict):
            usd = {}
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


def read_cmc_sentiment():
    api_key = os.environ["CMC_API_KEY"]
    headers = {"Accept": "application/json", "X-CMC_PRO_API_KEY": api_key}
    sentiment = {}
    for name, url in (
        ("fear_greed", CMC_FEAR_GREED_URL),
        ("altcoin_season", CMC_ALTCOIN_SEASON_URL),
    ):
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        data = result.get("data")
        if not data:
            raise RuntimeError(f"CoinMarketCap no devolvió datos para {name}.")
        sentiment[name] = data
    return sentiment


def read_alternative_me_fear_greed():
    request = urllib.request.Request(
        ALTERNATIVE_ME_FNG_URL,
        headers={"Accept": "application/json", "User-Agent": user_agent()},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    data = result.get("data") or []
    if not data:
        raise RuntimeError("Alternative.me no devolvió Fear & Greed.")
    latest = data[0]
    return {
        "value": latest.get("value"),
        "value_classification": latest.get("value_classification"),
        "update_time": latest.get("timestamp"),
        "source": "Alternative.me",
    }


def read_yahoo_market_data():
    market = {}
    for label, symbol in YAHOO_MARKET_SYMBOLS.items():
        request = urllib.request.Request(
            f"{YAHOO_CHART_URL}{urllib.parse.quote(symbol, safe='')}?range=5d&interval=1d",
            headers={"Accept": "application/json", "User-Agent": user_agent()},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        chart = (result.get("chart") or {}).get("result") or []
        if not chart:
            raise RuntimeError(f"Yahoo Finance no devolvió datos para {label}.")
        chart_data = chart[0]
        timestamps = chart_data.get("timestamp") or []
        quotes = (chart_data.get("indicators") or {}).get("quote") or []
        closes = (quotes[0] if quotes else {}).get("close") or []
        valid = [
            (timestamp, close)
            for timestamp, close in zip(timestamps, closes)
            if close is not None
        ]
        if not valid:
            raise RuntimeError(f"Yahoo Finance devolvió una cotización vacía para {label}.")
        timestamp, close = valid[-1]
        market[label] = {
            "timestamp": timestamp,
            "close": close,
            "source": "Yahoo Finance chart",
            "symbol": symbol,
        }
    return market


def format_extended_market_context(sentiment, traditional_market):
    lines = ["🌐 Contexto macro y sentimiento", ""]
    lines.append("📈 Mercados tradicionales")
    for label, item in traditional_market.items():
        updated = datetime.fromtimestamp(item["timestamp"], tz=timezone.utc)
        lines.append(
            f"{label}: {item['close']} ({updated.strftime('%Y-%m-%d %H:%M UTC')})"
        )
    lines.append("Fuente de mercado: Yahoo Finance chart · último dato disponible")
    lines.append("")

    fear_greed = sentiment.get("fear_greed") or {}
    if fear_greed.get("value") is not None:
        classification = fear_greed.get("value_classification", "N/D")
        lines.append(
            f"😨 Fear & Greed: {fear_greed.get('value')}/100 ({classification})"
        )
        lines.append(f"Fuente: {fear_greed.get('source', 'CoinMarketCap')}")

    altcoin = sentiment.get("altcoin_season") or {}
    if altcoin.get("altcoin_index") is not None:
        lines.append(
            f"🔄 Altcoin Season: {altcoin.get('altcoin_index')}/100"
        )
        lines.append(
            f"Fuente: CoinMarketCap · actualización {altcoin.get('snapshot_time', 'N/D')}"
        )
    lines.append("")
    lines.append("⚖️ Estado: datos de mercado informativos, no pronóstico")
    return "\n".join(lines)


def read_fomc_agenda(year=None):
    year = year or datetime.now(timezone.utc).year
    request = urllib.request.Request(FOMC_CALENDAR_URL, headers=rss_headers())
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"\s+", " ", text)
    section_marker = f"{year} FOMC Meetings"
    if section_marker not in text:
        raise RuntimeError(f"No se encontró el calendario FOMC de {year}.")
    section = text.split(section_marker, 1)[1]
    previous_year = f"{year - 1} FOMC Meetings"
    if previous_year in section:
        section = section.split(previous_year, 1)[0]
    month_names = (
        "January|February|March|April|May|June|July|August|September|October|November|December"
    )
    matches = re.findall(
        rf"({month_names})\s+(\d{{1,2}}(?:-\d{{1,2}})?)\*?\s+Statement:",
        section,
    )
    december_match = re.search(
        r"December\s+(\d{1,2}(?:-\d{1,2})?)\*?\s+\* Meeting associated",
        section,
    )
    if december_match:
        matches.append(("December", december_match.group(1)))
    agenda = []
    seen = set()
    month_numbers = {
        name: index for index, name in enumerate(
            ("January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December"),
            start=1,
        )
    }
    today = datetime.now(timezone.utc).date()
    for month_name, days in matches:
        key = (month_name, days)
        if key in seen:
            continue
        seen.add(key)
        first_day = int(days.split("-", 1)[0])
        start_date = datetime(year, month_numbers[month_name], first_day).date()
        if start_date < today:
            continue
        agenda.append({
            "title": f"Reunión FOMC · {month_name} {days} {year}",
            "date": f"{month_name} {days} {year}",
            "start_date": start_date.isoformat(),
            "source": "Federal Reserve",
            "link": FOMC_CALENDAR_URL,
        })
    if not agenda:
        raise RuntimeError("El calendario FOMC no devolvió reuniones.")
    return agenda


def read_bls_macro_calendar(year=None):
    """Lee el calendario oficial de publicaciones macroeconómicas del BLS.

    Los RSS de CPI y Employment Situation informan publicaciones ya emitidas;
    este calendario permite conocer fechas futuras sin depender de un proveedor
    comercial ni de una API de pago.
    """
    year = year or datetime.now(timezone.utc).year
    schedule_url = BLS_SCHEDULE_URL.format(year=year)
    request = urllib.request.Request(schedule_url, headers=rss_headers())
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"\s+", " ", text)
    weekdays = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
    month_names = (
        "January|February|March|April|May|June|July|August|September|"
        "October|November|December"
    )
    release_pattern = re.compile(
        rf"(?:{weekdays}),?\s+({month_names})\s+(\d{{1,2}}),\s+(\d{{4}})\s+"
        rf"(\d{{1,2}}:\d{{2}}\s+[AP]M)\s+(.+?)(?=(?:{weekdays}),?\s+"
        rf"(?:{month_names})\s+\d{{1,2}},\s+\d{{4}}\s+|NOTE:|$)",
        re.IGNORECASE,
    )
    relevant_titles = (
        "Consumer Price Index",
        "Employment Situation",
        "Producer Price Index",
        "Job Openings and Labor Turnover Survey",
        "Productivity and Costs",
        "Import and Export Price Indexes",
    )
    month_numbers = {
        name: index for index, name in enumerate(
            ("January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December"),
            start=1,
        )
    }
    today = datetime.now(timezone.utc).date()
    agenda = []
    seen = set()
    for match in release_pattern.finditer(text):
        month_name, day, item_year, release_time, title = match.groups()
        title = re.sub(r"\s+", " ", title).strip()
        if not any(keyword.lower() in title.lower() for keyword in relevant_titles):
            continue
        item_year = int(item_year)
        start_date = datetime(item_year, month_numbers[month_name.title()], int(day)).date()
        if start_date < today:
            continue
        key = (start_date.isoformat(), title)
        if key in seen:
            continue
        seen.add(key)
        agenda.append({
            "title": f"{title} · {month_name} {day}, {item_year}",
            "date": f"{month_name} {day}, {item_year} · {release_time} ET",
            "start_date": start_date.isoformat(),
            "source": "U.S. Bureau of Labor Statistics",
            "link": schedule_url,
        })
    agenda.sort(key=lambda item: item["start_date"])
    if not agenda:
        raise RuntimeError("El calendario BLS no devolvió eventos macroeconómicos futuros.")
    return agenda


def format_weekly_report(state, agenda, macro_agenda=None):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    recent = []
    for item in state.get("published_messages", {}).values():
        recorded_at = parse_news_datetime(item.get("recorded_at"))
        if recorded_at and recorded_at >= cutoff:
            recent.append(item)
    recent.sort(key=lambda item: item.get("telegram_date") or 0, reverse=True)
    lines = ["📅 NOTIKRYPTOS · Informe semanal", ""]
    lines.append("📰 Acontecimientos publicados en los últimos 7 días")
    if recent:
        for item in recent[:12]:
            lines.append(
                f"• [{item.get('relevance', 'N/D')}] "
                f"{item.get('title', 'Sin título')} · {item.get('source', 'N/D')}"
            )
    else:
        lines.append("• No hay publicaciones registradas en el período.")
    lines.append("")
    lines.append("🗓️ Agenda FOMC próxima")
    for event in agenda[:6]:
        lines.append(f"• {event['title']}")
    lines.append("")
    lines.append("📈 Agenda macroeconómica próxima · BLS")
    if macro_agenda:
        for event in macro_agenda[:10]:
            lines.append(f"• {event['title']} · {event['date'].split(' · ')[-1]}")
    else:
        lines.append("• No se pudo consultar el calendario BLS en esta ejecución.")
    lines.append("")
    lines.append("⚖️ Alcance")
    lines.append("Resumen informativo basado en publicaciones registradas y calendario oficial.")
    lines.append(f"🔗 Fuente del calendario: {FOMC_CALENDAR_URL}")
    lines.append(f"🔗 Fuente macroeconómica: {BLS_SCHEDULE_URL.format(year=now.year)}")
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


def read_official_tech_news():
    news = []
    for source_name, feed_url in OFFICIAL_TECH_FEEDS:
        request = urllib.request.Request(feed_url, headers=rss_headers())
        with urllib.request.urlopen(request, timeout=30) as response:
            root = ET.fromstring(response.read())
        items = [
            element for element in root.iter()
            if element.tag.split("}")[-1] in {"item", "entry"}
        ]
        if not items:
            print(f"{source_name}: feed sin publicaciones.")
            continue
        item = items[0]
        values = {}
        link = ""
        for child in item:
            name = child.tag.split("}")[-1]
            if name in {
                "title", "pubDate", "published", "updated", "date",
                "description", "summary", "content",
            }:
                values.setdefault(name, (child.text or "").strip())
            if name == "link":
                link = (child.attrib.get("href", "") or child.text or "").strip()
        title = values.get("title") or "Sin título"
        published = next(
            (values.get(k) for k in ("pubDate", "published", "updated", "date") if values.get(k)),
            "",
        )
        details = values.get("description") or values.get("summary") or values.get("content") or ""
        news.append({
            "id": f"tech:{source_name}:{link or title}",
            "source": source_name,
            "title": title,
            "link": link or feed_url,
            "published": published,
            "details": details,
        })
        print(f"{source_name}: publicación encontrada.")
    return news


def collect_news():
    news = []
    sources = [
        ("Federal Reserve", read_federal_reserve_news),
        ("Treasury", read_treasury_news),
        ("Coinbase Status", read_coinbase_incidents),
        ("Binance", read_binance_news),
        ("BLS", read_bls_news),
        ("Tecnología e IA", read_official_tech_news),
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
        return {
            "processed_ids": [],
            "published_messages": {},
            "alert_checked_ids": [],
        }
    with open(STATE_FILE, "r", encoding="utf-8") as file:
        state = json.load(file)
    state.setdefault("processed_ids", [])
    state.setdefault("published_messages", {})
    state.setdefault("alert_checked_ids", [])
    return state


def save_state(state):
    state.setdefault("processed_ids", [])
    state.setdefault("alert_checked_ids", [])
    state.setdefault("published_messages", {})
    state["processed_ids"] = state["processed_ids"][-MAX_PROCESSED_IDS:]
    state["alert_checked_ids"] = state["alert_checked_ids"][-MAX_PROCESSED_IDS:]
    published_messages = state.get("published_messages", {})
    if len(published_messages) > MAX_PROCESSED_IDS:
        recent_ids = state["processed_ids"]
        state["published_messages"] = {
            news_id: published_messages[news_id]
            for news_id in recent_ids
            if news_id in published_messages
        }
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


def has_cross_source_confirmation(news, news_items):
    if news["source"] in {"Federal Reserve", "U.S. Treasury", "BLS - Inflación CPI", "BLS - Empleo"}:
        return True
    words = {
        word for word in normalize_binance_title(news["title"]).split()
        if len(word) >= 5
    }
    if len(words) < 2:
        return False
    for other in news_items:
        if other is news or other["source"] == news["source"]:
            continue
        other_words = {
            word for word in normalize_binance_title(other["title"]).split()
            if len(word) >= 5
        }
        if len(words & other_words) >= 2:
            return True
    return False


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
    for attempt in range(1, TELEGRAM_MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not result.get("ok"):
                raise RuntimeError(result)
            message = result.get("result") or {}
            return {
                "message_id": message.get("message_id"),
                "chat_id": message.get("chat", {}).get("id"),
                "date": message.get("date"),
            }
        except urllib.error.HTTPError as error:
            if error.code not in TELEGRAM_RETRYABLE_STATUS_CODES or attempt == TELEGRAM_MAX_ATTEMPTS:
                raise
            retry_after = error.headers.get("Retry-After")
            try:
                wait_seconds = max(1, min(int(retry_after), 60))
            except (TypeError, ValueError):
                wait_seconds = 2 ** (attempt - 1)
            print(
                f"Telegram no disponible temporalmente (HTTP {error.code}). "
                f"Reintento en {wait_seconds} segundos."
            )
            time.sleep(wait_seconds)

    raise RuntimeError("Telegram no confirmó la entrega del mensaje.")


def build_message(news, analysis, cross_source_confirmed=False):
    notice = ""
    if news["source"] in {"Coinbase Status", "Binance"}:
        notice = (
            f"Comunicado oficial de {news['source']}.\n\n"
        )
    government_sources = {
        "Federal Reserve", "U.S. Treasury", "BLS - Inflación CPI",
        "BLS - Empleo",
    }
    if cross_source_confirmed:
        verification = "✅ CONFIRMADO · corroborado por más de una fuente"
    elif news["source"] in government_sources:
        verification = "✅ CONFIRMADO · fuente oficial"
    elif news["source"] in {
        "Coinbase Status", "Binance", "OpenAI News", "Google AI", "Microsoft AI",
    }:
        verification = "⚖️ COMUNICADO OFICIAL · requiere contexto independiente"
    else:
        verification = "🟡 EN VERIFICACIÓN"
    heading = (
        "🚨 NOTIKRYPTOS ALERT\n\n"
        if analysis.get("relevance") == "ALTA"
        else "🔴 COMUNICADO OFICIAL\n\n"
    )
    return (
        heading
        + "📰 Resumen del acontecimiento\n\n"
        f"{analysis['title_es']}\n\n"
        "📝 Síntesis\n\n"
        f"{analysis['summary_es']}\n\n"
        "📊 Impacto potencial en el mercado\n\n"
        f"{analysis['impact_es']}\n\n"
        "⚖️ Estado de verificación\n\n"
        f"{verification}\n\n"
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
    run_mode = os.environ.get("RUN_MODE", RUN_MODE).strip().lower()

    market_snapshot = ""
    try:
        market_data = read_coinmarketcap_market()
        market_snapshot = format_coinmarketcap_snapshot(market_data)
        print(market_snapshot)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(f"CoinMarketCap no disponible: HTTP {error.code} — {body}")
    except Exception as error:
        print(f"Error consultando CoinMarketCap: {error}")

    sentiment = {}
    try:
        sentiment = read_cmc_sentiment()
    except Exception as error:
        print(f"CoinMarketCap: sentimiento no disponible: {error}")
        try:
            sentiment["fear_greed"] = read_alternative_me_fear_greed()
            print("Fear & Greed: datos recibidos desde Alternative.me.")
        except Exception as fallback_error:
            print(f"Fear & Greed: fallback no disponible: {fallback_error}")

    traditional_market = {}
    try:
        traditional_market = read_yahoo_market_data()
    except Exception as error:
        print(f"Mercados tradicionales no disponibles: {error}")

    if run_mode == "daily":
        daily_sections = [section for section in (
            market_snapshot,
            format_extended_market_context(sentiment, traditional_market)
            if sentiment or traditional_market else "",
        ) if section]
        if daily_sections:
            delivery = send_message("\n\n".join(daily_sections))
            print(
                "Resumen diario de mercado enviado a Telegram. "
                f"message_id={delivery.get('message_id')}"
            )

    if run_mode == "weekly":
        try:
            agenda = read_fomc_agenda()
            macro_agenda = []
            try:
                macro_agenda = read_bls_macro_calendar()
                print(f"Calendario BLS: {len(macro_agenda)} eventos futuros recibidos.")
            except Exception as error:
                print(f"Calendario BLS no disponible: {error}")
            weekly_report = format_weekly_report(state, agenda, macro_agenda)
            delivery = send_message(weekly_report)
            print(
                "Informe semanal enviado a Telegram. "
                f"message_id={delivery.get('message_id')}"
            )
        except Exception as error:
            print(f"Informe semanal no disponible: {error}")
        return

    news_items = collect_news()
    if not news_items:
        print("No se encontraron noticias o incidentes nuevos.")
        return

    processed_any = False
    for news in news_items:
        news_id = news["id"]
        legacy_ids = news.get("legacy_ids", [])
        if run_mode == "alerts" and (
            news_id in state["alert_checked_ids"]
            or any(old_id in state["alert_checked_ids"] for old_id in legacy_ids)
        ):
            continue
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
        if run_mode == "alerts":
            state["alert_checked_ids"].append(news_id)
            save_state(state)
            if relevance != "ALTA":
                print(
                    f"{news['source']}: no es alerta crítica. "
                    f"Nivel de relevancia: {relevance}."
                )
                continue
        if relevance in {"BAJA", "DESCARTAR"}:
            state["processed_ids"].append(news_id)
            save_state(state)
            processed_any = True
            print(f"{news['source']}: noticia no publicada. Nivel de relevancia: {relevance}.")
            continue

        delivery = send_message(
            build_message(
                news,
                analysis,
                cross_source_confirmed=has_cross_source_confirmation(news, news_items),
            )
        )
        state["processed_ids"].append(news_id)
        state["published_messages"][news_id] = {
            "source": news["source"],
            "title": news["title"],
            "relevance": relevance,
            "telegram_message_id": delivery.get("message_id"),
            "telegram_chat_id": delivery.get("chat_id"),
            "telegram_date": delivery.get("date"),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        save_state(state)
        processed_any = True
        print(f"{news['source']}: noticia publicada. Nivel de relevancia: {relevance}.")
    if not processed_any:
        print("No hay noticias nuevas para procesar.")


if __name__ == "__main__":
    main()
