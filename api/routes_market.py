"""Market analytics API: RS + sector heatmap."""
from fastapi import APIRouter
from engine.market_analytics import compute_rs_ranks, sector_heatmap

router = APIRouter()


def _get_universe_syms(universe: str):
    from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK
    import os
    HIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")
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
    """RS percentile rank (1-99) for all stocks in the universe."""
    syms = _get_universe_syms(universe)
    ranks = compute_rs_ranks(syms)
    return {"universe": universe, "count": len(ranks), "rs": ranks}


@router.get("/market/sector-heatmap")
def market_sector_heatmap(universe: str = "nifty500"):
    syms = _get_universe_syms(universe)
    return {"universe": universe, "sectors": sector_heatmap(syms)}
