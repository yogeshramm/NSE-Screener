"""
TradingView earnings data fetcher.
Uses the same scanner.tradingview.com/india/scan endpoint as technical ratings.
One batch POST → all symbols at once. Cache: 24h flat JSON file.

Fields returned per symbol:
  eps_actual       — reported EPS for most recent quarter (fq)
  eps_estimate     — analyst consensus estimate for that quarter
  eps_surprise     — absolute (actual - estimate)
  eps_surprise_pct — percentage surprise
  beat             — True / False / None
  last_earnings_ts — Unix timestamp of last earnings release
  next_earnings_ts — Unix timestamp of next scheduled earnings release
  eps_ttm          — trailing 12-month EPS (bonus field)
"""

import os
import json
import time
import requests
from typing import Dict, Any, List, Optional

CACHE_DIR  = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "analyst")
CACHE_FILE = os.path.join(CACHE_DIR, "_tv_earnings_batch.json")
TTL        = 24 * 3600   # 24h

_COLS = [
    "earnings_per_share_fq",            # 0 — actual EPS last quarter
    "earnings_per_share_forecast_fq",   # 1 — analyst estimate
    "eps_surprise_fq",                  # 2 — actual minus estimate (absolute)
    "earnings_release_date",            # 3 — last earnings Unix ts
    "earnings_release_next_date",       # 4 — next earnings Unix ts
    "earnings_per_share_basic_ttm",     # 5 — trailing 12-month EPS
]

_HDR = {
    "Origin":     "https://www.tradingview.com",
    "Referer":    "https://www.tradingview.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}


def _load_cache() -> Dict[str, Any]:
    if (
        os.path.exists(CACHE_FILE)
        and time.time() - os.path.getmtime(CACHE_FILE) < TTL
    ):
        try:
            return json.load(open(CACHE_FILE))
        except Exception:
            pass
    return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        json.dump(cache, open(CACHE_FILE, "w"))
    except Exception:
        pass


def _batch_fetch(symbols: List[str]) -> Dict[str, Any]:
    """Single POST to TradingView scanner for all symbols. Returns {SYM: {...}}."""
    tickers = [f"NSE:{s}" for s in symbols]
    try:
        resp = requests.post(
            "https://scanner.tradingview.com/india/scan",
            json={
                "symbols": {"tickers": tickers, "query": {"types": []}},
                "columns": _COLS,
            },
            headers=_HDR,
            timeout=20,
        )
        if resp.status_code != 200:
            return {}

        out: Dict[str, Any] = {}
        for row in resp.json().get("data") or []:
            sym = row["s"].replace("NSE:", "")
            d   = row.get("d") or []
            if len(d) < 5:
                continue

            actual   = d[0]
            estimate = d[1]
            surprise = d[2]
            last_ts  = d[3]
            next_ts  = d[4]
            ttm      = d[5] if len(d) > 5 else None

            # Percentage surprise
            surprise_pct = None
            if estimate and estimate != 0 and actual is not None:
                surprise_pct = round((actual - estimate) / abs(estimate) * 100, 2)

            out[sym] = {
                "eps_actual":       round(actual,   2) if actual   is not None else None,
                "eps_estimate":     round(estimate, 2) if estimate is not None else None,
                "eps_surprise":     round(surprise, 4) if surprise is not None else None,
                "eps_surprise_pct": surprise_pct,
                "beat":             (actual > estimate) if (actual is not None and estimate is not None) else None,
                "last_earnings_ts": int(last_ts) if last_ts else None,
                "next_earnings_ts": int(next_ts) if next_ts else None,
                "eps_ttm":          round(ttm, 2) if ttm is not None else None,
            }
        return out
    except Exception:
        return {}


def get_earnings(symbol: str) -> Optional[Dict[str, Any]]:
    """Return earnings data for one symbol. Uses batch cache; fetches if missing."""
    symbol = symbol.upper().strip()
    cache  = _load_cache()
    if symbol in cache:
        return cache[symbol]
    # Cache miss — fetch just this symbol on-demand
    result = _batch_fetch([symbol])
    if result:
        cache.update(result)
        _save_cache(cache)
    return result.get(symbol)


def batch_prefetch(symbols: List[str]) -> Dict[str, Any]:
    """Pre-warm earnings cache for a list of symbols in one API call (cron use)."""
    cache   = _load_cache()
    missing = [s for s in symbols if s not in cache]
    if not missing:
        return cache
    result = _batch_fetch(missing)
    if result:
        cache.update(result)
        _save_cache(cache)
    return {s: cache.get(s) for s in symbols}
