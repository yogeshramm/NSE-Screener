"""Analyst Signal endpoint — MC + ET + Tickertape + Trendlyne + yfinance + RSS."""
from fastapi import APIRouter
from data.analyst_ratings import get_analyst_signal_async

router = APIRouter()


@router.get("/analyst/{symbol}")
async def analyst_signal(symbol: str, tf: str = "1y"):
    return await get_analyst_signal_async(symbol, tf=tf)
