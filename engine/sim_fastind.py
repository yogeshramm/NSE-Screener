"""Fast, bit-identical replacements for the two indicators that dominate the sim.

Profiling one screening day (194 symbols, 2,649 bars) showed 282 s total, of
which Supertrend was 204.7 s and OBV 72.5 s — 98% of the run. Neither is
expensive arithmetic; both walk the series with pandas .iloc scalar access,
which cost 8.5M __getitem__ and 2.2M __setitem__ calls for that single day.

The algorithms are unchanged here. Supertrend keeps its sequential recursion
but runs it over numpy scalars; OBV's loop is a signed cumulative sum and is
expressed as one. Both must reproduce the original output EXACTLY — they are
validated against it in deploy/verify_fastind.py before any sim uses them.

Applied only by the sim (engine/sim_patches.apply_all); indicators/*.py are
never modified, so the live site keeps running the original code.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_applied = False


def _fast_supertrend(self, df: pd.DataFrame, params: dict) -> dict:
    period = params["supertrend_period"]
    multiplier = params["supertrend_multiplier"]

    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    n = len(close)

    hl2 = (high + low) / 2.0
    prev_close = np.empty(n, dtype=float)
    prev_close[0] = np.nan
    prev_close[1:] = close[:-1]
    # pandas .max(axis=1) skips NaN; np.fmax does the same (np.maximum does not)
    tr = np.fmax(np.fmax(high - low, np.abs(high - prev_close)),
                 np.abs(low - prev_close))
    atr = pd.Series(tr, index=df.index).ewm(
        alpha=1.0 / period, min_periods=period).mean().to_numpy(dtype=float)

    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr
    upper = upper_basic.copy()
    lower = lower_basic.copy()
    st = np.full(n, np.nan)
    direction = np.full(n, np.nan)

    for i in range(period, n):
        if upper_basic[i] < upper[i - 1] or close[i - 1] > upper[i - 1]:
            upper[i] = upper_basic[i]
        else:
            upper[i] = upper[i - 1]
        if lower_basic[i] > lower[i - 1] or close[i - 1] < lower[i - 1]:
            lower[i] = lower_basic[i]
        else:
            lower[i] = lower[i - 1]

        if i == period:
            direction[i] = 1
            st[i] = lower[i]
        elif st[i - 1] == upper[i - 1]:
            if close[i] > upper[i]:
                direction[i] = 1
                st[i] = lower[i]
            else:
                direction[i] = -1
                st[i] = upper[i]
        else:
            if close[i] < lower[i]:
                direction[i] = -1
                st[i] = upper[i]
            else:
                direction[i] = 1
                st[i] = lower[i]

    latest_close = close[-1]
    latest_st = st[-1]
    above = latest_close > latest_st if not pd.isna(latest_st) else False
    return {
        "supertrend": round(latest_st, 2) if not pd.isna(latest_st) else None,
        "close": round(latest_close, 2),
        "above_supertrend": above,
        "direction": int(direction[-1]) if not pd.isna(direction[-1]) else 0,
    }


def _fast_obv(self, df: pd.DataFrame, params: dict) -> dict:
    lookback = params["obv_lookback"]
    close = df["Close"].to_numpy(dtype=float)
    volume = df["Volume"].to_numpy(dtype=float)

    step = np.zeros(len(close), dtype=float)
    if len(close) > 1:
        d = close[1:] - close[:-1]
        step[1:] = np.where(d > 0, volume[1:], np.where(d < 0, -volume[1:], 0.0))
    obv = np.cumsum(step)

    recent = obv[-lookback:]
    x = np.arange(len(recent))
    slope = np.polyfit(x, recent, 1)[0]
    return {
        "obv_latest": int(obv[-1]),
        "obv_slope": round(slope, 2),
        "obv_rising": slope > 0,
    }


def apply():
    """Swap in the fast implementations. Idempotent."""
    global _applied
    if _applied:
        return
    from indicators.supertrend import SupertrendIndicator as _ST
    from indicators.obv import OBVIndicator as _OBV
    _ST.compute = _fast_supertrend
    _OBV.compute = _fast_obv
    _applied = True
