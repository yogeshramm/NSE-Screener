"""Sector Performance — Stock's sector must outperform Nifty over lookback period."""

import pandas as pd
import yfinance as yf
from indicators.base import BaseIndicator


# Mapping of sectors to NSE sectoral indices
SECTOR_INDEX_MAP = {
    "Energy": "^CNXENERGY",
    "Financial Services": "NIFTY_FIN_SERVICE.NS",
    "Technology": "^CNXIT",
    "Information Technology": "^CNXIT",
    "Health Care": "^CNXPHARMA",
    "Consumer Cyclical": "^CNXAUTO",
    "Consumer Defensive": "^CNXFMCG",
    "Industrials": "^CNXINFRA",
    "Basic Materials": "^CNXMETAL",
    "Real Estate": "^CNXREALTY",
    "Communication Services": "^CNXMEDIA",
    "Utilities": "^CNXPSUBANK",
}

NIFTY_SYMBOL = "^NSEI"


class SectorPerformanceIndicator(BaseIndicator):
    name = "Sector Performance"
    indicator_type = "technical"
    description = "Stock sector must outperform Nifty"

    @property
    def default_params(self) -> dict:
        return {"sector_lookback": 30}

    def compute(self, df: pd.DataFrame, params: dict, sector: str = None) -> dict:
        lookback = params["sector_lookback"]

        if sector is None:
            return {
                "sector_return": None,
                "nifty_return": None,
                "outperforming": False,
                "reason": "No sector provided",
            }

        # Stock's own return over lookback
        if len(df) > lookback:
            stock_return = (df["Close"].iloc[-1] / df["Close"].iloc[-lookback] - 1) * 100
        else:
            stock_return = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100

        # Get Nifty return
        try:
            nifty = yf.Ticker(NIFTY_SYMBOL)
            nifty_hist = nifty.history(period=f"{lookback + 10}d")
            if len(nifty_hist) >= lookback:
                nifty_return = (nifty_hist["Close"].iloc[-1] / nifty_hist["Close"].iloc[-lookback] - 1) * 100
            else:
                nifty_return = (nifty_hist["Close"].iloc[-1] / nifty_hist["Close"].iloc[0] - 1) * 100
        except Exception:
            nifty_return = 0

        # Get sector index return
        sector_idx = SECTOR_INDEX_MAP.get(sector)
        sector_return = None
        if sector_idx:
            try:
                sec = yf.Ticker(sector_idx)
                sec_hist = sec.history(period=f"{lookback + 10}d")
                if len(sec_hist) >= lookback:
                    sector_return = (sec_hist["Close"].iloc[-1] / sec_hist["Close"].iloc[-lookback] - 1) * 100
                else:
                    sector_return = (sec_hist["Close"].iloc[-1] / sec_hist["Close"].iloc[0] - 1) * 100
            except Exception:
                sector_return = stock_return  # fallback to stock's own return

        if sector_return is None:
            sector_return = stock_return  # use stock return as proxy

        outperforming = sector_return > nifty_return

        return {
            "stock_return": round(stock_return, 2),
            "sector_return": round(sector_return, 2),
            "nifty_return": round(nifty_return, 2),
            "outperforming": outperforming,
            "sector": sector,
        }

    def check(self, computed: dict, params: dict) -> dict:
        outperforming = computed["outperforming"]
        sector_ret = computed.get("sector_return", 0)
        nifty_ret = computed.get("nifty_return", 0)

        if outperforming:
            status = "PASS"
        elif sector_ret is not None and nifty_ret is not None and abs(sector_ret - nifty_ret) < 1:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"Sector: {computed.get('sector_return')}% vs Nifty: {computed.get('nifty_return')}%",
            "threshold": "Sector outperforms Nifty",
            "details": f"Sector: {computed.get('sector')}, Stock: {computed.get('stock_return')}%",
        }
