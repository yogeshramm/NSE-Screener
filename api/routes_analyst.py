"""Analyst Signal endpoint — Moneycontrol + yfinance + RSS activity."""
from fastapi import APIRouter
from data.analyst_ratings import get_analyst_signal

router = APIRouter()


@router.get("/analyst/{symbol}")
def analyst_signal(symbol: str, tf: str = "1y"):
    return get_analyst_signal(symbol, tf=tf)
