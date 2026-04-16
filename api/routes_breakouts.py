"""Breakouts API: scan for pre-breakout, fresh, pullback, and PEG setups."""
from fastapi import APIRouter
from pydantic import BaseModel
from engine.breakouts import scan

router = APIRouter()


class ScanRequest(BaseModel):
    mode: str  # pre_breakout | fresh | pullback | peg
    universe: str = "nifty500"  # nifty500 | next500 | all


@router.post("/breakouts/scan")
def breakouts_scan(req: ScanRequest):
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
    hits = scan(req.mode, syms)
    return {"mode": req.mode, "universe": req.universe, "count": len(hits), "hits": hits}
