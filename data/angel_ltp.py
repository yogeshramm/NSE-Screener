"""
Angel One real-time LTP via the market-data quote REST API.
POST /rest/secure/angelbroking/market/v1/quote/
Rate: 1000/min. Returns LTP + OHLC + % change for up to 50 tokens per batch.
"""
from __future__ import annotations
import time
import requests
import pandas as pd

from data.angel_auth import get_authed_headers
from data.angel_master import symbol_to_token

_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/market/v1/quote/"
_BATCH = 50
_TTL = 4  # seconds cache
_cache: dict[str, tuple[float, dict]] = {}  # token → (ts, payload)


def is_market_open() -> bool:
    now = pd.Timestamp.now(tz="Asia/Kolkata")
    if now.weekday() >= 5:
        return False
    from datetime import time as T
    t = now.time()
    return T(9, 15) <= t <= T(15, 30)


def inject_live_candle(hist_df, sym_price: dict):
    """Append today's live candle to hist_df if today is absent.
    sym_price: one entry from get_ltp_bulk(), e.g. {ltp, open, high, low}.
    Returns (possibly_new_df, was_injected: bool).
    Shared by routes_chart and routes_screen so both charts and screener
    indicator computation reflect the live session price."""
    if not sym_price or not sym_price.get("ltp"):
        return hist_df, False
    try:
        today = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
        if not hist_df.empty and hist_df.index[-1].normalize() >= today:
            return hist_df, False          # already have today's bar
        ltp   = float(sym_price["ltp"])
        open_ = float(sym_price.get("open") or ltp)
        high  = max(float(sym_price.get("high") or ltp), ltp)
        low   = min(float(sym_price.get("low")  or ltp), ltp)
        new_row = pd.DataFrame(
            {"Open": [open_], "High": [high], "Low": [low],
             "Close": [ltp], "Volume": [0]},
            index=[today],
        )
        return pd.concat([hist_df, new_row]), True
    except Exception:
        return hist_df, False


def get_ltp_bulk(symbols: list[str], exchange: str = "NSE") -> dict[str, dict]:
    """Returns {symbol: {ltp, open, high, low, close, change_pct}} with _TTL-sec cache."""
    token_sym: dict[str, str] = {}
    for sym in symbols:
        tok = symbol_to_token(sym, exchange)
        if tok:
            token_sym[tok] = sym

    if not token_sym:
        return {}

    now = time.time()
    fresh = [t for t in token_sym if now - _cache.get(t, (0,))[0] >= _TTL]
    out: dict[str, dict] = {token_sym[t]: _cache[t][1] for t in token_sym if t not in fresh}

    if not fresh:
        return out

    headers = get_authed_headers()
    for i in range(0, len(fresh), _BATCH):
        batch = fresh[i:i + _BATCH]
        try:
            r = requests.post(_URL, headers=headers,
                              json={"mode": "FULL", "exchangeTokens": {exchange: batch}},
                              timeout=5)
            data = r.json()
        except Exception:
            continue
        if not data.get("status") or not data.get("data"):
            continue
        for item in data["data"].get("fetched", []):
            tok = str(item.get("symbolToken", ""))
            sym = token_sym.get(tok)
            if not sym:
                continue
            payload = {
                "ltp": round(float(item.get("ltp") or 0), 2),
                "open": round(float(item.get("open") or 0), 2),
                "high": round(float(item.get("high") or 0), 2),
                "low": round(float(item.get("low") or 0), 2),
                "close": round(float(item.get("close") or 0), 2),
                "change_pct": round(float(item.get("percentChange") or 0), 2),
            }
            _cache[tok] = (time.time(), payload)
            out[sym] = payload

    return out
