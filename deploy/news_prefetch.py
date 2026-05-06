#!/usr/bin/env python3
"""
Nifty 200 news pre-fetch — run at 4 PM and 6 PM IST (post-market).

Writes to data_store/news/_bulk_{SYMBOL}.json (2h TTL).
get_news() falls back to bulk cache when the 30-min on-demand cache is stale,
so the evening review session is instant for all 200 stocks.

Usage:
    python3 deploy/news_prefetch.py [--delay 0.4] [--dry-run]
"""
import os, sys, json, time, logging, argparse

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(PROJECT, "logs", "news_prefetch.log")),
    ],
)
log = logging.getLogger(__name__)

CACHE_DIR = os.path.join(PROJECT, "data_store", "news")
BULK_TTL  = 2 * 3600   # bulk cache valid for 2 hours


# ── Symbol list ────────────────────────────────────────────────────────────

def _get_nifty200() -> list:
    """Return Nifty 200 symbols. Tries NSE CSV first, falls back to nifty500_live.txt."""
    try:
        import requests
        url = "https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv"
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
        if r.status_code == 200:
            import csv, io
            reader = csv.DictReader(io.StringIO(r.text))
            syms = [row.get("Symbol", "").strip() for row in reader
                    if row.get("Symbol", "").strip()]
            if len(syms) >= 150:
                log.info(f"  NSE CSV: {len(syms)} Nifty 200 symbols")
                return syms
    except Exception as e:
        log.warning(f"  NSE CSV failed ({e}), using fallback")

    # Fallback: first 200 from local nifty500_live.txt
    txt = os.path.join(PROJECT, "data", "nifty500_live.txt")
    if os.path.exists(txt):
        syms = [l.strip() for l in open(txt) if l.strip()]
        log.info(f"  Fallback nifty500_live.txt: using first {min(200, len(syms))} symbols")
        return syms[:200]

    log.error("  No symbol source available")
    return []


# ── Per-symbol fetch ───────────────────────────────────────────────────────

def _prefetch(symbol: str, dry_run: bool) -> str:
    bulk_f = os.path.join(CACHE_DIR, f"_bulk_{symbol}.json")

    # Skip if bulk cache is still fresh
    if os.path.exists(bulk_f):
        age = time.time() - os.path.getmtime(bulk_f)
        if age < BULK_TTL:
            return "skip (fresh)"

    if dry_run:
        return "dry-run"

    from data.stock_news import (
        _search_query, _fetch_google_news,
        _fetch_direct_feeds, _match_direct, _merge_and_sort,
    )

    query  = _search_query(symbol)
    direct = _match_direct(_fetch_direct_feeds(), query, symbol)
    google = _fetch_google_news(query)
    uniq   = _merge_and_sort(direct + google, limit=5)

    json.dump(uniq, open(bulk_f, "w"))
    return f"{len(uniq)} items"


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay",   type=float, default=0.4,
                    help="Seconds between requests (default 0.4)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Simulate without making network requests")
    args = ap.parse_args()

    log.info("=== news_prefetch start ===")
    symbols = _get_nifty200()
    if not symbols:
        log.error("No symbols — aborting")
        sys.exit(1)

    log.info(f"Fetching news for {len(symbols)} stocks  delay={args.delay}s  "
             f"dry_run={args.dry_run}")

    ok = skip = err = 0
    t0 = time.time()

    for i, sym in enumerate(symbols, 1):
        try:
            result = _prefetch(sym, args.dry_run)
            if result.startswith("skip"):
                skip += 1
            else:
                ok += 1
                log.info(f"  [{i:>3}/{len(symbols)}] {sym:<16} {result}")
        except Exception as e:
            err += 1
            log.warning(f"  [{i:>3}/{len(symbols)}] {sym:<16} ERROR: {e}")

        if i < len(symbols):
            time.sleep(args.delay)

    elapsed = time.time() - t0
    log.info(f"=== done in {elapsed:.0f}s — ok={ok} skipped={skip} errors={err} ===")


if __name__ == "__main__":
    os.makedirs(os.path.join(PROJECT, "logs"), exist_ok=True)
    main()
