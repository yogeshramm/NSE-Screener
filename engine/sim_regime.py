"""Correction 1 — regime gate on the breakout premise.

The Feb-Aug 2026 replay showed every momentum formula losing while the market
rose, and the single strongest predictor in 893 screened candidates was
"% below the 52-week high" (corr +0.207, t=+6.33) — pointing the WRONG way for
a breakout system. Stocks nearest their highs returned -3.65% relative; those
furthest below returned +2.48%.

The honest fix is not to invert the signals (that would fit one regime). It is
to MEASURE, each day, whether the breakout premise is currently being paid, and
stand the breakout formulas down when it is not.

The gate is computed only from bars at or before the as-of date, so it is
usable live and honest in replay.

Construction matters here. Ranking today's near-high names by their trailing
return is a tautology — a stock is near its high BECAUSE it just ran. So the
cohorts are formed in the PAST and scored forward to today:

    at day D-L : split the universe by proximity to the 52W high AS OF D-L
    D-L -> D   : measure what each cohort actually returned since

    spread = return of the "was near its high" cohort
           - return of the "was far below" cohort

Positive  → buying strength was being paid → breakout formulas ON
Negative  → laggards led                   → breakout formulas STAND DOWN

Every bar used is at or before D, so this is honest in replay and computable
live.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

NEAR_PCT = 5.0       # "near the high" = within this % of the 52-week high
FAR_PCT = 20.0       # "far below"     = more than this % below it
LOOKBACK = 42        # trailing window (~2 months) used to score who is leading
MIN_NAMES = 15       # per side, else the reading is not meaningful


def _cohort_stats(df: pd.DataFrame, i: int, lookback: int):
    """Return (proximity to 52W high AS OF i-lookback, return from i-lookback to i)."""
    j = i - lookback
    if j < 60 or i >= len(df):
        return None
    past_close = float(df["Close"].iloc[j])
    if past_close <= 0:
        return None
    hi52_then = float(df["High"].iloc[max(0, j - 252): j + 1].max())
    if hi52_then <= 0:
        return None
    prox_then = (hi52_then - past_close) / hi52_then * 100
    fwd = (float(df["Close"].iloc[i]) - past_close) / past_close * 100
    return prox_then, fwd


def regime_for_day(uni: Dict[str, Dict[str, Any]], day: pd.Timestamp,
                   lookback: int = LOOKBACK) -> Dict[str, Any]:
    """Score the breakout premise as of `day`. Reads no bar later than `day`.

    Cohorts are formed `lookback` bars ago and scored forward to `day`, so this
    measures whether buying strength was actually PAID, not merely who ran.
    """
    near: List[float] = []
    far: List[float] = []
    for sym, u in uni.items():
        i = u["pos"].get(day)
        if i is None:
            continue
        r = _cohort_stats(u["df"], i, lookback)
        if r is None:
            continue
        prox_then, fwd = r
        if prox_then <= NEAR_PCT:
            near.append(fwd)
        elif prox_then >= FAR_PCT:
            far.append(fwd)

    if len(near) < MIN_NAMES or len(far) < MIN_NAMES:
        return {"spread": None, "state": "UNKNOWN", "near_n": len(near),
                "far_n": len(far),
                "detail": f"too few names to judge (near {len(near)}, far {len(far)})"}

    n, f = float(np.mean(near)), float(np.mean(far))
    spread = n - f
    state = "BREAKOUT_PAID" if spread > 0 else "LAGGARDS_LEADING"
    return {
        "spread": round(spread, 2),
        "state": state,
        "near_mean": round(n, 2), "far_mean": round(f, 2),
        "near_n": len(near), "far_n": len(far),
        "detail": (f"stocks that were within {NEAR_PCT:.0f}% of their 52W high "
                   f"{lookback} bars ago have since returned {n:+.2f}% vs {f:+.2f}% "
                   f"for those {FAR_PCT:.0f}%+ below — spread {spread:+.2f}"),
    }


def build_regime_series(uni: Dict[str, Dict[str, Any]], calendar: List[pd.Timestamp],
                        lookback: int = LOOKBACK) -> Dict[pd.Timestamp, Dict[str, Any]]:
    return {d: regime_for_day(uni, d, lookback) for d in calendar}


def gate_allows(regime: Dict[str, Any], mode: str = "off_when_negative",
                min_spread: float = 0.0) -> bool:
    """Should a breakout formula be allowed to open a new position today?

    off_when_negative — trade only while the breakout premise is being paid
    always            — no gate (control arm)
    """
    if mode == "always":
        return True
    sp = regime.get("spread")
    if sp is None:
        return True          # unknown → don't block; the formula's own filters still apply
    return sp > min_spread
