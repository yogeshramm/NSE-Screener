"""
Klinger Volume Oscillator (KVO)
Measures the difference between volume flowing in and out of a security.
Extremely effective at confirming breakouts with volume conviction.
"""

import pandas as pd
import numpy as np
from indicators.base import BaseIndicator


class KlingerOscillatorIndicator(BaseIndicator):
    name = "Klinger Volume Oscillator"
    indicator_type = "technical"
    description = "Volume flow confirmation for breakout conviction"
    precision_tier = "most_precise"

    @property
    def default_params(self) -> dict:
        return {"kvo_fast": 34, "kvo_slow": 55, "kvo_signal": 13}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        fast = params["kvo_fast"]
        slow = params["kvo_slow"]
        signal_period = params["kvo_signal"]

        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        volume = df["Volume"]

        # Trend direction
        hlc = high + low + close
        trend = pd.Series(0, index=df.index)
        trend[hlc > hlc.shift(1)] = 1
        trend[hlc <= hlc.shift(1)] = -1

        # dm (price movement)
        dm = high - low

        # Cumulative movement
        cm = pd.Series(0.0, index=df.index)
        for i in range(1, len(df)):
            if trend.iloc[i] == trend.iloc[i-1]:
                cm.iloc[i] = cm.iloc[i-1] + dm.iloc[i]
            else:
                cm.iloc[i] = dm.iloc[i-1] + dm.iloc[i]

        # Volume Force
        cm_safe = cm.replace(0, 0.0001)
        vf = volume * abs(2 * (dm / cm_safe) - 1) * trend * 100

        # KVO = EMA(VF, fast) - EMA(VF, slow)
        kvo = vf.ewm(span=fast, adjust=False).mean() - vf.ewm(span=slow, adjust=False).mean()

        # Signal line
        signal = kvo.ewm(span=signal_period, adjust=False).mean()

        latest_kvo = kvo.iloc[-1]
        latest_signal = signal.iloc[-1]
        prev_kvo = kvo.iloc[-2] if len(kvo) >= 2 else 0

        # Bullish: KVO crosses above signal
        bullish_cross = latest_kvo > latest_signal and prev_kvo <= signal.iloc[-2] if len(kvo) >= 2 else False

        return {
            "kvo": round(latest_kvo, 2),
            "signal": round(latest_signal, 2),
            "bullish_crossover": bullish_cross,
            "above_signal": latest_kvo > latest_signal,
            "positive": latest_kvo > 0,
        }

    def check(self, computed: dict, params: dict) -> dict:
        kvo = computed["kvo"]
        above = computed["above_signal"]
        positive = computed["positive"]
        bullish = computed["bullish_crossover"]

        if bullish or (above and positive):
            status = "PASS"
        elif above or positive:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"KVO={kvo}, Signal={computed['signal']}",
            "threshold": "KVO above signal line, positive",
            "details": f"Cross={bullish}, AboveSignal={above}, Positive={positive}",
        }
