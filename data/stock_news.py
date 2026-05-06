"""
Per-stock news feed.

Primary:   Google News RSS (stock-specific search query — always has results)
Secondary: ET Markets / Mint global feeds (catch market-wide mentions)
Cache:     data_store/news/{SYMBOL}.json  — 2h TTL for results, 20min for empty
"""
import os, re, json, time, html
from xml.etree import ElementTree as ET
from typing import List, Dict, Any, Optional
import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "news")
os.makedirs(CACHE_DIR, exist_ok=True)

TTL_HIT   = 2 * 3600   # 2h for non-empty results
TTL_MISS  = 20 * 60    # 20min if nothing found (retry sooner)

_HDR = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# Supplementary ET/Mint global feeds (broad market news)
_GLOBAL_FEEDS = [
    ("ET Markets",   "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("ET Stocks",    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    ("ET Companies", "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms"),
    ("Mint Markets", "https://www.livemint.com/rss/markets"),
    ("Mint Companies","https://www.livemint.com/rss/companies"),
]

_POS  = re.compile(r"\b(beat|beats|surge|surges|surged|gain|gains|rally|rallies|rises?|rose|jump|jumps|jumped|upgrade|outperform|record|profit|strong|growth|bullish|buy|positive|win|wins|tops?|exceeds?)\b", re.I)
_NEG  = re.compile(r"\b(miss|misses|missed|plunge|plunges|fall|falls|fell|drop|drops|dropped|decline|declines|downgrade|underperform|loss|losses|weak|bearish|sell|negative|probe|fraud|raid|cut|cuts)\b", re.I)
_WARN = re.compile(r"\b(probe|investigation|lawsuit|fraud|raid|sebi|default|warning|alert|scam)\b", re.I)

# In-process cache: symbol → company name from Angel master
_NAME_CACHE: Dict[str, Optional[str]] = {}


# ── Sentiment ──────────────────────────────────────────────────────────────

def _sentiment(text: str) -> str:
    if _WARN.search(text): return "⚠️"
    p = len(_POS.findall(text)); n = len(_NEG.findall(text))
    if p > n + 1: return "📈"
    if n > p + 1: return "📉"
    return "🟰"


# ── RSS parser ─────────────────────────────────────────────────────────────

def _parse_rss(xml_text: str, source: str) -> List[Dict[str, Any]]:
    out = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link  = (item.findtext("link")  or "").strip()
        pub   = (item.findtext("pubDate") or "").strip()
        desc  = re.sub(r"<[^>]+>", "", html.unescape(item.findtext("description") or "")).strip()
        if not title:
            continue
        # Google News appends " - Source Name" to titles — strip it for display
        # e.g. "Bajaj Auto Q4 results - Economic Times" → keep as-is (useful context)
        out.append({"source": source, "title": title, "link": link, "pub": pub, "desc": desc[:300]})
    return out


# ── Company name lookup ────────────────────────────────────────────────────

def _company_name_from_master(symbol: str) -> Optional[str]:
    """Angel One master → human-readable name e.g. 'Bajaj Auto Ltd'. In-process cached."""
    global _NAME_CACHE
    if symbol in _NAME_CACHE:
        return _NAME_CACHE[symbol]
    name = None
    try:
        from data.angel_master import get_nse_equity_df
        df = get_nse_equity_df()
        trading_sym = symbol if symbol.endswith("-EQ") else f"{symbol}-EQ"
        row = df[df["symbol"] == trading_sym]
        if not row.empty:
            v = str(row.iloc[0]["name"]).strip()
            if v and v.lower() not in ("nan", "none", ""):
                name = v
    except Exception:
        pass
    _NAME_CACHE[symbol] = name
    return name


def _search_query(symbol: str) -> str:
    """Build the best Google News search string for this stock.

    Priority: Angel master name (stripped of Ltd/Limited/etc.)
              → hyphen heuristic (BAJAJ-AUTO → 'Bajaj Auto')
              → raw symbol
    """
    name = _company_name_from_master(symbol)
    if name:
        # Strip legal suffixes one pass
        base = re.sub(
            r"\s+(ltd|limited|industries|industry|corporation|corp|inc|india|pvt|private"
            r"|group|solutions|technologies|technology|services|enterprises?)\.?\s*$",
            "", name, flags=re.I
        ).strip()
        return base or name

    if "-" in symbol:
        return symbol.replace("-", " ").title()   # BAJAJ-AUTO → "Bajaj Auto"

    return symbol   # RELIANCE, TCS, etc. often match directly


# ── Per-stock Google News fetch ────────────────────────────────────────────

def _fetch_google_news(query: str) -> List[Dict[str, Any]]:
    """Search Google News RSS for a stock-specific query."""
    import urllib.parse
    q = urllib.parse.quote_plus(f"{query} stock NSE")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        r = requests.get(url, headers=_HDR, timeout=12)
        if r.status_code == 200:
            return _parse_rss(r.text, "Google News")
    except Exception:
        pass
    return []


# ── Global ET/Mint feeds (supplementary) ──────────────────────────────────

_GLOBAL_CACHE_F  = os.path.join(CACHE_DIR, "_all.pkl")
_GLOBAL_CACHE_TTL = 6 * 3600

def _fetch_global_feeds() -> List[Dict[str, Any]]:
    if os.path.exists(_GLOBAL_CACHE_F) and time.time() - os.path.getmtime(_GLOBAL_CACHE_F) < _GLOBAL_CACHE_TTL:
        try:
            import pickle; return pickle.load(open(_GLOBAL_CACHE_F, "rb"))
        except Exception: pass
    items = []
    for src, url in _GLOBAL_FEEDS:
        try:
            r = requests.get(url, headers=_HDR, timeout=10)
            if r.status_code == 200:
                items.extend(_parse_rss(r.text, src))
        except Exception: continue
    try:
        import pickle; pickle.dump(items, open(_GLOBAL_CACHE_F, "wb"))
    except Exception: pass
    return items


def _match_global(items: List[Dict], symbol: str, query: str) -> List[Dict]:
    """Filter global feed items that mention this stock."""
    # Build match terms: raw symbol + words from the search query
    terms = [symbol]
    for word in re.split(r"\s+", query):
        if len(word) >= 4:
            terms.append(word)
    matches = []
    for it in items:
        text = (it["title"] + " " + it.get("desc", "")).lower()
        # Require ALL words of the query to appear (e.g. both "bajaj" and "auto")
        query_words = [w.lower() for w in re.split(r"\s+", query) if len(w) >= 4]
        if query_words and all(re.search(r"\b" + re.escape(w) + r"\b", text) for w in query_words):
            matches.append(it)
        elif re.search(r"\b" + re.escape(symbol.lower()) + r"\b", text):
            matches.append(it)
    return matches


# ── Public API ─────────────────────────────────────────────────────────────

def get_news(symbol: str, limit: int = 5) -> List[Dict[str, Any]]:
    symbol = symbol.upper().strip()
    cache_f = os.path.join(CACHE_DIR, f"{symbol}.json")

    # Serve from cache if fresh
    if os.path.exists(cache_f):
        age = time.time() - os.path.getmtime(cache_f)
        try:
            cached = json.load(open(cache_f))
            ttl = TTL_MISS if len(cached) == 0 else TTL_HIT
            if age < ttl:
                return cached[:limit]
        except Exception:
            pass

    query = _search_query(symbol)

    # Primary: Google News (stock-specific — always returns results if stock exists)
    google_items = _fetch_google_news(query)

    # Secondary: ET/Mint global feed filtered to this stock
    global_items = _match_global(_fetch_global_feeds(), symbol, query)

    # Merge: Google News first (more specific), then global feed
    all_raw = google_items + global_items

    # Build result objects with sentiment
    results = []
    for it in all_raw:
        text = it["title"] + " " + it.get("desc", "")
        results.append({
            "source":    it["source"],
            "title":     it["title"],
            "link":      it["link"],
            "pub":       it["pub"],
            "sentiment": _sentiment(text),
        })

    # Deduplicate by title (first 60 chars)
    seen = set(); uniq = []
    for m in results:
        k = m["title"].lower()[:60]
        if k not in seen:
            seen.add(k); uniq.append(m)

    try:
        json.dump(uniq, open(cache_f, "w"))
    except Exception:
        pass

    return uniq[:limit]
