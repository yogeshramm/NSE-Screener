"""
Data Helper — Fetches and caches stock data for API endpoints.
Uses the cache layer to avoid yfinance rate limiting.
"""

import time
from data.yfinance_fetcher import (
    fetch_price_history, fetch_4h_history, fetch_all,
    _retry_on_rate_limit
)
from data.cache import get_cached, set_cached

# Cache TTL in hours (data refreshes after this)
CACHE_TTL_HOURS = 4


def get_stock_daily(symbol: str, period_days: int = 250):
    """Get daily OHLCV data with caching."""
    cache_key = f"daily_{period_days}"
    cached = get_cached(symbol, cache_key)
    if cached is not None:
        return cached

    df = _retry_on_rate_limit(fetch_price_history, symbol, period_days=period_days)
    set_cached(symbol, cache_key, df)
    return df


def get_stock_4h(symbol: str):
    """Get 4H OHLCV data with caching."""
    cached = get_cached(symbol, "4h")
    if cached is not None:
        return cached

    df = _retry_on_rate_limit(fetch_4h_history, symbol)
    set_cached(symbol, "4h", df)
    return df


def get_stock_fundamentals(symbol: str) -> dict:
    """Get all fundamental data with caching."""
    cached = get_cached(symbol, "fundamentals")
    if cached is not None:
        return cached

    data = _retry_on_rate_limit(fetch_all, symbol)
    set_cached(symbol, "fundamentals", data)
    return data


def get_stock_bundle(symbol: str) -> dict:
    """
    Get everything needed for screening a single stock.
    Returns dict with daily_df, stock_data, df_4h.
    """
    # Try to get fundamentals (includes daily history)
    stock_data = get_stock_fundamentals(symbol)

    # Get daily separately if not in stock_data or too few bars
    daily_df = stock_data.get("daily_history")
    if daily_df is None or len(daily_df) < 200:
        time.sleep(1)
        daily_df = get_stock_daily(symbol)

    # Get 4H data
    try:
        time.sleep(1)
        df_4h = get_stock_4h(symbol)
    except Exception:
        df_4h = None

    return {
        "symbol": symbol,
        "daily_df": daily_df,
        "stock_data": stock_data,
        "df_4h": df_4h,
    }


def prepare_stock_result(stock_data: dict) -> dict:
    """
    Convert internal stock_data to API-safe dict (no DataFrames).
    """
    safe = {}
    skip_keys = {"daily_history", "h4_history", "balance_sheet",
                 "recommendations", "earnings_calendar"}

    for k, v in stock_data.items():
        if k in skip_keys:
            continue
        if hasattr(v, 'to_dict'):
            continue  # skip DataFrames
        safe[k] = v

    # Add recommendation summary
    recs = stock_data.get("recommendations")
    if recs is not None and hasattr(recs, 'empty') and not recs.empty:
        try:
            latest = recs.iloc[0]
            safe["analyst_summary"] = {
                "strongBuy": int(latest.get("strongBuy", 0)),
                "buy": int(latest.get("buy", 0)),
                "hold": int(latest.get("hold", 0)),
                "sell": int(latest.get("sell", 0)),
                "strongSell": int(latest.get("strongSell", 0)),
            }
        except Exception:
            safe["analyst_summary"] = None

    # Add earnings date
    cal = stock_data.get("earnings_calendar", {})
    if isinstance(cal, dict) and "Earnings Date" in cal:
        ed = cal["Earnings Date"]
        if isinstance(ed, list) and ed:
            safe["next_earnings"] = str(ed[0])
        elif ed is not None:
            safe["next_earnings"] = str(ed)

    return safe
