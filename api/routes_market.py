"""Market analytics API: RS + sector heatmap."""
import pickle
import time
from pathlib import Path
from fastapi import APIRouter
from engine.market_analytics import compute_rs_ranks, sector_heatmap

router = APIRouter()

_CACHE_DIR = Path(__file__).parent.parent / "data_store" / "market_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_TTL = 6 * 3600  # 6 hours


def _cache_get(key: str):
    p = _CACHE_DIR / f"{key}.pkl"
    if not p.exists():
        return None
    if time.time() - p.stat().st_mtime > _TTL:
        return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _cache_set(key: str, data):
    try:
        p = _CACHE_DIR / f"{key}.pkl"
        tmp = p.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(data, f, protocol=4)
        tmp.replace(p)
    except Exception:
        pass


def _get_universe_syms(universe: str):
    from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK
    import os
    HIST = str(Path(__file__).parent.parent / "data_store" / "history")
    all_h = sorted(f.replace(".pkl", "") for f in os.listdir(HIST) if f.endswith(".pkl")) if os.path.exists(HIST) else []
    try:
        nifty = set(get_nifty500_live())
    except Exception:
        nifty = set(NIFTY_500_FALLBACK)
    if universe == "nifty500":
        return [s for s in all_h if s in nifty]
    if universe == "next500":
        return [s for s in all_h if s not in nifty]
    return all_h


@router.get("/market/rs")
def market_rs(universe: str = "nifty500"):
    """RS percentile rank (1-99) for all stocks in the universe. Cached 6h."""
    key = f"rs_{universe}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    syms = _get_universe_syms(universe)
    ranks = compute_rs_ranks(syms)
    result = {"universe": universe, "count": len(ranks), "rs": ranks}
    _cache_set(key, result)
    return result


@router.get("/market/sector-heatmap")
def market_sector_heatmap(universe: str = "nifty500"):
    """Sector rotation heatmap. Cached 6h."""
    key = f"heatmap_{universe}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    syms = _get_universe_syms(universe)
    result = {"universe": universe, "sectors": sector_heatmap(syms)}
    _cache_set(key, result)
    return result
