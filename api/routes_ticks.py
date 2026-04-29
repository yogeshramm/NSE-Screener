"""GET /market/ltp — live LTP for a comma-separated symbol list (Angel One)."""
from fastapi import APIRouter
from data.angel_ltp import get_ltp_bulk, is_market_open

router = APIRouter()


@router.get("/market/ltp")
def live_ltp(symbols: str = ""):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:100]
    market_open = is_market_open()
    if not syms or not market_open:
        return {"market_open": market_open, "prices": {}}
    try:
        prices = get_ltp_bulk(syms)
    except Exception:
        prices = {}
    return {"market_open": market_open, "prices": prices}
