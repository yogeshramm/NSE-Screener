"""
Per-stock news feed from official RSS sources (Moneycontrol, Mint, ET Markets).
6h disk cache per symbol. Keyword-based sentiment tag.
"""
import os, re, json, time, html, urllib.parse as up
from xml.etree import ElementTree as ET
from typing import List, Dict, Any, Optional
import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "news")
os.makedirs(CACHE_DIR, exist_ok=True)
TTL = 6 * 3600
_EMPTY_CACHE_TTL = 1 * 3600  # re-fetch empty caches after 1h instead of 6h

# Module-level cache: symbol → company name (populated on first lookup)
_NAME_CACHE: Dict[str, Optional[str]] = {}

_HDR = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# Official RSS — live feeds only (Moneycontrol RSS is stale/broken as of 2025)
_FEEDS = [
    ("ET Markets",  "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("ET Stocks",   "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    ("ET Companies","https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms"),
    ("Mint Markets","https://www.livemint.com/rss/markets"),
    ("Mint Companies","https://www.livemint.com/rss/companies"),
]

_POS = re.compile(r"\b(beat|beats|surge|surges|surged|gain|gains|rally|rallies|rises?|rose|jump|jumps|jumped|upgrade|outperform|record|profit|strong|growth|bullish|buy|positive|win|wins|tops?|exceeds?)\b", re.I)
_NEG = re.compile(r"\b(miss|misses|missed|plunge|plunges|fall|falls|fell|drop|drops|dropped|decline|declines|downgrade|underperform|loss|losses|weak|bearish|sell|negative|probe|fraud|raid|cut|cuts)\b", re.I)
_WARN = re.compile(r"\b(probe|investigation|lawsuit|fraud|raid|sebi|default|warning|alert|scam)\b", re.I)


def _sentiment(text: str) -> str:
    if _WARN.search(text): return "⚠️"
    p = len(_POS.findall(text)); n = len(_NEG.findall(text))
    if p > n + 1: return "📈"
    if n > p + 1: return "📉"
    return "🟰"


def _parse_rss(xml_text: str, source: str) -> List[Dict[str, Any]]:
    out = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        desc = re.sub(r"<[^>]+>", "", html.unescape(item.findtext("description") or "")).strip()
        if title:
            out.append({"source": source, "title": title, "link": link, "pub": pub, "desc": desc[:220]})
    return out


def _fetch_all_feeds() -> List[Dict[str, Any]]:
    cache_f = os.path.join(CACHE_DIR, "_all.pkl")
    if os.path.exists(cache_f) and time.time() - os.path.getmtime(cache_f) < TTL:
        try:
            import pickle; return pickle.load(open(cache_f, "rb"))
        except Exception: pass
    items = []
    for src, url in _FEEDS:
        try:
            r = requests.get(url, headers=_HDR, timeout=10)
            if r.status_code == 200:
                items.extend(_parse_rss(r.text, src))
        except Exception: continue
    try:
        import pickle; pickle.dump(items, open(cache_f, "wb"))
    except Exception: pass
    return items


def _match_symbol(item_text: str, symbol: str, aliases: List[str]) -> bool:
    t = item_text.lower()
    for term in [symbol] + aliases:
        if len(term) < 3: continue
        if re.search(r"\b" + re.escape(term.lower()) + r"\b", t):
            return True
    return False


def _company_name_from_master(symbol: str) -> Optional[str]:
    """Look up human-readable company name from Angel One master (e.g. 'Bajaj Auto Ltd').
    Cached in-process; falls back gracefully if master not available."""
    global _NAME_CACHE
    if symbol in _NAME_CACHE:
        return _NAME_CACHE[symbol]
    name = None
    try:
        from data.angel_master import get_nse_equity_df
        df = get_nse_equity_df()
        # Angel symbol format: 'BAJAJ-AUTO-EQ'; our symbol: 'BAJAJ-AUTO'
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


def _aliases(symbol: str) -> List[str]:
    al: List[str] = []

    # 1. Angel master: most reliable source of company names
    master_name = _company_name_from_master(symbol)
    if master_name:
        al.append(master_name)

    # 2. Fundamentals pickle (future-proof: may gain 'company_name' field later)
    fa_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "fundamentals")
    fa_path = os.path.join(fa_dir, f"{symbol}.pkl")
    if os.path.exists(fa_path):
        try:
            import pickle
            fa = pickle.load(open(fa_path, "rb"))
            if isinstance(fa, dict):
                for k in ("company_name", "name", "long_name"):
                    v = fa.get(k)
                    if v and isinstance(v, str) and v not in al:
                        al.append(v)
        except Exception:
            pass

    # 3. Heuristic: NSE symbols with hyphens (BAJAJ-AUTO → "Bajaj Auto")
    #    and M&M style symbols (M&M → "M M" then dropped — keep only if useful)
    if "-" in symbol:
        readable = symbol.replace("-", " ").title()  # "Bajaj Auto"
        if readable not in al:
            al.append(readable)

    # 4. Strip common legal suffixes to get shorter searchable forms
    #    e.g. "Bajaj Auto Limited" → also add "Bajaj Auto"
    more = []
    for n in al:
        base = re.sub(
            r"\s+(ltd|limited|industries|industry|corporation|corp|inc|india|pvt|private|group|solutions|technologies|technology|services|enterprises?)\.?\s*$",
            "", n, flags=re.I
        ).strip()
        if base and base != n and base not in al and base not in more:
            more.append(base)
    return al + more


def get_news(symbol: str, limit: int = 5) -> List[Dict[str, Any]]:
    symbol = symbol.upper().strip()
    cache_f = os.path.join(CACHE_DIR, f"{symbol}.json")
    if os.path.exists(cache_f):
        age = time.time() - os.path.getmtime(cache_f)
        try:
            cached = json.load(open(cache_f))
            # Use cached result if fresh; but re-fetch sooner if cache was empty
            cache_ttl = _EMPTY_CACHE_TTL if len(cached) == 0 else TTL
            if age < cache_ttl:
                return cached[:limit]
        except Exception:
            pass
    items = _fetch_all_feeds()
    aliases = _aliases(symbol)
    matches = []
    for it in items:
        text = f"{it['title']} {it['desc']}"
        if _match_symbol(text, symbol, aliases):
            matches.append({
                "source": it["source"], "title": it["title"], "link": it["link"],
                "pub": it["pub"], "sentiment": _sentiment(text),
            })
    # Dedupe by title
    seen = set(); uniq = []
    for m in matches:
        k = m["title"].lower()[:60]
        if k in seen: continue
        seen.add(k); uniq.append(m)
    try: json.dump(uniq, open(cache_f, "w"))
    except Exception: pass
    return uniq[:limit]
