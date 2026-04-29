"""
Angel One instrument master.

Angel publishes a single JSON file daily with every instrument across NSE / BSE
/ MCX / CDS. We download once a day, cache as a pandas DataFrame pickle, and
expose a `symbol_to_token` lookup. NSE equity tickers in the master end with
'-EQ', so 'RELIANCE' (our internal symbol) maps to row symbol='RELIANCE-EQ',
token='2885'.

Master URL (refreshed daily by Angel ~07:00 IST):
    https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json

File size ~50 MB. Cache: data_store/angel_master.pkl, refresh if > 18h old.
"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CACHE_PATH = _PROJECT_ROOT / "data_store" / "angel_master.pkl"
_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)
_TTL_SECONDS = 18 * 3600  # refresh if > 18h old (Angel updates ~07:00 IST daily)

_df_cache: Optional[pd.DataFrame] = None


def _is_cache_fresh() -> bool:
    if not _CACHE_PATH.exists():
        return False
    return (time.time() - _CACHE_PATH.stat().st_mtime) < _TTL_SECONDS


def _download() -> pd.DataFrame:
    """Download fresh master JSON, parse to DataFrame, save to cache."""
    r = requests.get(_MASTER_URL, timeout=60)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    # Coerce numeric columns that occasionally arrive as strings
    for col in ("strike", "lotsize", "tick_size"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_pickle(_CACHE_PATH)
    return df


def get_master_df(force_refresh: bool = False) -> pd.DataFrame:
    """Returns the full master DataFrame (cached, refreshed daily)."""
    global _df_cache
    if _df_cache is not None and not force_refresh:
        return _df_cache
    if _is_cache_fresh() and not force_refresh:
        _df_cache = pd.read_pickle(_CACHE_PATH)
        return _df_cache
    _df_cache = _download()
    return _df_cache


def get_nse_equity_df() -> pd.DataFrame:
    """Subset of master: NSE cash-segment equities only (symbol ends with -EQ)."""
    df = get_master_df()
    mask = (df["exch_seg"] == "NSE") & df["symbol"].str.endswith("-EQ", na=False)
    return df[mask].reset_index(drop=True)


def symbol_to_token(symbol: str, exchange: str = "NSE") -> Optional[str]:
    """Map a plain symbol like 'RELIANCE' to its Angel token like '2885'.

    For NSE equity, looks for row with symbol='RELIANCE-EQ'. For other exchanges,
    matches symbol exactly. Returns None if not found.
    """
    sym_upper = symbol.upper().strip()
    df = get_master_df()
    if exchange == "NSE":
        target = sym_upper if sym_upper.endswith("-EQ") else f"{sym_upper}-EQ"
        match = df[(df["exch_seg"] == "NSE") & (df["symbol"] == target)]
    else:
        match = df[(df["exch_seg"] == exchange) & (df["symbol"] == sym_upper)]
    if match.empty:
        return None
    return str(match.iloc[0]["token"])


def trading_symbol(symbol: str) -> str:
    """Returns the Angel-formatted trading symbol (e.g. 'RELIANCE' -> 'RELIANCE-EQ')."""
    s = symbol.upper().strip()
    return s if s.endswith("-EQ") else f"{s}-EQ"


if __name__ == "__main__":
    print("=== downloading master (this may take 10-30 s on first run) ===")
    df = get_master_df()
    print(f"  total rows:      {len(df):,}")
    print(f"  NSE equities:    {len(get_nse_equity_df()):,}")

    print("\n=== sample lookups ===")
    for sym in ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN", "NIFTY50"]:
        tok = symbol_to_token(sym)
        ts = trading_symbol(sym)
        print(f"  {sym:12s} -> token {tok or 'NOT FOUND'} (tradingsymbol: {ts})")
