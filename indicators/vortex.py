"""
Vortex Indicator (VI)
Identifies trend direction and strength using +VI and -VI lines.
When +VI crosses above -VI = bullish trend confirmed.
Extra-highlighted as user's preferred replacement indicator.
"""

import pandas as pd
from indicators.base import BaseIndicator


class VortexIndicator(BaseIndicator):
    name = "Vortex Indicator"
    indicator_type = "technical"
    description = "Trend direction and strength via +VI/-VI crossover"
    precision_tier = "hidden_gem"
    highlighted = True  # User's extra-highlighted indicator

    @property
    def default_params(self) -> dict:
        return {"vortex_period": 14, "vi_threshold": 0.05}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["vortex_period"]

        high = df["High"]
        low = df["Low"]
        close = df["Close"]

        # True Range
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)

        # +VM (Vortex Movement Up) and -VM (Vortex Movement Down)
        vm_plus = (high - low.shift()).abs()
        vm_minus = (low - high.shift()).abs()

        # Sum over period
        tr_sum = tr.rolling(window=period).sum()
        vm_plus_sum = vm_plus.rolling(window=period).sum()
        vm_minus_sum = vm_minus.rolling(window=period).sum()

        # +VI and -VI
        tr_safe = tr_sum.replace(0, 0.0001)
        vi_plus = vm_plus_sum / tr_safe
        vi_minus = vm_minus_sum / tr_safe

        latest_plus = vi_plus.iloc[-1]
        latest_minus = vi_minus.iloc[-1]
        prev_plus = vi_plus.iloc[-2] if len(vi_plus) >= 2 else 0
        prev_minus = vi_minus.iloc[-2] if len(vi_minus) >= 2 else 0

        # Bullish crossover: +VI crosses above -VI
        bullish_cross = (latest_plus > latest_minus and prev_plus <= prev_minus)

        # Bullish trend: +VI > -VI
        bullish = latest_plus > latest_minus

        # Trend strength: difference between +VI and -VI
        spread = latest_plus - latest_minus

        return {
            "vi_plus": round(latest_plus, 4),
            "vi_minus": round(latest_minus, 4),
            "spread": round(spread, 4),
            "bullish": bullish,
            "bullish_crossover": bullish_cross,
        }

    def check(self, computed: dict, params: dict) -> dict:
        bullish = computed["bullish"]
        cross = computed["bullish_crossover"]
        spread = computed["spread"]
        threshold = params["vi_threshold"]

        if cross or (bullish and spread >= threshold):
            status = "PASS"
        elif bullish:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"+VI={computed['vi_plus']}, -VI={computed['vi_minus']}",
            "threshold": f"+VI > -VI (spread >= {threshold})",
            "details": f"Spread={spread}, Crossover={cross}, Bullish={bullish}",
        }
