"""GET /earnings/{symbol} — TradingView earnings data (EPS actual vs estimate)."""
from fastapi import APIRouter
from data.tv_earnings import get_earnings, batch_prefetch

router = APIRouter()


@router.get("/earnings/{symbol}")
def earnings_data(symbol: str):
    """
    Return EPS actual, estimate, surprise % and earnings dates for a symbol.
    Data sourced from TradingView scanner (same endpoint as technical ratings).
    24h cache — on-demand fetch on cache miss (~300ms).
    """
    data = get_earnings(symbol.upper().strip())
    return {"symbol": symbol.upper(), "earnings": data}


@router.post("/earnings/prefetch")
def earnings_prefetch(symbols: list[str]):
    """Pre-warm earnings cache for a batch of symbols (cron / warm_scope use)."""
    result = batch_prefetch(symbols)
    return {"prefetched": len([v for v in result.values() if v]), "total": len(symbols)}
