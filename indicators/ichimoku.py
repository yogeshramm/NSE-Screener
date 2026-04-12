"""Ichimoku Cloud — Price must be above the cloud confirming strong uptrend."""

import pandas as pd
from indicators.base import BaseIndicator


class IchimokuIndicator(BaseIndicator):
    name = "Ichimoku Cloud"
    indicator_type = "breakout"
    description = "Price must be above Ichimoku Cloud"
    precision_tier = "most_precise"

    @property
    def default_params(self) -> dict:
        return {"ichimoku_tenkan": 9, "ichimoku_kijun": 26, "ichimoku_senkou": 52}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        tenkan_period = params["ichimoku_tenkan"]
        kijun_period = params["ichimoku_kijun"]
        senkou_period = params["ichimoku_senkou"]

        # Tenkan-sen (Conversion Line)
        tenkan = (df["High"].rolling(window=tenkan_period).max() +
                  df["Low"].rolling(window=tenkan_period).min()) / 2

        # Kijun-sen (Base Line)
        kijun = (df["High"].rolling(window=kijun_period).max() +
                 df["Low"].rolling(window=kijun_period).min()) / 2

        # Senkou Span A (Leading Span A) = (Tenkan + Kijun) / 2, shifted forward 26 periods
        senkou_a = (tenkan + kijun) / 2

        # Senkou Span B (Leading Span B) = (52-period high + 52-period low) / 2, shifted forward 26
        senkou_b = (df["High"].rolling(window=senkou_period).max() +
                    df["Low"].rolling(window=senkou_period).min()) / 2

        # Current cloud top and bottom (without shift — we compare current price to current cloud)
        cloud_top = pd.concat([senkou_a, senkou_b], axis=1).max(axis=1)
        cloud_bottom = pd.concat([senkou_a, senkou_b], axis=1).min(axis=1)

        latest_close = df["Close"].iloc[-1]
        above_cloud = latest_close > cloud_top.iloc[-1]
        inside_cloud = cloud_bottom.iloc[-1] <= latest_close <= cloud_top.iloc[-1]

        # TK cross: Tenkan above Kijun = bullish
        tk_bullish = tenkan.iloc[-1] > kijun.iloc[-1]

        return {
            "close": round(latest_close, 2),
            "tenkan": round(tenkan.iloc[-1], 2),
            "kijun": round(kijun.iloc[-1], 2),
            "senkou_a": round(senkou_a.iloc[-1], 2),
            "senkou_b": round(senkou_b.iloc[-1], 2),
            "cloud_top": round(cloud_top.iloc[-1], 2),
            "cloud_bottom": round(cloud_bottom.iloc[-1], 2),
            "above_cloud": above_cloud,
            "inside_cloud": inside_cloud,
            "tk_bullish": tk_bullish,
        }

    def check(self, computed: dict, params: dict) -> dict:
        above = computed["above_cloud"]
        inside = computed["inside_cloud"]

        if above:
            status = "PASS"
        elif inside:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"Close={computed['close']} vs Cloud=[{computed['cloud_bottom']}, {computed['cloud_top']}]",
            "threshold": "Above Ichimoku Cloud",
            "details": f"Tenkan={computed['tenkan']}, Kijun={computed['kijun']}, TK Bullish={computed['tk_bullish']}",
        }
