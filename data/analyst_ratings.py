"""
Analyst Signal aggregator — free sources only.

Three inputs, combined per stock:
  A. Moneycontrol broker consensus (scrape target price + buy/hold/sell split)
  B. yfinance recommendationMean + numberOfAnalystOpinions
  C. Upgrade/downgrade activity from our existing RSS news cache (30d)

24h per-symbol disk cache at data_store/analyst/{SYM}.json.
All three sources are best-effort; missing ones just get omitted.
"""
import os, re, json, time, html, asyncio
from typing import Dict, Any, Optional, List
import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "analyst")
os.makedirs(CACHE_DIR, exist_ok=True)
TTL = 24 * 3600

_HDR = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-IN,en;q=0.9",
}


# ---------- A. Moneycontrol ----------
_MC_SCID_CACHE = os.path.join(CACHE_DIR, "_mc_scid_map.json")


def _mc_scid(symbol: str) -> Optional[str]:
    """Resolve symbol → Moneycontrol internal SC_ID via their autosuggest API.
    Note: MC often 403s direct calls; degrade gracefully when blocked."""
    cache = {}
    if os.path.exists(_MC_SCID_CACHE):
        try: cache = json.load(open(_MC_SCID_CACHE))
        except Exception: cache = {}
    if symbol in cache: return cache[symbol]
    try:
        url = f"https://www.moneycontrol.com/mccode/common/autosuggesion.php?query={symbol}&type=1&format=json"
        mc_hdr = {**_HDR, "Referer": "https://www.moneycontrol.com/", "X-Requested-With": "XMLHttpRequest"}
        r = requests.get(url, headers=mc_hdr, timeout=10)
        if r.status_code == 403:
            cache[symbol] = None  # don't retry for TTL
        if r.status_code == 200:
            # Response is JSONP-ish: "({...})"
            text = r.text.strip()
            m = re.search(r'\[(.*?)\]', text, re.S) or re.search(r'\{.*\}', text, re.S)
            if m:
                data = json.loads("[" + m.group(1) + "]" if m.group(0).startswith("[") else m.group(0))
                if isinstance(data, dict): data = data.get("results", [])
                for item in data if isinstance(data, list) else []:
                    if not isinstance(item, dict): continue
                    link = item.get("link_src") or item.get("url") or ""
                    # URLs look like /india/stockpricequote/industry/name/SC_ID
                    m2 = re.search(r"/([A-Z0-9]+)/?$", link)
                    if m2 and item.get("stock_name", "").upper().startswith(symbol[:4].upper()):
                        cache[symbol] = m2.group(1); break
    except Exception: pass
    try: json.dump(cache, open(_MC_SCID_CACHE, "w"))
    except Exception: pass
    return cache.get(symbol)


def _mc_consensus(symbol: str) -> Optional[Dict[str, Any]]:
    sc = _mc_scid(symbol)
    if not sc: return None
    try:
        url = f"https://www.moneycontrol.com/stocks/company_info/print_broker_targets.php?sc_id={sc}"
        r = requests.get(url, headers=_HDR, timeout=12)
        if r.status_code != 200 or not r.text: return None
        t = r.text
        # Extract target price (strongest field)
        tgt = None
        m = re.search(r"Target Price</[^>]+>[^<]*<[^>]+>\s*Rs?\.?\s*([\d,]+\.?\d*)", t, re.I)
        if not m: m = re.search(r"target\s+price[^<]*<[^>]+>\s*[:\-]?\s*(?:Rs?\.?\s*)?([\d,]+\.?\d*)", t, re.I)
        if m:
            try: tgt = float(m.group(1).replace(",", ""))
            except Exception: pass
        # Extract buy/hold/sell counts or mentions
        buy = _ct(t, r"\bbuy\b"); hold = _ct(t, r"\bhold\b"); sell = _ct(t, r"\bsell\b")
        # Broker rows (approximate)
        brokers = len(re.findall(r"<tr[^>]*>[\s\S]*?</tr>", t))
        if tgt is None and buy == 0 and sell == 0: return None
        return {
            "target_price": tgt,
            "buy": buy, "hold": hold, "sell": sell,
            "brokers_mentioned": max(0, brokers - 1),
            "source_url": url,
        }
    except Exception: return None


def _ct(text: str, pat: str) -> int:
    try: return len(re.findall(pat, text, re.I))
    except Exception: return 0


# ---------- A2. ET Markets broker recommendations ----------
_ET_COMPANYID = {
    "RELIANCE": ("reliance-industries-ltd", 13215),
    "TCS": ("tata-consultancy-services-ltd", 8345),          # corrected from 11356
    "INFY": ("infosys-ltd", 10960),                          # corrected from 11195
    "HDFCBANK": ("hdfc-bank-ltd", 9195),
    "ICICIBANK": ("icici-bank-ltd", 9194),
    "ITC": ("itc-ltd", 13554),
    "WIPRO": ("wipro-ltd", 12799),
    "SBIN": ("state-bank-of-india", 11984),
    "AXISBANK": ("axis-bank-ltd", 9175),
    "ADANIGREEN": ("adani-green-energy-ltd", 64847),
    "TRENT": ("trent-ltd", 13456),
    "VBL": ("varun-beverages-ltd", 18605),
    "BAJFINANCE": ("bajaj-finance-ltd", 8634),               # educated guess, may need verification
    "BHARTIARTL": ("bharti-airtel-ltd", 11958),
    "MARUTI": ("maruti-suzuki-india-ltd", 12137),
    "HINDUNILVR": ("hindustan-unilever-ltd", 13616),
    "LT": ("larsen-toubro-ltd", 13447),
    "ASIANPAINT": ("asian-paints-ltd", 13430),
    "HCLTECH": ("hcl-technologies-ltd", 4858),
    "KOTAKBANK": ("kotak-mahindra-bank-ltd", 13425),
    "TATAMOTORS": ("tata-motors-ltd", 12934),
    "TATAPOWER": ("tata-power-company-ltd", 12918),
    "SUNPHARMA": ("sun-pharmaceutical-industries-ltd", 3567),
    "TITAN": ("titan-company-ltd", 13596),
    "ULTRACEMCO": ("ultratech-cement-ltd", 13640),
    "ADANIENT": ("adani-enterprises-ltd", 13330),
    "NTPC": ("ntpc-ltd", 13641),
    "ONGC": ("oil-and-natural-gas-corporation-ltd", 13501),
    "POWERGRID": ("power-grid-corporation-of-india-ltd", 4628),
    "COALINDIA": ("coal-india-ltd", 11822),
    "TECHM": ("tech-mahindra-ltd", 12701),
    "NESTLEIND": ("nestle-india-ltd", 13330),
}


def _et_consensus(symbol: str) -> Optional[Dict[str, Any]]:
    """Scrape ET Markets per-stock page (requires companyid mapping).
    Falls back to generic URL; validates page is stock-specific."""
    try:
        m = _ET_COMPANYID.get(symbol)
        if m:
            slug, cid = m
            url = f"https://economictimes.indiatimes.com/{slug}/stocks/companyid-{cid}.cms"
        else:
            url = f"https://economictimes.indiatimes.com/markets/stocks/stock-quotes?ticker={symbol}"
        # Try curl_cffi first for stealth
        try:
            from curl_cffi import requests as cf
            r = cf.get(url, impersonate="chrome131", timeout=12)
        except ImportError:
            r = requests.get(url, headers=_HDR, timeout=12)
        if r.status_code != 200 or not r.text: return None
        t = r.text
        title_m = re.search(r"<title[^>]*>([^<]+)</title>", t)
        title = (title_m.group(1) if title_m else "").lower()
        if "list of companies" in title or "starting with" in title:
            return None
        # Rich analyst paragraph on ET's companyid page
        tgt = tgt_hi = tgt_lo = None; analysts = None
        mm = re.search(r"target price of Rs\.?\s*([\d,]+\.?\d*)\s*in\s*\d+\s*months?\s*by\s*(\d+)\s*analysts?\.?[\s\S]{0,400}", t, re.I)
        if mm:
            tgt = float(mm.group(1).replace(",", "")); analysts = int(mm.group(2))
            ctx = mm.group(0)
            hm = re.search(r"high\s*estimate\s*of\s*Rs\.?\s*([\d,]+\.?\d*)", ctx, re.I)
            lm = re.search(r"low\s*estimate\s*of\s*Rs\.?\s*([\d,]+\.?\d*)", ctx, re.I)
            if hm: tgt_hi = float(hm.group(1).replace(",", ""))
            if lm: tgt_lo = float(lm.group(1).replace(",", ""))
        if not tgt:
            for pat in [r'"targetPrice"\s*:\s*"?([\d,\.]+)"?', r"target\s*price[^<]*<[^>]*>\s*Rs?\.?\s*([\d,]+\.?\d*)"]:
                m = re.search(pat, t, re.I)
                if m:
                    try: tgt = float(m.group(1).replace(",", "")); break
                    except Exception: pass
        # Broker rating distribution (bounded block, cap at 20 each)
        blk_m = re.search(r"broker[^<]*(?:recommend|call|view)[\s\S]{0,6000}", t, re.I)
        blk = blk_m.group(0) if blk_m else ""
        sb = min(_ct(blk, r"\bstrong\s*buy\b"), 20); bu = min(_ct(blk, r"(?<!strong\s)\bbuy\b"), 20)
        ho = min(_ct(blk, r"\bhold\b"), 20); se = min(_ct(blk, r"(?<!strong\s)\bsell\b"), 20)
        ss = min(_ct(blk, r"\bstrong\s*sell\b"), 20)
        if tgt is None and analysts is None and sb + bu + ho + se + ss == 0: return None
        from datetime import date
        return {
            "target_price": tgt, "target_high": tgt_hi, "target_low": tgt_lo,
            "analysts": analysts,
            "strong_buy": sb, "buy": bu, "hold": ho, "sell": se, "strong_sell": ss,
            "source_url": url,
            "as_of": date.today().isoformat(),  # ET's consensus paragraph is "as of today"
        }
    except Exception: return None


# ---------- B. yfinance ----------
def _yf_rating(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        import yfinance as yf
        info = yf.Ticker(symbol + ".NS").info or {}
        mean = info.get("recommendationMean")
        n = info.get("numberOfAnalystOpinions")
        key = info.get("recommendationKey")  # "buy", "hold", etc.
        target = info.get("targetMeanPrice")
        high = info.get("targetHighPrice")
        low = info.get("targetLowPrice")
        if mean is None and target is None: return None
        from datetime import date
        return {
            "rating_mean": round(float(mean), 2) if isinstance(mean, (int, float)) else None,
            "analysts": int(n) if isinstance(n, (int, float)) and n else None,
            "key": key,
            "target_mean": round(float(target), 2) if isinstance(target, (int, float)) else None,
            "target_high": round(float(high), 2) if isinstance(high, (int, float)) else None,
            "target_low": round(float(low), 2) if isinstance(low, (int, float)) else None,
            "as_of": date.today().isoformat(),  # yfinance returns current Yahoo snapshot
        }
    except Exception: return None


# ---------- C. RSS upgrade / downgrade activity ----------
_UP = re.compile(r"\b(upgrade[ds]?|raise[ds]? target|hike[ds]? target|buy call|re-?rate[ds]? higher)\b", re.I)
_DN = re.compile(r"\b(downgrade[ds]?|cut target|reduce target|slash(?:ed)? target|sell call|re-?rate[ds]? lower)\b", re.I)


def _rss_activity(symbol: str, days: int = 30) -> Optional[Dict[str, Any]]:
    try:
        from data.stock_news import _fetch_all_feeds, _aliases, _match_symbol
    except Exception: return None
    try:
        items = _fetch_all_feeds()
        aliases = _aliases(symbol)
        up = dn = 0
        samples_up, samples_dn = [], []
        for it in items:
            text = f"{it.get('title','')} {it.get('desc','')}"
            if not _match_symbol(text, symbol, aliases): continue
            if _UP.search(text):
                up += 1
                if len(samples_up) < 2: samples_up.append(it.get("title", ""))
            if _DN.search(text):
                dn += 1
                if len(samples_dn) < 2: samples_dn.append(it.get("title", ""))
        if up == 0 and dn == 0: return None
        return {"window_days": days, "upgrades": up, "downgrades": dn, "sample_up": samples_up, "sample_dn": samples_dn}
    except Exception: return None


def _yf_rating_history(symbol: str, days: int) -> Optional[Dict[str, Any]]:
    """Analyst rating changes in the last `days` days from yfinance upgrades_downgrades."""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol + ".NS")
        df = getattr(t, "upgrades_downgrades", None)
        if df is None or len(df) == 0: return None
        import pandas as pd
        cutoff = pd.Timestamp.utcnow() - pd.Timedelta(days=days)
        if df.index.tz is None:
            try: df.index = df.index.tz_localize("UTC")
            except Exception: pass
        try: recent = df[df.index >= cutoff]
        except Exception: recent = df
        if len(recent) == 0: return None
        grades = recent.get("ToGrade") if "ToGrade" in recent.columns else None
        counts = {}
        if grades is not None:
            for g in grades.astype(str):
                counts[g] = counts.get(g, 0) + 1
        return {"window_days": days, "changes": int(len(recent)), "grade_counts": counts}
    except Exception: return None


# ---------- Aggregator ----------
def _composite(mc, et, yf_, rss) -> Dict[str, Any]:
    """Combine sources into one consensus number 1-5 (1=strong buy, 5=strong sell — same as yfinance scale)."""
    parts = []; targets = []
    if yf_ and yf_.get("rating_mean") is not None: parts.append(float(yf_["rating_mean"]))
    if yf_ and yf_.get("target_mean") is not None: targets.append(yf_["target_mean"])
    if mc:
        b, h, s = mc.get("buy", 0), mc.get("hold", 0), mc.get("sell", 0)
        tot = b + h + s
        if tot > 0: parts.append((b * 1.5 + h * 3 + s * 4.5) / tot)
        if mc.get("target_price"): targets.append(mc["target_price"])
    if et:
        sb, b, h, s, ss = et.get("strong_buy", 0), et.get("buy", 0), et.get("hold", 0), et.get("sell", 0), et.get("strong_sell", 0)
        tot = sb + b + h + s + ss
        if tot > 0: parts.append((sb * 1 + b * 2 + h * 3 + s * 4 + ss * 5) / tot)
        if et.get("target_price"): targets.append(et["target_price"])
    if rss:
        u, d = rss.get("upgrades_30d", 0), rss.get("downgrades_30d", 0)
        if u + d > 0: parts.append(3 - (u - d) / max(1, u + d))
    if not parts: return {"rating": None, "label": "No data", "inputs": 0, "target_avg": None}
    mean = sum(parts) / len(parts)
    target_avg = round(sum(targets) / len(targets), 2) if targets else None
    if mean < 2.0: label = "STRONG BUY"
    elif mean < 2.7: label = "BUY"
    elif mean < 3.3: label = "HOLD"
    elif mean < 4.0: label = "REDUCE"
    else: label = "SELL"
    return {"rating": round(mean, 2), "label": label, "inputs": len(parts), "target_avg": target_avg}


_TF_DAYS = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}


async def _crawl_sources(symbol: str, lookback_days: int = 365) -> Dict[str, Any]:
    """Try crawl4ai for MC + Tickertape + Trendlyne. Returns empty dict if crawl4ai unavailable."""
    try:
        from data.analyst_crawl import fetch_all_crawl_sources
        return await fetch_all_crawl_sources(symbol, lookback_days=lookback_days)
    except Exception: return {}


async def get_analyst_signal_async(symbol: str, tf: str = "1y") -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    tf = tf if tf in _TF_DAYS else "1y"
    days = _TF_DAYS[tf]
    cache_f = os.path.join(CACHE_DIR, f"{symbol}__{tf}.json")
    if os.path.exists(cache_f) and time.time() - os.path.getmtime(cache_f) < TTL:
        try: return json.load(open(cache_f))
        except Exception: pass
    # Fast sources (sync) + crawl4ai parallel
    et = _et_consensus(symbol)  # curl_cffi, ~300ms
    yf_ = _yf_rating(symbol)    # yfinance, often rate-limited
    rss = _rss_activity(symbol, days=days)
    yf_hist = _yf_rating_history(symbol, days=days)
    crawl = await _crawl_sources(symbol, lookback_days=days)
    mc = crawl.get("moneycontrol")
    tt = crawl.get("tickertape")
    tl = crawl.get("trendlyne")
    # Current price from local history (for target-based rating derivation)
    cur_price = None
    try:
        import pickle
        hp = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history", f"{symbol}.pkl")
        if os.path.exists(hp):
            df = pickle.load(open(hp, "rb"))
            cur_price = float(df["Close"].iloc[-1])
    except Exception: pass
    result = {
        "symbol": symbol,
        "timeframe": tf,
        "window_days": days,
        "target_horizon": "12M",
        "moneycontrol": mc,
        "et_markets": et,
        "tickertape": tt,
        "trendlyne": tl,
        "yfinance": yf_,
        "yfinance_history": yf_hist,
        "news_activity": rss,
        "composite": _composite_ext(mc, et, tt, tl, yf_, rss, current_price=cur_price),
        "sources_used": [n for n, v in [("moneycontrol", mc), ("et_markets", et), ("tickertape", tt), ("trendlyne", tl), ("yfinance", yf_), ("yf_history", yf_hist), ("news", rss)] if v],
    }
    try: json.dump(result, open(cache_f, "w"))
    except Exception: pass
    return result


def _composite_ext(mc, et, tt, tl, yf_, rss, current_price=None) -> Dict[str, Any]:
    """Extended composite. Uses explicit ratings where present, derives rating
    from target upside when only target prices are available."""
    parts = []; targets = []
    if yf_ and yf_.get("rating_mean") is not None: parts.append(float(yf_["rating_mean"]))
    if yf_ and yf_.get("target_mean") is not None: targets.append(yf_["target_mean"])
    for src in (mc, et, tt, tl):
        if not src: continue
        sb, b, h, s, ss = src.get("strong_buy", 0), src.get("buy", 0), src.get("hold", 0), src.get("sell", 0), src.get("strong_sell", 0)
        tot = sb + b + h + s + ss
        if tot > 0: parts.append((sb * 1 + b * 2 + h * 3 + s * 4 + ss * 5) / tot)
        if src.get("target_price"): targets.append(src["target_price"])
    if rss:
        u, d = rss.get("upgrades", 0), rss.get("downgrades", 0)
        if u + d > 0: parts.append(3 - (u - d) / max(1, u + d))
    target_avg = round(sum(targets) / len(targets), 2) if targets else None
    # Derive rating from target upside if no explicit ratings
    if not parts and target_avg and current_price:
        upside = (target_avg - current_price) / current_price * 100
        if upside > 25: parts.append(1.5)
        elif upside > 10: parts.append(2.2)
        elif upside > -5: parts.append(3.0)
        elif upside > -20: parts.append(3.8)
        else: parts.append(4.5)
    if not parts: return {"rating": None, "label": "No data", "inputs": 0, "target_avg": target_avg}
    mean = sum(parts) / len(parts)
    if mean < 2.0: label = "STRONG BUY"
    elif mean < 2.7: label = "BUY"
    elif mean < 3.3: label = "HOLD"
    elif mean < 4.0: label = "REDUCE"
    else: label = "SELL"
    return {"rating": round(mean, 2), "label": label, "inputs": len(parts), "target_avg": target_avg}


def get_analyst_signal(symbol: str, tf: str = "1y") -> Dict[str, Any]:
    """Sync wrapper — runs the async fetch in a new event loop if needed."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Called from async context (FastAPI) — caller should use _async directly
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as ex:
                return ex.submit(lambda: asyncio.run(get_analyst_signal_async(symbol, tf))).result()
    except RuntimeError: pass
    return asyncio.run(get_analyst_signal_async(symbol, tf))
