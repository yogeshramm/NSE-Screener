"""
Indicator Result Cache
Caches run_all_indicators() output keyed by (config_hash, sector, last_bar_date).
Cache auto-invalidates when new daily data arrives (last_bar_date changes).

Files: data_store/indicator_cache/{SYMBOL}_{config_hash}.pkl
One file per (symbol, config) pair so multiple preset configs coexist without
overwriting each other.
"""

import hashlib
import json
import pickle
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / "data_store" / "indicator_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Only these config keys affect indicator computation.
# UI-only fields (_category, label, description, etc.) are excluded
# so preset configs with extra metadata don't cause cache misses.
_INDICATOR_KEYS = {
    "ema", "rsi", "macd", "volume_surge", "sector_performance",
    "anchored_vwap", "hidden_divergence", "pivot_levels",
    "awesome_oscillator", "supertrend", "adx", "obv", "cmf", "roc",
    "fisher_transform", "klinger_oscillator", "chande_momentum",
    "force_index", "vortex", "bb_squeeze", "stochastic_rsi",
    "williams_r", "vwap_bands", "ichimoku", "risk_management",
}


def _config_hash(config: dict) -> str:
    """Stable MD5 of only the indicator-relevant config keys.

    Normalises whole-number floats (e.g. 2.0 → 2) so the hash is identical
    whether the value originated from Python get_default_config() (which uses
    float literals like 2.0) or from the browser, which round-trips JSON
    numbers without a fractional part back as integers.
    """
    subset = {}
    for k in _INDICATOR_KEYS:
        if k in config:
            v = config[k]
            if isinstance(v, dict):
                v = {
                    ik: (int(iv) if isinstance(iv, float) and iv.is_integer() else iv)
                    for ik, iv in v.items()
                    if not ik.startswith("_")
                }
            subset[k] = v
    return hashlib.md5(
        json.dumps(subset, sort_keys=True, default=str).encode()
    ).hexdigest()[:8]


def _cache_path(symbol: str, config_hash: str) -> Path:
    """Return the cache file path for a (symbol, config_hash) pair.
    Using {symbol}_{hash}.pkl lets multiple configs coexist per symbol."""
    return CACHE_DIR / f"{symbol}_{config_hash}.pkl"


def load_cached(symbol: str, config: dict, sector: str | None, last_bar_date: str) -> list | None:
    """Return cached indicator_results if valid, else None."""
    h = _config_hash(config)
    path = _cache_path(symbol, h)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            entry = pickle.load(f)
        if (entry.get("sector") == sector
                and entry.get("last_bar_date") == last_bar_date):
            return entry["results"]
    except Exception:
        pass
    return None


def save_cached(symbol: str, config: dict, sector: str | None,
                last_bar_date: str, results: list) -> None:
    """Atomically write indicator_results to cache."""
    h = _config_hash(config)
    path = _cache_path(symbol, h)
    entry = {
        "sector": sector,
        "last_bar_date": last_bar_date,
        "results": results,
    }
    try:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(entry, f, protocol=4)
        tmp.replace(path)
    except Exception:
        pass


def purge_stale_date_files(symbols: list[str], current_hashes: set[str],
                           current_date: str) -> int:
    """Delete cache files for unknown hashes or outdated dates.
    Call from warm_cache() before warming so stale entries don't persist."""
    deleted = 0
    for path in CACHE_DIR.glob("*.pkl"):
        # Filename: SYMBOL_HASH.pkl  (underscore separates)
        stem = path.stem
        parts = stem.rsplit("_", 1)
        if len(parts) != 2:
            # Old-format file (SYMBOL.pkl) — remove
            path.unlink(missing_ok=True)
            deleted += 1
            continue
        sym, h = parts
        if h not in current_hashes:
            path.unlink(missing_ok=True)
            deleted += 1
    return deleted
