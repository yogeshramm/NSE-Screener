"""
Daily Data Download Script
Run once after market close to pre-download all NSE stock data.
After this runs, all screening searches are instant — zero API calls.

HOW IT WORKS:
  Step 1: Downloads Bhavcopy from NSE (1 request = ALL stocks' prices)
  Step 2: Appends today's prices to persistent history
  Step 3: First time only — backfills 1 year history from yfinance
  Step 4: Downloads fundamentals (ROE, PE, etc.) from yfinance

After Day 1, only Steps 1-2 hit any API. Steps 3-4 are cached.

Usage:
  python daily_download.py                  # smart daily update (NSE-first)
  python daily_download.py --prices-only    # just Bhavcopy prices, no fundamentals
  python daily_download.py --backfill RELIANCE,TCS  # backfill specific stocks
  python daily_download.py --full           # full download (yfinance for everything)
  python daily_download.py --status         # check download status
"""

import argparse
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from data.batch_downloader import (
    run_batch_download, run_daily_update,
    get_downloaded_symbols, get_available_dates
)
from data.nse_history import get_history_stats
from data.nse_symbols import NIFTY_500_FALLBACK


CRON_STATUS_FILE = Path(__file__).parent / "data_store" / "cron_status.json"


def _write_cron_status(started_at: float, ok: bool, error: str | None,
                       precompute_summary: dict | None = None):
    """Atomically record the outcome of this run for /data/status to surface."""
    try:
        CRON_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "started_at": datetime.fromtimestamp(started_at, timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": round(time.time() - started_at, 1),
            "ok": ok,
            "error": error,
            "precompute": precompute_summary,
        }
        tmp = CRON_STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(CRON_STATUS_FILE)
    except Exception as e:
        print(f"  [WARN] Could not write cron_status.json: {e}")


def main():
    parser = argparse.ArgumentParser(description="NSE Daily Data Downloader")
    parser.add_argument("--prices-only", action="store_true",
                       help="Download only Bhavcopy prices (no yfinance fundamentals)")
    parser.add_argument("--backfill", type=str,
                       help="Backfill history for specific symbols (comma-separated)")
    parser.add_argument("--full", action="store_true",
                       help="Full yfinance download (all data, slower)")
    parser.add_argument("--symbols", type=str,
                       help="Specific symbols for --full mode (comma-separated)")
    parser.add_argument("--status", action="store_true",
                       help="Check download status")
    parser.add_argument("--no-precompute", action="store_true",
                       help="Skip the post-download indicator-cache warm-up")
    parser.add_argument("--precompute-scope", default="nifty500",
                       choices=["nifty200", "nifty500", "all"],
                       help="Universe for indicator precompute (default: nifty500)")
    args = parser.parse_args()

    if args.status:
        print("\n  NSE Screener — Download Status")
        print(f"  {'='*50}")

        # History store
        hist = get_history_stats()
        print(f"\n  Price History (data_store/history/):")
        print(f"    Symbols with history: {hist['total_symbols']}")
        print(f"    Latest date: {hist.get('latest_date', 'N/A')}")

        # Daily store
        dates = get_available_dates()
        print(f"\n  Daily Store (fundamentals):")
        if dates:
            for d in dates[:5]:
                count = len(get_downloaded_symbols(d))
                print(f"    {d}: {count} stocks")
        else:
            print("    No data downloaded yet.")

        today_count = len(get_downloaded_symbols())
        history_count = hist['total_symbols']
        ready = history_count > 50 and today_count > 50
        print(f"\n  Ready for instant screening: {'YES' if ready else 'NO'}")
        if not ready:
            print(f"  Run: python daily_download.py")
        return

    started_at = time.time()
    error = None
    precompute_summary = None
    try:
        if args.full:
            symbols = None
            if args.symbols:
                symbols = [s.strip().upper() for s in args.symbols.split(",")]
            else:
                symbols = list(NIFTY_500_FALLBACK)
            run_batch_download(symbols=symbols)
        else:
            backfill = None
            if args.backfill:
                backfill = [s.strip().upper() for s in args.backfill.split(",")]
            run_daily_update(
                backfill_symbols=backfill,
                skip_fundamentals=args.prices_only,
            )

        if not args.no_precompute:
            try:
                from engine.precompute import warm_cache
                precompute_summary = warm_cache(scope=args.precompute_scope, verbose=True)
            except Exception as e:
                print(f"\n  [WARN] Indicator precompute failed: {e}")
                precompute_summary = {"error": str(e)}

        _write_cron_status(started_at, ok=True, error=None,
                           precompute_summary=precompute_summary)
    except Exception:
        error = traceback.format_exc()
        print(f"\n  [ERROR] Daily download failed:\n{error}")
        _write_cron_status(started_at, ok=False, error=error,
                           precompute_summary=precompute_summary)
        raise

    print(f"\n  Your screener is now ready for instant searches!")
    print(f"  Start the API: python run_server.py")
    print(f"  Then search unlimited times with zero delays.\n")


if __name__ == "__main__":
    main()
