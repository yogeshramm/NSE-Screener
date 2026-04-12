"""Hidden Bullish Divergence — Must be present on 4H chart using RSI or MACD."""

import pandas as pd
import numpy as np
from indicators.base import BaseIndicator


class HiddenDivergenceIndicator(BaseIndicator):
    name = "Hidden Bullish Divergence"
    indicator_type = "technical"
    description = "Hidden bullish divergence on 4H chart"

    @property
    def default_params(self) -> dict:
        return {
            "divergence_timeframe": "4H",
            "divergence_indicator": "RSI",
            "divergence_lookback": 30,
            "rsi_period": 14,
        }

    def _compute_rsi(self, close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _find_swing_lows(self, series: pd.Series, lookback: int, window: int = 5) -> list:
        """Find swing lows in the series — local minimums."""
        lows = []
        data = series.iloc[-lookback:]
        for i in range(window, len(data) - window):
            if data.iloc[i] == data.iloc[max(0, i-window):i+window+1].min():
                lows.append((len(series) - lookback + i, data.iloc[i]))
        return lows

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        lookback = params["divergence_lookback"]
        rsi_period = params["rsi_period"]
        lookback = min(lookback, len(df) - rsi_period - 1)

        if len(df) < rsi_period + 10:
            return {"divergence_found": False, "reason": "Insufficient data"}

        rsi = self._compute_rsi(df["Close"], rsi_period)

        # Find swing lows in price and RSI
        price_lows = self._find_swing_lows(df["Close"], lookback)
        rsi_lows = self._find_swing_lows(rsi, lookback)

        # Hidden bullish divergence: price makes higher low, RSI makes lower low
        divergence = False
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            # Compare last two swing lows
            price_low1 = price_lows[-2][1]
            price_low2 = price_lows[-1][1]
            rsi_low1 = rsi_lows[-2][1]
            rsi_low2 = rsi_lows[-1][1]

            if price_low2 > price_low1 and rsi_low2 < rsi_low1:
                divergence = True

        return {
            "divergence_found": divergence,
            "price_swing_lows": len(price_lows),
            "rsi_swing_lows": len(rsi_lows),
            "latest_rsi": round(rsi.iloc[-1], 2),
        }

    def check(self, computed: dict, params: dict) -> dict:
        found = computed["divergence_found"]

        if found:
            status = "PASS"
        elif computed.get("price_swing_lows", 0) >= 2:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"Divergence: {'Yes' if found else 'No'}",
            "threshold": "Hidden bullish divergence present",
            "details": f"Price swing lows: {computed.get('price_swing_lows', 0)}, RSI swing lows: {computed.get('rsi_swing_lows', 0)}",
        }
