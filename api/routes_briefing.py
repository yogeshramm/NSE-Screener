"""Stock briefing endpoint: 52W range, avg volume, volatility, sector, market cap."""
from fastapi import APIRouter, HTTPException
import os, pickle
from engine.practice import _build_briefing, _load_history

router = APIRouter()


@router.get("/stock/{symbol}/briefing")
def stock_briefing(symbol: str):
    symbol = symbol.strip().upper()
    df = _load_history(symbol)
    if df is None or len(df) < 30:
        raise HTTPException(404, f"No history for {symbol}")
    # Use end of history as the "now" index
    start_idx = len(df)
    b = _build_briefing(symbol, df, start_idx)
    if not b:
        raise HTTPException(500, "Briefing computation failed")
    return b
