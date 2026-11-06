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
from zoneinfo import ZoneInfo


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
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
ALTERNATIVE_ME_FNG_URL = "https://api.alternative.me/fng/?limit=1"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_SCHEDULE_URL = "https://www.bls.gov/schedule/{year}/"
BEA_SCHEDULE_URL = "https://www.bea.gov/news/schedule/"
BLS_API_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
SHOWMYTRADES_CALENDAR_URL = "https://showmytrades.com/api/public/calendar/v1"

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
    "XAU": "GC=F",
    "OIL": "CL=F",
    "Dow Jones": "^DJI",
    "NQ100": "^NDX",
    "S&P 500": "^GSPC",
    "EUR/USD": "EURUSD=X",
    "USD/JPY": "JPY=X",
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
MACRO_PRE_RELEASE_MINUTES = 60
MACRO_PUBLICATION_LOOKBACK_MINUTES = 15
MACRO_ALERT_TOLERANCE_MINUTES = 7.5


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


def read_yahoo_intraday_change(symbol):
    request = urllib.request.Request(
        f"{YAHOO_CHART_URL}{urllib.parse.quote(symbol, safe='')}?range=2d&interval=1h",
        headers={"Accept": "application/json", "User-Agent": user_agent()},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    chart = (result.get("chart") or {}).get("result") or []
    if not chart:
        return None
    quotes = ((chart[0].get("indicators") or {}).get("quote") or [])
    closes = (quotes[0] if quotes else {}).get("close") or []
    closes = [float(value) for value in closes if value is not None]
    if len(closes) < 5 or closes[-5] == 0:
        return None
    return ((closes[-1] - closes[-5]) / closes[-5]) * 100


def read_binance_four_hour_changes():
    """Calcula variaciones de 4 horas y usa Yahoo como respaldo."""
    symbols = {
        "BTC": ("BTCUSDT", "BTC-USD"),
        "ETH": ("ETHUSDT", "ETH-USD"),
        "SOL": ("SOLUSDT", "SOL-USD"),
        "NEAR": ("NEARUSDT", "NEAR-USD"),
    }
    changes = {}
    for name, (symbol, fallback_symbol) in symbols.items():
        query = urllib.parse.urlencode({
            "symbol": symbol,
            "interval": "1h",
            "limit": 5,
        })
        request = urllib.request.Request(
            f"{BINANCE_KLINES_URL}?{query}",
            headers={"Accept": "application/json", "User-Agent": user_agent()},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                candles = json.loads(response.read().decode("utf-8"))
            closes = [float(candle[4]) for candle in candles if len(candle) > 4]
            if len(closes) >= 5 and closes[-5] != 0:
                changes[name] = ((closes[-1] - closes[-5]) / closes[-5]) * 100
                continue
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, IndexError) as error:
            print(f"Binance 4 h no disponible para {name}: {error}")
        try:
            fallback = read_yahoo_intraday_change(fallback_symbol)
            if fallback is not None:
                changes[name] = fallback
                print(f"4 h de {name}: respaldo Yahoo Finance chart.")
            else:
                print(f"4 h no disponible para {name}: serie insuficiente.")
        except Exception as error:
            print(f"4 h no disponible para {name}: {error}")
    return changes


def format_coinmarketcap_snapshot(market_data, four_hour_changes=None):
    lines = ["<b>🪙 NOTIKRYPTOS · Informe técnico cripto</b>", ""]
    names = {"1": "BTC", "1027": "ETH", "5426": "SOL", "6535": "NEAR"}
    quotes = market_data.get("quotes", {})
    four_hour_changes = four_hour_changes or {}
    if isinstance(quotes, list):
        assets = [(asset.get("id", ""), asset) for asset in quotes]
    else:
        assets = list(quotes.items())

    for index, (asset_id, asset) in enumerate(assets):
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
        price = usd.get("price")
        price_text = format_market_number(price)
        four_hour = four_hour_changes.get(symbol)
        lines.append(f"<b>{symbol}: ${price_text}</b>")
        one_hour = usd.get("percent_change_1h")
        four_hour_text = format_directional_change(four_hour)
        if four_hour is None:
            four_hour_text += (
                f" · referencia 1 h: {format_directional_change(one_hour)}"
            )
        lines.append(
            f"1 h: {format_directional_change(one_hour)} · "
            f"4 h: {four_hour_text} · "
            f"24 h: {format_directional_change(usd.get('percent_change_24h'))} · "
            f"7 d: {format_directional_change(usd.get('percent_change_7d'))} · "
            f"30 d: {format_directional_change(usd.get('percent_change_30d'))}"
        )
        lines.append("")
        if index < len(assets) - 1:
            lines.append("────────────────────")
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


def read_yahoo_daily_closes(symbol, range_name="30d"):
    request = urllib.request.Request(
        f"{YAHOO_CHART_URL}{urllib.parse.quote(symbol, safe='')}?range={range_name}&interval=1d",
        headers={"Accept": "application/json", "User-Agent": user_agent()},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    chart = (result.get("chart") or {}).get("result") or []
    if not chart:
        return []
    quotes = ((chart[0].get("indicators") or {}).get("quote") or [])
    closes = (quotes[0] if quotes else {}).get("close") or []
    return [float(value) for value in closes if value is not None]


def calculate_pearson(values_x, values_y):
    pairs = [
        (float(x), float(y))
        for x, y in zip(values_x, values_y)
        if x is not None and y is not None
    ]
    if len(pairs) < 3:
        return None
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    denominator_x = sum((x - mean_x) ** 2 for x in xs)
    denominator_y = sum((y - mean_y) ** 2 for y in ys)
    denominator = (denominator_x * denominator_y) ** 0.5
    if denominator == 0:
        return None
    return numerator / denominator


def calculate_daily_returns(closes):
    return [
        ((current - previous) / previous) * 100
        for previous, current in zip(closes, closes[1:])
        if previous not in (None, 0) and current is not None
    ]


def read_dxy_btc_pearson(temporalidad_days=30):
    dxy_closes = read_yahoo_daily_closes("DX-Y.NYB", f"{temporalidad_days}d")
    btc_closes = read_yahoo_daily_closes("BTC-USD", f"{temporalidad_days}d")
    dxy_returns = calculate_daily_returns(dxy_closes)
    btc_returns = calculate_daily_returns(btc_closes)
    return calculate_pearson(dxy_returns, btc_returns)


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
        previous_close = valid[-2][1] if len(valid) >= 2 else None
        change_percent = None
        if previous_close not in (None, 0):
            change_percent = ((close - previous_close) / previous_close) * 100
        market[label] = {
            "timestamp": timestamp,
            "close": close,
            "previous_close": previous_close,
            "change_percent": change_percent,
            "source": "Yahoo Finance chart",
            "symbol": symbol,
        }
    return market


def format_market_number(value):
    if value is None:
        return "N/D"
    return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_market_change(value):
    if value is None:
        return "N/D"
    return f"{float(value):+,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")


def format_directional_change(value):
    if value is None:
        return "N/D"
    if value > 0.05:
        marker = "📈"
    elif value < -0.05:
        marker = "📉"
    else:
        marker = "➡️"
    return f"{marker} {format_market_change(value)}"


def market_direction(change_percent):
    if change_percent is None:
        return "🟦►"
    if change_percent > 0.05:
        return "🟩▲"
    if change_percent < -0.05:
        return "🟥▼"
    return "🟦►"


def format_asset_comparison(market_data=None, traditional_market=None, temporalidad="24 h"):
    rows = []
    market_data = market_data or {}
    traditional_market = traditional_market or {}
    names = {"1": "BTC", "1027": "ETH", "5426": "SOL", "6535": "NEAR"}
    quotes = market_data.get("quotes", {})
    assets = [(asset.get("id", ""), asset) for asset in quotes] if isinstance(quotes, list) else list(quotes.items())
    for asset_id, asset in assets:
        quote = asset.get("quote", {}) if isinstance(asset, dict) else {}
        if isinstance(quote, list):
            quote = quote[0] if quote else {}
        usd = quote.get("USD", {}) if isinstance(quote, dict) and "USD" in quote else quote
        if isinstance(usd, list):
            usd = usd[0] if usd else {}
        if not isinstance(usd, dict):
            continue
        rows.append({
            "label": names.get(str(asset_id), asset.get("symbol", "ACTIVO")),
            "change": usd.get("percent_change_24h"),
            "secondary": usd.get("percent_change_7d"),
            "secondary_label": "7d",
        })
    for label, item in traditional_market.items():
        rows.append({
            "label": label,
            "change": item.get("change_percent"),
            "secondary": item.get("week_change_percent"),
            "secondary_label": "5d",
        })
    rows = [row for row in rows if row.get("change") is not None]
    rows.sort(key=lambda row: float(row["change"]), reverse=True)
    lines = [f"📊 Desempeño relativo · temporalidad {temporalidad}", ""]
    if not rows:
        lines.append("No hay datos comparables disponibles.")
        return "\n".join(lines)
    for row in rows:
        marker = "📈" if row["change"] > 0.05 else "📉" if row["change"] < -0.05 else "➡️"
        secondary = (
            f" · {row['secondary_label']}: {format_market_change(row['secondary'])}"
            if row.get("secondary") is not None else ""
        )
        lines.append(
            f"{marker} {row['label']}: 24h {format_market_change(row['change'])}{secondary}"
        )
    lines.extend([
        "",
        "🔎 Lectura relativa",
        "Se ordenan los activos por variación observada. Las diferencias de dirección o magnitud se informan como divergencias.",
        "La comparación no constituye pronóstico ni señal de operación.",
    ])
    return "\n".join(lines)


def format_crypto_comparison(market_data=None, four_hour_changes=None):
    market_data = market_data or {}
    four_hour_changes = four_hour_changes or {}
    names = {"1": "BTC", "1027": "ETH", "5426": "SOL", "6535": "NEAR"}
    quotes = market_data.get("quotes", {})
    assets = [(asset.get("id", ""), asset) for asset in quotes] if isinstance(quotes, list) else list(quotes.items())
    rows = []
    for asset_id, asset in assets:
        quote = asset.get("quote", {}) if isinstance(asset, dict) else {}
        if isinstance(quote, list):
            quote = quote[0] if quote else {}
        usd = quote.get("USD", {}) if isinstance(quote, dict) and "USD" in quote else quote
        if isinstance(usd, list):
            usd = usd[0] if usd else {}
        if not isinstance(usd, dict):
            continue
        label = names.get(str(asset_id), asset.get("symbol", "ACTIVO"))
        rows.append({
            "label": label,
            "change_1h": usd.get("percent_change_1h"),
            "change_4h": four_hour_changes.get(label),
            "change_24h": usd.get("percent_change_24h"),
            "change_7d": usd.get("percent_change_7d"),
        })
    rows = [row for row in rows if row["change_24h"] is not None]
    rows.sort(key=lambda row: float(row["change_24h"]), reverse=True)
    lines = [
        "<b>🪙 Desempeño relativo cripto · temporalidad 1 h · 4 h · 24 h · 7 d</b>",
        "",
    ]
    if not rows:
        lines.append("No hay datos comparables disponibles.")
        return "\n".join(lines)
    for row in rows:
        marker = "📈" if row["change_24h"] > 0.05 else "📉" if row["change_24h"] < -0.05 else "➡️"
        four_hour_text = format_market_change(row["change_4h"])
        if row["change_4h"] is None:
            four_hour_text += (
                f" · referencia 1 h {format_market_change(row['change_1h'])}"
            )
        lines.append(
            f"{marker} {row['label']}: "
            f"1 h {format_market_change(row['change_1h'])} · "
            f"4 h {four_hour_text} · "
            f"24 h {format_market_change(row['change_24h'])} · "
            f"7 d {format_market_change(row['change_7d'])}"
        )
        lines.append("────────────────────")
    best = rows[0]
    worst = rows[-1]
    lines.extend([
        "",
        f"Mejor desempeño observado: {best['label']} ({format_market_change(best['change_24h'])} en 24 h).",
        f"Menor desempeño observado: {worst['label']} ({format_market_change(worst['change_24h'])} en 24 h).",
        "Las diferencias se describen como desempeño relativo; no son señales de operación.",
    ])
    return "\n".join(lines)

def format_traditional_comparison(traditional_market):
    rows = [
        (label, item.get("change_percent"), item.get("week_change_percent"))
        for label, item in (traditional_market or {}).items()
        if item.get("change_percent") is not None
    ]
    rows.sort(key=lambda row: float(row[1]), reverse=True)
    lines = ["<b>📊 Comparación de mercados tradicionales · temporalidad 24 h · 5d</b>", ""]
    if not rows:
        lines.append("No hay datos comparables disponibles.")
        return "\n".join(lines)
    for label, daily, weekly in rows:
        marker = "📈" if daily > 0.05 else "📉" if daily < -0.05 else "➡️"
        weekly_text = (
            f" · 5d {format_market_change(weekly)}"
            if weekly is not None else ""
        )
        lines.append(f"{marker} {label}: 24h {format_market_change(daily)}{weekly_text}")
        lines.append("────────────────────")
    lines.extend([
        "",
        "La comparación ordena el desempeño observado y no constituye pronóstico.",
    ])
    return "\n".join(lines)


def format_crypto_intermarket_context(pearson_value, traditional_market):
    lines = ["<b>🔗 Cripto · dólar y activos de riesgo</b>", ""]
    for label in ("DXY", "NQ100", "S&P 500", "VIX", "XAU", "OIL", "EUR/USD", "USD/JPY"):
        item = (traditional_market or {}).get(label)
        if item and item.get("change_percent") is not None:
            lines.append(f"{label}: {format_market_change(item['change_percent'])} · 24 h")
    lines.append("")
    lines.append(format_correlation(pearson_value, "30 días"))
    lines.append(
        "La lectura intermercado describe co-movimientos observados; "
        "no atribuye causalidad."
    )
    return "\n".join(lines)


def format_correlation(pearson_value, temporalidad):
    if pearson_value is None:
        return (
            f"📐 Correlación DXY/BTC · temporalidad {temporalidad}: "
            "N/D · series históricas alineadas insuficientes"
        )
    if pearson_value >= 0.7:
        strength = "positiva fuerte"
    elif pearson_value >= 0.3:
        strength = "positiva moderada"
    elif pearson_value > -0.3:
        strength = "sin relación lineal clara"
    elif pearson_value > -0.7:
        strength = "inversa moderada"
    else:
        strength = "inversa fuerte"
    return "\n".join([
        f"📐 Correlación DXY/BTC · temporalidad {temporalidad}",
        f"Resultado: {pearson_value:+.2f} · relación {strength}",
        "Método: rendimientos diarios con fechas alineadas.",
        "Alcance: relación estadística observada; no implica causalidad ni proyección.",
    ])


def format_extended_market_context(
    sentiment,
    traditional_market,
    market_data=None,
    pearson_value=None,
):
    lines = ["<b>📈 NOTIKRYPTOS · Informe técnico de mercados</b>", ""]
    lines.append("<b>🌐 Mercados tradicionales y divisas</b>")
    for label, item in traditional_market.items():
        updated = datetime.fromtimestamp(item["timestamp"], tz=timezone.utc)
        change = item.get("change_percent")
        direction = market_direction(change)
        lines.append(
            f"{direction} {label}: {format_market_number(item.get('close'))} "
            f"({format_market_change(change)}) · "
            f"{updated.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        lines.append("")
        lines.append("────────────────────")
        lines.append("")
    lines.append("Flecha: variación frente al dato anterior · Yahoo Finance chart")
    lines.append("")
    lines.append(format_traditional_comparison(traditional_market))
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
        normalized_title = title.lower()
        if "consumer price index" in normalized_title:
            indicator = "CPI"
        elif "producer price index" in normalized_title:
            indicator = "PPI"
        elif "employment situation" in normalized_title:
            indicator = "Employment Situation"
        elif "job openings" in normalized_title:
            indicator = "JOLTS"
        else:
            indicator = title
        agenda.append({
            "title": f"{title} · {month_name} {day}, {item_year}",
            "date": f"{month_name} {day}, {item_year} · {release_time} ET",
            "start_date": start_date.isoformat(),
            "indicator": indicator,
            "previous": None,
            "expected": None,
            "actual": None,
            "core_previous": None,
            "core_expected": None,
            "core_actual": None,
            "status": "scheduled",
            "source": "U.S. Bureau of Labor Statistics",
            "link": schedule_url,
        })
    agenda.sort(key=lambda item: item["start_date"])
    if not agenda:
        raise RuntimeError("El calendario BLS no devolvió eventos macroeconómicos futuros.")
    return agenda


def read_bls_official_snapshot(indicator):
    """Obtiene valores oficiales publicados y anteriores desde la API pública BLS.

    No contiene consenso de mercado: expected permanece separado y sin inventar.
    """
    series_by_indicator = {
        "CPI": {
            "actual": "CUUR0000SA0",
            "core_actual": "CUUR0000SA0L1E",
        },
        "PPI": {
            "actual": "WPSFD4",
        },
        "Employment Situation": {
            "actual": "CES0000000001",
            "core_actual": "CES0500000003",
        },
    }
    series_ids = series_by_indicator.get(indicator)
    if not series_ids:
        return {}
    payload = json.dumps({
        "seriesid": list(series_ids.values()),
        "startyear": str(datetime.now(timezone.utc).year - 2),
        "endyear": str(datetime.now(timezone.utc).year),
    }).encode("utf-8")
    request = urllib.request.Request(
        BLS_API_URL,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API no confirmó la consulta: {result}")
    by_id = {series.get("seriesID"): series for series in (result.get("Results", {}).get("series") or [])}
    snapshot = {}
    for field, series_id in series_ids.items():
        observations = [
            item for item in (by_id.get(series_id, {}).get("data") or [])
            if item.get("period", "").startswith("M") and item.get("period") != "M13"
        ]
        if not observations:
            continue
        latest = observations[0]
        previous = observations[1] if len(observations) > 1 else None
        snapshot[field] = {
            "actual": latest.get("value"),
            "previous": previous.get("value") if previous else None,
            "year": latest.get("year"),
            "period": latest.get("period"),
            "source": "BLS Public Data API",
            "status": "confirmed",
        }
    return snapshot


def macro_reference_period(event):
    title = event.get("title", "")
    match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(20\d{2})\b",
        title,
        re.IGNORECASE,
    )
    if not match:
        return None
    month_numbers = {
        name: index for index, name in enumerate(
            ("January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December"),
            start=1,
        )
    }
    return int(match.group(2)), f"M{month_numbers[match.group(1).title()]:02d}"


def enrich_bls_macro_calendar(events, now=None):
    """Completa valores BLS sólo cuando el período oficial coincide."""
    indicator_snapshots = {}
    for indicator in ("CPI", "PPI", "Employment Situation"):
        try:
            indicator_snapshots[indicator] = read_bls_official_snapshot(indicator)
        except Exception as error:
            print(f"Datos BLS no disponibles para {indicator}: {error}")
    now = now or datetime.now(timezone.utc)
    for event in events:
        title = event.get("title", "").lower()
        if "consumer price index" in title:
            indicator = "CPI"
        elif "producer price index" in title:
            indicator = "PPI"
        elif "employment situation" in title:
            indicator = "Employment Situation"
        else:
            continue
        snapshot = indicator_snapshots.get(indicator, {})
        actual = snapshot.get("actual", {})
        core = snapshot.get("core_actual", {})
        event["previous"] = actual.get("actual")
        event["core_previous"] = core.get("actual")
        event["expected"] = None
        event["core_expected"] = None
        event["actual"] = None
        event["core_actual"] = None
        event["status"] = "scheduled · anterior oficial disponible"
        event["official_previous_period"] = (
            f"{actual.get('year')}-{actual.get('period')}"
            if actual.get("year") and actual.get("period") else None
        )
        release = parse_macro_event_datetime(event)
        reference_period = macro_reference_period(event)
        if (
            release is not None
            and release <= now
            and reference_period
            and actual.get("year") == str(reference_period[0])
            and actual.get("period") == reference_period[1]
        ):
            event["actual"] = actual.get("actual")
            event["core_actual"] = core.get("actual")
            event["status"] = "published · dato oficial disponible"
    return events


def read_bea_macro_calendar(year=None):
    """Lee el calendario oficial del BEA sin inventar consenso de mercado."""
    year = year or datetime.now(timezone.utc).year
    request = urllib.request.Request(BEA_SCHEDULE_URL, headers=rss_headers())
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"\s+", " ", text)
    month_names = (
        "January|February|March|April|May|June|July|August|September|"
        "October|November|December"
    )
    release_pattern = re.compile(
        rf"({month_names})\s+(\d{{1,2}})\s+(\d{{1,2}}:\d{{2}}\s+[AP]M)\s+(.+?)(?=(?:{month_names})\s+\d{{1,2}}\s+\d{{1,2}}:\d{{2}}\s+[AP]M|To Be Announced|$)",
        re.IGNORECASE,
    )
    relevant_titles = (
        "GDP",
        "Personal Income and Outlays",
        "Personal Income",
        "Personal Consumption Expenditures",
        "PCE",
        "Corporate Profits",
    )
    month_numbers = {
        name: index for index, name in enumerate(
            ("January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December"),
            start=1,
        )
    }
    today = datetime.now(timezone.utc).date()
    events = []
    seen = set()
    for match in release_pattern.finditer(text):
        month_name, day, release_time, title = match.groups()
        title = re.sub(r"\s+", " ", title).strip()
        if not any(keyword.lower() in title.lower() for keyword in relevant_titles):
            continue
        start_date = datetime(year, month_numbers[month_name.title()], int(day)).date()
        if start_date < today:
            continue
        key = (start_date.isoformat(), title)
        if key in seen:
            continue
        seen.add(key)
        indicator = "GDP" if "GDP" in title else "PCE/Ingresos y gastos personales"
        events.append({
            "title": f"{title} · {month_name} {day}, {year}",
            "date": f"{month_name} {day}, {year} · {release_time} ET",
            "start_date": start_date.isoformat(),
            "indicator": indicator,
            "previous": None,
            "expected": None,
            "actual": None,
            "core_previous": None,
            "core_expected": None,
            "core_actual": None,
            "status": "scheduled",
            "source": "U.S. Bureau of Economic Analysis",
            "link": BEA_SCHEDULE_URL,
        })
    events.sort(key=lambda item: item["start_date"])
    if not events:
        raise RuntimeError("El calendario BEA no devolvió eventos futuros de PIB o PCE.")
    return events


def format_official_macro_snapshot():
    lines = ["📌 Últimos datos macroeconómicos oficiales", ""]
    for indicator in ("CPI", "PPI", "Employment Situation"):
        snapshot = read_bls_official_snapshot(indicator)
        if not snapshot:
            continue
        lines.append(f"{indicator}")
        for field, label in (("actual", "Real"), ("previous", "Anterior"), ("core_actual", "Core")):
            values = [item for item in snapshot.values() if item.get(field) is not None]
            if values:
                item = values[0]
                lines.append(f"• {label}: {item.get(field)} · {item.get('year')}-{item.get('period')}")
        lines.append("• Estado: ✅ CONFIRMADO · fuente oficial BLS")
        lines.append("")
    if len(lines) == 2:
        return ""
    lines.append("🔗 Fuente: BLS Public Data API")
    return "\n".join(lines)


def format_macro_value(value, pending_label="N/D"):
    if value is None or value == "":
        return pending_label
    return str(value)


def translate_macro_date(value):
    if not value:
        return value
    months = {
        "January": "enero", "February": "febrero", "March": "marzo",
        "April": "abril", "May": "mayo", "June": "junio",
        "July": "julio", "August": "agosto", "September": "septiembre",
        "October": "octubre", "November": "noviembre", "December": "diciembre",
    }
    translated = value
    for english, spanish in months.items():
        translated = translated.replace(english, spanish)
    return translated


def translate_macro_title(title):
    translations = (
        ("Productivity and Costs", "Productividad y costos (Productivity and Costs)"),
        ("Employment Situation", "Situación del empleo (Employment Situation)"),
        ("Consumer Price Index", "Índice de precios al consumidor (CPI)"),
        ("Producer Price Index", "Índice de precios al productor (PPI)"),
        ("Job Openings and Labor Turnover Survey", "Ofertas de empleo y rotación laboral (JOLTS)"),
        ("Import and Export Price Indexes", "Índices de precios de importación y exportación"),
    )
    translated = title
    for english, spanish in translations:
        translated = translated.replace(english, spanish)
    return translated


def format_macro_metric(event, value, field):
    if value in (None, ""):
        return format_macro_value(value, "N/D" if field not in {"actual", "core_actual"} else "pendiente")
    title = event.get("title", "")
    if "Employment Situation" in title and field in {"previous", "actual"}:
        return f"{format_macro_value(value)} miles de empleos"
    if "Employment Situation" in title and field.startswith("core"):
        return f"USD {format_macro_value(value)} por hora"
    if "Consumer Price Index" in title:
        return f"índice {format_macro_value(value)}"
    if "Producer Price Index" in title:
        return f"índice {format_macro_value(value)}"
    return format_macro_value(value)


def format_macro_event(event):
    source = event.get("source", "fuente no disponible")
    is_bea = "Economic Analysis" in source
    section = "🏛️ BEA · ACTIVIDAD ECONÓMICA" if is_bea else "📈 BLS · INDICADORES MACRO"
    title = translate_macro_title(event.get("title", "Evento macroeconómico"))
    lines = [
        f"🗓️ {title}",
    ]
    if event.get("date"):
        lines.append(f"📅 {translate_macro_date(event['date'])}")
    lines.extend([
        "",
        f"Anterior: {format_macro_metric(event, event.get('previous'), 'previous')}",
        f"Esperado: {format_macro_metric(event, event.get('expected'), 'expected')}",
        f"Real: {format_macro_metric(event, event.get('actual'), 'actual')}",
    ])
    title_lower = event.get("title", "").lower()
    has_core = (
        any(
            event.get(field) not in (None, "")
            for field in ("core_previous", "core_expected", "core_actual")
        )
        or "cpi" in title_lower
        or "consumer price index" in title_lower
    )
    if has_core:
        lines.extend([
            "",
            "Core",
            f"Anterior: {format_macro_metric(event, event.get('core_previous'), 'core_previous')}",
            f"Esperado: {format_macro_metric(event, event.get('core_expected'), 'core_expected')}",
            f"Core real: {format_macro_metric(event, event.get('core_actual'), 'core_actual')}",
        ])
    lines.extend([
        "",
        "Estado: 🟡 PROGRAMADO",
        f"Fuente: {'Oficina de Estadísticas Laborales de EE. UU. (BLS)' if not is_bea else 'Oficina de Análisis Económico de EE. UU. (BEA)'}",
    ])
    return "\n".join(lines)

def parse_macro_event_datetime(event):
    """Convierte la hora ET publicada por BLS/BEA a UTC."""
    if event.get("release_time_utc"):
        try:
            return datetime.fromisoformat(
                str(event["release_time_utc"]).replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except ValueError:
            pass
    value = str(event.get("date", ""))
    match = re.search(
        r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})\s+·\s+"
        r"(\d{1,2}):(\d{2})\s+([AP]M)\s+ET",
        value,
        re.IGNORECASE,
    )
    if not match:
        return None
    month_name, day, year, hour, minute, meridiem = match.groups()
    month_numbers = {
        name: index for index, name in enumerate(
            ("January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December"),
            start=1,
        )
    }
    month = month_numbers.get(month_name.title())
    if month is None:
        return None
    hour = int(hour) % 12 + (12 if meridiem.upper() == "PM" else 0)
    return datetime(
        int(year), month, int(day), hour, int(minute),
        tzinfo=ZoneInfo("America/New_York"),
    ).astimezone(timezone.utc)


def macro_event_id(event):
    return "|".join([
        event.get("source", "macro"),
        event.get("start_date", ""),
        event.get("title", ""),
    ])


def macro_alert_window(event, now=None):
    now = now or datetime.now(timezone.utc)
    release = parse_macro_event_datetime(event)
    if release is None:
        return None
    minutes_until_release = (release - now).total_seconds() / 60
    if abs(minutes_until_release - MACRO_PRE_RELEASE_MINUTES) <= MACRO_ALERT_TOLERANCE_MINUTES:
        return "pre_release"
    if -MACRO_PUBLICATION_LOOKBACK_MINUTES <= minutes_until_release <= 0:
        return "publication"
    return None


def format_macro_alert(event, phase):
    source = event.get("source", "fuente oficial")
    source_name = "BLS" if "Labor" in source else "BEA/Fed"
    if phase == "pre_release":
        heading = "⏰ NOTIKRYPTOS · AVISO MACRO · 1 HORA ANTES"
        status = "🟡 PROGRAMADO · Esperado no oficial"
    else:
        heading = "📣 NOTIKRYPTOS · DATO MACRO PUBLICADO"
        status = "✅ PUBLICADO · Real con fuente oficial"
    lines = [
        heading,
        "",
        f"🗓️ {translate_macro_title(event.get('title', 'Evento macroeconómico'))}",
        f"📅 {translate_macro_date(event.get('date', 'Fecha no disponible'))}",
        "",
        f"Anterior: {format_macro_metric(event, event.get('previous'), 'previous')}",
        f"Esperado: {format_macro_metric(event, event.get('expected'), 'expected')}"
        + (
            f" · {event['expected_source']}"
            if event.get("expected_source") else ""
        ),
    ]
    if phase == "publication":
        lines.append(
            f"Real: {format_macro_metric(event, event.get('actual'), 'actual')}"
        )
    else:
        lines.append("Real: pendiente de publicación oficial")
    lines.extend([
        "",
        status,
        f"Fuente: {source_name} · {source}",
        f"🔗 {event.get('link', 'Enlace no disponible')}",
    ])
    return "\n".join(lines)


def run_macro_alerts(state):
    """Publica un aviso una hora antes y otro cuando el dato ya está disponible."""
    now = datetime.now(timezone.utc)
    events = []
    external_events = []
    try:
        external_events = read_showmytrades_macro_calendar()
    except Exception as error:
        print(f"Consenso macro no oficial no disponible: {error}")
    try:
        events.extend(enrich_bls_macro_calendar(read_bls_macro_calendar(), now=now))
    except Exception as error:
        print(f"Agenda BLS no disponible para alertas: {error}")
    try:
        events.extend(read_fomc_agenda())
    except Exception as error:
        print(f"Agenda FOMC no disponible para alertas: {error}")
    try:
        events.extend(read_bea_macro_calendar())
    except Exception as error:
        print(f"Agenda BEA no disponible para alertas: {error}")
    if external_events:
        events = apply_external_macro_data(events, external_events)

    sent = state.setdefault("macro_alerts_sent", {})
    published = 0
    for event in events:
        phase = macro_alert_window(event, now)
        if phase is None:
            continue
        if phase == "publication" and event.get("actual") in (None, ""):
            print(f"Dato oficial todavía no verificable: {event.get('title')}")
            continue
        key = f"{macro_event_id(event)}|{phase}"
        if key in sent:
            continue
        delivery = send_message(format_macro_alert(event, phase))
        sent[key] = {
            "phase": phase,
            "telegram_message_id": delivery.get("message_id"),
            "telegram_chat_id": delivery.get("chat_id"),
            "telegram_date": delivery.get("date"),
            "recorded_at": now.isoformat(),
        }
        published += 1
    if published:
        save_state(state)
    print(f"Alertas macro: {published} aviso(s) publicado(s).")


def format_weekly_report(state, agenda, macro_agenda=None, bea_agenda=None, market_data=None, traditional_market=None, pearson_value=None):
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
    lines.append("📈 BLS · AGENDA MACROECONÓMICA")
    lines.append("────────────────────")
    if macro_agenda:
        for event in macro_agenda[:10]:
            lines.append(format_macro_event(event))
            lines.append("────────────────────")
    else:
        lines.append("No se pudo consultar el calendario BLS en esta ejecución.")
    lines.append("")
    lines.append("🏛️ BEA · AGENDA MACROECONÓMICA")
    lines.append("────────────────────")
    if bea_agenda:
        for event in bea_agenda[:8]:
            lines.append(format_macro_event(event))
            lines.append("────────────────────")
    else:
        lines.append("No se pudo consultar el calendario BEA en esta ejecución.")
    lines.append("")
    lines.append("📈 RESUMEN TÉCNICO SEMANAL · MERCADOS TRADICIONALES")
    lines.append("────────────────────")
    lines.append(format_traditional_comparison(traditional_market or {}))
    lines.append("")
    lines.append("🪙 RESUMEN TÉCNICO SEMANAL · CRIPTO")
    lines.append("────────────────────")
    lines.append(format_crypto_comparison(market_data or {}))
    lines.append("")
    lines.append(format_crypto_intermarket_context(
        pearson_value, traditional_market or {}
    ))
    lines.append("")
    lines.append("⚖️ Alcance")
    lines.append("Resumen informativo basado en publicaciones registradas y calendario oficial.")
    lines.append(f"🔗 Fuente del calendario: {FOMC_CALENDAR_URL}")
    lines.append(f"🔗 Fuente macroeconómica: {BLS_SCHEDULE_URL.format(year=now.year)}")
    lines.append(f"🔗 Fuente BEA: {BEA_SCHEDULE_URL}")
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


def split_telegram_message(text, max_length=3900):
    """Divide mensajes largos sin cortar líneas y deja margen al límite de Telegram."""
    if len(text) <= max_length:
        return [text]
    chunks = []
    current = []
    current_length = 0
    for line in text.splitlines():
        addition = len(line) + (1 if current else 0)
        if current and current_length + addition > max_length:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        current.append(line)
        current_length += len(line) + (1 if current_length else 0)
    if current:
        chunks.append("\n".join(current))
    return chunks


def send_message(text, parse_mode=None):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    deliveries = []
    for chunk in split_telegram_message(text):
        payload = {
            "chat_id": os.environ["TELEGRAM_CHAT_ID"],
            "message_thread_id": int(os.environ["TELEGRAM_TOPIC_ID"]),
            "text": chunk,
            "disable_web_page_preview": False,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
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
                deliveries.append({
                    "message_id": message.get("message_id"),
                    "chat_id": message.get("chat", {}).get("id"),
                    "date": message.get("date"),
                })
                break
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
    if not deliveries:
        raise RuntimeError("Telegram no confirmó la entrega del mensaje.")
    return deliveries[-1]


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
    market_data = {}
    four_hour_changes = {}
    pearson_value = None
    try:
        market_data = read_coinmarketcap_market()
        four_hour_changes = read_binance_four_hour_changes()
        market_snapshot = format_coinmarketcap_snapshot(market_data, four_hour_changes)
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
        pearson_value = read_dxy_btc_pearson(30)
    except Exception as error:
        print(f"Correlación DXY/BTC no disponible: {error}")
    try:
        traditional_market = read_yahoo_market_data()
    except Exception as error:
        print(f"Mercados tradicionales no disponibles: {error}")

    if run_mode == "daily":
        if market_snapshot:
            crypto_sections = [
                market_snapshot,
                format_crypto_comparison(market_data, four_hour_changes),
                format_crypto_intermarket_context(pearson_value, traditional_market),
            ]
            crypto_delivery = send_message(
                "\n\n".join(crypto_sections), parse_mode="HTML"
            )
            print(
                "Informe técnico cripto enviado a Telegram. "
                f"message_id={crypto_delivery.get('message_id')}"
            )
        if sentiment or traditional_market:
            traditional_delivery = send_message(
                format_extended_market_context(
                    sentiment, traditional_market, market_data, pearson_value
                ),
                parse_mode="HTML",
            )
            print(
                "Informe técnico de mercados enviado a Telegram. "
                f"message_id={traditional_delivery.get('message_id')}"
            )

    if run_mode == "macro_alerts":
        run_macro_alerts(state)
        return

    if run_mode == "weekly":
        try:
            agenda = read_fomc_agenda()
            macro_agenda = []
            try:
                macro_agenda = read_bls_macro_calendar()
                macro_agenda = enrich_bls_macro_calendar(macro_agenda)
                print(f"Calendario BLS: {len(macro_agenda)} eventos futuros recibidos.")
            except Exception as error:
                print(f"Calendario BLS no disponible: {error}")
            bea_agenda = []
            try:
                bea_agenda = read_bea_macro_calendar()
                print(f"Calendario BEA: {len(bea_agenda)} eventos futuros recibidos.")
            except Exception as error:
                print(f"Calendario BEA no disponible: {error}")
            weekly_report = format_weekly_report(
                state, agenda, macro_agenda, bea_agenda,
                market_data, traditional_market, pearson_value,
            )
            try:
                official_snapshot = format_official_macro_snapshot()
                if official_snapshot:
                    weekly_report = weekly_report + "\\n\\n" + official_snapshot
            except Exception as error:
                print(f"Datos macro oficiales no disponibles: {error}")
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
