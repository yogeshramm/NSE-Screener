"""EMA Indicator — Price must be above both EMA 50 and EMA 200."""

import pandas as pd
from indicators.base import BaseIndicator


class EMAIndicator(BaseIndicator):
    name = "EMA"
    indicator_type = "technical"
    description = "Price must be above both fast and slow EMA"

    @property
    def default_params(self) -> dict:
        return {"fast_ema_period": 50, "slow_ema_period": 200}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        fast = params["fast_ema_period"]
        slow = params["slow_ema_period"]
        ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
        latest_close = df["Close"].iloc[-1]
        return {
            "ema_fast": round(ema_fast.iloc[-1], 2),
            "ema_slow": round(ema_slow.iloc[-1], 2),
            "close": round(latest_close, 2),
            "above_fast": latest_close > ema_fast.iloc[-1],
            "above_slow": latest_close > ema_slow.iloc[-1],
        }

    def check(self, computed: dict, params: dict) -> dict:
        above_both = computed["above_fast"] and computed["above_slow"]
        above_one = computed["above_fast"] or computed["above_slow"]
        if above_both:
            status = "PASS"
        elif above_one:
            status = "BORDERLINE"
        else:
            status = "FAIL"
        return {
            "status": status,
            "value": f"Close={computed['close']} vs EMA{params['fast_ema_period']}={computed['ema_fast']}, EMA{params['slow_ema_period']}={computed['ema_slow']}",
            "threshold": f"Above both EMA{params['fast_ema_period']} and EMA{params['slow_ema_period']}",
            "details": f"Above EMA{params['fast_ema_period']}: {computed['above_fast']}, Above EMA{params['slow_ema_period']}: {computed['above_slow']}",
        }
