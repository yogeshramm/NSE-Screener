"""
Chande Momentum Oscillator (CMO)
Measures momentum by calculating the difference between sum of gains
and sum of losses over a period. More responsive than RSI.
"""

import pandas as pd
from indicators.base import BaseIndicator


class ChandeMomentumIndicator(BaseIndicator):
    name = "Chande Momentum Oscillator"
    indicator_type = "technical"
    description = "Pure momentum measurement, more responsive than RSI"
    precision_tier = "hidden_gem"

    @property
    def default_params(self) -> dict:
        return {"cmo_period": 14, "cmo_min": 10, "cmo_max": 50}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["cmo_period"]
        close = df["Close"]
        delta = close.diff()

        gains = delta.where(delta > 0, 0.0)
        losses = (-delta).where(delta < 0, 0.0)

        sum_gains = gains.rolling(window=period).sum()
        sum_losses = losses.rolling(window=period).sum()

        total = sum_gains + sum_losses
        total = total.replace(0, 0.0001)

        cmo = ((sum_gains - sum_losses) / total) * 100

        latest = cmo.iloc[-1]
        prev = cmo.iloc[-2] if len(cmo) >= 2 else 0

        return {
            "cmo": round(latest, 2),
            "rising": latest > prev,
            "cmo_series": cmo,
        }

    def check(self, computed: dict, params: dict) -> dict:
        cmo = computed["cmo"]
        cmo_min = params["cmo_min"]
        cmo_max = params["cmo_max"]
        rising = computed["rising"]

        in_range = cmo_min <= cmo <= cmo_max
        margin = (cmo_max - cmo_min) * 0.05

        if in_range and rising:
            status = "PASS"
        elif in_range or (cmo_min - margin <= cmo <= cmo_max + margin):
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"{cmo}",
            "threshold": f"{cmo_min} to {cmo_max}, rising",
            "details": f"CMO({params['cmo_period']}) = {cmo}, Rising={rising}",
        }
