import json
import os
import re
import unicodedata
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


FED_RSS_URL = "https://www.federalreserve.gov/feeds/press_all.xml"
TREASURY_RSS_URL = "https://home.treasury.gov/rss.xml"

TREASURY_KEYWORDS = [
    "sanctions",
    "sanction",
    "ofac",
    "debt",
    "liquidity",
    "financial",
    "finance",
    "terrorist financing",
    "money laundering",
    "north korea",
    "dprk",
    "iran",
    "russia",
    "cyber",
    "crypto",
    "digital asset",
    "virtual currency",
]

COINBASE_INCIDENTS_URL = (
    "https://status.coinbase.com/api/v2/incidents/unresolved.json"
)

BINANCE_ANNOUNCEMENTS_URL = (
    "https://www.binance.com/bapi/composite/v1/public/"
    "cms/article/catalog/list/query"
)

BINANCE_CATALOG_IDS = [
    49,
    161,
]

BINANCE_KEYWORDS = [
    "security",
    "incident",
    "hack",
    "hacked",
    "unauthorized",
    "withdrawal",
    "withdrawals",
    "deposit",
    "deposits",
    "suspend",
    "suspended",
    "suspension",
    "security incident",
    "service disruption",
    "maintenance",
    "funds",
    "stolen",
    "breach",
    "exploit",
    "wallet",
    "retiro",
    "retiros",
    "depósito",
    "depósitos",
    "seguridad",
    "incidente",
    "hackeo",
]
CMC_QUOTES_URL = (
    "https://pro-api.coinmarketcap.com/v3/"
    "cryptocurrency/quotes/latest"
)

CMC_HISTORICAL_URL = (
    "https://pro-api.coinmarketcap.com/v2/"
    "cryptocurrency/ohlcv/historical"
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
MAX_NEWS_AGE_HOURS = 48


def http_get_json(url, headers=None):
    request = urllib.request.Request(
        url,
        headers=headers or {},
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_news_datetime(value):
    if not value:
        return None

    value = value.strip()

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        parsed = None

    if parsed is None:
        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            parsed = None

    if parsed is None:
        match = re.search(
            r"(20\d{2})[-/](\d{2})[-/](\d{2})",
            value,
        )

        if match:
            try:
                parsed = datetime(
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                parsed = None

    if parsed is None:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def is_recent_news(published):
    parsed = parse_news_datetime(published)

    if parsed is None:
        return False

    now = datetime.now(timezone.utc)
    age = now - parsed

    return timedelta(0) <= age <= timedelta(
        hours=MAX_NEWS_AGE_HOURS
    )


def format_published_date(published):
    parsed = parse_news_datetime(published)

    if parsed is None:
        return published or "Fecha no disponible"

    return parsed.strftime("%Y-%m-%d %H:%M UTC")


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

    title = item.findtext(
        "title",
        default="Sin título",
    ).strip()

    link = item.findtext(
        "link",
        default="",
    ).strip()

    published = item.findtext(
        "pubDate",
        default="",
    ).strip()

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

def read_treasury_news():
    request = urllib.request.Request(
        TREASURY_RSS_URL,
        headers={
            "User-Agent": os.environ["SEC_USER_AGENT"],
            "Accept": "application/rss+xml, application/xml",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        content = response.read()

    root = ET.fromstring(content)
    candidates = []

    for element in root.iter():
        tag_name = element.tag.split("}")[-1]

        if tag_name != "item":
            continue

        title = element.findtext(
            "title",
            default="Sin título",
        ).strip()

        title_lower = title.lower()

        description = element.findtext(
            "description",
            default="",
        ).strip()

        description_lower = description.lower()

        relevant = any(
            keyword in title_lower
            or keyword in description_lower
            for keyword in TREASURY_KEYWORDS
        )

        if not relevant:
            continue

        link = element.findtext(
            "link",
            default="",
        ).strip()

        published = element.findtext(
            "pubDate",
            default="",
        ).strip()

        if not link:
            link = TREASURY_RSS_URL

        candidates.append(
            {
                "id": f"treasury:{link or title}",
                "source": "U.S. Treasury",
                "title": title,
                "link": link,
                "published": published,
                "details": description,
            }
        )

    if not candidates:
        print(
            "Treasury: no se encontró un comunicado relevante."
        )
        return []

    def treasury_date(item):
        parsed = parse_news_datetime(
            item["published"]
        )

        if parsed is None:
            return datetime.min.replace(
                tzinfo=timezone.utc
            )

        return parsed

    latest = max(
        candidates,
        key=treasury_date,
    )

    print(
        f"Treasury detectado: {latest['title']}"
    )

    return [latest]


def read_coinbase_incidents():
    data = http_get_json(COINBASE_INCIDENTS_URL)
    incidents = []

    for incident in data.get("incidents", []):
        incident_id = incident.get("id", "")
        incident_name = incident.get(
            "name",
            "Incidente en Coinbase",
        )
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
                "link": shortlink
                or "https://status.coinbase.com/",
                "published": updated_at,
                "details": details,
            }
        )

    print(
        f"Coinbase Status: {len(incidents)} "
        "incidentes abiertos encontrados."
    )

    return incidents


def normalize_binance_title(title):
    normalized = unicodedata.normalize(
        "NFKD",
        title,
    )

    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )

    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)

    return normalized.strip()


def resolve_binance_url(url, headers):
    request = urllib.request.Request(
        url,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:
            return response.geturl()

    except Exception:
        return url


def read_binance_news():
    news = []
    seen_canonical_ids = set()

    headers = {
        "User-Agent": os.environ["SEC_USER_AGENT"],
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    for catalog_id in BINANCE_CATALOG_IDS:
        query = urllib.parse.urlencode(
            {
                "catalogId": catalog_id,
                "pageNo": 1,
                "pageSize": 20,
            }
        )

        url = f"{BINANCE_ANNOUNCEMENTS_URL}?{query}"

        data = http_get_json(
            url,
            headers=headers,
        )

        response_data = data.get("data") or {}
        articles = response_data.get("articles") or []

        for article in articles:
            title = (
                article.get("title")
                or "Anuncio de Binance"
            ).strip()

            title_lower = title.lower()

            relevant = any(
                keyword in title_lower
                for keyword in BINANCE_KEYWORDS
            )

            if not relevant:
                continue

            article_id = str(
                article.get("id")
                or article.get("code")
                or title
            )

            code = article.get("code", "")
            short_link = article.get("shortLink", "")

            if short_link:
                article_link = short_link
            elif code:
                article_link = (
                    "https://www.binance.com/en/support/"
                    f"announcement/{code}"
                )
            else:
                article_link = (
                    "https://www.binance.com/en/support/"
                    "announcement"
                )

            resolved_link = resolve_binance_url(
                article_link,
                headers,
            )

            normalized_title = normalize_binance_title(
                title
            )

            canonical_value = (
                f"{resolved_link}|{normalized_title}"
            )

            canonical_id = f"binance:{canonical_value}"

            if canonical_id in seen_canonical_ids:
                continue

            seen_canonical_ids.add(canonical_id)

            published = (
                article.get("releaseDate")
                or article.get("publishDate")
                or ""
            )

            if isinstance(published, (int, float)):
                published = datetime.fromtimestamp(
                    published / 1000,
                    tz=timezone.utc,
                ).isoformat()

            if not published:
                date_match = re.search(
                    r"(20\d{2})[-/](\d{2})[-/](\d{2})",
                    title,
                )

                if date_match:
                    published = (
                        f"{date_match.group(1)}-"
                        f"{date_match.group(2)}-"
                        f"{date_match.group(3)}"
                    )

            if not published:
                print(
                    "Binance: anuncio relevante sin fecha, "
                    f"omitido: {title}"
                )
                continue

            details = (
                "Comunicado oficial publicado por Binance.\n"
                f"Categoría consultada: {catalog_id}"
            )

            news.append(
                {
                    "id": canonical_id,
                    "legacy_ids": [
                        f"binance:{article_id}",
                    ],
                    "source": "Binance",
                    "title": title,
                    "link": resolved_link,
                    "published": published,
                    "details": details,
                }
            )

            print(
                f"Binance detectado: {title}"
            )

    security_updates = [
        item
        for item in news
        if "security incident" in item["title"].lower()
    ]

    if len(security_updates) > 1:
        def update_priority(item):
            title_lower = item["title"].lower()
            published_date = parse_news_datetime(
                item["published"]
            )

            if published_date is None:
                published_date = datetime.min.replace(
                    tzinfo=timezone.utc
                )

            update_number = 0
            match = re.search(
                r"(?:update|recovery update)\s*#?(\d+)",
                title_lower,
            )

            if match:
                update_number = int(match.group(1))

            return (
                published_date,
                update_number,
            )

        latest_update = max(
            security_updates,
            key=update_priority,
        )

        news = [
            item
            for item in news
            if item not in security_updates
        ]

        news.append(latest_update)

        print(
            "Binance: se conservará únicamente la "
            "actualización más reciente del incidente."
        )

    print(
        f"Binance: {len(news)} "
        "anuncios relevantes encontrados."
    )

    return news

def read_coinmarketcap_ohlcv(interval, count):
    api_key = os.environ["CMC_API_KEY"]

    query = urllib.parse.urlencode(
        {
            "slug": (
                "bitcoin,ethereum,solana,"
                "near-protocol"
            ),
            "interval": interval,
            "count": count,
            "convert": "USD",
            "skip_invalid": "true",
        }
    )

    url = f"{CMC_HISTORICAL_URL}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-CMC_PRO_API_KEY": api_key,
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        result = json.loads(
            response.read().decode("utf-8")
        )

    historical_data = result.get("data", {})

    if not historical_data:
        raise RuntimeError(
            f"CoinMarketCap no devolvió datos para {interval}."
        )

    print(
        f"CoinMarketCap: datos históricos recibidos "
        f"para intervalo {interval}."
    )

    return historical_data


def read_coinmarketcap_market():
    api_key = os.environ["CMC_API_KEY"]

    query = urllib.parse.urlencode(
        {
            "slug": (
                "bitcoin,ethereum,solana,"
                "near-protocol"
            ),
            "convert": "USD",
        }
    )

    url = f"{CMC_QUOTES_URL}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-CMC_PRO_API_KEY": api_key,
        },
    )

    with urllib.request.urlopen(
    request,
    timeout=30,
) as response:
        result = json.loads(
            response.read().decode("utf-8")
        )

    market_data = result.get(
        "data",
        {},
    )

    if not market_data:
        raise RuntimeError(
            "CoinMarketCap no devolvió datos de mercado."
        )

    print(
        "CoinMarketCap: cotizaciones actuales recibidas "
        f"para {len(market_data)} activos."
    )

    return {
        "quotes": market_data,
    }

def format_coinmarketcap_snapshot(market_data):
    lines = [
        "📊 Estado actual del mercado cripto",
        "",
    ]

    quotes = market_data.get(
        "quotes",
        {},
    )

    names = {
        "1": "BTC",
        "1027": "ETH",
        "5426": "SOL",
        "6535": "NEAR",
    }

    for asset_id, asset in quotes.items():
        symbol = names.get(
            str(asset_id),
            asset.get("symbol", "ACTIVO"),
        )

        quote_data = asset.get(
            "quote",
            {},
        )

        if isinstance(quote_data, list):
            if not quote_data:
                continue

            quote_data = quote_data[0]

        usd = quote_data.get(
            "USD",
            {},
        )

        price = usd.get(
            "price",
            "N/D",
        )

        change_1h = usd.get(
            "percent_change_1h",
            "N/D",
        )

        change_24h = usd.get(
            "percent_change_24h",
            "N/D",
        )

        change_7d = usd.get(
            "percent_change_7d",
            "N/D",
        )

        change_30d = usd.get(
            "percent_change_30d",
            "N/D",
        )

        lines.append(
            f"{symbol}: ${price}"
        )

        lines.append(
            f"1 h: {change_1h}% · "
            f"24 h: {change_24h}% · "
            f"7 d: {change_7d}% · "
            f"30 d: {change_30d}%"
        )

        lines.append("")

    return "\n".join(lines)



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

        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            content = response.read()

        root = ET.fromstring(content)
        entries = []

        for element in root.iter():
            tag_name = element.tag.split("}")[-1]

            if tag_name in {"item", "entry"}:
                entries.append(element)

        if not entries:
            print(
                f"{source_name}: "
                "no se encontró ningún comunicado."
            )
            continue

        item = entries[0]

        def get_text(element, names):
            for child in element:
                child_name = child.tag.split("}")[-1]

                if child_name in names:
                    return (child.text or "").strip()

            return ""

        title = get_text(
            item,
            ["title"],
        )

        published = get_text(
            item,
            [
                "pubDate",
                "published",
                "updated",
                "date",
            ],
        )

        details = get_text(
            item,
            [
                "description",
                "summary",
                "content",
            ],
        )

        link = ""

        for child in item:
            child_name = child.tag.split("}")[-1]

            if child_name == "link":
                link = (
                    child.attrib.get("href", "")
                    or child.text
                    or ""
                ).strip()

                if link:
                    break

        if not title:
            title = "Sin título"

        if not published:
            published = "Fecha no disponible"

        if not link:
            link = feed_url

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

        print(
            f"{source_name}: comunicado encontrado."
        )

    print(
        f"BLS: {len(news)} comunicados encontrados."
    )

    return news


def collect_news():
    news = []

    try:
        news.extend(read_federal_reserve_news())
    except urllib.error.HTTPError as error:
        print(
            "Federal Reserve no disponible temporalmente: "
            f"HTTP {error.code}"
        )
    except Exception as error:
        print(
            f"Error consultando Federal Reserve: {error}"
        )
    try:
        news.extend(read_treasury_news())
    except urllib.error.HTTPError as error:
        print(
            "Treasury no disponible temporalmente: "
            f"HTTP {error.code}"
        )
    except Exception as error:
        print(
            f"Error consultando Treasury: {error}"
        )

    try:
        news.extend(read_coinbase_incidents())
   
    except urllib.error.HTTPError as error:
        print(
            "Coinbase Status no disponible temporalmente: "
            f"HTTP {error.code}"
        )
    except Exception as error:
        print(
            f"Error consultando Coinbase Status: {error}"
        )

    try:
        news.extend(read_binance_news())
    except urllib.error.HTTPError as error:
        print(
            "Binance no disponible temporalmente: "
            f"HTTP {error.code}"
        )
    except Exception as error:
        print(
            f"Error consultando Binance: {error}"
        )

    try:
        news.extend(read_bls_news())
    except urllib.error.HTTPError as error:
        print(
            f"BLS no disponible temporalmente: "
            f"HTTP {error.code}"
        )
    except Exception as error:
        print(
            f"Error consultando BLS: {error}"
        )

    return news


def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "processed_ids": []
        }

    with open(
        STATE_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        state = json.load(file)

    state.setdefault(
        "processed_ids",
        [],
    )

    return state


def save_state(state):
    state["processed_ids"] = state[
        "processed_ids"
    ][-MAX_PROCESSED_IDS:]

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
        )


def analyze_news(news):
    api_key = os.environ["GEMINI_API_KEY"]

    encoded_key = urllib.parse.quote(
        api_key,
        safe="",
    )

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
- listados;
- airdrops;
- competencias;
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
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    result = None

    for attempt in range(3):
        try:
            with urllib.request.urlopen(
                request,
                timeout=60,
            ) as response:
                result = json.loads(
                    response.read().decode("utf-8")
                )

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
        raise RuntimeError(
            "Gemini no devolvió una respuesta."
        )

    candidates = result.get(
        "candidates",
        [],
    )

    if not candidates:
        raise RuntimeError(
            "Gemini no devolvió una respuesta."
        )

    generated_text = candidates[0]["content"]["parts"][0][
        "text"
    ].strip()

    content = json.loads(generated_text)

    required_fields = {
        "relevance",
        "title_es",
        "summary_es",
        "impact_es",
    }

    if not required_fields.issubset(content):
        raise RuntimeError(
            "La respuesta de Gemini no tiene el formato esperado."
        )

    content["relevance"] = content[
        "relevance"
    ].upper().strip()

    if content["relevance"] not in {
        "ALTA",
        "MEDIA",
        "BAJA",
        "DESCARTAR",
    }:
        raise RuntimeError(
            "Gemini devolvió una clasificación no válida."
        )

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
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        result = json.loads(
            response.read().decode("utf-8")
        )

    if not result.get("ok"):
        raise RuntimeError(result)


def build_message(news, analysis):
    company_notice = ""

    if news["source"] == "Coinbase Status":
        company_notice = (
            "⚖️ Estado de la información\n\n"
            "Comunicado oficial de Coinbase Status.\n\n"
        )

    if news["source"] == "Binance":
        company_notice = (
            "⚖️ Estado de la información\n\n"
            "Comunicado oficial de Binance.\n\n"
        )

    published = format_published_date(
        news["published"]
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
        f"{published}\n\n"
        "🏛️ Fuente\n\n"
        f"{news['source']}\n\n"
        "🔗 Documento oficial\n\n"
        f"{news['link']}"
    )


def main():
    state = load_state()

    try:
        read_coinmarketcap_market()

    except urllib.error.HTTPError as error:
        error_body = error.read().decode(
            "utf-8",
            errors="replace",
        )

        print(
            "CoinMarketCap no disponible: "
            f"HTTP {error.code} — {error_body}"
        )

    except Exception as error:
        print(
            f"Error consultando CoinMarketCap: {error}"
        )

    news_items = collect_news()

    if not news_items:
        print(
            "No se encontraron noticias o incidentes nuevos."
        )
        return

    processed_any = False

    for news in news_items:
        news_id = news["id"]

        legacy_ids = news.get(
            "legacy_ids",
            [],
        )

        already_processed = (
            news_id in state["processed_ids"]
            or any(
                old_id in state["processed_ids"]
                for old_id in legacy_ids
            )
        )

        if already_processed:
            continue

        if not is_recent_news(news["published"]):
            print(
                f"{news['source']}: comunicado antiguo o "
                f"sin fecha válida omitido. "
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
                print(
                    "Gemini no está disponible. "
                    "La noticia queda pendiente para otra ejecución."
                )
                return

            raise

        relevance = analysis["relevance"]

        state["processed_ids"].append(news_id)
        save_state(state)
        processed_any = True

        if relevance in {
            "BAJA",
            "DESCARTAR",
        }:
            print(
                f"{news['source']}: noticia no publicada. "
                f"Nivel de relevancia: {relevance}."
            )
            continue

        message = build_message(
            news,
            analysis,
        )

        send_message(message)

        print(
            f"{news['source']}: noticia publicada. "
            f"Nivel de relevancia: {relevance}."
        )

    if not processed_any:
        print(
            "No hay noticias nuevas para procesar."
        )

if __name__ == "__main__":
    main()
