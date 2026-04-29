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
from datetime import datetime, timezone
from pathlib import Path

from data.batch_downloader import (
    run_batch_download, run_daily_update,
    get_downloaded_symbols, get_available_dates
)
from data.nse_history import get_history_stats
from data.nse_symbols import NIFTY_500_FALLBACK


_CRON_STATUS_FILE = Path(__file__).resolve().parent / "data_store" / "cron_status.json"


def _write_cron_status(started_at: str, ok: bool, error: str | None, duration_s: float | None) -> None:
    """Persist cron heartbeat — read by /data/status to drive STALE badge.
    Without this, the UI shows STALE forever even when the cron runs daily."""
    try:
        _CRON_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CRON_STATUS_FILE.write_text(json.dumps({
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": round(duration_s, 1) if duration_s else None,
            "ok": bool(ok),
            "error": (error or "")[:500] if error else None,
        }, indent=2))
    except Exception:
        pass  # never let heartbeat write break the actual download


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

    if args.full:
        # Legacy full yfinance download
        symbols = None
        if args.symbols:
            symbols = [s.strip().upper() for s in args.symbols.split(",")]
        else:
            symbols = list(NIFTY_500_FALLBACK)
        run_batch_download(symbols=symbols)
    else:
        # Smart NSE-first daily update
        backfill = None
        if args.backfill:
            backfill = [s.strip().upper() for s in args.backfill.split(",")]

        run_daily_update(
            backfill_symbols=backfill,
            skip_fundamentals=args.prices_only,
        )

    # Warm indicator cache so next scan is instant
    if not args.prices_only:
        print("  Warming indicator cache...")
        from engine.precompute import warm_cache
        stats = warm_cache(verbose=True)
        print(f"  Cache ready: {stats['computed']} computed, {stats['cached']} reused")

    print(f"\n  Your screener is now ready for instant searches!")
    print(f"  Start the API: python run_server.py")
    print(f"  Then search unlimited times with zero delays.\n")


if __name__ == "__main__":
    # Wrap main() so the cron-driven invocation writes a heartbeat to
    # cron_status.json. Manual invocations (e.g. --status) skip the
    # heartbeat by short-circuiting in main() before it returns.
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.time()
    err: str | None = None
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        # Skip heartbeat for --status (read-only inspection — main returns early)
        import sys as _sys
        if "--status" not in _sys.argv:
            _write_cron_status(started, ok=err is None, error=err, duration_s=time.time() - t0)
