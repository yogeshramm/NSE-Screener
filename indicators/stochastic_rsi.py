"""Stochastic RSI — Must be crossing up from oversold zone."""

import pandas as pd
from indicators.base import BaseIndicator


class StochasticRSIIndicator(BaseIndicator):
    name = "Stochastic RSI"
    indicator_type = "breakout"
    description = "StochRSI crossing up from oversold zone"

    @property
    def default_params(self) -> dict:
        return {
            "stochrsi_rsi_period": 14,
            "stochrsi_stoch_period": 14,
            "stochrsi_oversold": 20,
            "stochrsi_overbought": 80,
        }

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        rsi_period = params["stochrsi_rsi_period"]
        stoch_period = params["stochrsi_stoch_period"]

        # RSI
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/rsi_period, min_periods=rsi_period).mean()
        avg_loss = loss.ewm(alpha=1/rsi_period, min_periods=rsi_period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        # Stochastic RSI
        rsi_min = rsi.rolling(window=stoch_period).min()
        rsi_max = rsi.rolling(window=stoch_period).max()
        rsi_range = rsi_max - rsi_min
        rsi_range = rsi_range.replace(0, 0.0001)
        stoch_rsi = ((rsi - rsi_min) / rsi_range) * 100

        # %K (smoothed StochRSI) and %D (signal)
        k = stoch_rsi.rolling(window=3).mean()
        d = k.rolling(window=3).mean()

        latest_k = k.iloc[-1]
        prev_k = k.iloc[-2] if len(k) >= 2 else 0
        latest_d = d.iloc[-1]

        # Crossing up from oversold
        oversold = params["stochrsi_oversold"]
        crossing_up = prev_k < oversold and latest_k > prev_k

        return {
            "stochrsi_k": round(latest_k, 2),
            "stochrsi_d": round(latest_d, 2),
            "crossing_up_from_oversold": crossing_up,
            "in_oversold": latest_k < oversold,
            "in_overbought": latest_k > params["stochrsi_overbought"],
        }

    def check(self, computed: dict, params: dict) -> dict:
        crossing = computed["crossing_up_from_oversold"]
        k = computed["stochrsi_k"]
        oversold = params["stochrsi_oversold"]

        if crossing:
            status = "PASS"
        elif k < oversold * 1.5 and not computed["in_overbought"]:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"%K={k}, %D={computed['stochrsi_d']}",
            "threshold": f"Crossing up from below {oversold}",
            "details": f"Oversold: {computed['in_oversold']}, Overbought: {computed['in_overbought']}",
        }
