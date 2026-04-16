"""Multi-timeframe confluence endpoint."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from engine.mtf_confluence import compute_mtf, compute_bulk

router = APIRouter()


class MTFReq(BaseModel):
    symbols: List[str]


@router.get("/mtf/{symbol}")
def mtf_single(symbol: str):
    r = compute_mtf(symbol.strip().upper())
    return r or {"symbol": symbol.upper(), "error": "no history"}


@router.post("/mtf")
def mtf_bulk(req: MTFReq):
    syms = [s.strip().upper() for s in req.symbols if s.strip()]
    return {"count": len(syms), "mtf": compute_bulk(syms)}
