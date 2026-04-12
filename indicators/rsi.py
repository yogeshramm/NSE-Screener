"""RSI Indicator — RSI must be between rsi_min and rsi_max."""

import pandas as pd
from indicators.base import BaseIndicator


class RSIIndicator(BaseIndicator):
    name = "RSI"
    indicator_type = "technical"
    description = "RSI must be in the sweet spot range"

    @property
    def default_params(self) -> dict:
        return {"rsi_period": 14, "rsi_min": 50, "rsi_max": 65}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["rsi_period"]
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return {"rsi": round(rsi.iloc[-1], 2), "rsi_series": rsi}

    def check(self, computed: dict, params: dict) -> dict:
        rsi = computed["rsi"]
        rsi_min = params["rsi_min"]
        rsi_max = params["rsi_max"]
        in_range = rsi_min <= rsi <= rsi_max

        # Check borderline (within 5% of boundaries)
        margin = (rsi_max - rsi_min) * 0.05
        borderline = (rsi_min - margin <= rsi < rsi_min) or (rsi_max < rsi <= rsi_max + margin)

        if in_range:
            status = "PASS"
        elif borderline:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": rsi,
            "threshold": f"{rsi_min}-{rsi_max}",
            "details": f"RSI({params['rsi_period']}) = {rsi}",
        }
