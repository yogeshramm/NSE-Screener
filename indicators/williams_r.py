"""Williams %R — Must be between min and max, confirming strong but not overbought."""

import pandas as pd
from indicators.base import BaseIndicator


class WilliamsRIndicator(BaseIndicator):
    name = "Williams %R"
    indicator_type = "breakout"
    description = "Williams %R confirms strong but not overbought"

    @property
    def default_params(self) -> dict:
        return {"williams_period": 14, "williams_min": -40, "williams_max": -10}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["williams_period"]

        highest_high = df["High"].rolling(window=period).max()
        lowest_low = df["Low"].rolling(window=period).min()
        hl_range = highest_high - lowest_low
        hl_range = hl_range.replace(0, 0.0001)

        williams_r = -100 * (highest_high - df["Close"]) / hl_range

        return {
            "williams_r": round(williams_r.iloc[-1], 2),
        }

    def check(self, computed: dict, params: dict) -> dict:
        wr = computed["williams_r"]
        wr_min = params["williams_min"]
        wr_max = params["williams_max"]

        in_range = wr_min <= wr <= wr_max
        margin = abs(wr_max - wr_min) * 0.05

        if in_range:
            status = "PASS"
        elif (wr_min - margin <= wr < wr_min) or (wr_max < wr <= wr_max + margin):
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": wr,
            "threshold": f"{wr_min} to {wr_max}",
            "details": f"Williams %R({params['williams_period']}) = {wr}",
        }
