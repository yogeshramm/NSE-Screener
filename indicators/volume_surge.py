"""Volume Surge Indicator — Latest volume must exceed N-day average by multiplier."""

import pandas as pd
from indicators.base import BaseIndicator


class VolumeSurgeIndicator(BaseIndicator):
    name = "Volume Surge"
    indicator_type = "technical"
    description = "Volume on latest candle must exceed average by multiplier"

    @property
    def default_params(self) -> dict:
        return {"volume_surge_multiplier": 1.5, "volume_lookback": 20}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        lookback = params["volume_lookback"]
        latest_vol = df["Volume"].iloc[-1]
        avg_vol = df["Volume"].iloc[-lookback-1:-1].mean()
        ratio = latest_vol / avg_vol if avg_vol > 0 else 0
        return {
            "latest_volume": int(latest_vol),
            "avg_volume": int(avg_vol),
            "volume_ratio": round(ratio, 2),
        }

    def check(self, computed: dict, params: dict) -> dict:
        ratio = computed["volume_ratio"]
        multiplier = params["volume_surge_multiplier"]
        margin = multiplier * 0.05

        if ratio >= multiplier:
            status = "PASS"
        elif ratio >= multiplier - margin:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"{ratio}x avg",
            "threshold": f">= {multiplier}x",
            "details": f"Latest: {computed['latest_volume']:,} | Avg({params['volume_lookback']}d): {computed['avg_volume']:,}",
        }
