"""
Per-stock news feed from official RSS sources (Moneycontrol, Mint, ET Markets).
6h disk cache per symbol. Keyword-based sentiment tag.
"""
import os, re, json, time, html, urllib.parse as up
from xml.etree import ElementTree as ET
from typing import List, Dict, Any
import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "news")
os.makedirs(CACHE_DIR, exist_ok=True)
TTL = 6 * 3600

_HDR = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# Official RSS (market / business feeds — per-stock filtering via keyword)
_FEEDS = [
    ("Moneycontrol", "https://www.moneycontrol.com/rss/business.xml"),
    ("Moneycontrol Markets", "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("Moneycontrol Results", "https://www.moneycontrol.com/rss/results.xml"),
    ("Mint Markets", "https://www.livemint.com/rss/markets"),
    ("Mint Companies", "https://www.livemint.com/rss/companies"),
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("ET Stocks", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
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


def _aliases(symbol: str) -> List[str]:
    # Load company name from fundamentals pickle if available
    fa_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "fundamentals")
    fa_path = os.path.join(fa_dir, f"{symbol}.pkl")
    al = []
    if os.path.exists(fa_path):
        try:
            import pickle
            fa = pickle.load(open(fa_path, "rb"))
            if isinstance(fa, dict):
                for k in ("company_name", "name", "long_name"):
                    v = fa.get(k)
                    if v and isinstance(v, str): al.append(v)
        except Exception: pass
    # Strip common suffixes
    more = []
    for n in al:
        base = re.sub(r"\s+(ltd|limited|industries|corporation|corp|inc|india|pvt|private)\.?\s*$", "", n, flags=re.I).strip()
        if base and base != n: more.append(base)
    return al + more


def get_news(symbol: str, limit: int = 5) -> List[Dict[str, Any]]:
    symbol = symbol.upper().strip()
    cache_f = os.path.join(CACHE_DIR, f"{symbol}.json")
    if os.path.exists(cache_f) and time.time() - os.path.getmtime(cache_f) < TTL:
        try: return json.load(open(cache_f))[:limit]
        except Exception: pass
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
