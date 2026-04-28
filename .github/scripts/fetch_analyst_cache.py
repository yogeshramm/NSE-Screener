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


def _write_cache(symbol: str, tl_data: dict | None) -> bool:
    """Merge Trendlyne data into the existing analyst cache file (or create minimal one)."""
    cache_path = CACHE_DIR / f"{symbol}__1y.json"
    existing = {}
    if cache_path.exists():
        try:
            existing = json.loads(cache_path.read_text())
        except Exception:
            existing = {}

    if tl_data is None and existing.get("trendlyne") is not None:
        # Already have TL data from a previous run — keep it
        return False

    existing["symbol"] = symbol
    existing["timeframe"] = "1y"
    existing["trendlyne"] = tl_data
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
        # Try to read from local history (available if repo has data_store)
        hist = ROOT / "data_store" / "history"
        if hist.exists():
            symbols = [p.stem for p in hist.glob("*.pkl")]
            print(f"Found {len(symbols)} symbols in history store.")
        else:
            symbols = list(dict.fromkeys(NIFTY_500_FALLBACK))  # dedup
            print(f"Using {len(symbols)} fallback symbols.")

    ok = fail = skip = 0
    for i, sym in enumerate(symbols, 1):
        cache_path = CACHE_DIR / f"{sym}__1y.json"
        if not _is_stale(cache_path):
            skip += 1
            continue
        print(f"  [{i}/{len(symbols)}] {sym}... ", end="", flush=True)
        tl = _fetch_trendlyne(sym)
        changed = _write_cache(sym, tl)
        if tl:
            print(f"✓ TL analysts={tl.get('analysts')} target={tl.get('target_price')}")
            ok += 1
        else:
            print("– TL no data")
            fail += 1
        time.sleep(1.2)  # polite rate limit

    print(f"\nDone: {ok} fetched, {fail} failed, {skip} skipped (fresh cache).")


if __name__ == "__main__":
    main()
