"""
Per-stock news feed.

Primary:   Google News RSS (stock-specific search query)
Secondary: Business Standard, ET, Mint, Business Line, Moneycontrol direct feeds
           filtered to this stock

Results sorted by: recency desc → preferred source rank → others
Cache:     data_store/news/{SYMBOL}.json  — 30min TTL
"""
import os, re, json, time, html
from xml.etree import ElementTree as ET
from typing import List, Dict, Any, Optional
import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "news")
os.makedirs(CACHE_DIR, exist_ok=True)

TTL_HIT  = 30 * 60   # 30min — fresh enough for trading
TTL_MISS = 10 * 60   # 10min if nothing found (retry sooner)
BULK_TTL = 2 * 3600  # 2h — pre-fetch bulk cache (written by news_prefetch.py)

_HDR = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# ── Preferred source order ─────────────────────────────────────────────────
# Lower rank = shown first (when articles have same recency)
_SOURCE_RANK: Dict[str, int] = {
    "business standard": 1,
    "economic times":    2,
    "et markets":        2,
    "business line":     3,
    "hindu business":    3,
    "moneycontrol":      4,
    "mint":              5,
    "livemint":          5,
    "live mint":         5,
}

def _source_rank(source_str: str) -> int:
    s = source_str.lower()
    for key, rank in _SOURCE_RANK.items():
        if key in s:
            return rank
    return 9  # unknown sources shown last

# Sources to skip entirely (low quality / non-news / non-English outlets)
_SKIP_SOURCES = {
    "simplywall.st", "simply wall st", "equitypandit", "moneymunch",
    "scanx.trade", "latestsly", "latestly", "tradingview",
    "tickertape", "trendlyne",
}

def _is_quality_item(item: Dict[str, Any]) -> bool:
    """Return False for low-quality or non-English articles."""
    src = item.get("source", "").lower()
    if any(skip in src for skip in _SKIP_SOURCES):
        return False
    # Skip titles with heavy non-ASCII (Hindi/other scripts)
    title = item.get("title", "")
    non_ascii = sum(1 for c in title if ord(c) > 127)
    if non_ascii > len(title) * 0.3:   # >30% non-ASCII → skip
        return False
    return True

# ── Preferred direct RSS feeds (checked first, before Google News) ──────────
# These carry today's articles reliably; fetched once per 30min (shared cache)
_DIRECT_FEEDS = [
    ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss"),
    ("Business Standard", "https://www.business-standard.com/rss/companies-101.rss"),
    ("Economic Times",    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    ("Economic Times",    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Mint",              "https://www.livemint.com/rss/markets"),
    ("Mint",              "https://www.livemint.com/rss/companies"),
    ("Business Line",     "https://www.thehindubusinessline.com/markets/?service=rss"),
    ("Moneycontrol",      "https://www.moneycontrol.com/rss/buzzingstocks.xml"),
]

# ── Sentiment ──────────────────────────────────────────────────────────────
_POS  = re.compile(r"\b(beat|beats|surge|surges|surged|gain|gains|rally|rallies|rises?|rose|jump|jumps|jumped|upgrade|outperform|record|profit|strong|growth|bullish|buy|positive|win|wins|tops?|exceeds?)\b", re.I)
_NEG  = re.compile(r"\b(miss|misses|missed|plunge|plunges|fall|falls|fell|drop|drops|dropped|decline|declines|downgrade|underperform|loss|losses|weak|bearish|sell|negative|probe|fraud|raid|cut|cuts)\b", re.I)
_WARN = re.compile(r"\b(probe|investigation|lawsuit|fraud|raid|sebi|default|warning|alert|scam)\b", re.I)

def _sentiment(text: str) -> str:
    if _WARN.search(text): return "⚠️"
    p = len(_POS.findall(text)); n = len(_NEG.findall(text))
    if p > n + 1: return "📈"
    if n > p + 1: return "📉"
    return "🟰"


# ── Date parsing ───────────────────────────────────────────────────────────
def _pub_ts(pub_str: str) -> float:
    """Parse RSS pubDate → Unix timestamp. Returns 0 on failure."""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(pub_str).timestamp()
    except Exception:
        return 0.0

def _fmt_pub(pub_str: str) -> str:
    """Format pub date for display: 'Wed, 07 May 2026 14:30' → '07 May 2026, 2:30 PM'"""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pub_str)
        # Convert to IST (UTC+5:30)
        import datetime
        ist = dt.utctimetuple()
        # Simple: just format the original datetime nicely
        return dt.strftime("%-d %b %Y, %-I:%M %p")
    except Exception:
        return pub_str[:16] if pub_str else ""


# ── RSS parser ─────────────────────────────────────────────────────────────
def _parse_rss(xml_text: str, default_source: str) -> List[Dict[str, Any]]:
    out = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out
    for item in root.iter("item"):
        raw_title = (item.findtext("title") or "").strip()
        link  = (item.findtext("link")  or "").strip()
        pub   = (item.findtext("pubDate") or "").strip()
        desc  = re.sub(r"<[^>]+>", "", html.unescape(item.findtext("description") or "")).strip()
        if not raw_title:
            continue

        # Google News appends " - Source Name" to titles — extract and strip it
        title = raw_title
        source = default_source
        if default_source == "Google News" and " - " in raw_title:
            parts = raw_title.rsplit(" - ", 1)
            title  = parts[0].strip()
            source = parts[1].strip()   # e.g. "Economic Times", "Moneycontrol.com"

        out.append({
            "source": source,
            "title":  title,
            "link":   link,
            "pub":    pub,
            "desc":   desc[:300],
            "_ts":    _pub_ts(pub),
            "_rank":  _source_rank(source),
        })
    return out


# ── Company name lookup ────────────────────────────────────────────────────

# Brand overrides: legal name ≠ media name, or stock missing from NSE CSV
_BRAND_OVERRIDE: Dict[str, str] = {
    "TATAMOTORS":   "Tata Motors",
    "TATACONSUM":   "Tata Consumer Products",
    "TATASTEEL":    "Tata Steel",
    "TATAPOWER":    "Tata Power",
    "HDFCBANK":     "HDFC Bank",
    "ICICIBANK":    "ICICI Bank",
    "KOTAKBANK":    "Kotak Mahindra Bank",
    "AXISBANK":     "Axis Bank",
    "INDUSINDBK":   "IndusInd Bank",
    "BAJFINANCE":   "Bajaj Finance",
    "BAJAJFINSV":   "Bajaj Finserv",
    "BAJAJ-AUTO":   "Bajaj Auto",
    "ZOMATO":       "Zomato",
    "NYKAA":        "Nykaa",
    "PAYTM":        "Paytm",
    "SWIGGY":       "Swiggy",
    "MAPMYINDIA":   "MapMyIndia",
    "POLICYBZR":    "Policybazaar",
    "DELHIVERY":    "Delhivery",
    "IXIGO":        "Ixigo",
    "FIRSTCRY":     "FirstCry",
    "YATHARTH":     "Yatharth Hospital",
    "LTIM":         "LTIMindtree",
    "LTTS":         "L&T Technology Services",
    "LT":           "Larsen and Toubro",
    "RELIANCE":     "Reliance Industries",
    "SUNPHARMA":    "Sun Pharma",
    "DRREDDY":      "Dr Reddys",
    "CIPLA":        "Cipla",
    "APOLLOHOSP":   "Apollo Hospitals",
    "ONGC":         "ONGC",
    "NTPC":         "NTPC",
    "POWERGRID":    "Power Grid",
    "COALINDIA":    "Coal India",
}

# NSE equity full-name map from EQUITY_L.csv (7-day TTL cache)
_NSE_NAME_MAP: Dict[str, str] = {}
_NSE_NAME_MAP_READY: bool = False
_NSE_NAMES_CACHE_F = os.path.join(CACHE_DIR, "_nse_names.json")
_SUFFIX_RE = re.compile(
    r"\s+(limited|ltd\.?|industries|industry|corporation|corp\.?|inc\.?"
    r"|pvt\.?|private|enterprises?|laboratories|lab)\.?\s*$",
    re.I,
)

def _load_nse_name_map() -> None:
    global _NSE_NAME_MAP, _NSE_NAME_MAP_READY
    if _NSE_NAME_MAP_READY:
        return
    # Try local 7-day cache first
    if os.path.exists(_NSE_NAMES_CACHE_F):
        age = time.time() - os.path.getmtime(_NSE_NAMES_CACHE_F)
        if age < 7 * 86400:
            try:
                _NSE_NAME_MAP.update(json.load(open(_NSE_NAMES_CACHE_F)))
                _NSE_NAME_MAP_READY = True
                return
            except Exception:
                pass
    # Fetch from NSE archives
    try:
        import csv, io
        r = requests.get(
            "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
            timeout=15,
        )
        if r.status_code == 200:
            reader = csv.DictReader(io.StringIO(r.text))
            for row in reader:
                sym  = row.get("SYMBOL", "").strip()
                name = row.get("NAME OF COMPANY", "").strip()
                if sym and name:
                    _NSE_NAME_MAP[sym] = name
            try:
                json.dump(_NSE_NAME_MAP, open(_NSE_NAMES_CACHE_F, "w"))
            except Exception:
                pass
    except Exception:
        pass
    _NSE_NAME_MAP_READY = True


def _search_query(symbol: str) -> str:
    """Return the best search query for this symbol's news."""
    # 1. Hard-coded brand override (highest priority)
    if symbol in _BRAND_OVERRIDE:
        return _BRAND_OVERRIDE[symbol]

    # 2. NSE EQUITY_L.csv — full legal name, stripped of generic suffixes
    _load_nse_name_map()
    raw = _NSE_NAME_MAP.get(symbol, "")
    if raw:
        cleaned = _SUFFIX_RE.sub("", raw).strip()
        return cleaned if cleaned else raw

    # 3. Hyphenated symbol → title-case words (e.g. BAJAJ-AUTO → "Bajaj Auto")
    if "-" in symbol:
        return symbol.replace("-", " ").title()

    # 4. Symbol as-is (Google News often recognises tickers directly)
    return symbol


# ── Google News fetch ──────────────────────────────────────────────────────
def _fetch_google_news(query: str) -> List[Dict[str, Any]]:
    import urllib.parse
    q = urllib.parse.quote_plus(f"{query} NSE stock")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        r = requests.get(url, headers=_HDR, timeout=12)
        if r.status_code == 200:
            return _parse_rss(r.text, "Google News")
    except Exception:
        pass
    return []


# ── Direct preferred-source feeds (shared 30-min cache) ───────────────────
_DIRECT_CACHE_F   = os.path.join(CACHE_DIR, "_direct.pkl")
_DIRECT_CACHE_TTL = 30 * 60   # refresh every 30 min

def _fetch_direct_feeds() -> List[Dict[str, Any]]:
    if os.path.exists(_DIRECT_CACHE_F):
        age = time.time() - os.path.getmtime(_DIRECT_CACHE_F)
        if age < _DIRECT_CACHE_TTL:
            try:
                import pickle
                return pickle.load(open(_DIRECT_CACHE_F, "rb"))
            except Exception:
                pass
    items = []
    for src, url in _DIRECT_FEEDS:
        try:
            r = requests.get(url, headers=_HDR, timeout=10)
            if r.status_code == 200:
                items.extend(_parse_rss(r.text, src))
        except Exception:
            continue
    try:
        import pickle
        pickle.dump(items, open(_DIRECT_CACHE_F, "wb"))
    except Exception:
        pass
    return items

def _match_direct(items: List[Dict], query: str, symbol: str) -> List[Dict]:
    """Return direct-feed items that mention this stock by name or symbol."""
    query_words = [w.lower() for w in re.split(r"\s+", query) if len(w) >= 4]
    out = []
    for it in items:
        text = (it["title"] + " " + it.get("desc", "")).lower()
        if query_words and all(re.search(r"\b" + re.escape(w) + r"\b", text) for w in query_words):
            out.append(it)
        elif len(symbol) >= 4 and re.search(r"\b" + re.escape(symbol.lower()) + r"\b", text):
            out.append(it)
    return out


# ── Merge + sort ───────────────────────────────────────────────────────────
def _merge_and_sort(all_raw: List[Dict], limit: int) -> List[Dict]:
    """Deduplicate, sort by recency desc then source rank, build final dicts."""
    # Quality filter first
    all_raw = [it for it in all_raw if _is_quality_item(it)]
    # Sort: most recent first; among same-day, preferred source first
    now = time.time()
    all_raw.sort(key=lambda x: (-(x.get("_ts") or 0), x.get("_rank", 9)))

    seen: set = set()
    out: List[Dict] = []
    for it in all_raw:
        k = it["title"].lower()[:60]
        if k in seen:
            continue
        seen.add(k)
        text = it["title"] + " " + it.get("desc", "")
        out.append({
            "source":    it["source"],
            "title":     it["title"],
            "link":      it["link"],
            "pub":       it["pub"],
            "pub_fmt":   _fmt_pub(it["pub"]),   # formatted for display
            "sentiment": _sentiment(text),
            "age_days":  round((now - (it.get("_ts") or now)) / 86400, 1),
        })
        if len(out) >= limit * 4:   # collect more than needed before slicing
            break
    return out[:limit]


# ── Public API ─────────────────────────────────────────────────────────────
def get_news_fetched_at(symbol: str) -> Optional[float]:
    cache_f = os.path.join(CACHE_DIR, f"{symbol.upper().strip()}.json")
    return os.path.getmtime(cache_f) if os.path.exists(cache_f) else None


def get_news(symbol: str, limit: int = 5) -> List[Dict[str, Any]]:
    symbol = symbol.upper().strip()
    cache_f = os.path.join(CACHE_DIR, f"{symbol}.json")

    if os.path.exists(cache_f):
        age = time.time() - os.path.getmtime(cache_f)
        try:
            cached = json.load(open(cache_f))
            ttl = TTL_MISS if len(cached) == 0 else TTL_HIT
            if age < ttl:
                return cached[:limit]
        except Exception:
            pass

    # Bulk pre-fetch fallback (written by news_prefetch.py at 4 PM / 6 PM IST)
    bulk_f = os.path.join(CACHE_DIR, f"_bulk_{symbol}.json")
    if os.path.exists(bulk_f):
        bulk_age = time.time() - os.path.getmtime(bulk_f)
        if bulk_age < BULK_TTL:
            try:
                cached = json.load(open(bulk_f))
                if cached:
                    return cached[:limit]
            except Exception:
                pass

    query = _search_query(symbol)

    # 1. Direct preferred-source feeds (Business Standard, ET, Mint, BL, MC)
    direct = _match_direct(_fetch_direct_feeds(), query, symbol)

    # 2. Google News (wider net, real source extracted from title)
    google = _fetch_google_news(query)

    # Merge: direct feeds have proper source labels; Google adds breadth
    uniq = _merge_and_sort(direct + google, limit)

    try:
        json.dump(uniq, open(cache_f, "w"))
    except Exception:
        pass
    return uniq
