"""
Angel One historical OHLC fetcher.

Wraps POST /rest/secure/angelbroking/historical/v1/getCandleData via direct
HTTP (the smartapi-python SDK rehydrates poorly from cached sessions). Returns
a pandas DataFrame indexed by IST timestamp with columns Open/High/Low/Close/Volume,
matching the existing data_store/history/{SYM}.pkl shape.

API per-request caps (Angel forum, 2025-26):
  ONE_MINUTE     30 days
  THREE_MINUTE   60 days
  FIVE_MINUTE    100 days
  TEN_MINUTE     100 days
  FIFTEEN_MINUTE 200 days
  THIRTY_MINUTE  200 days
  ONE_HOUR       400 days
  ONE_DAY        2000 days  (~5.5 years)

Rate limit on this endpoint: 3/sec, 180/min, 5000/hr. Single-call API for now;
batch caller (Phase 2.B) is responsible for sleeping 0.34 s between calls.
"""
from __future__ import annotations
import time
from datetime import datetime
from typing import Optional, Union

import pandas as pd
import requests

from data.angel_auth import get_authed_headers
from data.angel_master import symbol_to_token

_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"

INTERVALS = (
    "ONE_MINUTE", "THREE_MINUTE", "FIVE_MINUTE", "TEN_MINUTE",
    "FIFTEEN_MINUTE", "THIRTY_MINUTE", "ONE_HOUR", "ONE_DAY",
)


def _fmt_dt(dt: Union[str, datetime, pd.Timestamp]) -> str:
    """Coerce to 'YYYY-MM-DD HH:MM' format Angel expects."""
    if isinstance(dt, str):
        if " " in dt and len(dt) >= 16:
            return dt[:16]
        return f"{dt} 09:15"  # date-only -> market open
    return pd.Timestamp(dt).strftime("%Y-%m-%d %H:%M")


def get_candles(
    symbol: str,
    interval: str = "ONE_DAY",
    from_date: Union[str, datetime, pd.Timestamp] = None,
    to_date: Union[str, datetime, pd.Timestamp] = None,
    exchange: str = "NSE",
    timeout: float = 10.0,
) -> pd.DataFrame:
    """Fetch OHLCV candles for a single symbol over a date range.

    Returns a DataFrame indexed by IST timestamp (tz-aware, Asia/Kolkata) with
    columns Open, High, Low, Close, Volume. Empty DataFrame on any error
    (missing token, API failure, no data).

    For ranges exceeding the per-interval cap (e.g. 10 y of daily candles),
    use a batching wrapper (Phase 2.B). This function is a single API call.
    """
    if interval not in INTERVALS:
        raise ValueError(f"interval must be one of {INTERVALS}")
    token = symbol_to_token(symbol, exchange)
    if not token:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    today = pd.Timestamp.now(tz="Asia/Kolkata")
    if to_date is None:
        to_date = today
    if from_date is None:
        # default: 30 days back for intraday, 1 year for daily
        days_back = 365 if interval == "ONE_DAY" else 30
        from_date = today - pd.Timedelta(days=days_back)

    body = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": interval,
        "fromdate": _fmt_dt(from_date),
        "todate": _fmt_dt(to_date),
    }

    try:
        r = requests.post(_URL, headers=get_authed_headers(), json=body, timeout=timeout)
        data = r.json()
    except Exception:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    if not data.get("status") or not data.get("data"):
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    rows = data["data"]
    df = pd.DataFrame(rows, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
    df["ts"] = pd.to_datetime(df["ts"])  # ISO-8601 with +05:30 offset
    df = df.set_index("ts").sort_index()
    df["Volume"] = df["Volume"].astype("int64")
    return df


def get_candles_with_retry(
    symbol: str,
    interval: str = "ONE_DAY",
    from_date=None, to_date=None, exchange: str = "NSE",
    retries: int = 3, backoff: float = 1.0,
) -> pd.DataFrame:
    """Wrapper with exponential backoff for transient rate-limit / 5xx errors."""
    for attempt in range(retries):
        df = get_candles(symbol, interval, from_date, to_date, exchange)
        if not df.empty:
            return df
        time.sleep(backoff * (2 ** attempt))
    return df  # empty DataFrame after all retries


if __name__ == "__main__":
    # Smoke test: pull 30 days of RELIANCE daily, compare against existing
    # screener data_store cache to verify alignment.
    print("=== Angel candles: RELIANCE last 30 days, ONE_DAY ===")
    df = get_candles(
        "RELIANCE",
        interval="ONE_DAY",
        from_date=pd.Timestamp.now(tz="Asia/Kolkata") - pd.Timedelta(days=30),
    )
    print(f"  rows: {len(df)}")
    if not df.empty:
        print(f"  range: {df.index[0]} → {df.index[-1]}")
        print(f"  last close: ₹{df['Close'].iloc[-1]}")
        print(df.tail(3).to_string())

    # Cross-check vs local NSE Bhavcopy cache
    from pathlib import Path
    cache = Path(__file__).parent.parent / "data_store" / "history" / "RELIANCE.pkl"
    if cache.exists() and not df.empty:
        local = pd.read_pickle(cache).tail(5)
        angel_close = round(df["Close"].iloc[-1], 2)
        local_close = round(local["Close"].iloc[-1], 2)
        diff = abs(angel_close - local_close)
        ok = "✓" if diff < 0.5 else "✗"
        print(f"\n  {ok} Angel vs Bhavcopy last close: ₹{angel_close} vs ₹{local_close} (diff ₹{diff:.2f})")

    # Try a 5-min intraday slice
    print("\n=== Angel candles: RELIANCE last 2 days, FIVE_MINUTE ===")
    df5 = get_candles(
        "RELIANCE",
        interval="FIVE_MINUTE",
        from_date=pd.Timestamp.now(tz="Asia/Kolkata") - pd.Timedelta(days=3),
    )
    print(f"  rows: {len(df5)}")
    if not df5.empty:
        print(df5.tail(3).to_string())
