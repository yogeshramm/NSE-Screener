"""
NSE Bhavcopy (EOD) Downloader
Downloads the official NSE end-of-day Bhavcopy CSV and extracts closing prices.

NSE publishes Bhavcopy after market close (~6 PM IST) at:
https://nsearchives.nseindia.com/content/cm/BhsecYYMMDD.csv  (new format)
https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv

We try multiple URL formats and date fallbacks to handle weekends/holidays.
"""

import requests
import pandas as pd
import io
from datetime import datetime, timedelta


# NSE requires browser-like headers to allow downloads
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.nseindia.com/",
}


def _get_nse_session() -> requests.Session:
    """Create a session that first visits NSE homepage to get cookies."""
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    # Visit main page to get cookies
    try:
        session.get("https://www.nseindia.com/", timeout=10)
    except Exception:
        pass
    return session


def _try_download_bhavcopy(session: requests.Session, date: datetime) -> pd.DataFrame | None:
    """Try multiple URL formats for a given date. Returns DataFrame or None."""
    dd = date.strftime("%d")
    mm = date.strftime("%m")
    yyyy = date.strftime("%Y")
    yy = date.strftime("%y")
    ddmmyyyy = date.strftime("%d%m%Y")
    mon = date.strftime("%b").upper()

    # URL patterns NSE has used (try all)
    urls = [
        f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv",
        f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyy}{mm}{dd}_F_0000.csv.zip",
        f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mon}/cm{dd}{mon}{yyyy}bhav.csv.zip",
    ]

    for url in urls:
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 500:
                # Handle zip files
                if url.endswith(".zip"):
                    import zipfile
                    z = zipfile.ZipFile(io.BytesIO(resp.content))
                    csv_name = [n for n in z.namelist() if n.endswith(".csv")][0]
                    df = pd.read_csv(z.open(csv_name))
                else:
                    df = pd.read_csv(io.StringIO(resp.text))
                # Standardize column names (strip whitespace)
                df.columns = df.columns.str.strip()
                return df
        except Exception:
            continue
    return None


def download_bhavcopy(target_date: datetime | None = None, max_retries: int = 5) -> pd.DataFrame:
    """
    Download NSE Bhavcopy for the target date.
    If target_date is None, uses today.
    If today's data isn't available (weekend/holiday), tries previous days.

    Returns the full Bhavcopy DataFrame.
    """
    if target_date is None:
        target_date = datetime.now()

    session = _get_nse_session()

    for i in range(max_retries):
        check_date = target_date - timedelta(days=i)
        # Skip weekends
        if check_date.weekday() >= 5:
            continue
        df = _try_download_bhavcopy(session, check_date)
        if df is not None:
            print(f"  Bhavcopy downloaded for: {check_date.strftime('%Y-%m-%d')}")
            return df

    raise ValueError(f"Could not download Bhavcopy for any date in the last {max_retries} days")


def get_bhavcopy_close(symbol: str, bhavcopy_df: pd.DataFrame | None = None) -> dict:
    """
    Get the official NSE closing price for a symbol from Bhavcopy.

    Returns dict with:
      - symbol: the stock symbol
      - close_price: official closing price
      - date: date of the Bhavcopy
      - found: True/False
    """
    if bhavcopy_df is None:
        bhavcopy_df = download_bhavcopy()

    symbol = symbol.strip().upper()

    # Find the symbol column — Bhavcopy uses various column names
    symbol_col = None
    for candidate in ["SYMBOL", "TckrSymb", "TCKRSYMB", "Symbol"]:
        if candidate in bhavcopy_df.columns:
            symbol_col = candidate
            break

    if symbol_col is None:
        # Try case-insensitive match
        for col in bhavcopy_df.columns:
            if col.strip().upper() == "SYMBOL":
                symbol_col = col
                break

    if symbol_col is None:
        return {"symbol": symbol, "close_price": None, "date": None, "found": False,
                "error": f"Could not find symbol column. Available columns: {list(bhavcopy_df.columns)}"}

    # Also strip the symbol values in the dataframe
    bhavcopy_df[symbol_col] = bhavcopy_df[symbol_col].astype(str).str.strip()

    # Find the stock row
    row = bhavcopy_df[bhavcopy_df[symbol_col] == symbol]

    if row.empty:
        return {"symbol": symbol, "close_price": None, "date": None, "found": False,
                "error": f"Symbol {symbol} not found in Bhavcopy"}

    # Find close price column
    close_col = None
    for candidate in ["CLOSE_PRICE", "CLOSE", "ClsPric", "Close Price", "ClosePric"]:
        if candidate in bhavcopy_df.columns:
            close_col = candidate
            break

    if close_col is None:
        for col in bhavcopy_df.columns:
            if "CLOSE" in col.upper() and "PREV" not in col.upper():
                close_col = col
                break

    if close_col is None:
        return {"symbol": symbol, "close_price": None, "date": None, "found": False,
                "error": f"Could not find close price column. Available: {list(bhavcopy_df.columns)}"}

    # Find date column
    date_val = None
    for candidate in ["DATE1", "TRADING_DATE", "TradDt", "Date", "TRADE_DATE"]:
        if candidate in bhavcopy_df.columns:
            date_val = str(row.iloc[0][candidate]).strip()
            break

    close_price = float(row.iloc[0][close_col])

    return {
        "symbol": symbol,
        "close_price": round(close_price, 2),
        "date": date_val,
        "found": True,
    }
