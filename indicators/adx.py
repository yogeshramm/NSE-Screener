"""ADX Indicator — ADX must be >= minimum, confirming trend strength."""

import pandas as pd
from indicators.base import BaseIndicator


class ADXIndicator(BaseIndicator):
    name = "ADX"
    indicator_type = "technical"
    description = "ADX confirms trend strength, avoids choppy markets"

    @property
    def default_params(self) -> dict:
        return {"adx_period": 14, "adx_minimum": 20}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["adx_period"]

        high = df["High"]
        low = df["Low"]
        close = df["Close"]

        # +DM and -DM
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        # True Range
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)

        # Smoothed values
        atr = tr.ewm(alpha=1/period, min_periods=period).mean()
        plus_di = 100 * (plus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)

        # DX and ADX
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
        adx = dx.ewm(alpha=1/period, min_periods=period).mean()

        return {
            "adx": round(adx.iloc[-1], 2),
            "plus_di": round(plus_di.iloc[-1], 2),
            "minus_di": round(minus_di.iloc[-1], 2),
        }

    def check(self, computed: dict, params: dict) -> dict:
        adx = computed["adx"]
        minimum = params["adx_minimum"]
        margin = minimum * 0.05

        if adx >= minimum:
            status = "PASS"
        elif adx >= minimum - margin:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": adx,
            "threshold": f">= {minimum}",
            "details": f"+DI={computed['plus_di']}, -DI={computed['minus_di']}",
        }
