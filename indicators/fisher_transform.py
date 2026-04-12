"""
Ehlers Fisher Transform
Converts price into a Gaussian normal distribution, making turning points
extremely sharp and easy to identify. One of the most precise indicators
for swing trade timing.
"""

import pandas as pd
import numpy as np
from indicators.base import BaseIndicator


class FisherTransformIndicator(BaseIndicator):
    name = "Ehlers Fisher Transform"
    indicator_type = "technical"
    description = "Precise turning point detection via Gaussian transformation"
    precision_tier = "most_precise"

    @property
    def default_params(self) -> dict:
        return {"fisher_period": 10, "fisher_signal_period": 1}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["fisher_period"]

        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        midpoint = (high + low) / 2

        # Normalize price to -1 to +1 range over lookback period
        highest = midpoint.rolling(window=period).max()
        lowest = midpoint.rolling(window=period).min()
        hl_range = highest - lowest
        hl_range = hl_range.replace(0, 0.0001)

        raw = 2 * ((midpoint - lowest) / hl_range) - 1
        # Clamp to avoid infinity in log
        raw = raw.clip(-0.999, 0.999)

        # Smooth
        smoothed = raw.ewm(alpha=0.5, min_periods=1).mean()
        smoothed = smoothed.clip(-0.999, 0.999)

        # Fisher Transform: 0.5 * ln((1 + x) / (1 - x))
        fisher = 0.5 * np.log((1 + smoothed) / (1 - smoothed))

        # Signal line (previous bar's fisher value)
        signal = fisher.shift(params["fisher_signal_period"])

        latest_fisher = fisher.iloc[-1]
        latest_signal = signal.iloc[-1]
        prev_fisher = fisher.iloc[-2] if len(fisher) >= 2 else 0

        # Bullish crossover: fisher crosses above signal
        bullish_cross = latest_fisher > latest_signal and prev_fisher <= signal.iloc[-2] if len(fisher) >= 2 else False

        # Bearish crossover
        bearish_cross = latest_fisher < latest_signal and prev_fisher >= signal.iloc[-2] if len(fisher) >= 2 else False

        # Rising fisher = momentum building
        rising = latest_fisher > prev_fisher

        return {
            "fisher": round(latest_fisher, 4),
            "signal": round(latest_signal, 4) if not pd.isna(latest_signal) else 0,
            "bullish_crossover": bullish_cross,
            "bearish_crossover": bearish_cross,
            "rising": rising,
            "fisher_series": fisher,
        }

    def check(self, computed: dict, params: dict) -> dict:
        fisher = computed["fisher"]
        bullish = computed["bullish_crossover"]
        rising = computed["rising"]

        if bullish:
            status = "PASS"
        elif rising and fisher > 0:
            status = "PASS"
        elif rising and fisher > -0.5:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"Fisher={fisher}, Signal={computed['signal']}",
            "threshold": "Bullish crossover or rising above zero",
            "details": f"Cross={bullish}, Rising={rising}, Bearish={computed['bearish_crossover']}",
        }
