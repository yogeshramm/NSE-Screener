"""News / Corporate Events / IPO API."""
from fastapi import APIRouter
from data.nse_events import fetch_nse_events, events_for_symbol, dividends_for_symbol
from data.nse_ipo import fetch_ipos

router = APIRouter()


@router.get("/events/upcoming")
def events_upcoming(days: int = 14):
    return {"days": days, "events": fetch_nse_events(days_ahead=days)}


@router.get("/events/symbol/{symbol}")
def events_symbol(symbol: str):
    return {"symbol": symbol.upper(), "events": events_for_symbol(symbol)}


@router.get("/events/dividends/{symbol}")
def events_dividends(symbol: str, years: int = 5):
    """Historical dividend ex-dates + amounts from NSE corporate actions (24h cache).
    Returns [{date_ts: unix, amount: float|null, label: str}] sorted oldest→newest.
    Used by the chart to place 'D' markers on past dividend ex-dates.
    Source: NSE /api/corporates-corporateActions (authoritative, curl_cffi Chrome impersonation).
    """
    sym = symbol.upper().strip()
    result = dividends_for_symbol(sym, years=years)
    return {"symbol": sym, "dividends": result}


@router.get("/events/ipos")
def events_ipos():
    """Upcoming + currently open + recently listed IPOs from NSE."""
    return fetch_ipos()
