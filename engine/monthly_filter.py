"""
Stage 3: Monthly Timeframe Confirmation Filter.

Checks 4 monthly conditions on daily OHLCV data (resampled internally).
No extra data fetches — uses the same daily pkl already loaded by screener.

Conditions:
  1. Price above rising 10-month SMA (Weinstein Stage 2 core)
  2. Monthly RSI > 50 (bullish momentum regime)
  3. Monthly MACD histogram > 0 (macro momentum positive)
  4. Monthly Supertrend bullish (period=3, mult=2.0)
"""

import numpy as np
import pandas as pd


# ── Indicator helpers (monthly-scale) ────────────────────────────────────────

def _ema(s, span):
    return s.ewm(span=span, adjust=False).mean()


def _rsi(close, period=14):
    d = close.diff()
    g = d.where(d > 0, 0.0).rolling(period, min_periods=period).mean()
    l = (-d.where(d < 0, 0.0)).rolling(period, min_periods=period).mean()
    rs = g / l.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _macd_hist(close, fast=12, slow=26, sig=9):
    macd = _ema(close, fast) - _ema(close, slow)
    return macd - _ema(macd, sig)


def _supertrend(mdf, period=3, mult=2.0):
    h = mdf["High"].astype(float)
    l = mdf["Low"].astype(float)
    c = mdf["Close"].astype(float)
    hl2 = (h + l) / 2
    pc  = c.shift(1)
    tr  = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr

    trend = pd.Series(True, index=c.index)
    for i in range(1, len(c)):
        pu = float(upper.iloc[i - 1]); pl = float(lower.iloc[i - 1])
        cc = float(c.iloc[i]);         pc_ = float(c.iloc[i - 1])
        lower.iloc[i] = float(lower.iloc[i]) if float(lower.iloc[i]) < pl or pc_ < pl else pl
        upper.iloc[i] = float(upper.iloc[i]) if float(upper.iloc[i]) > pu or pc_ > pu else pu
        if   trend.iloc[i - 1] and cc < float(lower.iloc[i]): trend.iloc[i] = False
        elif not trend.iloc[i - 1] and cc > float(upper.iloc[i]): trend.iloc[i] = True
        else: trend.iloc[i] = trend.iloc[i - 1]
    return trend


# ── Main filter ──────────────────────────────────────────────────────────────

def check_stage3_monthly(daily_df: pd.DataFrame) -> dict:
    """
    Run Stage 3 monthly confirmation filter.

    Args:
        daily_df: Daily OHLCV DataFrame with DatetimeIndex (already loaded).

    Returns dict:
        passed       : bool — True if all 4 conditions pass
        monthly_bars : int  — number of completed monthly bars available
        conditions   : dict of individual condition results
        passed_count : int  — how many of 4 conditions passed
        reason       : str  — human-readable summary
    """
    NEED_BARS = 300  # ~14 months of daily data minimum

    if daily_df is None or len(daily_df) < NEED_BARS:
        return {
            "passed": False,
            "monthly_bars": 0,
            "conditions": {},
            "passed_count": 0,
            "total_conditions": 4,
            "reason": f"Insufficient history ({len(daily_df) if daily_df is not None else 0} daily bars)",
        }

    try:
        # Resample daily → monthly bars
        mdf = daily_df.resample("ME").agg(
            Open=("Open", "first"),
            High=("High", "max"),
            Low=("Low", "min"),
            Close=("Close", "last"),
            Volume=("Volume", "sum"),
        ).dropna(subset=["Close"])

        if len(mdf) < 14:
            return {
                "passed": False,
                "monthly_bars": len(mdf),
                "conditions": {},
                "passed_count": 0,
                "total_conditions": 4,
                "reason": f"Only {len(mdf)} monthly bars (need 14+)",
            }

        c = mdf["Close"].astype(float)
        conditions = {}

        # ── Condition 1: Price above rising 10-month SMA ─────────────────────
        sma10      = c.rolling(10).mean()
        last_price = float(c.iloc[-1])
        last_sma   = float(sma10.iloc[-1])
        prev_sma   = float(sma10.iloc[-2])
        price_above = last_price > last_sma
        sma_rising  = last_sma > prev_sma
        c1_pass     = price_above and sma_rising
        conditions["sma10_rising"] = {
            "status":  "PASS" if c1_pass else "FAIL",
            "label":   "Price > Rising 10M SMA",
            "value":   f"₹{last_price:.1f} vs SMA ₹{last_sma:.1f}",
            "details": (
                f"SMA rising ({prev_sma:.1f}→{last_sma:.1f})" if sma_rising
                else f"SMA flat/falling ({prev_sma:.1f}→{last_sma:.1f})"
            ),
        }

        # ── Condition 2: Monthly RSI > 50 ────────────────────────────────────
        rsi_m    = _rsi(c)
        last_rsi = round(float(rsi_m.iloc[-1]), 1)
        c2_pass  = last_rsi > 50
        conditions["rsi_above50"] = {
            "status":  "PASS" if c2_pass else "FAIL",
            "label":   "Monthly RSI > 50",
            "value":   f"RSI {last_rsi}",
            "details": "Bullish momentum regime" if c2_pass else "Below midline — bearish bias",
        }

        # ── Condition 3: Monthly MACD histogram > 0 ──────────────────────────
        hist_m    = _macd_hist(c)
        last_hist = float(hist_m.iloc[-1])
        prev_hist = float(hist_m.iloc[-2])
        c3_pass   = last_hist > 0
        expanding = last_hist > prev_hist
        conditions["macd_positive"] = {
            "status":  "PASS" if c3_pass else "FAIL",
            "label":   "Monthly MACD > 0",
            "value":   f"Hist {last_hist:+.3f}",
            "details": (
                f"Expanding ({prev_hist:+.3f}→{last_hist:+.3f})" if expanding
                else f"Fading ({prev_hist:+.3f}→{last_hist:+.3f})"
            ),
        }

        # ── Condition 4: Monthly Supertrend bullish ───────────────────────────
        st_m       = _supertrend(mdf, period=3, mult=2.0)
        st_bull    = bool(st_m.iloc[-1])
        prev_bull  = bool(st_m.iloc[-2])
        fresh_flip = st_bull and not prev_bull
        conditions["supertrend_bullish"] = {
            "status":  "PASS" if st_bull else "FAIL",
            "label":   "Monthly Supertrend",
            "value":   "Bullish" if st_bull else "Bearish",
            "details": (
                "Fresh bullish flip! High conviction." if fresh_flip
                else ("In bullish zone" if st_bull else "Bearish — avoid longs")
            ),
        }

        passed_count = sum(1 for cond in conditions.values() if cond["status"] == "PASS")
        all_pass     = passed_count == 4

        return {
            "passed":           all_pass,
            "monthly_bars":     len(mdf),
            "conditions":       conditions,
            "passed_count":     passed_count,
            "total_conditions": 4,
            "reason":           (
                "All 4 monthly conditions met ✓" if all_pass
                else f"{passed_count}/4 monthly conditions met"
            ),
        }

    except Exception as e:
        return {
            "passed":           False,
            "monthly_bars":     0,
            "conditions":       {},
            "passed_count":     0,
            "total_conditions": 4,
            "reason":           f"Error: {e}",
        }
