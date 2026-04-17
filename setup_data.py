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
import json
import threading
import time
import pickle
import io
import zipfile
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from pathlib import Path
from datetime import datetime, timedelta

from data.nse_symbols import NIFTY_500_FALLBACK
from data.screener_in import fetch_from_screener

DATA_DIR = Path("data_store")
HISTORY_DIR = DATA_DIR / "history"
FUNDAMENTALS_DIR = DATA_DIR / "fundamentals"
PROGRESS_FILE = Path("/tmp/history_refresh.progress.json")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Referer": "https://www.nseindia.com/",
}

# NSE equity-market holidays 2024-2026 (Republic Day, Holi, Good Friday, Eid,
# Independence Day, Janmashtami, Gandhi Jayanti, Dussehra, Diwali Laxmi Pujan,
# Diwali Balipratipada, Guru Nanak Jayanti, Christmas + a few others).
# Missing entries are caught by the 404 path, so this set is a speed hint only.
NSE_HOLIDAYS = {
    # 2024
    "2024-01-26", "2024-03-08", "2024-03-25", "2024-03-29", "2024-04-11",
    "2024-04-17", "2024-05-01", "2024-06-17", "2024-07-17", "2024-08-15",
    "2024-10-02", "2024-11-01", "2024-11-15", "2024-12-25",
    # 2025
    "2025-02-26", "2025-03-14", "2025-03-31", "2025-04-10", "2025-04-14",
    "2025-04-18", "2025-05-01", "2025-08-15", "2025-08-27", "2025-10-02",
    "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25",
    # 2026
    "2026-01-26", "2026-03-03", "2026-03-19", "2026-04-03", "2026-04-14",
    "2026-05-01", "2026-08-15", "2026-09-04", "2026-10-02",
    "2026-11-08", "2026-11-09", "2026-11-24", "2026-12-25",
}

# Rate-limit / worker coordination
_rate_lock = threading.Lock()
_recent_429 = []  # rolling window of (timestamp, is_429_bool) for last 30 attempts
_merge_lock = threading.Lock()


def _is_trading_day(dt: datetime) -> bool:
    """Weekend + NSE holiday check. Cheap, no HTTP."""
    if dt.weekday() >= 5:
        return False
    if dt.strftime("%Y-%m-%d") in NSE_HOLIDAYS:
        return False
    return True


def _get_nse_session():
    """Create session with NSE cookies + pooled adapter."""
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    adapter = HTTPAdapter(pool_connections=5, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    try:
        session.get("https://www.nseindia.com/", timeout=(5, 10))
    except Exception:
        pass
    return session


def _record_attempt(is_429: bool):
    """Track rolling window of last 30 download attempts for 429 rate detection."""
    with _rate_lock:
        _recent_429.append((time.time(), is_429))
        if len(_recent_429) > 30:
            _recent_429.pop(0)


def _recent_429_count() -> int:
    with _rate_lock:
        return sum(1 for _, f in _recent_429 if f)


def _load_progress() -> dict:
    """Load checkpoint file if present."""
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_progress(state: dict):
    """Atomically save checkpoint."""
    state["last_checkpoint_at"] = datetime.utcnow().isoformat() + "Z"
    tmp = PROGRESS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f)
    tmp.replace(PROGRESS_FILE)


def _scan_existing_coverage() -> tuple:
    """Fallback when no progress file: infer coverage from existing pickles.
    Returns (min_date, max_date) across sample liquid stocks, or (None, None).
    Caller treats the [min, max] range as already-covered and only fetches
    OUTSIDE that range (older than min)."""
    samples = ["RELIANCE", "TCS", "HDFCBANK"]
    earliest = None
    latest = None
    for sym in samples:
        p = HISTORY_DIR / f"{sym}.pkl"
        if p.exists():
            try:
                with open(p, "rb") as f:
                    df = pickle.load(f)
                if len(df) > 0:
                    d0, d1 = df.index[0], df.index[-1]
                    if earliest is None or d0 < earliest:
                        earliest = d0
                    if latest is None or d1 > latest:
                        latest = d1
            except Exception:
                continue
    return earliest, latest


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


def _parse_bhavcopy_df(df: pd.DataFrame, fallback_dt: datetime) -> list[tuple]:
    """Pure parse: returns [(symbol, trade_date, ohlcv_dict), ...]. No I/O."""
    symbol_col = next((c for c in ["SYMBOL", "TckrSymb"] if c in df.columns), None)
    series_col = next((c for c in ["SERIES", "SctySrs"] if c in df.columns), None)
    date_col = next((c for c in ["DATE1", "TradDt", "TRADING_DATE"] if c in df.columns), None)
    if symbol_col is None:
        return []

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

    if series_col:
        df = df[df[series_col].astype(str).str.strip() == "EQ"]

    rows = []
    for _, row in df.iterrows():
        symbol, trade_date, ohlcv = _parse_bhavcopy_row(row, col_map, symbol_col, date_col)
        if trade_date is None:
            trade_date = pd.Timestamp(fallback_dt.date())
        if len(ohlcv) >= 4:
            rows.append((symbol, trade_date, ohlcv))
    return rows


def _fetch_one_day(dt: datetime, session_getter) -> tuple:
    """Worker: fetch + parse one bhavcopy. Returns (date_str, rows_or_None, had_429).
    On 429: waits 15s, retries ONCE."""
    date_str = dt.strftime("%Y-%m-%d")
    session = session_getter()
    had_429 = False

    for attempt in range(2):
        try:
            df = _download_bhavcopy_for_date(session, dt)
            if df is None:
                # 404 or empty -> likely a holiday we didn't anticipate; not a 429
                return date_str, None, had_429
            rows = _parse_bhavcopy_df(df, dt)
            time.sleep(0.1)  # polite per-worker pacing
            return date_str, rows, had_429
        except requests.HTTPError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code == 429 and attempt == 0:
                had_429 = True
                _record_attempt(True)
                time.sleep(15)
                continue
            return date_str, None, had_429
        except Exception as e:
            msg = str(e)
            if ("429" in msg or "Rate" in msg) and attempt == 0:
                had_429 = True
                _record_attempt(True)
                time.sleep(15)
                continue
            return date_str, None, had_429

    _record_attempt(had_429)
    return date_str, None, had_429


def _flush_batch(batch: dict) -> int:
    """Merge the in-memory batch into existing pickles via merge + atomic write.
    batch: {symbol: [(date, ohlcv), ...]}.
    Returns number of stocks written. Respects the same merge path used before."""
    if not batch:
        return 0
    written = 0
    with _merge_lock:
        for symbol, entries in batch.items():
            try:
                entries.sort(key=lambda x: x[0])
                dates = [e[0] for e in entries]
                ohlcv_list = [e[1] for e in entries]
                new_df = pd.DataFrame(ohlcv_list, index=pd.DatetimeIndex(dates))
                new_df.index.name = "Date"

                filepath = HISTORY_DIR / f"{symbol}.pkl"
                existing_df = None
                if filepath.exists():
                    try:
                        with open(filepath, "rb") as f:
                            existing_df = pickle.load(f)
                    except Exception:
                        existing_df = None

                if existing_df is not None and len(existing_df) > 0:
                    combined = pd.concat([existing_df, new_df])
                    combined = combined[~combined.index.duplicated(keep="last")]
                    combined.sort_index(inplace=True)
                    out_df = combined
                else:
                    out_df = new_df

                # Atomic write: temp + rename
                tmp_path = filepath.with_suffix(".pkl.tmp")
                with open(tmp_path, "wb") as f:
                    pickle.dump(out_df, f)
                tmp_path.replace(filepath)
                written += 1
            except Exception:
                pass
    return written


def download_historical_prices(days: int = 260) -> dict:
    """
    Download historical Bhavcopies from NSE archives in parallel, with
    checkpoint + resume + merge + atomic write.

    Args:
        days: number of calendar days to go back (800 ≈ 2 years of trading days)
    """
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    # --- Resume bookkeeping -------------------------------------------------
    progress = _load_progress()
    completed_set = set(progress.get("completed_dates", []))
    resume_mode = bool(completed_set)

    # Target date list (most recent first — same shape as original).
    today = datetime.now()
    target_dates = []
    for i in range(days):
        dt = today - timedelta(days=i)
        if not _is_trading_day(dt):
            continue
        target_dates.append(dt)

    if not resume_mode:
        # No progress file — skip dates already covered by existing pickles.
        # Existing pickles span [emin, emax]; treat that whole range as covered
        # and only fetch OLDER dates (the gap we're extending backward).
        emin, emax = _scan_existing_coverage()
        if emin is not None:
            covered = {d.strftime("%Y-%m-%d") for d in target_dates
                       if emin <= pd.Timestamp(d.date()) <= emax}
            if covered:
                completed_set = covered
                print(f"  [resume-scan] skipping {len(covered)} dates already covered "
                      f"({emin.date()} … {emax.date()})")

    remaining = [d for d in target_dates if d.strftime("%Y-%m-%d") not in completed_set]

    state = {
        "target_days_back": days,
        "completed_dates": sorted(completed_set),
        "started_at": progress.get("started_at", datetime.utcnow().isoformat() + "Z"),
        "last_checkpoint_at": progress.get("last_checkpoint_at"),
    }
    _save_progress(state)

    print(f"\n  Downloading {days}d window (2-year target), {len(target_dates)} trading days.")
    print(f"  Already complete: {len(completed_set)}. To fetch: {len(remaining)}.\n")

    if not remaining:
        PROGRESS_FILE.unlink(missing_ok=True)
        return {"days_downloaded": 0, "days_skipped": 0, "stocks_saved": 0, "total_symbols": 0}

    # --- Per-worker sessions -----------------------------------------------
    thread_local = threading.local()

    def _session():
        if not hasattr(thread_local, "s"):
            thread_local.s = _get_nse_session()
        return thread_local.s

    # --- Download loop ------------------------------------------------------
    batch = {}  # {symbol: [(date, ohlcv), ...]}
    batch_dates = []  # dates covered by current unflushed batch
    downloaded = 0
    empty = 0
    max_workers = 3  # start at 3; hard ceiling 4; drop to 2 on sustained 429s
    throttled = False

    def _run_pool(dates_chunk, workers):
        nonlocal downloaded, empty, throttled
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_fetch_one_day, dt, _session): dt for dt in dates_chunk}
            for fut in as_completed(futures):
                date_str, rows, _ = fut.result()
                if rows is None:
                    empty += 1
                    # mark empty dates complete too so resume doesn't re-try them
                    batch_dates.append(date_str)
                    continue
                for symbol, trade_date, ohlcv in rows:
                    batch.setdefault(symbol, []).append((trade_date, ohlcv))
                batch_dates.append(date_str)
                downloaded += 1

                # 429 throttle check
                if not throttled and _recent_429_count() >= 2:
                    throttled = True
                    print(f"    [throttle] 2+ 429s in rolling window — "
                          f"dropping workers to 2 for rest of run")

                # Flush batch every 50 dates covered
                if len(batch_dates) >= 50:
                    _checkpoint(batch, batch_dates, completed_set, state)
                    batch.clear()
                    batch_dates.clear()

                if downloaded % 10 == 0:
                    print(f"    {downloaded} days downloaded, {empty} empty "
                          f"(batch {len(batch_dates)}, stocks {len(batch)})")

    def _checkpoint(_batch, _dates, _completed_set, _state):
        written = _flush_batch(_batch)
        _completed_set.update(_dates)
        _state["completed_dates"] = sorted(_completed_set)
        _save_progress(_state)
        print(f"    [checkpoint] +{len(_dates)} dates, merged {written} stocks, "
              f"total complete {len(_completed_set)}")

    # Process remaining in windowed batches of 60 so we revisit the throttle decision.
    i = 0
    while i < len(remaining):
        chunk_size = 60
        chunk = remaining[i : i + chunk_size]
        workers = min(4, 2 if throttled else max_workers)
        _run_pool(chunk, workers)
        i += chunk_size

    # Final flush for whatever remains in the batch.
    if batch_dates:
        _checkpoint(batch, batch_dates, completed_set, state)
        batch.clear()
        batch_dates.clear()

    # --- Done — drop progress file so next run starts clean -----------------
    PROGRESS_FILE.unlink(missing_ok=True)

    # Count stocks present on disk for reporting (cheap listdir).
    total_stocks = len(list(HISTORY_DIR.glob("*.pkl")))

    stats = {
        "days_downloaded": downloaded,
        "days_skipped": empty,
        "stocks_saved": total_stocks,
        "total_symbols": total_stocks,
    }
    print(f"\n  Prices complete: {total_stocks} stocks on disk, "
          f"{downloaded} days fetched this run ({empty} empty).")
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
