"""ATR Indicator — Used for stop loss and target calculations."""

import pandas as pd
from indicators.base import BaseIndicator


class ATRIndicator(BaseIndicator):
    name = "ATR"
    indicator_type = "breakout"
    description = "Average True Range for stop loss and target calculation"

    @property
    def default_params(self) -> dict:
        return {
            "sl_atr_period": 14,
            "sl_atr_multiplier": 1.3,
            "target_atr_multiplier": 1.8,
        }

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["sl_atr_period"]

        tr = pd.concat([
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift()).abs(),
            (df["Low"] - df["Close"].shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/period, min_periods=period).mean()

        latest_close = df["Close"].iloc[-1]
        latest_atr = atr.iloc[-1]

        sl_mult = params["sl_atr_multiplier"]
        tgt_mult = params["target_atr_multiplier"]

        stop_loss = latest_close - sl_mult * latest_atr
        target = latest_close + tgt_mult * latest_atr
        risk = latest_close - stop_loss
        reward = target - latest_close
        rr_ratio = reward / risk if risk > 0 else 0

        return {
            "atr": round(latest_atr, 2),
            "close": round(latest_close, 2),
            "stop_loss": round(stop_loss, 2),
            "target": round(target, 2),
            "risk": round(risk, 2),
            "reward": round(reward, 2),
            "risk_reward_ratio": round(rr_ratio, 2),
        }

    def check(self, computed: dict, params: dict) -> dict:
        rr = computed["risk_reward_ratio"]

        if rr >= 1.3:
            status = "PASS"
        elif rr >= 1.0:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"R:R = 1:{rr}",
            "threshold": "R:R >= 1:1.3",
            "details": f"Entry={computed['close']}, SL={computed['stop_loss']}, Target={computed['target']}, ATR={computed['atr']}",
        }
