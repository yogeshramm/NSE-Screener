"""Anchored VWAP — Price must be above VWAP anchored from last major swing point."""

import pandas as pd
import numpy as np
from indicators.base import BaseIndicator


class AnchoredVWAPIndicator(BaseIndicator):
    name = "Anchored VWAP"
    indicator_type = "technical"
    description = "Price must be above VWAP anchored from last major swing low"

    @property
    def default_params(self) -> dict:
        return {"vwap_anchor": "auto", "swing_lookback": 50}

    def _find_swing_low(self, df: pd.DataFrame, lookback: int) -> int:
        """Find the index of the last major swing low in the lookback window."""
        window = df.iloc[-lookback:]
        # Swing low: a bar where low is lower than the 5 bars before and after it
        lows = window["Low"]
        swing_idx = len(window) - 1  # default to start of window

        for i in range(5, len(lows) - 5):
            if lows.iloc[i] == lows.iloc[max(0, i-5):i+6].min():
                swing_idx = i  # keep updating to get the most recent swing low

        # Return absolute index in original dataframe
        return len(df) - lookback + swing_idx

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        lookback = params["swing_lookback"]
        lookback = min(lookback, len(df) - 1)

        # Find anchor point (last major swing low)
        anchor_idx = self._find_swing_low(df, lookback)

        # Compute VWAP from anchor point
        anchored = df.iloc[anchor_idx:]
        typical_price = (anchored["High"] + anchored["Low"] + anchored["Close"]) / 3
        cum_tp_vol = (typical_price * anchored["Volume"]).cumsum()
        cum_vol = anchored["Volume"].cumsum()
        vwap = cum_tp_vol / cum_vol

        latest_close = df["Close"].iloc[-1]
        latest_vwap = vwap.iloc[-1]

        return {
            "vwap": round(latest_vwap, 2),
            "close": round(latest_close, 2),
            "above_vwap": latest_close > latest_vwap,
            "anchor_date": str(df.index[anchor_idx].date()) if hasattr(df.index[anchor_idx], 'date') else str(df.index[anchor_idx]),
            "pct_from_vwap": round((latest_close - latest_vwap) / latest_vwap * 100, 2),
        }

    def check(self, computed: dict, params: dict) -> dict:
        above = computed["above_vwap"]
        pct = computed["pct_from_vwap"]

        if above:
            status = "PASS"
        elif abs(pct) < 1:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"Close={computed['close']} vs VWAP={computed['vwap']} ({pct:+.2f}%)",
            "threshold": "Above anchored VWAP",
            "details": f"Anchor date: {computed['anchor_date']}",
        }
