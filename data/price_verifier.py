"""
Price Verification Module
Compares yfinance closing prices against NSE Bhavcopy official prices.
Flags discrepancies greater than 0.5%.
"""


def verify_price(yf_close: float, bhavcopy_close: float, symbol: str, threshold_pct: float = 0.5) -> dict:
    """
    Compare yfinance close price vs NSE Bhavcopy close price.

    Args:
        yf_close: Closing price from yfinance
        bhavcopy_close: Closing price from NSE Bhavcopy
        symbol: Stock symbol for reporting
        threshold_pct: Maximum allowed difference in percent (default 0.5%)

    Returns dict with:
        - symbol
        - yfinance_close
        - bhavcopy_close
        - difference_pct: absolute percentage difference
        - match: True if within threshold
        - flagged: True if mismatch exceeds threshold
        - message: human-readable status
    """
    if yf_close is None or bhavcopy_close is None:
        return {
            "symbol": symbol,
            "yfinance_close": yf_close,
            "bhavcopy_close": bhavcopy_close,
            "difference_pct": None,
            "match": False,
            "flagged": True,
            "message": f"Cannot verify {symbol}: missing price data (yf={yf_close}, bhavcopy={bhavcopy_close})",
        }

    diff_pct = abs(yf_close - bhavcopy_close) / bhavcopy_close * 100
    diff_pct = round(diff_pct, 4)
    is_match = diff_pct <= threshold_pct

    if is_match:
        message = f"MATCH: {symbol} — YF: {yf_close} | Bhavcopy: {bhavcopy_close} | Diff: {diff_pct}%"
    else:
        message = f"MISMATCH FLAGGED: {symbol} — YF: {yf_close} | Bhavcopy: {bhavcopy_close} | Diff: {diff_pct}% (>{threshold_pct}%)"

    return {
        "symbol": symbol,
        "yfinance_close": yf_close,
        "bhavcopy_close": bhavcopy_close,
        "difference_pct": diff_pct,
        "match": is_match,
        "flagged": not is_match,
        "message": message,
    }
