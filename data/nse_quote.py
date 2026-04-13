"""
NSE Quote API — Fetches real-time quote + company info from NSE.
Supplements screener.in with: face value, issued size, F&O status,
industry classification, VWAP, live price.
"""

import requests
import time
from data.cache import get_cached, set_cached

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


def _get_nse_session():
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get("https://www.nseindia.com/", timeout=10)
    except Exception:
        pass
    return session


def fetch_nse_quote(symbol: str, use_cache: bool = True) -> dict:
    """
    Fetch quote data from NSE API for a symbol.
    Returns company info, price, industry, face value, etc.
    """
    symbol = symbol.strip().upper()

    if use_cache:
        cached = get_cached(symbol, "nse_quote")
        if cached is not None:
            return cached

    session = _get_nse_session()
    url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"

    try:
        resp = session.get(url, timeout=10)
        if resp.status_code != 200:
            return {"symbol": symbol, "error": f"HTTP {resp.status_code}"}

        data = resp.json()
        info = data.get("info", {})
        security = data.get("securityInfo", {})
        price = data.get("priceInfo", {})
        industry = data.get("industryInfo", {})

        result = {
            "symbol": symbol,
            "source": "nse_quote",
            "company_name": info.get("companyName"),
            "industry": info.get("industry"),
            "is_fno": info.get("isFNOSec", False),
            "is_etf": info.get("isETFSec", False),
            "isin": info.get("isin"),
            "listing_date": info.get("listingDate"),
            "face_value": security.get("faceValue"),
            "issued_size": security.get("issuedSize"),
            "last_price": price.get("lastPrice"),
            "vwap": price.get("vwap"),
            "open": price.get("open"),
            "close": price.get("close"),
            "previous_close": price.get("previousClose"),
            "change": price.get("change"),
            "change_pct": price.get("pChange"),
            "sector": industry.get("macro"),
            "sub_sector": industry.get("sector"),
            "nse_industry": industry.get("industry"),
            "basic_industry": industry.get("basicIndustry"),
        }

        set_cached(symbol, "nse_quote", result)
        return result

    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def fetch_nse_quotes_batch(symbols: list[str], delay: float = 1.5) -> dict:
    """Fetch NSE quotes for multiple symbols with delays."""
    results = {}
    session = _get_nse_session()

    for i, symbol in enumerate(symbols):
        if i > 0:
            time.sleep(delay)
        try:
            result = fetch_nse_quote(symbol)
            results[symbol] = result
        except Exception:
            pass

    return results
