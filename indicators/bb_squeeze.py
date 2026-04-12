"""Bollinger Band Squeeze — BB contracting inside Keltner Channels = energy buildup."""

import pandas as pd
from indicators.base import BaseIndicator


class BBSqueezeIndicator(BaseIndicator):
    name = "Bollinger Band Squeeze"
    indicator_type = "breakout"
    description = "Bollinger Bands contracting inside Keltner Channels"

    @property
    def default_params(self) -> dict:
        return {"bb_period": 20, "bb_multiplier": 2.0, "kc_multiplier": 1.5}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["bb_period"]
        bb_mult = params["bb_multiplier"]
        kc_mult = params["kc_multiplier"]

        close = df["Close"]
        high = df["High"]
        low = df["Low"]

        # Bollinger Bands
        sma = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        bb_upper = sma + bb_mult * std
        bb_lower = sma - bb_mult * std

        # Keltner Channels
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/period, min_periods=period).mean()
        kc_upper = sma + kc_mult * atr
        kc_lower = sma - kc_mult * atr

        # Squeeze: BB inside KC
        squeeze = (bb_lower.iloc[-1] > kc_lower.iloc[-1]) and (bb_upper.iloc[-1] < kc_upper.iloc[-1])

        # BB width (narrowing = squeeze building)
        bb_width = (bb_upper - bb_lower) / sma * 100
        bb_width_pct = round(bb_width.iloc[-1], 2)

        return {
            "squeeze_on": squeeze,
            "bb_upper": round(bb_upper.iloc[-1], 2),
            "bb_lower": round(bb_lower.iloc[-1], 2),
            "kc_upper": round(kc_upper.iloc[-1], 2),
            "kc_lower": round(kc_lower.iloc[-1], 2),
            "bb_width_pct": bb_width_pct,
        }

    def check(self, computed: dict, params: dict) -> dict:
        squeeze = computed["squeeze_on"]
        width = computed["bb_width_pct"]

        if squeeze:
            status = "PASS"
        elif width < 5:  # narrow bands even if not inside KC
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"Squeeze: {'ON' if squeeze else 'OFF'} (BB width: {width}%)",
            "threshold": "BB inside Keltner Channels",
            "details": f"BB=[{computed['bb_lower']}, {computed['bb_upper']}], KC=[{computed['kc_lower']}, {computed['kc_upper']}]",
        }
