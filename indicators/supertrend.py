"""Supertrend Indicator — Price must be above the Supertrend line."""

import pandas as pd
import numpy as np
from indicators.base import BaseIndicator


class SupertrendIndicator(BaseIndicator):
    name = "Supertrend"
    indicator_type = "technical"
    description = "Price must be above the Supertrend line"

    @property
    def default_params(self) -> dict:
        return {"supertrend_period": 7, "supertrend_multiplier": 3.0}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["supertrend_period"]
        multiplier = params["supertrend_multiplier"]

        hl2 = (df["High"] + df["Low"]) / 2

        # ATR calculation
        tr = pd.concat([
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift()).abs(),
            (df["Low"] - df["Close"].shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/period, min_periods=period).mean()

        # Upper and lower bands
        upper_basic = hl2 + multiplier * atr
        lower_basic = hl2 - multiplier * atr

        upper_band = upper_basic.copy()
        lower_band = lower_basic.copy()
        supertrend = pd.Series(index=df.index, dtype=float)
        direction = pd.Series(index=df.index, dtype=int)

        for i in range(period, len(df)):
            # Upper band
            if upper_basic.iloc[i] < upper_band.iloc[i-1] or df["Close"].iloc[i-1] > upper_band.iloc[i-1]:
                upper_band.iloc[i] = upper_basic.iloc[i]
            else:
                upper_band.iloc[i] = upper_band.iloc[i-1]

            # Lower band
            if lower_basic.iloc[i] > lower_band.iloc[i-1] or df["Close"].iloc[i-1] < lower_band.iloc[i-1]:
                lower_band.iloc[i] = lower_basic.iloc[i]
            else:
                lower_band.iloc[i] = lower_band.iloc[i-1]

            # Direction and supertrend value
            if i == period:
                direction.iloc[i] = 1
                supertrend.iloc[i] = lower_band.iloc[i]
            elif supertrend.iloc[i-1] == upper_band.iloc[i-1]:
                if df["Close"].iloc[i] > upper_band.iloc[i]:
                    direction.iloc[i] = 1
                    supertrend.iloc[i] = lower_band.iloc[i]
                else:
                    direction.iloc[i] = -1
                    supertrend.iloc[i] = upper_band.iloc[i]
            else:
                if df["Close"].iloc[i] < lower_band.iloc[i]:
                    direction.iloc[i] = -1
                    supertrend.iloc[i] = upper_band.iloc[i]
                else:
                    direction.iloc[i] = 1
                    supertrend.iloc[i] = lower_band.iloc[i]

        latest_close = df["Close"].iloc[-1]
        latest_st = supertrend.iloc[-1]
        above = latest_close > latest_st if not pd.isna(latest_st) else False

        return {
            "supertrend": round(latest_st, 2) if not pd.isna(latest_st) else None,
            "close": round(latest_close, 2),
            "above_supertrend": above,
            "direction": int(direction.iloc[-1]) if not pd.isna(direction.iloc[-1]) else 0,
        }

    def check(self, computed: dict, params: dict) -> dict:
        above = computed["above_supertrend"]
        st_val = computed["supertrend"]

        if st_val is None:
            return {"status": "FAIL", "value": "N/A", "threshold": "Above Supertrend", "details": "Insufficient data"}

        if above:
            status = "PASS"
        else:
            # Check if close is within 2% of supertrend (borderline)
            pct_diff = abs(computed["close"] - st_val) / st_val * 100
            status = "BORDERLINE" if pct_diff < 2 else "FAIL"

        return {
            "status": status,
            "value": f"Close={computed['close']} vs ST={st_val}",
            "threshold": "Price above Supertrend",
            "details": f"Direction: {'Bullish' if computed['direction'] == 1 else 'Bearish'}",
        }
