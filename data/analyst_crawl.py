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
_RESOLVE_TTL = timedelta(days=60)
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
            # Only populate cache with confirmed resolved data — missing TL meta means
            # "not yet tried", not "failed". Don't cache None here or we skip live resolve.
            if tid and tls and sym not in _TL_META_CACHE:
                _TL_META_CACHE[sym] = {"tid": tid, "slug": tls}


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


# ---------- Tickertape via sitemap + curl_cffi (no crawl4ai / no API subdomain) ----------
# The Tickertape search API (api.tickertape.in) returns 403 from datacenter IPs.
# BUT: the main page loads fine with curl_cffi + full Sec-Fetch navigation headers.
# Slug is resolved from Tickertape's public sitemap (5410 stock URLs, 30-day disk cache).
#
# Resolution priority: 1) memory cache, 2) disk cache, 3) sitemap code-match,
#                      4) sitemap company-name fuzzy-match, 5) API fallback (local IPs)

_TT_SLUG_CACHE: Dict[str, Optional[str]] = {}
_TT_SITEMAP_CACHE: Dict[str, str] = {}   # tickertape-code → slug
_TT_SITEMAP_LOADED = False
_TT_SITEMAP_FILE = _RESOLVE_CACHE_FILE.parent / "tt_sitemap.json"

_NSE_EQUITY_NAMES: Dict[str, str] = {}   # NSE symbol → company name (lazy-loaded)
_NSE_EQUITY_NAMES_LOADED = False

_TT_FETCH_HDR = {
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}


def _tt_load_sitemap() -> None:
    """Download Tickertape stocks sitemap once (30-day disk cache) → code→slug dict."""
    global _TT_SITEMAP_LOADED
    if _TT_SITEMAP_LOADED:
        return
    _TT_SITEMAP_LOADED = True
    # Try disk cache
    if _TT_SITEMAP_FILE.exists():
        try:
            mtime = datetime.fromtimestamp(_TT_SITEMAP_FILE.stat().st_mtime, tz=timezone.utc)
            if (datetime.now(timezone.utc) - mtime) < _RESOLVE_TTL:
                with open(_TT_SITEMAP_FILE) as f:
                    _TT_SITEMAP_CACHE.update(json.load(f))
                return
        except Exception:
            pass
    # Fetch sitemap fresh
    try:
        from curl_cffi import requests as cf
        r = cf.get("https://www.tickertape.in/sitemaps/stocks/sitemap.xml",
                   impersonate="chrome131", timeout=20, headers=_TT_FETCH_HDR)
        if r.status_code != 200:
            return
        for slug in re.findall(r"<loc>https://www\.tickertape\.in/stocks/([^<]+)</loc>", r.text):
            parts = slug.rsplit("-", 1)
            if len(parts) == 2:
                _TT_SITEMAP_CACHE[parts[1].upper()] = slug
        _TT_SITEMAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_TT_SITEMAP_FILE, "w") as f:
            json.dump(_TT_SITEMAP_CACHE, f)
    except Exception:
        pass


def _tt_load_nse_names() -> Dict[str, str]:
    """Lazy-load NSE equity CSV → {SYMBOL: company_name}. Tries local cache then network."""
    global _NSE_EQUITY_NAMES, _NSE_EQUITY_NAMES_LOADED
    if _NSE_EQUITY_NAMES_LOADED:
        return _NSE_EQUITY_NAMES
    _NSE_EQUITY_NAMES_LOADED = True
    # Try local cached CSV first
    local_csv = Path(__file__).resolve().parent.parent / "data_store" / "nse_equity_list.csv"
    try:
        import csv
        if local_csv.exists():
            with open(local_csv, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    sym = (row.get("SYMBOL") or "").strip()
                    name = (row.get("NAME OF COMPANY") or "").strip()
                    if sym and name:
                        _NSE_EQUITY_NAMES[sym] = name
            if _NSE_EQUITY_NAMES:
                return _NSE_EQUITY_NAMES
    except Exception:
        pass
    # Fallback: fetch from NSE (best-effort, non-blocking on failure)
    try:
        from curl_cffi import requests as cf
        r = cf.get(
            "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
            impersonate="chrome124", timeout=10,
        )
        if r.status_code == 200:
            import csv, io
            for row in csv.DictReader(io.StringIO(r.text)):
                sym = (row.get("SYMBOL") or "").strip()
                name = (row.get("NAME OF COMPANY") or "").strip()
                if sym and name:
                    _NSE_EQUITY_NAMES[sym] = name
            # Save locally for next time
            try:
                local_csv.parent.mkdir(parents=True, exist_ok=True)
                local_csv.write_text(r.text, encoding="utf-8")
            except Exception:
                pass
    except Exception:
        pass
    return _NSE_EQUITY_NAMES


def _tt_company_name(symbol: str) -> Optional[str]:
    """Return company name: fundamentals pkl first, then NSE equity CSV."""
    try:
        import pickle
        p = Path(__file__).resolve().parent.parent / "data_store" / "fundamentals" / f"{symbol}.pkl"
        if p.exists():
            with open(p, "rb") as f:
                fund = pickle.load(f)
            if isinstance(fund, dict):
                name = fund.get("longName") or fund.get("shortName")
                if name:
                    return name
    except Exception:
        pass
    # Fallback: NSE equity CSV (covers stocks with screener.in-only pkls)
    return _tt_load_nse_names().get(symbol)


def _tt_slug_from_sitemap(symbol: str) -> Optional[str]:
    """NSE ticker → Tickertape slug via sitemap code/name matching (no API call).

    Priority:
      1. Exact NSE symbol == Tickertape code  (TCS, INFY, WIPRO, SBI…)
      2. Company name fuzzy match — most reliable for complex symbols
         (HDFCBANK→"hdfc-bank-HDBK", BAJFINANCE→"bajaj-finance-BJFN", SBIN→"state-bank-…-SBI")
      3. Short-code prefix 4→3 chars (RELIANCE→RELI, SBIN→SBI)
    """
    _tt_load_sitemap()
    if not _TT_SITEMAP_CACHE:
        return None

    # 1. Exact code match
    s = _TT_SITEMAP_CACHE.get(symbol)
    if s:
        return s

    # 2. Company name fuzzy match (uses fundamentals pkl — available for downloaded stocks)
    cname = _tt_company_name(symbol)
    if cname:
        # Strip generic suffixes; keep differentiating words like "bank", "finance", "auto"
        norm = re.sub(
            r"\b(ltd|limited|pvt|private|corp|corporation|the|and|enterprise|company)\b",
            "", cname, flags=re.I,
        )
        norm = re.sub(r"[^a-z0-9 ]", " ", norm.lower()).strip()
        words = [w for w in norm.split() if len(w) >= 2]
        # Try from most-specific (N words) down to 2 words
        for size in range(min(4, len(words)), 1, -1):
            prefix = "-".join(words[:size])
            for slug in _TT_SITEMAP_CACHE.values():
                if slug.startswith(prefix):
                    return slug

    # 3. Short-code prefix: try 4-char then 3-char (handles SBIN→SBI, etc.)
    for n in (4, 3):
        if len(symbol) >= n:
            s = _TT_SITEMAP_CACHE.get(symbol[:n])
            if s:
                return s

    return None


def _tt_resolve_slug(symbol: str) -> Optional[str]:
    """Resolve NSE ticker → Tickertape slug. Sitemap-first; API as fallback."""
    _hydrate_from_disk()
    if symbol in _TT_SLUG_CACHE:
        return _TT_SLUG_CACHE[symbol]
    # Sitemap resolution (works from any IP)
    slug = _tt_slug_from_sitemap(symbol)
    if slug:
        _TT_SLUG_CACHE[symbol] = slug
        _persist_resolve(symbol, tt_slug=slug)
        return slug
    # API fallback (works from residential IPs only)
    try:
        from curl_cffi import requests as cf
        r = cf.get(
            f"https://api.tickertape.in/search?text={symbol}&types=stock",
            impersonate="chrome131", timeout=8,
            headers={"Origin": "https://www.tickertape.in", "Referer": "https://www.tickertape.in/"},
        )
        if r.status_code == 200:
            d = r.json()
            for stk in (d.get("data", {}) or {}).get("stocks", []):
                if (stk.get("ticker") or "").upper() == symbol.upper():
                    s = (stk.get("slug") or "").lstrip("/")
                    if s.startswith("stocks/"):
                        s = s[len("stocks/"):]
                    if s:
                        slug = s
                        break
    except Exception:
        pass
    _TT_SLUG_CACHE[symbol] = slug
    _persist_resolve(symbol, tt_slug=slug)
    return slug


def _tt_fetch_sync(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch Tickertape page via curl_cffi (works from datacenter IPs with nav headers)."""
    from curl_cffi import requests as cf
    url = f"https://www.tickertape.in/stocks/{slug}"
    try:
        r = cf.get(url, impersonate="chrome131", timeout=20, headers=_TT_FETCH_HDR)
        if r.status_code != 200 or len(r.text) < 50000:
            return None
        mj = re.search(r'<script id="__NEXT_DATA__"[^>]*>({.*?})</script>', r.text, re.S)
        if not mj:
            return None
        try:
            data = json.loads(mj.group(1))
        except Exception:
            return None
        pp = data.get("props", {}).get("pageProps", {})
        ss = pp.get("securitySummary", {})
        fc = ss.get("forecast") or {}
        out: Dict[str, Any] = {"source_url": url}
        tot = fc.get("totalReco")
        pct_buy = fc.get("percBuyReco")
        pct_sell = fc.get("percSellReco") or fc.get("percNegReco") or 0
        if isinstance(tot, (int, float)) and tot > 0:
            out["analysts"] = int(tot)
            if isinstance(pct_buy, (int, float)):
                buy = int(round(tot * pct_buy / 100))
                sell = int(round(tot * pct_sell / 100)) if pct_sell else 0
                out["buy"] = buy
                out["sell"] = sell
                out["hold"] = int(tot) - buy - sell
                out["perc_buy"] = round(pct_buy, 1)
                if pct_sell:
                    out["perc_sell"] = round(pct_sell, 1)
        # Target price — try common field names
        for field in ("target", "avgTarget", "medianTarget", "targetPrice", "meanTarget"):
            v = fc.get(field)
            if isinstance(v, (int, float)) and v > 0:
                out["target_price"] = round(v, 2)
                break
        if out.get("analysts") or out.get("target_price"):
            from datetime import date
            out["as_of"] = date.today().isoformat()
            return out
    except Exception:
        pass
    return None


def _tt_fetch_forecasts_sync(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch quarterly EPS actuals + annual EPS consensus from Tickertape /forecasts page.
    Uses curl_cffi chrome131 — works from datacenter IPs (proven in test_scrape_eps.py)."""
    from curl_cffi import requests as cf
    url = f"https://www.tickertape.in/stocks/{slug}/forecasts"
    try:
        r = cf.get(url, impersonate="chrome131", timeout=20, headers=_TT_FETCH_HDR)
        if r.status_code != 200 or len(r.text) < 10000:
            return None
        mj = re.search(r'<script id="__NEXT_DATA__"[^>]*>({.*?})</script>', r.text, re.S)
        if not mj:
            return None
        try:
            data = json.loads(mj.group(1))
        except Exception:
            return None
        props = data.get("props", {}).get("pageProps", {})
        quarterly = []
        for q in (props.get("income-normal-interim") or []):
            quarterly.append({
                "quarter": q.get("displayPeriod"),
                "eps_actual": q.get("qIncEps"),
                "net_profit_cr": q.get("qIncNinc"),
            })
        eps_forecast = []
        for e in (props.get("forecastsHistory", {}).get("eps") or []):
            eps_forecast.append({
                "fy_end": (e.get("date") or "")[:7],
                "eps_consensus": round(e.get("value", 0), 2),
                "yoy_change_pct": e.get("change"),
            })
        if not quarterly and not eps_forecast:
            return None
        from datetime import date
        return {
            "source_url": url,
            "quarterly_eps": quarterly[-8:],
            "annual_eps_forecast": eps_forecast,
            "as_of": date.today().isoformat(),
        }
    except Exception:
        return None


def tt_fetch_forecasts_for_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    """Resolve slug then fetch Tickertape /forecasts page (quarterly EPS + annual consensus)."""
    slug = _tt_resolve_slug(symbol)
    if not slug:
        return None
    return _tt_fetch_forecasts_sync(slug)


async def fetch_tickertape(symbol: str) -> Optional[Dict[str, Any]]:
    slug = _tt_resolve_slug(symbol)
    if not slug:
        return None
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _tt_fetch_sync, slug)


# ---------- Trendlyne via cloudscraper (Cloudflare bypass, no browser) ----------
# TID + slug resolved DYNAMICALLY via Trendlyne's own search API — no hardcoded map.
_TL_META_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}


def _tl_resolve(symbol: str) -> Optional[Dict[str, Any]]:
    """Resolve NSE ticker → Trendlyne {tid, slug} via their autosuggest endpoint.
    Uses curl_cffi (TLS fingerprint spoof) — works from datacenter IPs.
    Disk-backed with 30-day TTL."""
    _hydrate_from_disk()
    if symbol in _TL_META_CACHE: return _TL_META_CACHE[symbol]
    meta = None
    try:
        from curl_cffi import requests as cf
        s = cf.Session(impersonate="chrome124")
        hdrs = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://trendlyne.com/"}
        r = s.get(f"https://trendlyne.com/equity/api/ac_snames/price/?term={symbol}",
                  headers=hdrs, timeout=10)
        if r.status_code == 200 and r.text.strip() not in ("fail", "[]", ""):
            d = r.json()
            for item in (d if isinstance(d, list) else []):
                if not isinstance(item, dict): continue
                if (item.get("value") or "").upper() == symbol.upper():
                    tid = item.get("k")
                    pageurl = item.get("pageurl", "")
                    m = re.search(r"/equity/\d+/[A-Z0-9&.]+/([a-z0-9\-]+)", pageurl)
                    slug = m.group(1) if m else None
                    if tid and slug: meta = {"tid": tid, "slug": slug}; break
    except Exception:
        # Fall back to cloudscraper if curl_cffi unavailable
        try:
            import cloudscraper
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
                        pageurl = item.get("pageurl", "")
                        m = re.search(r"/equity/\d+/[A-Z0-9&.]+/([a-z0-9\-]+)", pageurl)
                        slug = m.group(1) if m else None
                        if tid and slug: meta = {"tid": tid, "slug": slug}; break
        except Exception:
            pass
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
    recoType, upside, postAuthor}. curl_cffi TLS spoofing works from datacenter IPs."""
    try:
        from curl_cffi import requests as cf
        from datetime import datetime, timedelta
        s = cf.Session(impersonate="chrome124")
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
    """Parallel fetch Tickertape + Trendlyne with per-source timeouts.

    MC (crawl4ai/Chromium) is excluded — it's always IP-blocked from the
    datacenter and was adding up to 18s of dead wait on every cache-miss.
    TT/TL use curl_cffi + cloudscraper — typically 3-8s, capped at 15s.
    GHA pre-fetches TT+TL daily so the live attempts are a best-effort bonus.
    """
    async def _safe(coro, timeout: float):
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except Exception:
            return None

    tt, tl = await asyncio.gather(
        _safe(fetch_tickertape(symbol), timeout=15),
        _safe(fetch_trendlyne(symbol, lookback_days=lookback_days), timeout=15),
    )
    return {"moneycontrol": None, "tickertape": tt, "trendlyne": tl}
