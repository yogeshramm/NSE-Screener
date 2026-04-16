"""Pattern library API: /patterns/list + /patterns/scan."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from engine.patterns import list_patterns, scan_universe

router = APIRouter()


class ScanRequest(BaseModel):
    pattern: str
    universe: str = "nifty500"  # nifty500 | next500 | all
    lookback: int = 5


@router.get("/patterns/list")
def patterns_list():
    return {"patterns": list_patterns()}


@router.post("/patterns/scan")
def patterns_scan(req: ScanRequest):
    from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK
    import os
    HIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")
    all_hist = sorted(f.replace(".pkl", "") for f in os.listdir(HIST) if f.endswith(".pkl")) if os.path.exists(HIST) else []
    try:
        nifty = set(get_nifty500_live())
    except Exception:
        nifty = set(NIFTY_500_FALLBACK)
    if req.universe == "nifty500":
        syms = [s for s in all_hist if s in nifty]
    elif req.universe == "next500":
        syms = [s for s in all_hist if s not in nifty]
    else:
        syms = all_hist
    hits = scan_universe(req.pattern, syms, lookback=max(1, min(10, req.lookback)))
    return {"pattern": req.pattern, "universe": req.universe, "count": len(hits), "hits": hits[:100]}
