"""News / Corporate Events / IPO API."""
from fastapi import APIRouter
from data.nse_events import fetch_nse_events, events_for_symbol
from data.nse_ipo import fetch_ipos

router = APIRouter()


@router.get("/events/upcoming")
def events_upcoming(days: int = 14):
    return {"days": days, "events": fetch_nse_events(days_ahead=days)}


@router.get("/events/symbol/{symbol}")
def events_symbol(symbol: str):
    return {"symbol": symbol.upper(), "events": events_for_symbol(symbol)}


@router.get("/events/ipos")
def events_ipos():
    """Upcoming + currently open + recently listed IPOs from NSE."""
    return fetch_ipos()
