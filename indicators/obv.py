"""OBV Indicator — On Balance Volume must be rising, confirming accumulation."""

import pandas as pd
import numpy as np
from indicators.base import BaseIndicator


class OBVIndicator(BaseIndicator):
    name = "OBV"
    indicator_type = "technical"
    description = "On Balance Volume trend must be rising"

    @property
    def default_params(self) -> dict:
        return {"obv_lookback": 20, "obv_direction": "rising"}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        lookback = params["obv_lookback"]

        # Compute OBV
        obv = pd.Series(0.0, index=df.index)
        for i in range(1, len(df)):
            if df["Close"].iloc[i] > df["Close"].iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] + df["Volume"].iloc[i]
            elif df["Close"].iloc[i] < df["Close"].iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] - df["Volume"].iloc[i]
            else:
                obv.iloc[i] = obv.iloc[i-1]

        # Check trend over lookback period using linear regression slope
        recent_obv = obv.iloc[-lookback:]
        x = np.arange(len(recent_obv))
        slope = np.polyfit(x, recent_obv.values, 1)[0]

        return {
            "obv_latest": int(obv.iloc[-1]),
            "obv_slope": round(slope, 2),
            "obv_rising": slope > 0,
        }

    def check(self, computed: dict, params: dict) -> dict:
        rising = computed["obv_rising"]
        slope = computed["obv_slope"]

        if rising and slope > 0:
            status = "PASS"
        elif abs(slope) < abs(computed["obv_latest"]) * 0.001:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        direction = "Rising" if rising else "Falling"
        return {
            "status": status,
            "value": f"{direction} (slope={slope})",
            "threshold": f"Direction: {params['obv_direction']}",
            "details": f"OBV={computed['obv_latest']:,}, Slope={slope}",
        }
