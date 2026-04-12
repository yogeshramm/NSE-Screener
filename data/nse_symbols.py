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
