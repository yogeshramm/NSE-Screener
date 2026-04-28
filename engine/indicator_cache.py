"""
Indicator Result Cache — skip recomputation when nothing has changed.

Key insight: yesterday's RSI(14) for RELIANCE is the same value today as it
was yesterday. Re-running 25 indicators on 480 bars × 500 stocks every scan
is wasted work. Cache the indicator_results list keyed by:

    (config_hash, sector, last_bar_date)

If any of those change, we recompute. Otherwise we load from disk.

Cache file: data_store/indicator_cache/{SYMBOL}.pkl
Layout:     {cache_key: {"last_bar_date": str, "indicator_results": list}}

A single symbol holds up to 5 entries (different configs / dates) before the
oldest is evicted, so disk stays bounded.
"""

import hashlib
import json
import pickle
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / "data_store" / "indicator_cache"

# Only these config keys influence indicator computation. Score weights,
# fundamental thresholds, breakout params etc. don't change indicator output.
_INDICATOR_CONFIG_KEYS = {
    "ema", "rsi", "macd", "volume_surge", "sector_performance", "anchored_vwap",
    "atr", "supertrend", "vwap_bands", "vortex", "obv", "adx", "stochastic",
    "cci", "williams_r", "bollinger_bands", "keltner_channels", "donchian_channels",
    "psar", "ichimoku", "mfi", "tsi", "roc", "trix", "hidden_divergence",
}


def _config_hash(config: dict, sector: str | None) -> str:
    relevant = {k: config[k] for k in _INDICATOR_CONFIG_KEYS if k in config}
    payload = json.dumps({"cfg": relevant, "sec": sector or ""},
                         sort_keys=True, default=str)
    return hashlib.md5(payload.encode()).hexdigest()[:12]


def _cache_path(symbol: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{symbol.upper()}.pkl"


def load_cached(symbol: str, config: dict, sector: str | None,
                last_bar_date: str) -> list[dict] | None:
    """Return cached indicator_results if fresh, else None."""
    path = _cache_path(symbol)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            cache = pickle.load(f)
    except Exception:
        return None
    key = _config_hash(config, sector)
    entry = cache.get(key)
    if entry and entry.get("last_bar_date") == last_bar_date:
        return entry.get("indicator_results")
    return None


def save_cached(symbol: str, config: dict, sector: str | None,
                last_bar_date: str, indicator_results: list[dict]):
    """Persist indicator_results. Caps entries per symbol to bound disk."""
    path = _cache_path(symbol)
    cache: dict = {}
    if path.exists():
        try:
            with open(path, "rb") as f:
                cache = pickle.load(f)
        except Exception:
            cache = {}
    key = _config_hash(config, sector)
    cache[key] = {
        "last_bar_date": last_bar_date,
        "indicator_results": indicator_results,
    }
    if len(cache) > 5:
        cache = dict(list(cache.items())[-5:])
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "wb") as f:
            pickle.dump(cache, f)
        tmp.replace(path)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def clear_cache(symbol: str | None = None):
    """Drop cache for one symbol, or all if symbol is None."""
    if not CACHE_DIR.exists():
        return
    if symbol:
        p = _cache_path(symbol)
        if p.exists():
            p.unlink()
    else:
        for p in CACHE_DIR.glob("*.pkl"):
            p.unlink()
