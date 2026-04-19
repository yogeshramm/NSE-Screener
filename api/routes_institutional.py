"""Institutional Radar: FII/DII flows, bulk/block deals, delivery leaders, breadth."""
from fastapi import APIRouter
from data.nse_fii_dii import get_net_fii_dii_summary
from data.nse_institutional import (
    fetch_bulk_deals, fetch_block_deals, fetch_delivery_leaders, compute_market_breadth,
    deals_for_symbol,
)

router = APIRouter()


@router.get("/market/institutional")
def institutional_radar():
    """All four panels in one payload (served from 24h disk cache)."""
    try: flows = get_net_fii_dii_summary(last_n_days=5)
    except Exception: flows = {"days_available": 0, "total_fii_net": 0, "total_dii_net": 0, "combined_net": 0, "daily_data": []}
    try: bulk = fetch_bulk_deals(7)
    except Exception: bulk = []
    try: block = fetch_block_deals(7)
    except Exception: block = []
    try: deliv = fetch_delivery_leaders(25)
    except Exception: deliv = []
    try: breadth = compute_market_breadth()
    except Exception: breadth = {}
    return {"flows": flows, "bulk_deals": bulk, "block_deals": block, "delivery_leaders": deliv, "breadth": breadth}


@router.get("/institutional/{symbol}")
def institutional_symbol(symbol: str):
    """Per-stock bulk + block deal footprint from NSE's daily archive CSV.
    Note: the source file contains only the LATEST TRADING DAY's deals (not
    rolling 30-day, despite the filename's appearance). Used by the Insights
    popup + Practice review overlay when the game window overlaps with that
    single trading day."""
    try:
        return {"symbol": symbol.upper(), **deals_for_symbol(symbol)}
    except Exception as e:
        return {"symbol": symbol.upper(), "bulk": [], "block": [], "error": str(e)}
