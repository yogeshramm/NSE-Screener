"""
GitHub Actions analyst cache fetcher.
Runs on GitHub's Azure servers (different IPs from DigitalOcean).
Fetches Trendlyne + Tickertape data for Nifty 500 and writes to
data_store/analyst/{SYM}__1y.json — same format as the live server cache.
The server does `git pull` daily to pick up fresh data.
"""

import os, sys, json, time, asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data_store" / "analyst"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TTL = 20 * 3600  # 20h — refresh daily

NIFTY_500_FALLBACK = [
    "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC","SBIN",
    "BHARTIARTL","KOTAKBANK","BAJFINANCE","WIPRO","HCLTECH","ASIANPAINT",
    "LT","MARUTI","AXISBANK","SUNPHARMA","TITAN","ULTRACEMCO","TECHM",
    "ADANIGREEN","POWERGRID","NTPC","ONGC","COALINDIA","TATAMOTORS","TATAPOWER",
    "BAJAJFINSV","HINDALCO","JSWSTEEL","TATASTEEL","NESTLEIND","GRASIM","DIVISLAB",
    "DRREDDY","CIPLA","HEROMOTOCO","EICHERMOT","APOLLOHOSP","BPCL","INDUSINDBK",
    "TRENT","VBL","ADANIENT","ADANIPORTS","SIEMENS","HAVELLS","MCDOWELL-N",
    "PIDILITIND","SRF","BERGEPAINT","COLPAL","MARICO","BRITANNIA","DABUR",
    "GODREJCP","PGHH","EMAMILTD","JUBLFOOD","ZOMATO","NYKAA","PAYTM",
    "DMART","ICICIGI","HDFCLIFE","SBILIFE","BAJAJ-AUTO","TVSMOTORS","M&M",
    "TVSMOTOR","ASHOKLEY","BALKRISIND","EXIDEIND","MOTHERSON","BOSCHLTD",
    "ESCORTS","CUMMINSIND","VOLTAS","WHIRLPOOL","RAJESHEXPO","KAJARIACER",
    "CENTURYTEX","RAMCOCEM","SHREECEM","AMBUJACEM","ACCGUJ","JKCEMENT",
    "IDFCFIRSTB","BANDHANBNK","FEDERALBNK","AUBANK","RBLBANK","YESBANK",
    "MUTHOOTFIN","BAJAJHLDNG","LTIM","LTTS","MINDTREE","MPHASIS","PERSISTENT",
    "COFORGE","ZENSARTECH","HEXAWARE","OFSS","ORACLE","INFY","WIPRO",
    "VEDL","HINDZINC","NMDC","NATIONALUM","GMRINFRA","IRB","IRFC","PFC",
    "RECLTD","NHPC","SJVN","TORNTPOWER","CESC","TATAPOWER","ADANIGREEN",
]


def _is_stale(cache_path: Path) -> bool:
    if not cache_path.exists():
        return True
    age = time.time() - cache_path.stat().st_mtime
    return age > TTL


def _fetch_trendlyne(symbol: str) -> dict | None:
    """Fetch Trendlyne broker research data. cloudscraper bypasses their CF challenge."""
    try:
        import cloudscraper, re
        from datetime import datetime, timedelta

        # Step 1: resolve tid + slug
        s = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "darwin", "desktop": True})
        s.headers.update({"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
        s.get("https://trendlyne.com/", timeout=15)
        r = s.get(f"https://trendlyne.com/equity/api/ac_snames/price/?term={symbol}", timeout=10)
        if r.status_code != 200 or r.text.strip() in ("fail", "[]"):
            return None
        d = r.json()
        tid = slug = None
        for item in (d if isinstance(d, list) else []):
            if isinstance(item, dict) and (item.get("value") or "").upper() == symbol.upper():
                tid = item.get("k")
                m = re.search(r"/equity/\d+/[A-Z0-9&]+/([a-z0-9\-]+)", item.get("pageurl", ""))
                slug = m.group(1) if m else None
                if tid and slug:
                    break
        if not (tid and slug):
            return None

        # Step 2: warm equity page + hit API
        s.get(f"https://trendlyne.com/equity/{tid}/{symbol}/{slug}/", timeout=15)
        r2 = s.get(f"https://trendlyne.com/equity/overview-second-part/{tid}/", timeout=15)
        if r2.status_code != 200:
            return None
        body = r2.json()
        rr = (body.get("body", {}) or {}).get("researchReports", {}) or {}
        rows = rr.get("tableData") or []
        if not rows:
            return None

        cutoff = datetime.now() - timedelta(days=365)
        recent = [rw for rw in rows
                  if rw.get("recoDate") and datetime.strptime(rw["recoDate"], "%Y-%m-%d") >= cutoff]
        if not recent:
            return None

        targets = [r["targetPrice"] for r in recent if isinstance(r.get("targetPrice"), (int, float)) and r["targetPrice"] > 0]
        recos: dict = {}
        for r in recent:
            rt = (r.get("recoType") or "").strip().title()
            if rt:
                recos[rt] = recos.get(rt, 0) + 1

        sb = recos.get("Strong Buy", 0) + recos.get("Accumulate", 0)
        bu = recos.get("Buy", 0) + recos.get("Add", 0) + recos.get("Outperform", 0)
        ho = recos.get("Hold", 0) + recos.get("Neutral", 0) + recos.get("Not Rated", 0)
        se = recos.get("Sell", 0) + recos.get("Reduce", 0) + recos.get("Underperform", 0)
        ss = recos.get("Strong Sell", 0)

        out = {
            "source_url": f"https://trendlyne.com/equity/{tid}/{symbol}/{slug}/",
            "reports_in_window": len(recent),
            "lookback_days": 365,
            "analysts": len({(r.get("postAuthor") or "").strip() for r in recent if r.get("postAuthor")}) or len(recent),
            "reco_raw": recos,
        }
        if targets:
            out["target_price"] = round(sum(targets) / len(targets), 2)
            out["target_low"] = round(min(targets), 2)
            out["target_high"] = round(max(targets), 2)
        reco_dates = sorted([r.get("recoDate") for r in recent if r.get("recoDate")])
        if reco_dates:
            out["latest_date"] = reco_dates[-1]
        if sb: out["strong_buy"] = sb
        if bu: out["buy"] = bu
        if ho: out["hold"] = ho
        if se: out["sell"] = se
        if ss: out["strong_sell"] = ss
        return out
    except Exception as e:
        print(f"  TL error {symbol}: {e}")
        return None


# ---------- Tickertape via sitemap + curl_cffi ----------
_TT_SITEMAP: dict = {}
_TT_SITEMAP_FILE = CACHE_DIR / "tt_sitemap.json"
_TT_SITEMAP_LOADED = False
_TT_HDR = {
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}


def _tt_load_sitemap() -> None:
    global _TT_SITEMAP_LOADED
    if _TT_SITEMAP_LOADED:
        return
    _TT_SITEMAP_LOADED = True
    if _TT_SITEMAP_FILE.exists():
        age = time.time() - _TT_SITEMAP_FILE.stat().st_mtime
        if age < 30 * 86400:
            try:
                _TT_SITEMAP.update(json.loads(_TT_SITEMAP_FILE.read_text()))
                return
            except Exception:
                pass
    try:
        from curl_cffi import requests as cf
        r = cf.get("https://www.tickertape.in/sitemaps/stocks/sitemap.xml",
                   impersonate="chrome131", timeout=20, headers=_TT_HDR)
        if r.status_code != 200:
            return
        import re
        for slug in re.findall(r"<loc>https://www\.tickertape\.in/stocks/([^<]+)</loc>", r.text):
            parts = slug.rsplit("-", 1)
            if len(parts) == 2:
                _TT_SITEMAP[parts[1].upper()] = slug
        _TT_SITEMAP_FILE.write_text(json.dumps(_TT_SITEMAP))
    except Exception:
        pass


def _tt_slug(symbol: str) -> str | None:
    _tt_load_sitemap()
    return _TT_SITEMAP.get(symbol)


def _fetch_tickertape(symbol: str) -> dict | None:
    """Fetch Tickertape analyst consensus via curl_cffi + __NEXT_DATA__ parse."""
    try:
        import re as _re
        from curl_cffi import requests as cf
        slug = _tt_slug(symbol)
        if not slug:
            return None
        url = f"https://www.tickertape.in/stocks/{slug}"
        r = cf.get(url, impersonate="chrome131", timeout=20, headers=_TT_HDR)
        if r.status_code != 200 or len(r.text) < 50000:
            return None
        mj = _re.search(r'<script id="__NEXT_DATA__"[^>]*>({.*?})</script>', r.text, _re.S)
        if not mj:
            return None
        data = json.loads(mj.group(1))
        pp = data.get("props", {}).get("pageProps", {})
        ss = pp.get("securitySummary", {})
        fc = ss.get("forecast") or {}
        out: dict = {"source_url": url}
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
        if not out.get("analysts"):
            return None
        from datetime import date
        out["as_of"] = date.today().isoformat()
        return out
    except Exception as e:
        print(f"  TT error {symbol}: {e}")
        return None


def _write_cache(symbol: str, tl_data: dict | None, tt_data: dict | None) -> bool:
    """Merge Trendlyne + Tickertape data into the existing analyst cache file."""
    cache_path = CACHE_DIR / f"{symbol}__1y.json"
    existing = {}
    if cache_path.exists():
        try:
            existing = json.loads(cache_path.read_text())
        except Exception:
            existing = {}

    # Keep existing data if new fetch returned nothing
    if tl_data is None and existing.get("trendlyne") is not None:
        tl_data = existing["trendlyne"]
    if tt_data is None and existing.get("tickertape") is not None:
        tt_data = existing["tickertape"]

    existing["symbol"] = symbol
    existing["timeframe"] = "1y"
    existing["trendlyne"] = tl_data
    existing["tickertape"] = tt_data
    existing["_gh_updated"] = datetime.now(timezone.utc).isoformat()

    cache_path.write_text(json.dumps(existing))
    return True


def main():
    # Which symbols to process
    env_syms = os.environ.get("INPUT_SYMBOLS", "").strip()
    if env_syms:
        symbols = [s.strip().upper() for s in env_syms.split(",") if s.strip()]
        print(f"Processing {len(symbols)} specified symbols.")
    else:
        nifty500_file = ROOT / "data" / "nifty500_live.txt"
        if nifty500_file.exists():
            symbols = [l.strip() for l in nifty500_file.read_text().splitlines() if l.strip()]
            print(f"Loaded {len(symbols)} symbols from nifty500_live.txt.")
        else:
            symbols = list(dict.fromkeys(NIFTY_500_FALLBACK))
            print(f"Using {len(symbols)} fallback symbols.")

    # Pre-load sitemap once for all Tickertape lookups
    print("Loading Tickertape sitemap...")
    _tt_load_sitemap()
    print(f"  Sitemap: {len(_TT_SITEMAP)} slugs loaded.")

    tl_ok = tl_fail = tt_ok = tt_fail = skip = 0
    for i, sym in enumerate(symbols, 1):
        cache_path = CACHE_DIR / f"{sym}__1y.json"
        if not _is_stale(cache_path):
            skip += 1
            continue
        print(f"  [{i}/{len(symbols)}] {sym}... ", end="", flush=True)
        tl = _fetch_trendlyne(sym)
        tt = _fetch_tickertape(sym)
        _write_cache(sym, tl, tt)
        parts = []
        if tl:
            parts.append(f"TL✓ a={tl.get('analysts')} tgt={tl.get('target_price')}")
            tl_ok += 1
        else:
            parts.append("TL–")
            tl_fail += 1
        if tt:
            parts.append(f"TT✓ a={tt.get('analysts')} buy={tt.get('perc_buy')}%")
            tt_ok += 1
        else:
            parts.append("TT–")
            tt_fail += 1
        print(" | ".join(parts))
        time.sleep(1.5)  # polite rate limit (two requests per stock)

    print(f"\nDone: TL {tl_ok}ok/{tl_fail}fail | TT {tt_ok}ok/{tt_fail}fail | {skip} skipped.")


if __name__ == "__main__":
    main()
