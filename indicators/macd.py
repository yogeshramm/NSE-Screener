"""MACD Indicator — Must show bullish crossover or imminent bullish crossover."""

import pandas as pd
from indicators.base import BaseIndicator


class MACDIndicator(BaseIndicator):
    name = "MACD"
    indicator_type = "technical"
    description = "MACD bullish crossover with expanding histogram"

    @property
    def default_params(self) -> dict:
        return {"macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                "histogram_mode": False}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        fast = params["macd_fast"]
        slow = params["macd_slow"]
        signal_period = params["macd_signal"]

        ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        histogram = macd_line - signal_line

        # Check crossover: MACD crossed above signal in last 3 bars
        bullish_cross = False
        imminent_cross = False
        expanding_hist = False

        if len(histogram) >= 3:
            # Bullish crossover: histogram went from negative to positive
            for i in range(-3, 0):
                if histogram.iloc[i-1] < 0 and histogram.iloc[i] > 0:
                    bullish_cross = True
                    break

            # Imminent crossover: histogram negative but rising for 2+ bars
            if not bullish_cross and histogram.iloc[-1] < 0:
                if histogram.iloc[-1] > histogram.iloc[-2] > histogram.iloc[-3]:
                    imminent_cross = True

            # Expanding histogram: last 2 bars increasing
            if histogram.iloc[-1] > histogram.iloc[-2]:
                expanding_hist = True

        return {
            "macd": round(macd_line.iloc[-1], 4),
            "signal": round(signal_line.iloc[-1], 4),
            "histogram": round(histogram.iloc[-1], 4),
            "bullish_crossover": bullish_cross,
            "imminent_crossover": imminent_cross,
            "expanding_histogram": expanding_hist,
            "macd_series": macd_line,
            "signal_series": signal_line,
            "histogram_series": histogram,
        }

    def check(self, computed: dict, params: dict) -> dict:
        bullish = computed["bullish_crossover"]
        imminent = computed["imminent_crossover"]
        expanding = computed["expanding_histogram"]
        hist_mode = params.get("histogram_mode", False)

        if hist_mode:
            # OF6 mode: histogram accelerating is the primary signal (data-derived)
            # PASS = expanding for 2+ consecutive bars (momentum building)
            # BORDERLINE = expanding today only
            hist_pos = computed["histogram"] > 0
            if expanding and hist_pos:
                status = "PASS"
            elif expanding:
                status = "BORDERLINE"
            else:
                status = "FAIL"
            threshold = "Histogram rising (momentum mode)"
        else:
            if bullish and expanding:
                status = "PASS"
            elif bullish or (imminent and expanding):
                status = "BORDERLINE"
            else:
                status = "FAIL"
            threshold = "Bullish crossover with expanding histogram"

        return {
            "status": status,
            "value": f"MACD={computed['macd']}, Signal={computed['signal']}, Hist={computed['histogram']}",
            "threshold": threshold,
            "details": f"Crossover: {bullish}, Imminent: {imminent}, Expanding: {expanding}, HistMode: {hist_mode}",
        }
