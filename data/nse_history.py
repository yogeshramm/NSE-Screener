"""
NSE History Builder
Builds and maintains price history from daily Bhavcopy downloads.
After initial yfinance backfill, prices come entirely from NSE — no rate limits.

How it works:
1. First run: yfinance backfills 1 year of history (one-time, slow)
2. Every day after: Bhavcopy appends today's OHLCV (instant, no rate limits)
3. Result: complete price history for ALL NSE stocks, updated daily

Storage: data_store/history/{SYMBOL}.pkl — persistent across sessions
"""

import pickle
import pandas as pd
from pathlib import Path
from datetime import datetime

from data.nse_bhavcopy import download_bhavcopy

HISTORY_DIR = Path(__file__).parent.parent / "data_store" / "history"


def _get_history_path(symbol: str) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_DIR / f"{symbol.upper()}.pkl"


def load_history(symbol: str) -> pd.DataFrame | None:
    """Load stored price history for a symbol."""
    path = _get_history_path(symbol)
    if path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    return None


def save_history(symbol: str, df: pd.DataFrame):
    """Save price history for a symbol."""
    path = _get_history_path(symbol)
    with open(path, "wb") as f:
        pickle.dump(df, f)


def get_history_stats() -> dict:
    """Get stats about stored history."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    files = list(HISTORY_DIR.glob("*.pkl"))
    if not files:
        return {"total_symbols": 0, "symbols": []}

    symbols = [f.stem for f in files]
    # Check one file for date range
    sample = load_history(symbols[0])
    latest_date = str(sample.index[-1].date()) if sample is not None and len(sample) > 0 else "N/A"

    return {
        "total_symbols": len(symbols),
        "latest_date": latest_date,
        "symbols": sorted(symbols),
    }


def append_bhavcopy_to_history(bhavcopy_df: pd.DataFrame = None) -> dict:
    """
    Download today's Bhavcopy and append OHLCV data to all stored histories.
    This is the daily update — no yfinance needed.

    Returns stats about the update.
    """
    if bhavcopy_df is None:
        print("  Downloading today's Bhavcopy from NSE...")
        bhavcopy_df = download_bhavcopy()

    # Find columns
    symbol_col = None
    for col in ["SYMBOL", "TckrSymb", "Symbol"]:
        if col in bhavcopy_df.columns:
            symbol_col = col
            break

    if symbol_col is None:
        raise ValueError(f"Cannot find symbol column. Columns: {list(bhavcopy_df.columns)}")

    # Map Bhavcopy columns to OHLCV
    col_map = {}
    for target, candidates in {
        "Open": ["OPEN_PRICE", "OPEN", "OpnPric"],
        "High": ["HIGH_PRICE", "HIGH", "HghPric"],
        "Low": ["LOW_PRICE", "LOW", "LwPric"],
        "Close": ["CLOSE_PRICE", "CLOSE", "ClsPric"],
        "Volume": ["TTL_TRD_QNTY", "TOTTRDQTY", "TtlTrdQnty"],
    }.items():
        for c in candidates:
            if c in bhavcopy_df.columns:
                col_map[c] = target
                break

    if len(col_map) < 5:
        # Try to find at least close and volume
        print(f"  [WARN] Could only map {len(col_map)} OHLCV columns from Bhavcopy")

    # Find date column
    date_col = None
    date_val = None
    for col in ["DATE1", "TRADING_DATE", "TradDt", "Date"]:
        if col in bhavcopy_df.columns:
            date_col = col
            break

    # Filter EQ series only
    series_col = None
    for col in ["SERIES", "SctySrs", "Series"]:
        if col in bhavcopy_df.columns:
            series_col = col
            break

    if series_col:
        eq_df = bhavcopy_df[bhavcopy_df[series_col].str.strip() == "EQ"].copy()
    else:
        eq_df = bhavcopy_df.copy()

    updated = 0
    new = 0
    errors = 0

    for _, row in eq_df.iterrows():
        symbol = str(row[symbol_col]).strip()
        try:
            # Build today's OHLCV row
            today_data = {}
            for bhav_col, ohlcv_col in col_map.items():
                today_data[ohlcv_col] = float(row[bhav_col])

            if len(today_data) < 4:
                continue

            # Parse date
            if date_col and row[date_col]:
                try:
                    date_str = str(row[date_col]).strip()
                    for fmt in ["%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"]:
                        try:
                            trade_date = pd.Timestamp(datetime.strptime(date_str, fmt))
                            break
                        except ValueError:
                            continue
                    else:
                        trade_date = pd.Timestamp.now().normalize()
                except Exception:
                    trade_date = pd.Timestamp.now().normalize()
            else:
                trade_date = pd.Timestamp.now().normalize()

            today_row = pd.DataFrame([today_data], index=pd.DatetimeIndex([trade_date]))
            today_row.index.name = "Date"

            # Load existing history
            existing = load_history(symbol)

            if existing is not None and len(existing) > 0:
                # Check if today already exists
                if trade_date in existing.index:
                    continue  # already have this day
                # Append
                combined = pd.concat([existing, today_row])
                combined = combined[~combined.index.duplicated(keep="last")]
                combined.sort_index(inplace=True)
                save_history(symbol, combined)
                updated += 1
            else:
                # First time — just save today (will need yfinance backfill for full history)
                save_history(symbol, today_row)
                new += 1

        except Exception:
            errors += 1

    stats = {
        "total_in_bhavcopy": len(eq_df),
        "updated": updated,
        "new": new,
        "errors": errors,
    }

    print(f"  Bhavcopy update: {updated} updated, {new} new, {errors} errors")
    return stats


def backfill_from_yfinance(symbol: str, days: int = 365) -> bool:
    """
    One-time backfill of price history from yfinance.
    Only needed for initial setup or if history is too short.
    """
    from data.yfinance_fetcher import fetch_price_history, _retry_on_rate_limit

    try:
        df = _retry_on_rate_limit(fetch_price_history, symbol, period_days=days)
        if df is not None and len(df) > 50:
            # Merge with any existing Bhavcopy data
            existing = load_history(symbol)
            if existing is not None and len(existing) > 0:
                combined = pd.concat([df, existing])
                combined = combined[~combined.index.duplicated(keep="last")]
                combined.sort_index(inplace=True)
                save_history(symbol, combined)
            else:
                save_history(symbol, df)
            return True
    except Exception as e:
        print(f"  Backfill failed for {symbol}: {e}")
    return False


def get_stock_history(symbol: str, min_bars: int = 200) -> pd.DataFrame | None:
    """
    Get price history for a stock.
    Returns stored history if sufficient, otherwise None.
    """
    df = load_history(symbol)
    if df is not None and len(df) >= min_bars:
        return df
    return None
