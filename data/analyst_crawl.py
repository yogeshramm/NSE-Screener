"""
Analyst data via crawl4ai (Chromium stealth) + cloudscraper (Cloudflare bypass).
JS-protected sites: Moneycontrol, Tickertape, Trendlyne.

Tickertape: parse __NEXT_DATA__ JSON (cleaner than regex on HTML).
Trendlyne:  cloudscraper bypasses their Cloudflare in ~1s — no browser.
Moneycontrol: crawl4ai + hardcoded SC_ID map (8 large caps).
"""
import re, json, asyncio, threading
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

_CRAWLER = None
_LOCK = threading.Lock()

# ---------- disk-backed resolve cache (30-day TTL) ----------
# Tickertape slugs + Trendlyne {tid, slug} are both durable identifiers — they
# change only on corporate actions. Persisting them avoids re-hitting the
# autocomplete endpoints every cold start.
_RESOLVE_CACHE_FILE = Path(__file__).resolve().parent.parent / "data_store" / "analyst" / "resolve_cache.json"
_RESOLVE_TTL = timedelta(days=30)
_DISK_LOADED = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_fresh(cached_at: Optional[str]) -> bool:
    if not cached_at:
        return False
    try:
        ts = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts) <= _RESOLVE_TTL
    except Exception:
        return False


def _hydrate_from_disk():
    """Populate _TT_SLUG_CACHE + _TL_META_CACHE from disk (fresh entries only).
    Called lazily on first resolve. Thread-safe via _LOCK."""
    global _DISK_LOADED
    with _LOCK:
        if _DISK_LOADED:
            return
        _DISK_LOADED = True
        if not _RESOLVE_CACHE_FILE.exists():
            return
        try:
            with open(_RESOLVE_CACHE_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            return
        for sym, entry in (data or {}).items():
            if not isinstance(entry, dict):
                continue
            if not _is_fresh(entry.get("cached_at")):
                continue
            tt = entry.get("tt_slug")
            if tt is not None and sym not in _TT_SLUG_CACHE:
                _TT_SLUG_CACHE[sym] = tt or None
            tid, tls = entry.get("tl_tid"), entry.get("tl_slug")
            if sym not in _TL_META_CACHE:
                _TL_META_CACHE[sym] = ({"tid": tid, "slug": tls} if tid and tls else None)


def _persist_resolve(symbol: str, tt_slug: Optional[str] = None,
                     tl_meta: Optional[Dict[str, Any]] = None):
    """Merge (symbol, tt_slug, tl_meta) into the disk cache with atomic write.
    Call sites pass whichever field they just resolved; the other is preserved
    from any existing entry."""
    with _LOCK:
        try:
            _RESOLVE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data: Dict[str, Any] = {}
            if _RESOLVE_CACHE_FILE.exists():
                try:
                    with open(_RESOLVE_CACHE_FILE, "r") as f:
                        data = json.load(f) or {}
                except Exception:
                    data = {}
            entry = data.get(symbol, {}) if isinstance(data.get(symbol), dict) else {}
            if tt_slug is not None:
                entry["tt_slug"] = tt_slug
            if tl_meta is not None:
                entry["tl_tid"] = tl_meta.get("tid")
                entry["tl_slug"] = tl_meta.get("slug")
            entry["cached_at"] = _now_iso()
            data[symbol] = entry
            tmp = _RESOLVE_CACHE_FILE.with_suffix(".json.tmp")
            with open(tmp, "w") as f:
                json.dump(data, f)
            tmp.replace(_RESOLVE_CACHE_FILE)
        except Exception:
            pass


async def _get_crawler():
    global _CRAWLER
    if _CRAWLER is None:
        from crawl4ai import AsyncWebCrawler, BrowserConfig
        bcfg = BrowserConfig(
            headless=True, browser_type="chromium",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport_width=1920, viewport_height=1080,
        )
        _CRAWLER = AsyncWebCrawler(config=bcfg, verbose=False)
        await _CRAWLER.__aenter__()
    return _CRAWLER


def _run_cfg():
    from crawl4ai import CrawlerRunConfig
    return CrawlerRunConfig(
        magic=True, wait_until="networkidle", page_timeout=25000,
        simulate_user=True, override_navigator=True,
    )


def _num(s):
    try: return float(str(s).replace(",", "").strip())
    except Exception: return None


# ---------- Moneycontrol via crawl4ai ----------
_MC_INDUSTRY_MAP = {
    "RELIANCE": ("refineries", "relianceindustries", "RI"),
    "TCS": ("computerssoftware", "tataconsultancyservices", "TCS"),
    "INFY": ("computerssoftware", "infosys", "IT"),
    "HDFCBANK": ("banks-private-sector", "hdfcbank", "HDF01"),
    "ICICIBANK": ("banks-private-sector", "icicibank", "ICI02"),
    "ITC": ("cigarettes", "itc", "ITC"),
    "WIPRO": ("computerssoftware", "wipro", "W"),
    "SBIN": ("banks-public-sector", "statebankindia", "SBI"),
}


async def fetch_mc(symbol: str) -> Optional[Dict[str, Any]]:
    m = _MC_INDUSTRY_MAP.get(symbol)
    if not m: return None
    ind, name, sc = m
    url = f"https://www.moneycontrol.com/india/stockpricequote/{ind}/{name}/{sc}"
    try:
        c = await _get_crawler()
        r = await c.arun(url=url, config=_run_cfg())
        if not r.success or not r.html: return None
        h = r.html
        out: Dict[str, Any] = {"source_url": url}
        for pat in [r"target\s*price[^<>]{0,100}(?:rs\.?|₹)\s*([\d,]+\.?\d*)",
                   r"consensus[^<>]{0,100}(?:rs\.?|₹)\s*([\d,]+\.?\d*)",
                   r'"targetPrice"\s*:\s*"?([\d,\.]+)']:
            mm = re.search(pat, h, re.I)
            if mm:
                out["target_price"] = _num(mm.group(1)); break
        blk_m = re.search(r"broker[\s\S]{0,15000}?(?=</section|</div>\s*<section|$)", h, re.I)
        blk = blk_m.group(0) if blk_m else ""
        if blk:
            for rk in ["strong buy", "buy", "hold", "sell", "strong sell"]:
                k = rk.replace(" ", "_")
                cnt = len(re.findall(rf"\b{rk}\b", blk, re.I))
                if 0 < cnt <= 20: out[k] = cnt
        if out.get("target_price") is None and not any(out.get(k, 0) for k in ["strong_buy","buy","hold","sell","strong_sell"]):
            return None
        return out
    except Exception: return None


# ---------- Tickertape via crawl4ai + __NEXT_DATA__ ----------
# Slug resolved DYNAMICALLY via Tickertape's own search API — no hardcoded map needed.
# Cached per session to avoid re-lookup.
_TT_SLUG_CACHE: Dict[str, Optional[str]] = {}


def _tt_resolve_slug(symbol: str) -> Optional[str]:
    """Resolve NSE ticker → Tickertape canonical slug via their public search API.
    Endpoint: https://api.tickertape.in/search?text=X&types=stock
    Disk-backed with 30-day TTL; in-memory cache hit is free, disk hit is one
    small JSON read, miss is a network call that gets persisted to both."""
    _hydrate_from_disk()
    if symbol in _TT_SLUG_CACHE: return _TT_SLUG_CACHE[symbol]
    slug = None
    try:
        from curl_cffi import requests as cf
        r = cf.get(
            f"https://api.tickertape.in/search?text={symbol}&types=stock",
            impersonate="chrome131", timeout=8,
            headers={"Origin":"https://www.tickertape.in","Referer":"https://www.tickertape.in/"},
        )
        if r.status_code == 200:
            d = r.json()
            for stk in (d.get("data", {}) or {}).get("stocks", []):
                if (stk.get("ticker") or "").upper() == symbol.upper():
                    s = (stk.get("slug") or "").lstrip("/")
                    if s.startswith("stocks/"): s = s[len("stocks/"):]
                    if s: slug = s; break
    except Exception: pass
    _TT_SLUG_CACHE[symbol] = slug
    _persist_resolve(symbol, tt_slug=slug)
    return slug


async def fetch_tickertape(symbol: str) -> Optional[Dict[str, Any]]:
    slug = _tt_resolve_slug(symbol)
    if not slug: return None
    candidates = [f"https://www.tickertape.in/stocks/{slug}"]
    try:
        c = await _get_crawler()
        for url in candidates:
            r = await c.arun(url=url, config=_run_cfg())
            if not (r.success and r.html and len(r.html) > 50000): continue
            h = r.html
            # Parse __NEXT_DATA__ JSON — authoritative source
            mj = re.search(r'<script id="__NEXT_DATA__"[^>]*>({.*?})</script>', h, re.S)
            if not mj: continue
            try: data = json.loads(mj.group(1))
            except Exception: continue
            pp = data.get("props", {}).get("pageProps", {})
            ss = pp.get("securitySummary", {})
            fc = ss.get("forecast") or {}
            out = {"source_url": url}
            tot = fc.get("totalReco")
            pct_buy = fc.get("percBuyReco")
            if isinstance(tot, (int, float)) and tot > 0:
                out["analysts"] = int(tot)
                # Derive buy/hold/sell from percBuy: high pct → dominantly buy
                if isinstance(pct_buy, (int, float)):
                    buy = int(round(tot * pct_buy / 100))
                    out["buy"] = buy
                    out["hold"] = tot - buy
                    out["perc_buy"] = round(pct_buy, 1)
            # Note: forecastsHistory.price contains historical price-at-date, not forward
            # analyst target. Tickertape's target isn't in the public JSON, so we skip it.
            if out.get("analysts") or out.get("target_price"):
                from datetime import date
                out["as_of"] = date.today().isoformat()  # Tickertape aggregates are current
                return out
    except Exception: pass
    return None


# ---------- Trendlyne via cloudscraper (Cloudflare bypass, no browser) ----------
# TID + slug resolved DYNAMICALLY via Trendlyne's own search API — no hardcoded map.
_TL_META_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}


def _tl_resolve(symbol: str) -> Optional[Dict[str, Any]]:
    """Resolve NSE ticker → Trendlyne {tid, slug} via their autosuggest endpoint.
    Disk-backed with 30-day TTL (see _tt_resolve_slug for the cache strategy)."""
    _hydrate_from_disk()
    if symbol in _TL_META_CACHE: return _TL_META_CACHE[symbol]
    meta = None
    try:
        import cloudscraper, re
        s = cloudscraper.create_scraper(browser={"browser":"chrome","platform":"darwin","desktop":True})
        s.headers.update({"Accept":"application/json","X-Requested-With":"XMLHttpRequest"})
        s.get("https://trendlyne.com/", timeout=15)
        r = s.get(f"https://trendlyne.com/equity/api/ac_snames/price/?term={symbol}", timeout=10)
        if r.status_code == 200 and r.text.strip() not in ("fail", "[]"):
            d = r.json()
            for item in (d if isinstance(d, list) else []):
                if not isinstance(item, dict): continue
                if (item.get("value") or "").upper() == symbol.upper():
                    tid = item.get("k")
                    # Extract slug from pageurl: https://trendlyne.com/equity/{tid}/{SYM}/{slug}/
                    pageurl = item.get("pageurl", "")
                    m = re.search(r"/equity/\d+/[A-Z0-9&]+/([a-z0-9\-]+)", pageurl)
                    slug = m.group(1) if m else None
                    if tid and slug: meta = {"tid": tid, "slug": slug}; break
    except Exception: pass
    _TL_META_CACHE[symbol] = meta
    if meta is not None:
        _persist_resolve(symbol, tl_meta=meta)
    return meta


async def fetch_trendlyne(symbol: str, lookback_days: int = 365) -> Optional[Dict[str, Any]]:
    meta = _tl_resolve(symbol)
    if not meta: return None
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _tl_sync, meta["tid"], symbol, meta["slug"], lookback_days)
    except Exception: return None


def _tl_sync(tid, symbol, slug, lookback_days=365) -> Optional[Dict[str, Any]]:
    """Trendlyne /equity/overview-second-part/{tid}/ returns JSON with
    researchReports.tableData[] containing {recoDate, targetPrice, recoPrice,
    recoType, upside, postAuthor}. Discovered via XHR-interception on their
    main equity page. cloudscraper bypasses the Cloudflare TLS challenge in ~1s."""
    try:
        import cloudscraper
        from datetime import datetime, timedelta
        s = cloudscraper.create_scraper(browser={"browser":"chrome","platform":"darwin","desktop":True})
        s.headers.update({"Accept":"application/json,text/plain,*/*","X-Requested-With":"XMLHttpRequest"})
        # Warm cookies by hitting the public equity page first
        s.get(f"https://trendlyne.com/equity/{tid}/{symbol}/{slug}/", timeout=15)
        r = s.get(f"https://trendlyne.com/equity/overview-second-part/{tid}/", timeout=15)
        if r.status_code != 200: return None
        d = r.json()
        rr = (d.get("body", {}) or {}).get("researchReports", {}) or {}
        rows = rr.get("tableData") or []
        if not rows: return None
        cutoff = datetime.now() - timedelta(days=lookback_days)
        recent = []
        for rw in rows:
            try:
                if rw.get("recoDate") and datetime.strptime(rw["recoDate"], "%Y-%m-%d") >= cutoff:
                    recent.append(rw)
            except Exception: continue
        if not recent: return None
        targets = [r["targetPrice"] for r in recent if isinstance(r.get("targetPrice"), (int, float)) and r["targetPrice"] > 0]
        upsides = [r["upside"] for r in recent if isinstance(r.get("upside"), (int, float))]
        recos: Dict[str, int] = {}
        for r in recent:
            rt = (r.get("recoType") or "").strip().title()
            if rt: recos[rt] = recos.get(rt, 0) + 1
        out = {
            "source_url": f"https://trendlyne.com/equity/{tid}/{symbol}/{slug}/",
            "reports_in_window": len(recent),
            "lookback_days": lookback_days,
            "analysts": len({(r.get("postAuthor") or "").strip() for r in recent if r.get("postAuthor")}) or len(recent),
            "reco_raw": recos,
        }
        if targets:
            out["target_price"] = round(sum(targets)/len(targets), 2)
            out["target_low"] = round(min(targets), 2)
            out["target_high"] = round(max(targets), 2)
        if upsides:
            out["avg_upside_pct"] = round(sum(upsides)/len(upsides), 2)
        # Date range metadata — so the UI can show users exactly WHEN these ratings are from
        reco_dates = sorted([r.get("recoDate") for r in recent if r.get("recoDate")])
        if reco_dates:
            out["latest_date"] = reco_dates[-1]
            out["earliest_date"] = reco_dates[0]
        # Normalize into the 5-bucket rating system used across other sources
        sb = recos.get("Strong Buy", 0) + recos.get("Accumulate", 0)
        bu = recos.get("Buy", 0) + recos.get("Add", 0) + recos.get("Outperform", 0)
        ho = recos.get("Hold", 0) + recos.get("Neutral", 0) + recos.get("Not Rated", 0) + recos.get("Results Update", 0)
        se = recos.get("Sell", 0) + recos.get("Reduce", 0) + recos.get("Underperform", 0)
        ss = recos.get("Strong Sell", 0)
        if sb: out["strong_buy"] = sb
        if bu: out["buy"] = bu
        if ho: out["hold"] = ho
        if se: out["sell"] = se
        if ss: out["strong_sell"] = ss
        return out
    except Exception:
        return None


async def fetch_all_crawl_sources(symbol: str, lookback_days: int = 365) -> Dict[str, Any]:
    """Parallel fetch MC + Tickertape + Trendlyne. Returns dict with each key present (None if failed)."""
    try:
        mc, tt, tl = await asyncio.gather(
            fetch_mc(symbol), fetch_tickertape(symbol), fetch_trendlyne(symbol, lookback_days=lookback_days),
            return_exceptions=False,
        )
        return {"moneycontrol": mc, "tickertape": tt, "trendlyne": tl}
    except Exception as e:
        return {"moneycontrol": None, "tickertape": None, "trendlyne": None, "_error": str(e)}
