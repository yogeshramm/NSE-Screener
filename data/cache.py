"""
Simple file-based cache for yfinance data.
Avoids re-downloading when running tests repeatedly.
Cache expires after cache_hours (default: 4 hours).
"""

import pickle
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

CACHE_DIR = Path(__file__).parent.parent / ".cache"
CACHE_HOURS = 4


def _cache_key(symbol: str, data_type: str) -> str:
    return hashlib.md5(f"{symbol}_{data_type}".encode()).hexdigest()


def get_cached(symbol: str, data_type: str):
    """Get cached data if available and not expired."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"{_cache_key(symbol, data_type)}.pkl"

    if cache_file.exists():
        try:
            with open(cache_file, "rb") as f:
                cached = pickle.load(f)
            if datetime.now() - cached["timestamp"] < timedelta(hours=CACHE_HOURS):
                return cached["data"]
        except Exception:
            pass
    return None


def set_cached(symbol: str, data_type: str, data):
    """Cache data to disk."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"{_cache_key(symbol, data_type)}.pkl"
    try:
        with open(cache_file, "wb") as f:
            pickle.dump({"data": data, "timestamp": datetime.now()}, f)
    except Exception:
        pass
