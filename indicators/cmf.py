"""CMF Indicator — Chaikin Money Flow must be >= minimum."""

import pandas as pd
from indicators.base import BaseIndicator


class CMFIndicator(BaseIndicator):
    name = "CMF"
    indicator_type = "technical"
    description = "Chaikin Money Flow confirms positive money flow"

    @property
    def default_params(self) -> dict:
        return {"cmf_period": 20, "cmf_minimum": 0.1}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["cmf_period"]

        # Money Flow Multiplier = ((Close - Low) - (High - Close)) / (High - Low)
        high_low = df["High"] - df["Low"]
        high_low = high_low.replace(0, 0.0001)  # avoid division by zero
        mf_multiplier = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / high_low

        # Money Flow Volume
        mf_volume = mf_multiplier * df["Volume"]

        # CMF = Sum(MF Volume, period) / Sum(Volume, period)
        cmf = mf_volume.rolling(window=period).sum() / df["Volume"].rolling(window=period).sum()

        return {
            "cmf": round(cmf.iloc[-1], 4),
        }

    def check(self, computed: dict, params: dict) -> dict:
        cmf = computed["cmf"]
        minimum = params["cmf_minimum"]
        margin = minimum * 0.05

        if cmf >= minimum:
            status = "PASS"
        elif cmf >= minimum - margin:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": cmf,
            "threshold": f">= {minimum}",
            "details": f"CMF({params['cmf_period']}) = {cmf}",
        }
