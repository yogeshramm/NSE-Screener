"""RSI Indicator — RSI must be between rsi_min and rsi_max.

delay_f_entry mode (DELAY-F validated logic):
  Requires RSI dipped below 50 within last delay_f_lookback bars AND
  RSI crossed above rsi_min today (prev bar was below rsi_min).
  This is the exact entry sequence backtested at WR 60.9% / EV +4.24%.
"""

import pandas as pd
from indicators.base import BaseIndicator


class RSIIndicator(BaseIndicator):
    name = "RSI"
    indicator_type = "technical"
    description = "RSI must be in the sweet spot range"

    @property
    def default_params(self) -> dict:
        return {"rsi_period": 14, "rsi_min": 50, "rsi_max": 65,
                "delay_f_entry": False, "delay_f_lookback": 15}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["rsi_period"]
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return {"rsi": round(rsi.iloc[-1], 2), "rsi_series": rsi}

    def check(self, computed: dict, params: dict) -> dict:
        rsi = computed["rsi"]
        rsi_min = params["rsi_min"]
        rsi_max = params["rsi_max"]
        delay_f = params.get("delay_f_entry", False)
        lookback = int(params.get("delay_f_lookback", 15))

        if delay_f:
            rsi_series = computed.get("rsi_series")
            if rsi_series is None or len(rsi_series) < lookback + 1:
                return {
                    "status": "FAIL",
                    "value": rsi,
                    "threshold": f"DELAY-F: dip<50 in {lookback}b + cross≥{rsi_min}",
                    "details": f"RSI({params['rsi_period']}) = {rsi} — insufficient history",
                }

            recent = rsi_series.iloc[-(lookback + 1):]
            dipped = bool((recent.iloc[:-1] < 50).any())
            crossed = bool(recent.iloc[-2] < rsi_min and rsi >= rsi_min)
            in_range = rsi_min <= rsi <= rsi_max

            if dipped and crossed and in_range:
                status = "PASS"
            elif dipped and in_range and recent.iloc[-2] < rsi_min + (rsi_max - rsi_min) * 0.05:
                # borderline: dipped but crossover is marginal
                status = "BORDERLINE"
            else:
                status = "FAIL"

            missing = []
            if not dipped:
                missing.append(f"no dip<50 in last {lookback}b")
            if not crossed:
                missing.append(f"no cross≥{rsi_min} (prev={round(float(recent.iloc[-2]), 1)})")
            if not in_range:
                missing.append(f"RSI {rsi} outside {rsi_min}-{rsi_max}")

            details = f"RSI({params['rsi_period']}) = {rsi}"
            if missing:
                details += " | FAIL: " + ", ".join(missing)
            else:
                details += f" | dipped<50 ✓ crossed≥{rsi_min} ✓"

            return {
                "status": status,
                "value": rsi,
                "threshold": f"DELAY-F: dip<50 in {lookback}b + cross≥{rsi_min}",
                "details": details,
            }

        # Standard RSI range check
        in_range = rsi_min <= rsi <= rsi_max
        margin = (rsi_max - rsi_min) * 0.05
        borderline = (rsi_min - margin <= rsi < rsi_min) or (rsi_max < rsi <= rsi_max + margin)

        if in_range:
            status = "PASS"
        elif borderline:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": rsi,
            "threshold": f"{rsi_min}-{rsi_max}",
            "details": f"RSI({params['rsi_period']}) = {rsi}",
        }
