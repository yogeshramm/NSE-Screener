"""Awesome Oscillator — AO must show positive histogram or bullish zero-line crossover."""

import pandas as pd
from indicators.base import BaseIndicator


class AwesomeOscillatorIndicator(BaseIndicator):
    name = "Awesome Oscillator"
    indicator_type = "technical"
    description = "AO positive histogram or bullish zero-line crossover"

    @property
    def default_params(self) -> dict:
        return {"ao_fast": 5, "ao_slow": 34, "ao_timeframe": "daily"}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        fast = params["ao_fast"]
        slow = params["ao_slow"]

        midpoint = (df["High"] + df["Low"]) / 2
        ao = midpoint.rolling(window=fast).mean() - midpoint.rolling(window=slow).mean()

        latest_ao = ao.iloc[-1]
        prev_ao = ao.iloc[-2] if len(ao) >= 2 else 0

        # Bullish zero-line crossover: AO crossed from negative to positive in last 3 bars
        zero_cross = False
        if len(ao) >= 3:
            for i in range(-3, 0):
                if ao.iloc[i-1] < 0 and ao.iloc[i] > 0:
                    zero_cross = True
                    break

        # Bullish saucer: AO positive, dipped then rose (green-red-green)
        saucer = False
        if len(ao) >= 3 and latest_ao > 0:
            if ao.iloc[-3] > ao.iloc[-2] and ao.iloc[-2] < latest_ao:
                saucer = True

        return {
            "ao": round(latest_ao, 4),
            "ao_prev": round(prev_ao, 4),
            "positive": latest_ao > 0,
            "zero_line_crossover": zero_cross,
            "bullish_saucer": saucer,
            "rising": latest_ao > prev_ao,
        }

    def check(self, computed: dict, params: dict) -> dict:
        positive = computed["positive"]
        zero_cross = computed["zero_line_crossover"]
        saucer = computed["bullish_saucer"]

        if positive and (zero_cross or computed["rising"]):
            status = "PASS"
        elif positive or saucer:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": computed["ao"],
            "threshold": "Positive histogram or bullish crossover",
            "details": f"AO={computed['ao']}, ZeroCross={zero_cross}, Saucer={saucer}, Rising={computed['rising']}",
        }
