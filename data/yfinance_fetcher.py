"""
YFinance Data Fetcher for NSE Stocks
Fetches price history, fundamentals, and corporate data via yfinance.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta

# Delay between yfinance API calls to avoid rate limiting
API_DELAY = 1.5  # seconds


def _retry_on_rate_limit(func, *args, max_retries=3, base_delay=5, **kwargs):
    """Retry a function call if rate limited, with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "Rate" in str(e) or "429" in str(e) or "Too Many" in str(e):
                wait = base_delay * (2 ** attempt)
                print(f"  [RATE LIMITED] Waiting {wait}s before retry {attempt + 1}/{max_retries}...")
                time.sleep(wait)
            else:
                raise
    return func(*args, **kwargs)  # final attempt, let exception propagate


def _nse_symbol(symbol: str) -> str:
    """Ensure symbol has .NS suffix for NSE."""
    symbol = symbol.strip().upper()
    if not symbol.endswith(".NS"):
        symbol = f"{symbol}.NS"
    return symbol


def fetch_price_history(symbol: str, period_days: int = 250) -> pd.DataFrame:
    """
    Fetch daily OHLCV data for at least `period_days` trading days.
    Returns DataFrame with columns: Open, High, Low, Close, Volume.
    We request extra calendar days to account for weekends/holidays.
    """
    ticker = yf.Ticker(_nse_symbol(symbol))
    calendar_days = int(period_days * 1.6)  # rough trading-to-calendar conversion
    start = datetime.now() - timedelta(days=calendar_days)
    df = ticker.history(start=start.strftime("%Y-%m-%d"), interval="1d")
    if df.empty:
        raise ValueError(f"No daily price data returned for {symbol}")
    # Keep only OHLCV columns
    for col in ["Dividends", "Stock Splits"]:
        if col in df.columns:
            df.drop(columns=[col], inplace=True)
    return df


def fetch_4h_history(symbol: str, days: int = 60) -> pd.DataFrame:
    """
    Fetch 4-hour OHLCV data. yfinance limits intraday data to ~60 days.
    Returns DataFrame or empty DataFrame if unavailable.
    """
    ticker = yf.Ticker(_nse_symbol(symbol))
    # yfinance doesn't support 4h directly; we'll use 1h and resample
    # For intraday, max period depends on interval: 1h -> 730 days on yfinance
    try:
        start = datetime.now() - timedelta(days=min(days, 59))
        df = ticker.history(start=start.strftime("%Y-%m-%d"), interval="1h")
        if df.empty:
            return pd.DataFrame()
        # Resample 1h -> 4h
        for col in ["Dividends", "Stock Splits"]:
            if col in df.columns:
                df.drop(columns=[col], inplace=True)
        df_4h = df.resample("4h").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }).dropna()
        return df_4h
    except Exception as e:
        print(f"  [WARN] 4H data unavailable for {symbol}: {e}")
        return pd.DataFrame()


def fetch_fundamentals(symbol: str) -> dict:
    """
    Fetch all fundamental data points from ticker.info.
    Returns a dict with keys matching the project spec.
    """
    ticker = yf.Ticker(_nse_symbol(symbol))
    info = ticker.info or {}

    fundamentals = {
        "roe": info.get("returnOnEquity"),
        "debt_to_equity": info.get("debtToEquity"),
        "trailing_eps": info.get("trailingEps"),
        "free_cash_flow": info.get("freeCashflow"),
        "institutional_holdings": info.get("institutionPercentHeld"),
        "trailing_pe": info.get("trailingPE"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "average_volume": info.get("averageVolume"),
        "market_cap": info.get("marketCap"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "short_name": info.get("shortName"),
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
    }

    # Fallback: compute ROE from income statement + balance sheet if yfinance returns None
    if fundamentals["roe"] is None:
        try:
            inc = ticker.income_stmt
            bs = ticker.balance_sheet
            if inc is not None and not inc.empty and bs is not None and not bs.empty:
                net_income = None
                for key in ["Net Income", "Net Income Common Stockholders"]:
                    if key in inc.index:
                        net_income = inc.iloc[:, 0][key]
                        break
                equity = None
                for key in ["Stockholders Equity", "Total Stockholder Equity",
                            "Stockholders' Equity", "Common Stock Equity"]:
                    if key in bs.index:
                        equity = bs.iloc[:, 0][key]
                        break
                if net_income is not None and equity is not None and equity != 0:
                    fundamentals["roe"] = net_income / equity
                    print(f"         ROE computed from financials: {round(fundamentals['roe'] * 100, 2)}%")
        except Exception:
            pass

    # Fallback: compute free cash flow from cash flow statement if yfinance info returns None
    if fundamentals["free_cash_flow"] is None:
        try:
            cf = ticker.cashflow
            if cf is not None and not cf.empty:
                latest_cf = cf.iloc[:, 0]
                op_cf = None
                capex = None
                for key in ["Operating Cash Flow", "Total Cash From Operating Activities"]:
                    if key in latest_cf.index:
                        op_cf = latest_cf[key]
                        break
                for key in ["Capital Expenditure", "Capital Expenditures"]:
                    if key in latest_cf.index:
                        capex = latest_cf[key]
                        break
                if op_cf is not None and capex is not None:
                    fundamentals["free_cash_flow"] = op_cf + capex  # capex is typically negative
                    print(f"         FCF computed from cash flow: {fundamentals['free_cash_flow']}")
        except Exception:
            pass

    return fundamentals


def fetch_analyst_recommendations(symbol: str) -> pd.DataFrame:
    """Fetch analyst recommendations. Returns DataFrame or empty."""
    ticker = yf.Ticker(_nse_symbol(symbol))
    try:
        recs = ticker.recommendations
        if recs is not None and not recs.empty:
            return recs
    except Exception as e:
        print(f"  [WARN] Analyst recommendations unavailable for {symbol}: {e}")
    return pd.DataFrame()


def fetch_earnings_calendar(symbol: str) -> dict:
    """Fetch upcoming earnings/events calendar. Returns dict or empty dict."""
    ticker = yf.Ticker(_nse_symbol(symbol))
    try:
        cal = ticker.calendar
        if cal is not None:
            if isinstance(cal, pd.DataFrame):
                return cal.to_dict()
            elif isinstance(cal, dict):
                return cal
    except Exception as e:
        print(f"  [WARN] Earnings calendar unavailable for {symbol}: {e}")
    return {}


def fetch_balance_sheet(symbol: str) -> pd.DataFrame:
    """Fetch annual balance sheet. Returns DataFrame or empty."""
    ticker = yf.Ticker(_nse_symbol(symbol))
    try:
        bs = ticker.balance_sheet
        if bs is not None and not bs.empty:
            return bs
    except Exception as e:
        print(f"  [WARN] Balance sheet unavailable for {symbol}: {e}")
    return pd.DataFrame()


def compute_roce(symbol: str) -> float | None:
    """
    Compute ROCE = EBIT / Capital Employed
    Capital Employed = Total Assets - Current Liabilities
    EBIT is fetched from income statement (EBIT or Operating Income).
    Returns ROCE as a percentage, or None if data unavailable.
    """
    ticker = yf.Ticker(_nse_symbol(symbol))
    try:
        bs = ticker.balance_sheet
        inc = ticker.income_stmt
        if bs is None or bs.empty or inc is None or inc.empty:
            return None

        # Use most recent year (first column)
        latest_bs = bs.iloc[:, 0]
        latest_inc = inc.iloc[:, 0]

        # Get EBIT (try multiple keys)
        ebit = None
        for key in ["EBIT", "Operating Income", "Pretax Income",
                     "Net Income", "Net Income Common Stockholders"]:
            if key in latest_inc.index:
                val = latest_inc[key]
                if val is not None and not pd.isna(val):
                    ebit = val
                    break
        if ebit is None:
            return None

        # Get Total Assets
        total_assets = None
        for key in ["Total Assets"]:
            if key in latest_bs.index:
                val = latest_bs[key]
                if val is not None and not pd.isna(val):
                    total_assets = val
                    break
        if total_assets is None:
            return None

        # Get Current Liabilities — for banks this may not exist,
        # so fall back to Total Liabilities or Stockholders Equity method
        current_liabilities = None
        for key in ["Current Liabilities", "Total Current Liabilities"]:
            if key in latest_bs.index:
                val = latest_bs[key]
                if val is not None and not pd.isna(val):
                    current_liabilities = val
                    break

        if current_liabilities is not None:
            capital_employed = total_assets - current_liabilities
        else:
            # For banks/financial companies: use Stockholders Equity as Capital Employed
            equity = None
            for key in ["Stockholders Equity", "Total Stockholder Equity",
                        "Stockholders' Equity", "Common Stock Equity"]:
                if key in latest_bs.index:
                    val = latest_bs[key]
                    if val is not None and not pd.isna(val):
                        equity = val
                        break
            if equity is None:
                return None
            capital_employed = equity
        if capital_employed == 0:
            return None

        roce = (ebit / capital_employed) * 100
        return round(roce, 2)
    except Exception as e:
        print(f"  [WARN] ROCE computation failed for {symbol}: {e}")
        return None


def fetch_all(symbol: str) -> dict:
    """
    Master function: fetch everything for a stock.
    Returns a single dict with all data.
    """
    print(f"\n{'='*60}")
    print(f"  Fetching data for: {symbol}")
    print(f"{'='*60}")

    result = {"symbol": symbol}

    # 1. Daily price history
    print(f"  [1/8] Daily price history...")
    try:
        daily = _retry_on_rate_limit(fetch_price_history, symbol)
        result["daily_history"] = daily
        result["daily_rows"] = len(daily)
        result["latest_close"] = round(daily["Close"].iloc[-1], 2)
        result["latest_date"] = str(daily.index[-1].date())
        print(f"         {len(daily)} trading days fetched, latest close: {result['latest_close']}")
    except Exception as e:
        result["daily_history"] = pd.DataFrame()
        result["daily_rows"] = 0
        result["latest_close"] = None
        print(f"         FAILED: {e}")

    time.sleep(API_DELAY)

    # 2. 4H price history
    print(f"  [2/8] 4H price history...")
    try:
        h4 = _retry_on_rate_limit(fetch_4h_history, symbol)
    except Exception:
        h4 = pd.DataFrame()
    result["h4_history"] = h4
    result["h4_rows"] = len(h4)
    print(f"         {len(h4)} 4H bars fetched")

    time.sleep(API_DELAY)

    # 3. Fundamentals
    print(f"  [3/8] Fundamentals...")
    try:
        fundamentals = _retry_on_rate_limit(fetch_fundamentals, symbol)
    except Exception as e:
        print(f"         FAILED: {e}")
        fundamentals = {k: None for k in ["roe", "debt_to_equity", "trailing_eps",
                        "free_cash_flow", "institutional_holdings", "trailing_pe",
                        "fifty_two_week_high", "average_volume", "market_cap",
                        "sector", "industry", "short_name", "current_price"]}
    result.update(fundamentals)
    for k, v in fundamentals.items():
        print(f"         {k}: {v}")

    time.sleep(API_DELAY)

    # 4. Analyst recommendations
    print(f"  [4/8] Analyst recommendations...")
    try:
        recs = _retry_on_rate_limit(fetch_analyst_recommendations, symbol)
    except Exception:
        recs = pd.DataFrame()
    result["recommendations"] = recs
    result["recommendations_count"] = len(recs)
    if not recs.empty:
        print(f"         {len(recs)} recommendation records")
    else:
        print(f"         No recommendations available")

    time.sleep(API_DELAY)

    # 5. Earnings calendar
    print(f"  [5/8] Earnings calendar...")
    try:
        cal = _retry_on_rate_limit(fetch_earnings_calendar, symbol)
    except Exception:
        cal = {}
    result["earnings_calendar"] = cal
    if cal:
        print(f"         Calendar data: {list(cal.keys())}")
    else:
        print(f"         No earnings calendar data")

    time.sleep(API_DELAY)

    # 6. Balance sheet
    print(f"  [6/8] Balance sheet...")
    try:
        bs = _retry_on_rate_limit(fetch_balance_sheet, symbol)
    except Exception:
        bs = pd.DataFrame()
    result["balance_sheet"] = bs
    if not bs.empty:
        result["balance_sheet_years"] = len(bs.columns)
        print(f"         {len(bs.columns)} years of balance sheet data, {len(bs)} line items")
    else:
        result["balance_sheet_years"] = 0
        print(f"         No balance sheet data")

    time.sleep(API_DELAY)

    # 7. ROCE
    print(f"  [7/8] ROCE computation...")
    try:
        roce = _retry_on_rate_limit(compute_roce, symbol)
    except Exception:
        roce = None
    result["roce"] = roce
    print(f"         ROCE: {roce}%") if roce else print(f"         ROCE: unavailable")

    # 8. Convert ROE and D/E to readable format
    print(f"  [8/8] Formatting values...")
    if result.get("roe") is not None:
        result["roe_pct"] = round(result["roe"] * 100, 2)
        print(f"         ROE: {result['roe_pct']}%")
    else:
        result["roe_pct"] = None
        print(f"         ROE: unavailable")

    if result.get("debt_to_equity") is not None:
        result["debt_to_equity_ratio"] = round(result["debt_to_equity"] / 100, 2) if result["debt_to_equity"] > 10 else round(result["debt_to_equity"], 2)
        print(f"         D/E Ratio: {result['debt_to_equity_ratio']}")
    else:
        result["debt_to_equity_ratio"] = None

    if result.get("institutional_holdings") is not None:
        result["institutional_holdings_pct"] = round(result["institutional_holdings"] * 100, 2)
        print(f"         Institutional Holdings: {result['institutional_holdings_pct']}%")
    else:
        result["institutional_holdings_pct"] = None

    return result
