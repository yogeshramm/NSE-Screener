"""Chart Patterns API: advanced multi-bar breakout patterns."""
from fastapi import APIRouter
from pydantic import BaseModel
from engine.chart_patterns import list_patterns, scan

router = APIRouter()


class ScanReq(BaseModel):
    pattern: str
    universe: str = "nifty500"


@router.get("/chart-patterns/list")
def chart_patterns_list():
    return {"patterns": list_patterns()}


@router.post("/chart-patterns/scan")
def chart_patterns_scan(req: ScanReq):
    from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK
    import os
    HIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")
    all_h = sorted(f.replace(".pkl", "") for f in os.listdir(HIST) if f.endswith(".pkl")) if os.path.exists(HIST) else []
    try:
        nifty = set(get_nifty500_live())
    except Exception:
        nifty = set(NIFTY_500_FALLBACK)
    syms = [s for s in all_h if s in nifty] if req.universe == "nifty500" else [s for s in all_h if s not in nifty] if req.universe == "next500" else all_h
    hits = scan(req.pattern, syms)
    return {"pattern": req.pattern, "universe": req.universe, "count": len(hits), "hits": hits}
