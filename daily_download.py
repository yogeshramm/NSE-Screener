"""
Daily Data Download Script
Run once after market close (6:30 PM IST) to pre-download all NSE stock data.
After this runs, all screening searches are instant — zero API calls.

Usage:
  python daily_download.py                    # download all NSE stocks
  python daily_download.py --symbols RELIANCE,TCS,INFY   # specific stocks
  python daily_download.py --fallback         # use curated 150-stock list
  python daily_download.py --status           # check download status
"""

import argparse
import sys
from data.batch_downloader import (
    run_batch_download, is_today_downloaded, get_downloaded_symbols,
    get_available_dates
)
from data.nse_symbols import get_nse_stock_list, NIFTY_500_FALLBACK


def main():
    parser = argparse.ArgumentParser(description="NSE Daily Data Downloader")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols to download")
    parser.add_argument("--fallback", action="store_true", help="Use curated 150-stock list instead of full Bhavcopy")
    parser.add_argument("--status", action="store_true", help="Check today's download status")
    parser.add_argument("--no-resume", action="store_true", help="Re-download everything (ignore cache)")
    parser.add_argument("--date", type=str, help="Download for specific date (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.status:
        print("\n  NSE Screener — Download Status")
        print(f"  {'='*40}")
        dates = get_available_dates()
        if not dates:
            print("  No data downloaded yet.")
        else:
            for d in dates[:5]:
                count = len(get_downloaded_symbols(d))
                print(f"  {d}: {count} stocks")
        today_count = len(get_downloaded_symbols())
        print(f"\n  Today: {today_count} stocks cached")
        print(f"  Ready for instant screening: {'YES' if today_count > 50 else 'NO'}")
        return

    print("\n" + "="*60)
    print("  NSE SCREENER — DAILY DATA DOWNLOAD")
    print("  Run this after market close (3:30 PM IST)")
    print("  All subsequent searches will be instant")
    print("="*60)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    elif args.fallback:
        symbols = list(NIFTY_500_FALLBACK)
    else:
        symbols = None  # will auto-fetch from Bhavcopy

    stats = run_batch_download(
        symbols=symbols,
        trade_date=args.date,
        resume=not args.no_resume,
    )

    print(f"\n  Your screener is now ready for instant searches!")
    print(f"  Start the API: python run_server.py")
    print(f"  Then search unlimited times with zero delays.\n")


if __name__ == "__main__":
    main()
