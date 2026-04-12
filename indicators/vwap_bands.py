"""VWAP Bands — Price must be within N sigma bands of VWAP."""

import pandas as pd
import numpy as np
from indicators.base import BaseIndicator


class VWAPBandsIndicator(BaseIndicator):
    name = "VWAP Bands"
    indicator_type = "breakout"
    description = "Price within sigma bands of VWAP (not extended)"
    precision_tier = "most_precise"
    highlighted = True

    @property
    def default_params(self) -> dict:
        return {"vwap_sigma": 1.0, "vwap_period": 20}

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        period = params["vwap_period"]

        # Rolling VWAP over the period
        typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_tp_vol = (typical_price * df["Volume"]).rolling(window=period).sum()
        cum_vol = df["Volume"].rolling(window=period).sum()
        vwap = cum_tp_vol / cum_vol

        # Standard deviation of typical price from VWAP
        vwap_diff_sq = ((typical_price - vwap) ** 2).rolling(window=period).mean()
        vwap_std = np.sqrt(vwap_diff_sq)

        sigma = params["vwap_sigma"]
        upper = vwap + sigma * vwap_std
        lower = vwap - sigma * vwap_std

        latest_close = df["Close"].iloc[-1]
        latest_vwap = vwap.iloc[-1]
        within_bands = lower.iloc[-1] <= latest_close <= upper.iloc[-1]

        # How many sigmas from VWAP
        sigmas_from_vwap = (latest_close - latest_vwap) / vwap_std.iloc[-1] if vwap_std.iloc[-1] != 0 else 0

        return {
            "vwap": round(latest_vwap, 2),
            "upper_band": round(upper.iloc[-1], 2),
            "lower_band": round(lower.iloc[-1], 2),
            "close": round(latest_close, 2),
            "within_bands": within_bands,
            "sigmas_from_vwap": round(sigmas_from_vwap, 2),
        }

    def check(self, computed: dict, params: dict) -> dict:
        within = computed["within_bands"]
        sigmas = computed["sigmas_from_vwap"]

        if within:
            status = "PASS"
        elif abs(sigmas) < params["vwap_sigma"] * 1.2:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"{sigmas}σ from VWAP",
            "threshold": f"Within ±{params['vwap_sigma']}σ",
            "details": f"Close={computed['close']}, VWAP={computed['vwap']}, Band=[{computed['lower_band']}, {computed['upper_band']}]",
        }
