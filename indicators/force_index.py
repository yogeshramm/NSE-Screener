"""
Elder's Force Index (EFI)
Combines price change and volume to measure the force behind price moves.
Positive force = bulls in control, negative = bears in control.
"""

import pandas as pd
from indicators.base import BaseIndicator


class ForceIndexIndicator(BaseIndicator):
    name = "Elder Force Index"
    indicator_type = "technical"
    description = "Price-volume force measurement, confirms trend conviction"
    precision_tier = "hidden_gem"

    @property
    def default_params(self) -> dict:
        return {"efi_period": 13}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["efi_period"]

        # Raw force index: (Close - PrevClose) * Volume
        raw_fi = df["Close"].diff() * df["Volume"]

        # Smoothed with EMA
        efi = raw_fi.ewm(span=period, adjust=False).mean()

        latest = efi.iloc[-1]
        prev = efi.iloc[-2] if len(efi) >= 2 else 0

        # Zero line crossover
        zero_cross_bullish = prev < 0 and latest > 0
        # Rising
        rising = latest > prev

        return {
            "efi": round(latest, 2),
            "positive": latest > 0,
            "rising": rising,
            "zero_cross_bullish": zero_cross_bullish,
        }

    def check(self, computed: dict, params: dict) -> dict:
        efi = computed["efi"]
        positive = computed["positive"]
        rising = computed["rising"]
        cross = computed["zero_cross_bullish"]

        if cross or (positive and rising):
            status = "PASS"
        elif positive:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"{efi:,.0f}",
            "threshold": "Positive and rising",
            "details": f"EFI({params['efi_period']}) = {efi:,.0f}, ZeroCross={cross}, Rising={rising}",
        }
