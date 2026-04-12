"""
Data Helper — Fetches stock data for API endpoints.
Priority: Pre-downloaded daily store > Cache > Live yfinance

After daily_download.py runs, ALL searches use stored data — zero API calls.
"""

import time
from data.batch_downloader import load_stock_data
from data.yfinance_fetcher import (
    fetch_price_history, fetch_4h_history, fetch_all,
    _retry_on_rate_limit
)
from data.cache import get_cached, set_cached


def get_stock_bundle(symbol: str) -> dict:
    """
    Get everything needed for screening a single stock.
    Returns dict with daily_df, stock_data, df_4h.

    Priority:
    1. Pre-downloaded daily store (instant, no API call)
    2. Session cache (fast, no API call)
    3. Live yfinance (slow, may rate limit)
    """
    symbol = symbol.strip().upper()

    # 1. Try pre-downloaded daily store (from daily_download.py)
    stored = load_stock_data(symbol)
    if stored is not None and stored.get("daily_history") is not None:
        daily_df = stored["daily_history"]
        if len(daily_df) >= 50:
            return {
                "symbol": symbol,
                "daily_df": daily_df,
                "stock_data": stored,
                "df_4h": None,  # 4H not pre-downloaded (not needed for swing)
                "source": "daily_store",
            }

    # 2. Try session cache
    cached = get_cached(symbol, "fundamentals")
    if cached is not None:
        daily_df = cached.get("daily_history")
        if daily_df is not None and len(daily_df) >= 50:
            return {
                "symbol": symbol,
                "daily_df": daily_df,
                "stock_data": cached,
                "df_4h": None,
                "source": "cache",
            }

    # 3. Fallback to live yfinance (may hit rate limits)
    stock_data = _retry_on_rate_limit(fetch_all, symbol)
    set_cached(symbol, "fundamentals", stock_data)

    daily_df = stock_data.get("daily_history")
    if daily_df is None or len(daily_df) < 50:
        time.sleep(1)
        daily_df = _retry_on_rate_limit(fetch_price_history, symbol, period_days=250)

    return {
        "symbol": symbol,
        "daily_df": daily_df,
        "stock_data": stock_data,
        "df_4h": None,
        "source": "live_yfinance",
    }


def prepare_stock_result(stock_data: dict) -> dict:
    """Convert internal stock_data to API-safe dict (no DataFrames)."""
    safe = {}
    skip_keys = {"daily_history", "h4_history", "balance_sheet",
                 "recommendations", "earnings_calendar"}

    for k, v in stock_data.items():
        if k in skip_keys:
            continue
        if hasattr(v, 'to_dict'):
            continue
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
