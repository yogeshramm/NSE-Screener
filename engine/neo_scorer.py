"""
Neo Radar — multi-indicator inflection detector for Stage 2.

TWO distinct outputs per stock, with Supertrend (period=7, mult=3 —
matching the chart's overlay exactly) as the anchor:

  INFLECTION  ("post-flip" — primary):
    ST has flipped to bullish within the last 4 bars (today + 3 prior).
    All 5 indicator events must land inside that 4-bar window.
    Sorted in the UI by bars-since-flip ascending (today's flip first,
    then yesterday's, then 2 / 3 days ago).

  PENDING     ("pre-flip" — secondary watchlist):
    ST has NOT flipped yet (current direction = -1).
    But MACD + AO + RSI + Vortex have all aligned within the last 3 bars
    (today + 2 prior). Read: "everything's lined up, just waiting for
    Supertrend to confirm tomorrow or the day after."

Indicator parameters match indicators/*.py defaults — the same code that
draws the chart overlay.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ── tunable constants ─────────────────────────────────────────────────────
INFLECTION_LOOKBACK = 4   # today + 3 prior bars — "ST flipped within 3 days"
PENDING_LOOKBACK    = 3   # today + 2 prior bars — "4 of 4 non-ST aligned in last 3 days"
RSI_MIN          = 45
RSI_MAX          = 65
AO_SLIM_RATIO    = 0.40
MACD_LINE_MAX    = 5.0
NEO_MIN_SCORE    = 4
# Back-compat constants
LOOKBACK         = INFLECTION_LOOKBACK
STRICT_LOOKBACK  = INFLECTION_LOOKBACK
FLEX_LOOKBACK    = INFLECTION_LOOKBACK


# ── series computers (self-contained — match indicators/*.py defaults) ────

def _ao_series(h: pd.Series, l: pd.Series) -> pd.Series:
    """Bill Williams AO: SMA5 - SMA34 of median price (matches indicators/awesome_oscillator.py)."""
    median = (h + l) / 2
    return median.rolling(5).mean() - median.rolling(34).mean()


def _vortex_series(h: pd.Series, l: pd.Series, c: pd.Series, period: int = 14):
    """Standard Vortex VI+/VI- (matches indicators/vortex.py)."""
    h_prev = h.shift(1); l_prev = l.shift(1); c_prev = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
    vm_p = (h - l_prev).abs()
    vm_m = (l - h_prev).abs()
    tr_n = tr.rolling(period).sum()
    return vm_p.rolling(period).sum() / tr_n, vm_m.rolling(period).sum() / tr_n


def _supertrend_dir(h: pd.Series, l: pd.Series, c: pd.Series,
                    period: int = 7, mult: float = 3.0) -> pd.Series:
    """Supertrend direction series (+1 / -1). Params match indicators/supertrend.py
    so the scanner agrees with what's drawn on the chart."""
    h_prev = h.shift(1); l_prev = l.shift(1); c_prev = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    hl2 = (h + l) / 2
    upper = (hl2 + mult * atr).values
    lower = (hl2 - mult * atr).values
    cv = c.values
    n = len(c)
    fu = np.copy(upper); fl = np.copy(lower)
    dir_ = np.ones(n, dtype=int)
    for i in range(1, n):
        if math.isnan(atr.iloc[i]):
            dir_[i] = dir_[i-1] if i else 1
            continue
        if not math.isnan(fu[i-1]):
            fu[i] = min(upper[i], fu[i-1]) if cv[i-1] <= fu[i-1] else upper[i]
        if not math.isnan(fl[i-1]):
            fl[i] = max(lower[i], fl[i-1]) if cv[i-1] >= fl[i-1] else lower[i]
        prev = dir_[i-1]
        if prev == 1 and cv[i] < fl[i]:
            dir_[i] = -1
        elif prev == -1 and cv[i] > fu[i]:
            dir_[i] = 1
        else:
            dir_[i] = prev
    return pd.Series(dir_, index=c.index)


# ── helpers ───────────────────────────────────────────────────────────────

def _find(indicator_results: list, name: str) -> Optional[dict]:
    return next((r for r in indicator_results if r.get("indicator") == name), None)


def _series_recently_crossed_up(s: pd.Series, threshold: float, lookback: int) -> bool:
    """True iff series[-1] > threshold AND any of the `lookback` prior bars
    were ≤ threshold (cross happened within the last `lookback` bars inclusive)."""
    if s is None or len(s) < lookback + 1:
        return False
    vals = s.values
    if math.isnan(vals[-1]) or vals[-1] <= threshold:
        return False
    prior = vals[-(lookback + 1):-1]
    return any(not math.isnan(v) and v <= threshold for v in prior)


# ── per-condition checks (parametrised on lookback) ───────────────────────

def _c_macd(ind: Optional[dict], lookback: int) -> bool:
    if not ind:
        return False
    c = ind.get("computed", {})
    hist_s = c.get("histogram_series")
    macd_s = c.get("macd_series")
    if hist_s is None or macd_s is None:
        return False
    if not _series_recently_crossed_up(hist_s, 0.0, lookback):
        return False
    if macd_s.values[-1] >= MACD_LINE_MAX:
        return False
    return True


def _c_ao(daily_df: Optional[pd.DataFrame], lookback: int) -> bool:
    if daily_df is None or len(daily_df) < 35:
        return False
    ao = _ao_series(daily_df["High"], daily_df["Low"])
    if _series_recently_crossed_up(ao, 0.0, lookback):
        return True
    # slim-red rising fallback
    vals = ao.values
    if len(vals) >= 2 and not math.isnan(vals[-1]) and not math.isnan(vals[-2]):
        curr, prev = vals[-1], vals[-2]
        if curr < 0 and prev < 0 and curr > prev:
            if abs(curr) / max(abs(prev), 1e-9) <= AO_SLIM_RATIO:
                return True
    return False


def _c_rsi(ind: Optional[dict]) -> bool:
    if not ind:
        return False
    rsi = ind.get("computed", {}).get("rsi")
    if rsi is None:
        return False
    return RSI_MIN <= float(rsi) <= RSI_MAX


def _c_vortex(daily_df: Optional[pd.DataFrame], lookback: int) -> bool:
    if daily_df is None or len(daily_df) < 20:
        return False
    vi_p, vi_m = _vortex_series(daily_df["High"], daily_df["Low"], daily_df["Close"])
    if len(vi_p) < lookback + 1:
        return False
    p = vi_p.values; m = vi_m.values
    if math.isnan(p[-1]) or math.isnan(m[-1]) or p[-1] <= m[-1]:
        return False
    for i in range(-(lookback + 1), -1):
        if not math.isnan(p[i]) and not math.isnan(m[i]) and p[i] <= m[i]:
            return True
    return False


# ── supertrend helpers ────────────────────────────────────────────────────

def _st_currently_bullish_and_flip_age(daily_df: Optional[pd.DataFrame]) -> Tuple[bool, Optional[int]]:
    """Return (currently_bullish, bars_since_last_flip).
    bars_since_last_flip counts current bar as 1 (flip on most recent bar = 1).
    If currently bearish, returns (False, None)."""
    if daily_df is None or len(daily_df) < 20:
        return False, None
    dir_ = _supertrend_dir(daily_df["High"], daily_df["Low"], daily_df["Close"])
    vals = dir_.values
    if vals[-1] != 1:
        return False, None
    # find most recent bar where dir was -1 (the bar BEFORE the flip)
    for i in range(len(vals) - 1, -1, -1):
        if vals[i] == -1:
            # flip happened at i+1; bars from i+1 to last (= len-1) = len - (i+1) bars
            return True, len(vals) - 1 - i   # i+1 → len-1 inclusive distance
    return True, None   # entirely bullish history — degenerate


# ── scoring ───────────────────────────────────────────────────────────────

def _score_inflection(indicator_results: list,
                      daily_df: Optional[pd.DataFrame]) -> Dict:
    """Post-flip Inflection: ST currently +1 AND flipped within INFLECTION_LOOKBACK
    bars, with the other 4 indicators also firing in the same window."""
    st_bull, bars_since = _st_currently_bullish_and_flip_age(daily_df)
    # ST has to be bullish + flip within 0..(INFLECTION_LOOKBACK-1) bars-since
    # (bars_since=1 means flip happened on today's bar)
    st_ok = st_bull and bars_since is not None and bars_since <= INFLECTION_LOOKBACK

    lb = INFLECTION_LOOKBACK
    conditions = {
        "macd":       bool(_c_macd(_find(indicator_results, "MACD"), lb)),
        "ao":         bool(_c_ao(daily_df, lb)),
        "rsi":        bool(_c_rsi(_find(indicator_results, "RSI"))),
        "vortex":     bool(_c_vortex(daily_df, lb)),
        "supertrend": bool(st_ok),
    }
    score = sum(1 for v in conditions.values() if v)
    missing = [k.upper() for k, v in conditions.items() if not v]
    if not conditions["supertrend"]:
        tier = "below"
    elif score >= 5:
        tier = "perfect"
    elif score >= NEO_MIN_SCORE:
        tier = "watch" if "RSI" in missing else "strong"
    else:
        tier = "below"
    return {
        "score":            score,
        "label":            f"{score}/5",
        "is_neo":           tier in ("perfect", "strong", "watch"),
        "tier":             tier,
        "profile":          "inflection",
        "conditions":       conditions,
        "missing":          missing,
        "bars_since_flip":  bars_since if st_bull else None,
    }


def _score_pending(indicator_results: list,
                   daily_df: Optional[pd.DataFrame]) -> Dict:
    """Pre-flip Pending: ST currently -1 (NOT yet flipped) but the other 4
    indicators (MACD, AO, RSI, Vortex) have all aligned within the last
    PENDING_LOOKBACK bars. Watchlist for an imminent flip."""
    st_bull, _ = _st_currently_bullish_and_flip_age(daily_df)
    if st_bull:
        # Pending only applies when ST is still bearish
        return {
            "score":      0,
            "label":      "0/4",
            "is_pending": False,
            "tier":       "below",
            "profile":    "pending",
            "conditions": {},
            "missing":    [],
        }

    lb = PENDING_LOOKBACK
    conditions = {
        "macd":   bool(_c_macd(_find(indicator_results, "MACD"), lb)),
        "ao":     bool(_c_ao(daily_df, lb)),
        "rsi":    bool(_c_rsi(_find(indicator_results, "RSI"))),
        "vortex": bool(_c_vortex(daily_df, lb)),
    }
    score = sum(1 for v in conditions.values() if v)
    missing = [k.upper() for k, v in conditions.items() if not v]
    tier = "pending" if score >= 4 else "below"
    return {
        "score":      score,
        "label":      f"{score}/4",
        "is_pending": tier == "pending",
        "tier":       tier,
        "profile":    "pending",
        "conditions": conditions,
        "missing":    missing,
    }


def _fresh_count(indicator_results: list, daily_df: Optional[pd.DataFrame]) -> int:
    """How many of the 5 conditions fired specifically on TODAY (lookback=1)."""
    return sum(1 for v in [
        _c_macd(_find(indicator_results, "MACD"), 1),
        _c_ao(daily_df, 1),
        _c_rsi(_find(indicator_results, "RSI")),
        _c_vortex(daily_df, 1),
        _st_currently_bullish_and_flip_age(daily_df)[1] == 1,   # ST flipped today
    ] if v)


# ── public API ────────────────────────────────────────────────────────────

def neo_radar_score(indicator_results: list,
                    daily_df: Optional[pd.DataFrame] = None) -> Dict:
    """
    Returns:
      {
        "inflection":     { score, tier, is_neo, conditions, missing,
                            bars_since_flip, ... },
        "pending":        { score, tier, is_pending, conditions, missing, ... },
        "bars_since_flip": int | None,
        "fresh_count":    int (0–5),
      }
    """
    infl = _score_inflection(indicator_results, daily_df)
    pend = _score_pending(indicator_results, daily_df)
    return {
        "inflection":      infl,
        "pending":         pend,
        "bars_since_flip": infl["bars_since_flip"],
        "fresh_count":     _fresh_count(indicator_results, daily_df),
    }


def neo_score(indicator_results: list,
              daily_df: Optional[pd.DataFrame] = None,
              lookback: int = INFLECTION_LOOKBACK) -> Dict:
    """Back-compat shim — returns the inflection score in the legacy shape."""
    return _score_inflection(indicator_results, daily_df)
