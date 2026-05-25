"""
NSE Stock List Fetcher
Gets the full list of tradeable NSE equity symbols.
Uses the Bhavcopy (already downloaded daily) as the source of truth.
"""

import requests
import pandas as pd
import io
from datetime import datetime, timedelta
from data.nse_bhavcopy import download_bhavcopy


# Curated Nifty 500 + popular stocks as fallback
# This covers all major tradeable stocks for swing trading
NIFTY_500_FALLBACK = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
    "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK",
    "BAJFINANCE", "ASIANPAINT", "MARUTI", "HCLTECH", "WIPRO",
    "SUNPHARMA", "TATAMOTORS", "ULTRACEMCO", "TITAN", "NESTLEIND",
    "NTPC", "POWERGRID", "ONGC", "JSWSTEEL", "TATASTEEL", "ADANIENT",
    "ADANIPORTS", "BAJAJFINSV", "TECHM", "INDUSINDBK", "HDFCLIFE",
    "SBILIFE", "DIVISLAB", "DRREDDY", "CIPLA", "GRASIM", "APOLLOHOSP",
    "BRITANNIA", "EICHERMOT", "HEROMOTOCO", "M&M", "BPCL", "COALINDIA",
    "HINDALCO", "TATACONSUM", "BAJAJ-AUTO", "UPL", "SHREECEM",
    "DABUR", "GODREJCP", "PIDILITIND", "BERGEPAINT", "HAVELLS",
    "VOLTAS", "PAGEIND", "MUTHOOTFIN", "CHOLAFIN", "BANDHANBNK",
    "IDFCFIRSTB", "FEDERALBNK", "PNB", "BANKBARODA", "CANBK",
    "AUBANK", "MANAPPURAM", "L&TFH", "SBICARD", "IRCTC",
    "TATAPOWER", "ADANIGREEN", "ADANITRANS", "TORNTPHARM", "LUPIN",
    "AUROPHARMA", "BIOCON", "ALKEM", "IPCALAB", "LALPATHLAB",
    "METROPOLIS", "DMART", "TRENT", "ZOMATO", "NYKAA", "PAYTM",
    "POLICYBZR", "LTIM", "PERSISTENT", "COFORGE", "MPHASIS",
    "LTTS", "HAPPSTMNDS", "NAUKRI", "INDIAMART", "DEEPAKNTR",
    "ATUL", "PIIND", "SRF", "NAVINFLOUR", "CLEAN", "ASTRAL",
    "SUPREMEIND", "POLYCAB", "KEI", "DIXON", "AMBER",
    "RAJESHEXPO", "TATAELXSI", "CUMMINSIND", "SIEMENS", "ABB",
    "BEL", "HAL", "BHEL", "CONCOR", "IRFC",
    "RECLTD", "PFC", "NHPC", "SJVN", "TATACOMM",
    "IDEA", "INDUSTOWER", "DALBHARAT", "RAMCOCEM", "JKCEMENT",
    "ACC", "AMBUJACEM", "OBEROIRLTY", "DLF", "GODREJPROP",
    "PHOENIXLTD", "PRESTIGE", "SOBHA", "MARICO", "COLPAL",
    "EMAMILTD", "BATAINDIA", "RELAXO", "CROMPTON", "WHIRLPOOL",
    "BLUESTARLT", "MCDOWELL-N", "UBL", "VBL", "JUBLFOOD",
    "DEVYANI", "SAPPHIRE", "ZYDUSLIFE", "GLENMARK", "TORNTPOWER",
    "CESC", "JSL", "JINDALSTEL", "NATIONALUM", "VEDL",
    "NMDC", "SAIL", "GAIL", "IGL", "MGL",
    "PETRONET", "PIPL", "HINDPETRO", "IOC", "MOTHERSON",
    "BALKRISIND", "MRF", "APOLLOTYRE", "CEATLTD", "EXIDEIND",
    "AMARAJABAT", "ESCORTS", "ASHOKLEY", "TVSMOTOR", "BHARATFORG",
    "SUNTV", "PVRINOX", "PERSISTENT", "MFSL", "ICICIGI",
    "ICICIPRULI", "STARHEALTH", "MAXHEALTH", "FORTIS", "MEDANTA",
]


def get_nse_stock_list(source: str = "bhavcopy") -> list[str]:
    """
    Get list of all tradeable NSE equity symbols.

    Args:
        source: "bhavcopy" (downloads today's bhavcopy) or "fallback" (curated list)

    Returns:
        List of NSE stock symbols (without .NS suffix)
    """
    if source == "bhavcopy":
        try:
            bhavcopy = download_bhavcopy()
            # Filter for EQ series only (regular equity, not derivatives)
            series_col = None
            for col in ["SERIES", "SctySrs", "Series"]:
                if col in bhavcopy.columns:
                    series_col = col
                    break

            symbol_col = None
            for col in ["SYMBOL", "TckrSymb", "Symbol"]:
                if col in bhavcopy.columns:
                    symbol_col = col
                    break

            if series_col and symbol_col:
                eq = bhavcopy[bhavcopy[series_col].str.strip() == "EQ"]
                symbols = eq[symbol_col].str.strip().tolist()
                print(f"  Got {len(symbols)} EQ symbols from Bhavcopy")
                return symbols
            elif symbol_col:
                symbols = bhavcopy[symbol_col].str.strip().unique().tolist()
                print(f"  Got {len(symbols)} symbols from Bhavcopy (all series)")
                return symbols
        except Exception as e:
            print(f"  Bhavcopy fetch failed: {e}, using fallback list")

    # Fallback
    print(f"  Using curated fallback list: {len(NIFTY_500_FALLBACK)} stocks")
    return list(NIFTY_500_FALLBACK)


# In-memory cache for Nifty 500 list. Was being re-fetched from NSE on
# every API call that needed it — saturated 1-vCPU droplet with repeated
# HTTP requests every ~80s in production. Now cached for 24h, refreshed
# on first call after expiry.
_NIFTY_TTL = 86400  # 24 hours — all index caches

# Per-index caches: keyed by index name
_nifty_cache: dict = {}   # { "nifty50": {"data": [...], "ts": 0.0}, ... }

# NSE archives CSV URLs — Symbol is column index 2 (0-based)
_NIFTY_URLS = {
    "nifty50":  "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "nifty100": "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "nifty200": "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
    "nifty500": "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
}
_NIFTY_MIN = {"nifty50": 40, "nifty100": 80, "nifty200": 150, "nifty500": 400}


def _fetch_nifty_index(key: str) -> list:
    """Generic fetcher for any NSE index CSV. Returns list of symbols."""
    import time
    cache = _nifty_cache.setdefault(key, {"data": None, "ts": 0.0})
    now = time.time()
    if cache["data"] and (now - cache["ts"]) < _NIFTY_TTL:
        return cache["data"]

    url = _NIFTY_URLS[key]
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code == 200:
            lines = r.text.strip().split("\n")
            symbols = []
            for line in lines[1:]:
                parts = line.split(",")
                if len(parts) >= 3:
                    sym = parts[2].strip().strip('"')
                    if sym:
                        symbols.append(sym)
            if len(symbols) >= _NIFTY_MIN[key]:
                print(f"  Fetched {len(symbols)} {key} symbols from NSE (cached 24h)")
                cache["data"] = symbols
                cache["ts"] = now
                return symbols
    except Exception as e:
        print(f"  {key} live fetch failed: {e}")

    return []   # caller falls back


def get_nifty50_live() -> list:
    return _fetch_nifty_index("nifty50") or list(NIFTY_500_FALLBACK[:50])

def get_nifty100_live() -> list:
    return _fetch_nifty_index("nifty100") or list(NIFTY_500_FALLBACK[:100])

def get_nifty200_live() -> list:
    return _fetch_nifty_index("nifty200") or list(NIFTY_500_FALLBACK[:120])

def get_nifty500_live() -> list:
    """Fetch current Nifty 500 constituents from NSE archives (24h cache)."""
    return _fetch_nifty_index("nifty500") or list(NIFTY_500_FALLBACK)

# Keep legacy alias
_nifty500_cache = _nifty_cache.setdefault("nifty500", {"data": None, "ts": 0.0})
