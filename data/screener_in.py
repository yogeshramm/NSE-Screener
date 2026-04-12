"""
Screener.in Fundamental Data Fetcher
Scrapes fundamental data from screener.in — the best source for Indian stock fundamentals.
No rate limits if requests are spaced 1-2 seconds apart.

Data available: ROE, ROCE, D/E, EPS, PE, Book Value, Market Cap,
                Promoter/FII/DII holdings, Free Cash Flow, and more.
"""

import requests
import re
import time
from data.cache import get_cached, set_cached

SCREENER_URL = "https://www.screener.in/company/{symbol}/consolidated/"
SCREENER_STANDALONE_URL = "https://www.screener.in/company/{symbol}/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.5",
}

# Delay between requests to be respectful
REQUEST_DELAY = 1.5  # seconds


def _extract_number(text: str) -> float | None:
    """Extract a number from text like '₹18,234 Cr.' or '14.5%' or '-2.3'."""
    if not text:
        return None
    # Remove currency symbols, commas, Cr, %
    cleaned = text.replace("₹", "").replace(",", "").replace("Cr.", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _find_value_after_label(html: str, label: str) -> str | None:
    """
    Find the value that appears after a label in screener.in HTML.
    Screener.in format:
      <span class="name">Label</span>
      <span class="nowrap value">₹<span class="number">18,27,154</span> Cr.</span>
    """
    # Primary pattern: label in <span class="name"> followed by <span class="number">
    pattern = (
        rf'{re.escape(label)}\s*'
        r'</span>\s*'
        r'(?:</?[^>]*>\s*)*'  # skip intermediate tags
        r'(?:₹\s*)?'  # optional currency symbol
        r'<span[^>]*class="number"[^>]*>\s*([^<]+)'
    )
    match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Fallback: look for number near the label
    pattern2 = rf'{re.escape(label)}[^<]*?<span[^>]*class="number"[^>]*>\s*([^<]+)'
    match2 = re.search(pattern2, html, re.DOTALL | re.IGNORECASE)
    if match2:
        return match2.group(1).strip()

    return None


def _extract_ratios(html: str) -> dict:
    """Extract key ratios from the top section of screener.in page."""
    ratios = {}

    # Key ratio patterns in screener.in
    ratio_labels = {
        "market_cap": "Market Cap",
        "current_price": "Current Price",
        "pe": "Stock P/E",
        "book_value": "Book Value",
        "dividend_yield": "Dividend Yield",
        "roce": "ROCE",
        "roe": "ROE",
        "face_value": "Face Value",
        "debt_to_equity": "Debt to equity",
        "eps": "EPS",
        "pb": "Price to book value",
        "industry_pe": "Industry PE",
    }

    for key, label in ratio_labels.items():
        value_str = _find_value_after_label(html, label)
        if value_str:
            ratios[key] = _extract_number(value_str)
            ratios[f"{key}_raw"] = value_str
        else:
            ratios[key] = None

    return ratios


def _extract_shareholding(html: str) -> dict:
    """Extract promoter, FII, DII holdings from screener.in."""
    holdings = {}

    # Screener.in pattern: Label&nbsp;<span>+</span></button></td><td>50.41%</td>
    for label, key in [("Promoters", "promoter"), ("FIIs", "fii"), ("DIIs", "dii"),
                       ("Public", "public"), ("Government", "govt")]:
        # Get the first percentage after the label (most recent quarter)
        pattern = rf'{re.escape(label)}[^<]*(?:<[^>]*>)*\s*</td>\s*<td[^>]*>\s*([\d.]+)%'
        match = re.search(pattern, html, re.DOTALL)
        if match:
            holdings[f"{key}_holding"] = float(match.group(1))
        else:
            # Simpler: label followed by percentage anywhere nearby
            pattern2 = rf'{re.escape(label)}.*?<td[^>]*>\s*([\d.]+)%'
            match2 = re.search(pattern2, html, re.DOTALL)
            if match2:
                holdings[f"{key}_holding"] = float(match2.group(1))

    return holdings


def fetch_from_screener(symbol: str, use_cache: bool = True) -> dict:
    """
    Fetch fundamental data from screener.in for a given NSE symbol.

    Args:
        symbol: NSE stock symbol (without .NS)
        use_cache: use cached data if available (4 hour TTL)

    Returns:
        dict with all available fundamental data
    """
    symbol = symbol.strip().upper()

    # Check cache
    if use_cache:
        cached = get_cached(symbol, "screener_in")
        if cached is not None:
            return cached

    # Try consolidated first, then standalone
    html = None
    for url_template in [SCREENER_URL, SCREENER_STANDALONE_URL]:
        url = url_template.format(symbol=symbol)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200 and len(resp.text) > 10000:
                html = resp.text
                break
        except Exception:
            continue

    if html is None:
        return {"symbol": symbol, "source": "screener.in", "error": "Page not found"}

    # Extract data
    ratios = _extract_ratios(html)
    holdings = _extract_shareholding(html)

    result = {
        "symbol": symbol,
        "source": "screener.in",
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        **ratios,
        **holdings,
    }

    # Derive additional fields for compatibility with our screener
    if result.get("roe") is not None:
        result["roe_pct"] = result["roe"]
        result["roe_decimal"] = result["roe"] / 100

    if result.get("roce") is not None:
        result["roce_pct"] = result["roce"]

    if result.get("pe") is not None:
        result["trailing_pe"] = result["pe"]

    if result.get("eps") is not None:
        result["trailing_eps"] = result["eps"]

    if result.get("debt_to_equity") is not None:
        result["debt_to_equity_ratio"] = result["debt_to_equity"]

    if result.get("fii_holding") is not None:
        result["institutional_holdings_pct"] = (
            (result.get("fii_holding", 0) or 0) + (result.get("dii_holding", 0) or 0)
        )

    # Cache result
    set_cached(symbol, "screener_in", result)

    return result


def fetch_fundamentals_batch(symbols: list[str], delay: float = REQUEST_DELAY) -> dict:
    """
    Fetch fundamentals for multiple symbols with polite delays.

    Returns dict mapping symbol -> fundamental data.
    """
    results = {}
    for i, symbol in enumerate(symbols):
        if i > 0:
            time.sleep(delay)
        try:
            data = fetch_from_screener(symbol)
            results[symbol] = data
            roe = data.get("roe_pct", "N/A")
            roce = data.get("roce_pct", "N/A")
            pe = data.get("pe", "N/A")
            print(f"  {symbol:15s}: ROE={roe}% ROCE={roce}% PE={pe}")
        except Exception as e:
            results[symbol] = {"symbol": symbol, "error": str(e)}
            print(f"  {symbol:15s}: ERROR — {e}")
    return results
