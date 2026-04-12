"""
Batch Data Downloader
Downloads data for all NSE stocks in controlled batches.
Designed to run once daily after market close (6:30 PM IST).
Stores everything in a persistent daily data store.

After this runs, all screening searches use cached data — zero API calls.
"""

import time
import json
import pickle
import pandas as pd
from pathlib import Path
from datetime import datetime, date

from data.yfinance_fetcher import (
    fetch_price_history, fetch_fundamentals, fetch_analyst_recommendations,
    fetch_earnings_calendar, fetch_balance_sheet, compute_roce,
    _nse_symbol, _retry_on_rate_limit
)
from data.nse_symbols import get_nse_stock_list

# Persistent daily store — survives across sessions
DATA_STORE_DIR = Path(__file__).parent.parent / "data_store"

# Batch settings (tuned to avoid yfinance rate limits)
BATCH_SIZE = 5           # stocks per batch
DELAY_BETWEEN_CALLS = 2  # seconds between yfinance calls
DELAY_BETWEEN_BATCHES = 15  # seconds between batches
MAX_RETRIES_PER_STOCK = 2


def _today_str() -> str:
    return date.today().isoformat()


def _get_store_path(trade_date: str = None) -> Path:
    """Get the data store directory for a given date."""
    if trade_date is None:
        trade_date = _today_str()
    store_path = DATA_STORE_DIR / trade_date
    store_path.mkdir(parents=True, exist_ok=True)
    return store_path


def _save_stock_data(symbol: str, data: dict, trade_date: str = None):
    """Save a single stock's data to the daily store."""
    store = _get_store_path(trade_date)
    filepath = store / f"{symbol}.pkl"
    with open(filepath, "wb") as f:
        pickle.dump(data, f)


def load_stock_data(symbol: str, trade_date: str = None) -> dict | None:
    """Load a single stock's pre-downloaded data. Returns None if not found."""
    if trade_date is None:
        trade_date = _today_str()
    store = DATA_STORE_DIR / trade_date
    filepath = store / f"{symbol.upper()}.pkl"
    if filepath.exists():
        with open(filepath, "rb") as f:
            return pickle.load(f)
    return None


def load_stock_daily_df(symbol: str, trade_date: str = None) -> pd.DataFrame | None:
    """Load just the daily OHLCV DataFrame for a stock."""
    data = load_stock_data(symbol, trade_date)
    if data and "daily_history" in data:
        return data["daily_history"]
    return None


def get_available_dates() -> list[str]:
    """List all dates that have downloaded data."""
    DATA_STORE_DIR.mkdir(parents=True, exist_ok=True)
    dates = [d.name for d in DATA_STORE_DIR.iterdir() if d.is_dir()]
    return sorted(dates, reverse=True)


def get_downloaded_symbols(trade_date: str = None) -> list[str]:
    """List all symbols downloaded for a given date."""
    if trade_date is None:
        trade_date = _today_str()
    store = DATA_STORE_DIR / trade_date
    if not store.exists():
        return []
    return [f.stem for f in store.glob("*.pkl")]


def is_today_downloaded() -> bool:
    """Check if today's data has been downloaded."""
    symbols = get_downloaded_symbols()
    return len(symbols) > 50  # at least 50 stocks downloaded


def download_single_stock(symbol: str) -> dict | None:
    """
    Download all data for a single stock.
    Returns dict with daily_history, fundamentals, etc.
    """
    import yfinance as yf

    ticker_sym = _nse_symbol(symbol)
    result = {"symbol": symbol, "download_time": datetime.now().isoformat()}

    try:
        ticker = yf.Ticker(ticker_sym)

        # 1. Daily price history (1 year)
        try:
            hist = ticker.history(period="1y")
            if hist is not None and not hist.empty:
                for col in ["Dividends", "Stock Splits"]:
                    if col in hist.columns:
                        hist.drop(columns=[col], inplace=True)
                result["daily_history"] = hist
                result["daily_rows"] = len(hist)
                result["latest_close"] = round(hist["Close"].iloc[-1], 2)
                result["latest_date"] = str(hist.index[-1].date())
            else:
                result["daily_history"] = pd.DataFrame()
                result["daily_rows"] = 0
                return None  # no price data = skip this stock
        except Exception:
            return None

        time.sleep(DELAY_BETWEEN_CALLS)

        # 2. Fundamentals from ticker.info
        try:
            info = ticker.info or {}
            result["roe"] = info.get("returnOnEquity")
            result["debt_to_equity"] = info.get("debtToEquity")
            result["trailing_eps"] = info.get("trailingEps")
            result["free_cash_flow"] = info.get("freeCashflow")
            result["institutional_holdings"] = info.get("institutionPercentHeld")
            result["trailing_pe"] = info.get("trailingPE")
            result["fifty_two_week_high"] = info.get("fiftyTwoWeekHigh")
            result["average_volume"] = info.get("averageVolume")
            result["market_cap"] = info.get("marketCap")
            result["sector"] = info.get("sector")
            result["industry"] = info.get("industry")
            result["short_name"] = info.get("shortName")
            result["current_price"] = info.get("currentPrice") or info.get("regularMarketPrice")
        except Exception:
            pass

        time.sleep(DELAY_BETWEEN_CALLS)

        # 3. ROE fallback
        if result.get("roe") is None:
            try:
                inc = ticker.income_stmt
                bs = ticker.balance_sheet
                if inc is not None and not inc.empty and bs is not None and not bs.empty:
                    net_income = None
                    for key in ["Net Income", "Net Income Common Stockholders"]:
                        if key in inc.index:
                            net_income = inc.iloc[:, 0][key]
                            break
                    equity = None
                    for key in ["Stockholders Equity", "Common Stock Equity"]:
                        if key in bs.index:
                            equity = bs.iloc[:, 0][key]
                            break
                    if net_income is not None and equity is not None and equity != 0:
                        result["roe"] = net_income / equity
            except Exception:
                pass

        # 4. FCF fallback
        if result.get("free_cash_flow") is None:
            try:
                cf = ticker.cashflow
                if cf is not None and not cf.empty:
                    latest = cf.iloc[:, 0]
                    op_cf = None
                    for key in ["Operating Cash Flow", "Total Cash From Operating Activities"]:
                        if key in latest.index:
                            op_cf = latest[key]
                            break
                    capex = None
                    for key in ["Capital Expenditure", "Capital Expenditures"]:
                        if key in latest.index:
                            capex = latest[key]
                            break
                    if op_cf is not None and capex is not None:
                        result["free_cash_flow"] = op_cf + capex
            except Exception:
                pass

        time.sleep(DELAY_BETWEEN_CALLS)

        # 5. Analyst recommendations
        try:
            recs = ticker.recommendations
            result["recommendations"] = recs if recs is not None and not recs.empty else pd.DataFrame()
            result["recommendations_count"] = len(result["recommendations"])
        except Exception:
            result["recommendations"] = pd.DataFrame()
            result["recommendations_count"] = 0

        # 6. Earnings calendar
        try:
            cal = ticker.calendar
            if isinstance(cal, pd.DataFrame):
                result["earnings_calendar"] = cal.to_dict()
            elif isinstance(cal, dict):
                result["earnings_calendar"] = cal
            else:
                result["earnings_calendar"] = {}
        except Exception:
            result["earnings_calendar"] = {}

        # 7. Balance sheet + ROCE
        try:
            bs = ticker.balance_sheet
            result["balance_sheet"] = bs if bs is not None and not bs.empty else pd.DataFrame()
            result["balance_sheet_years"] = len(bs.columns) if bs is not None and not bs.empty else 0
        except Exception:
            result["balance_sheet"] = pd.DataFrame()
            result["balance_sheet_years"] = 0

        try:
            result["roce"] = compute_roce(symbol)
        except Exception:
            result["roce"] = None

        # 8. Format derived values
        if result.get("roe") is not None:
            result["roe_pct"] = round(result["roe"] * 100, 2)
        else:
            result["roe_pct"] = None

        if result.get("debt_to_equity") is not None:
            de = result["debt_to_equity"]
            result["debt_to_equity_ratio"] = round(de / 100, 2) if de > 10 else round(de, 2)
        else:
            result["debt_to_equity_ratio"] = None

        if result.get("institutional_holdings") is not None:
            result["institutional_holdings_pct"] = round(result["institutional_holdings"] * 100, 2)
        else:
            result["institutional_holdings_pct"] = None

        return result

    except Exception as e:
        print(f"    FAILED {symbol}: {e}")
        return None


def run_batch_download(symbols: list[str] = None, trade_date: str = None,
                       resume: bool = True) -> dict:
    """
    Download data for all stocks in batches.

    Args:
        symbols: list of symbols to download. If None, fetches full NSE list.
        trade_date: date string. If None, uses today.
        resume: if True, skips already-downloaded symbols.

    Returns:
        dict with download stats.
    """
    if trade_date is None:
        trade_date = _today_str()

    if symbols is None:
        print("Fetching NSE stock list...")
        symbols = get_nse_stock_list()

    # Resume support — skip already downloaded
    if resume:
        already = set(get_downloaded_symbols(trade_date))
        remaining = [s for s in symbols if s not in already]
        print(f"Total: {len(symbols)} | Already downloaded: {len(already)} | Remaining: {len(remaining)}")
        symbols = remaining
    else:
        print(f"Total symbols to download: {len(symbols)}")

    if not symbols:
        print("Nothing to download — all stocks already cached!")
        return {"total": 0, "success": 0, "failed": 0, "skipped": len(get_downloaded_symbols(trade_date))}

    success = 0
    failed = 0
    failed_symbols = []
    start_time = time.time()

    # Process in batches
    total_batches = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(total_batches):
        batch_start = batch_idx * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, len(symbols))
        batch = symbols[batch_start:batch_end]

        print(f"\n  Batch {batch_idx + 1}/{total_batches}: {batch}")

        for symbol in batch:
            try:
                data = download_single_stock(symbol)
                if data is not None:
                    _save_stock_data(symbol, data, trade_date)
                    success += 1
                    print(f"    OK  {symbol} (₹{data.get('latest_close', '?')})")
                else:
                    failed += 1
                    failed_symbols.append(symbol)
                    print(f"    SKIP {symbol} (no data)")
            except Exception as e:
                failed += 1
                failed_symbols.append(symbol)
                print(f"    ERR  {symbol}: {e}")

        # Delay between batches
        if batch_idx < total_batches - 1:
            print(f"  Waiting {DELAY_BETWEEN_BATCHES}s before next batch...")
            time.sleep(DELAY_BETWEEN_BATCHES)

    elapsed = time.time() - start_time
    total_stored = len(get_downloaded_symbols(trade_date))

    stats = {
        "trade_date": trade_date,
        "total_attempted": len(symbols),
        "success": success,
        "failed": failed,
        "failed_symbols": failed_symbols,
        "total_stored": total_stored,
        "elapsed_seconds": round(elapsed, 1),
    }

    # Save stats
    stats_path = _get_store_path(trade_date) / "_stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  DOWNLOAD COMPLETE")
    print(f"  Date: {trade_date}")
    print(f"  Success: {success} | Failed: {failed} | Total stored: {total_stored}")
    print(f"  Time: {elapsed:.0f}s")
    print(f"{'='*60}")

    return stats
