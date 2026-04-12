"""ROC Indicator — Rate of Change must be > minimum."""

import pandas as pd
from indicators.base import BaseIndicator


class ROCIndicator(BaseIndicator):
    name = "ROC"
    indicator_type = "technical"
    description = "Rate of Change confirms positive momentum"

    @property
    def default_params(self) -> dict:
        return {"roc_period": 20, "roc_minimum": 0}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["roc_period"]
        roc = ((df["Close"] - df["Close"].shift(period)) / df["Close"].shift(period)) * 100
        return {"roc": round(roc.iloc[-1], 2)}

    def check(self, computed: dict, params: dict) -> dict:
        roc = computed["roc"]
        minimum = params["roc_minimum"]

        if roc > minimum:
            status = "PASS"
        elif roc == minimum:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"{roc}%",
            "threshold": f"> {minimum}%",
            "details": f"ROC({params['roc_period']}) = {roc}%",
        }
