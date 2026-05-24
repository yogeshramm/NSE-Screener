"""Analyst Signal endpoint — MC + ET + Tickertape + Trendlyne + yfinance + RSS."""
from fastapi import APIRouter
from data.analyst_ratings import get_analyst_signal_async

router = APIRouter()


@router.get("/analyst/{symbol}")
async def analyst_signal(symbol: str, tf: str = "1y"):
    return await get_analyst_signal_async(symbol, tf=tf)


@router.get("/financials/{symbol}")
def financials_data(symbol: str):
    """
    Aggregated financials for the full-screen workspace sidebar.
    Returns: EPS/earnings (TV scanner), analyst consensus (cached JSON),
             key fundamentals (screener.in pkl).
    """
    sym = symbol.upper().strip()

    # ── Analyst JSON ──────────────────────────────────────────────
    analyst_raw: dict = {}
    try:
        from pathlib import Path
        import json
        aj = Path("data_store/analyst") / f"{sym}__1y.json"
        if aj.exists():
            analyst_raw = json.loads(aj.read_text())
    except Exception:
        pass

    # ── TV Earnings ───────────────────────────────────────────────
    earnings: dict = {}
    try:
        from data.tv_earnings import get_earnings
        earnings = get_earnings(sym) or {}
    except Exception:
        pass

    # ── Fundamentals pkl ─────────────────────────────────────────
    funda: dict = {}
    try:
        import pickle
        from setup_data import FUNDAMENTALS_DIR
        fp = FUNDAMENTALS_DIR / f"{sym}.pkl"
        if fp.exists():
            with open(fp, "rb") as f:
                raw = pickle.load(f)
            _keys = ['pe', 'roe_pct', 'roce_pct', 'debt_to_equity', 'pb',
                     'dividend_yield', 'eps', 'market_cap', 'current_price',
                     'book_value', 'promoter_holding', 'fii_holding', 'dii_holding']
            funda = {k: raw.get(k) for k in _keys}
    except Exception:
        pass

    return {
        "symbol": sym,
        "earnings":     earnings,
        "analyst":      analyst_raw.get("composite") or {},
        "et_markets":   analyst_raw.get("et_markets") or {},
        "trendlyne":    analyst_raw.get("trendlyne")  or {},
        "fundamentals": funda,
    }
