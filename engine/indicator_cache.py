"""
Indicator Result Cache
Caches run_all_indicators() output keyed by (config_hash, sector, last_bar_date).
Cache auto-invalidates when new daily data arrives (last_bar_date changes).
"""

import hashlib
import json
import pickle
import tempfile
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
    """Stable MD5 of only the indicator-relevant config keys."""
    subset = {}
    for k in _INDICATOR_KEYS:
        if k in config:
            v = config[k]
            # Strip any UI metadata keys (start with _)
            if isinstance(v, dict):
                v = {ik: iv for ik, iv in v.items() if not ik.startswith("_")}
            subset[k] = v
    return hashlib.md5(
        json.dumps(subset, sort_keys=True, default=str).encode()
    ).hexdigest()[:8]


def load_cached(symbol: str, config: dict, sector: str | None, last_bar_date: str) -> list | None:
    """Return cached indicator_results if valid, else None."""
    path = CACHE_DIR / f"{symbol}.pkl"
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            entry = pickle.load(f)
        if (entry.get("config_hash") == _config_hash(config)
                and entry.get("sector") == sector
                and entry.get("last_bar_date") == last_bar_date):
            return entry["results"]
    except Exception:
        pass
    return None


def save_cached(symbol: str, config: dict, sector: str | None,
                last_bar_date: str, results: list) -> None:
    """Atomically write indicator_results to cache."""
    path = CACHE_DIR / f"{symbol}.pkl"
    entry = {
        "config_hash": _config_hash(config),
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
