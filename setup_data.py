"""
ONE-TIME DATA SETUP — Downloads ALL historical data from NSE + screener.in

PRICES:  NSE Bhavcopy archives (1 CSV per day = ALL stocks, no rate limit)
         Downloads ~250 trading days to build 1 year of OHLCV history.
FUNDAMENTALS: screener.in (ROE, ROCE, PE, D/E, FII/DII, promoter holdings)

NO yfinance dependency. NO rate limits. Pure NSE + screener.in data.

Usage:
  python setup_data.py                          # full setup
  python setup_data.py --days 30                # last 30 trading days only
  python setup_data.py --symbols RELIANCE,TCS   # check specific stocks after setup
  python setup_data.py --status                 # check what's downloaded
  python setup_data.py --fundamentals-only      # just screener.in data
"""

import argparse
import time
import pickle
import io
import zipfile
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

from data.nse_symbols import NIFTY_500_FALLBACK
from data.screener_in import fetch_from_screener

DATA_DIR = Path("data_store")
HISTORY_DIR = DATA_DIR / "history"
FUNDAMENTALS_DIR = DATA_DIR / "fundamentals"

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Referer": "https://www.nseindia.com/",
}


def _get_nse_session():
    """Create session with NSE cookies."""
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get("https://www.nseindia.com/", timeout=10)
    except Exception:
        pass
    return session


def _download_bhavcopy_for_date(session, dt: datetime) -> pd.DataFrame | None:
    """Download Bhavcopy for a specific date. Returns DataFrame or None."""
    dd = dt.strftime("%d")
    mm = dt.strftime("%m")
    yyyy = dt.strftime("%Y")
    ddmmyyyy = dt.strftime("%d%m%Y")
    mon = dt.strftime("%b").upper()

    urls = [
        f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv",
        f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mon}/cm{dd}{mon}{yyyy}bhav.csv.zip",
    ]

    for url in urls:
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 500:
                if url.endswith(".zip"):
                    z = zipfile.ZipFile(io.BytesIO(resp.content))
                    csv_name = [n for n in z.namelist() if n.endswith(".csv")][0]
                    df = pd.read_csv(z.open(csv_name))
                else:
                    df = pd.read_csv(io.StringIO(resp.text))
                df.columns = df.columns.str.strip()
                return df
        except Exception:
            continue
    return None


def _parse_bhavcopy_row(row, col_map: dict, symbol_col: str, date_col: str) -> tuple:
    """Parse a single Bhavcopy row into (symbol, date, OHLCV dict)."""
    symbol = str(row[symbol_col]).strip()
    ohlcv = {}
    for bhav_col, target_col in col_map.items():
        if bhav_col in row.index:
            ohlcv[target_col] = float(row[bhav_col])

    # Parse date
    if date_col and date_col in row.index:
        date_str = str(row[date_col]).strip()
        for fmt in ["%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"]:
            try:
                trade_date = pd.Timestamp(datetime.strptime(date_str, fmt))
                return symbol, trade_date, ohlcv
            except ValueError:
                continue

    return symbol, None, ohlcv


def download_historical_prices(days: int = 260) -> dict:
    """
    Download historical Bhavcopies from NSE archives.
    Each Bhavcopy has ALL stocks for that day — no rate limits.

    Args:
        days: number of calendar days to go back (260 ≈ 1 year of trading days)
    """
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    session = _get_nse_session()
    all_data = {}  # {symbol: list of (date, ohlcv)}

    print(f"\n  Downloading {days} calendar days of Bhavcopies from NSE...")
    print(f"  Each file has ALL stocks. No rate limits.\n")

    downloaded = 0
    skipped = 0
    today = datetime.now()

    for i in range(days):
        dt = today - timedelta(days=i)

        # Skip weekends
        if dt.weekday() >= 5:
            continue

        date_str = dt.strftime("%Y-%m-%d")

        try:
            df = _download_bhavcopy_for_date(session, dt)
            if df is None:
                skipped += 1
                continue

            # Find columns
            symbol_col = next((c for c in ["SYMBOL", "TckrSymb"] if c in df.columns), None)
            series_col = next((c for c in ["SERIES", "SctySrs"] if c in df.columns), None)
            date_col = next((c for c in ["DATE1", "TradDt", "TRADING_DATE"] if c in df.columns), None)

            if symbol_col is None:
                skipped += 1
                continue

            # Column mapping
            col_map = {}
            for target, candidates in {
                "Open": ["OPEN_PRICE", "OPEN", "OpnPric"],
                "High": ["HIGH_PRICE", "HIGH", "HghPric"],
                "Low": ["LOW_PRICE", "LOW", "LwPric"],
                "Close": ["CLOSE_PRICE", "CLOSE", "ClsPric"],
                "Volume": ["TTL_TRD_QNTY", "TOTTRDQTY", "TtlTrdQnty"],
            }.items():
                for c in candidates:
                    if c in df.columns:
                        col_map[c] = target
                        break

            # Filter EQ series
            if series_col:
                df = df[df[series_col].str.strip() == "EQ"]

            # Parse all rows
            for _, row in df.iterrows():
                symbol, trade_date, ohlcv = _parse_bhavcopy_row(row, col_map, symbol_col, date_col)
                if trade_date is None:
                    trade_date = pd.Timestamp(dt.date())
                if len(ohlcv) >= 4:
                    if symbol not in all_data:
                        all_data[symbol] = []
                    all_data[symbol].append((trade_date, ohlcv))

            downloaded += 1
            if downloaded % 10 == 0:
                print(f"    {downloaded} days downloaded... ({len(all_data)} stocks found)")

            # Small delay to be polite to NSE
            time.sleep(0.5)

        except Exception as e:
            skipped += 1
            if "Rate" in str(e) or "429" in str(e):
                print(f"    Rate limited, waiting 10s...")
                time.sleep(10)

    # Save each stock's history
    print(f"\n  Saving {len(all_data)} stocks to disk...")
    saved = 0
    for symbol, entries in all_data.items():
        try:
            # Sort by date
            entries.sort(key=lambda x: x[0])
            dates = [e[0] for e in entries]
            ohlcv_list = [e[1] for e in entries]

            stock_df = pd.DataFrame(ohlcv_list, index=pd.DatetimeIndex(dates))
            stock_df.index.name = "Date"

            filepath = HISTORY_DIR / f"{symbol}.pkl"
            with open(filepath, "wb") as f:
                pickle.dump(stock_df, f)
            saved += 1
        except Exception:
            pass

    stats = {
        "days_downloaded": downloaded,
        "days_skipped": skipped,
        "stocks_saved": saved,
        "total_symbols": len(all_data),
    }

    print(f"\n  Prices complete: {saved} stocks, {downloaded} trading days")
    return stats


def download_all_fundamentals(symbols: list[str]) -> dict:
    """Download fundamentals from screener.in. ~1.5s per stock."""
    FUNDAMENTALS_DIR.mkdir(parents=True, exist_ok=True)

    # Skip already downloaded
    existing = {f.stem for f in FUNDAMENTALS_DIR.glob("*.pkl")}
    remaining = [s for s in symbols if s not in existing]

    if not remaining:
        print(f"\n  All {len(symbols)} stocks already have fundamentals cached.")
        return {"saved": len(existing), "failed": 0}

    print(f"\n  Downloading fundamentals for {len(remaining)} stocks from screener.in...")
    print(f"  ({len(existing)} already cached, skipping)")
    print(f"  Estimated time: {len(remaining) * 1.5 / 60:.1f} minutes\n")

    saved = 0
    failed = 0

    for i, symbol in enumerate(remaining):
        try:
            data = fetch_from_screener(symbol, use_cache=False)
            if data.get("error"):
                failed += 1
                continue

            filepath = FUNDAMENTALS_DIR / f"{symbol}.pkl"
            with open(filepath, "wb") as f:
                pickle.dump(data, f)

            saved += 1
            roe = data.get("roe_pct", "N/A")
            pe = data.get("pe", "N/A")
            print(f"    {symbol:15s}: ROE={roe}% PE={pe}")
        except Exception:
            failed += 1

        if i < len(remaining) - 1:
            time.sleep(1.5)

    print(f"\n  Fundamentals: {saved} saved, {failed} failed")
    return {"saved": saved + len(existing), "failed": failed}


def load_stock_full(symbol: str) -> dict | None:
    """Load both price history + fundamentals for a stock."""
    symbol = symbol.upper()
    result = {"symbol": symbol}

    # Prices
    hist_path = HISTORY_DIR / f"{symbol}.pkl"
    if hist_path.exists():
        with open(hist_path, "rb") as f:
            result["daily_history"] = pickle.load(f)
            result["daily_rows"] = len(result["daily_history"])
            result["latest_close"] = round(result["daily_history"]["Close"].iloc[-1], 2)
            result["latest_date"] = str(result["daily_history"].index[-1].date())

    # Fundamentals
    fund_path = FUNDAMENTALS_DIR / f"{symbol}.pkl"
    if fund_path.exists():
        with open(fund_path, "rb") as f:
            fund = pickle.load(f)
            result.update(fund)

    if "daily_history" not in result:
        return None

    return result


def check_status():
    """Show download status."""
    print("\n  NSE Screener — Data Status")
    print(f"  {'='*50}")

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    FUNDAMENTALS_DIR.mkdir(parents=True, exist_ok=True)

    price_files = list(HISTORY_DIR.glob("*.pkl"))
    fund_files = list(FUNDAMENTALS_DIR.glob("*.pkl"))

    print(f"\n  Prices:       {len(price_files)} stocks")
    if price_files:
        with open(price_files[0], "rb") as f:
            sample = pickle.load(f)
        print(f"  Date range:   {sample.index[0].date()} to {sample.index[-1].date()}")
        print(f"  Trading days: {len(sample)}")

    print(f"\n  Fundamentals: {len(fund_files)} stocks")

    ready = len(price_files) >= 50 and len(fund_files) >= 50
    print(f"\n  Ready: {'YES — run python run_server.py' if ready else 'NO — run python setup_data.py'}")


def main():
    parser = argparse.ArgumentParser(description="NSE Screener — Data Setup")
    parser.add_argument("--days", type=int, default=370, help="Calendar days of history (default 370 ≈ 1 year trading)")
    parser.add_argument("--symbols", type=str, help="Check specific symbols after setup")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--prices-only", action="store_true")
    parser.add_argument("--fundamentals-only", action="store_true")
    args = parser.parse_args()

    if args.status:
        check_status()
        return

    print("\n" + "="*60)
    print("  NSE SCREENER — DATA SETUP")
    print("  Source: NSE Bhavcopy archives + screener.in")
    print("  No yfinance. No rate limits.")
    print("="*60)

    start = time.time()

    # STEP 1: Prices from NSE
    if not args.fundamentals_only:
        print(f"\n  STEP 1: HISTORICAL PRICES (NSE Bhavcopy archives)")
        price_stats = download_historical_prices(days=args.days)
    else:
        price_stats = {"stocks_saved": 0}

    # STEP 2: Fundamentals from screener.in
    if not args.prices_only:
        print(f"\n  STEP 2: FUNDAMENTALS (screener.in)")
        fund_stats = download_all_fundamentals(list(NIFTY_500_FALLBACK))
    else:
        fund_stats = {"saved": 0}

    elapsed = time.time() - start

    print(f"\n{'='*60}")
    print(f"  SETUP COMPLETE ({elapsed:.0f}s)")
    print(f"  Prices: {price_stats.get('stocks_saved', 0)} stocks")
    print(f"  Fundamentals: {fund_stats.get('saved', 0)} stocks")
    print(f"  Ready for unlimited instant screening!")
    print(f"{'='*60}\n")

    # Show specific stocks if requested
    if args.symbols:
        for sym in args.symbols.split(","):
            sym = sym.strip().upper()
            data = load_stock_full(sym)
            if data:
                print(f"  {sym}: {data.get('daily_rows', 0)} bars, "
                      f"Close=₹{data.get('latest_close')}, "
                      f"ROE={data.get('roe_pct', 'N/A')}%, "
                      f"PE={data.get('pe', 'N/A')}")
            else:
                print(f"  {sym}: not found")


if __name__ == "__main__":
    main()
