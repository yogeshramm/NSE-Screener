"""
Neo Radar — multi-indicator inflection detector for Stage 2.

Two windows from the same scoring logic:
  STRICT  (lookback = 3) — today + 2 prior bars. The "exact moment" view.
                            Preferably the indicators all synced on today
                            itself; the 3-bar window allows for the typical
                            1-2 bar spread between oscillator turns.
  FLEX    (lookback = 5) — today + 4 prior bars. The "still recent" view.
                            Catches stocks where the sync happened earlier
                            in the past week and is still actionable.

A stock's Stage 2 row carries both `neo` (strict) and `neo_flex` (flex).
Frontend renders two sub-sections — Inflection (strict tier) on top,
Extended (flex-only tier) below — so the result list is always
moment-anchored to today, never to old setups.

5 conditions (Supertrend is the anchor):
  1. MACD       histogram crossed red→green within last LOOKBACK bars
                AND line still below MACD_LINE_MAX.
  2. AO         crossed zero within last LOOKBACK bars  OR  slim-red rising.
  3. RSI        currently in [RSI_MIN, RSI_MAX].
  4. Vortex     VI+ crossed above VI- within last LOOKBACK bars.
  5. Supertrend direction flipped -1 → +1 within last LOOKBACK bars.

Tier classification (per profile):
  perfect — 5/5
  strong  — 4/5 with MACD/AO/Vortex missing
  watch   — 4/5 with RSI missing
  below   — anything else (or Supertrend anchor missing)
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ── tunable constants ─────────────────────────────────────────────────────
STRICT_LOOKBACK  = 3       # today + 2 prior — "exact moment"
FLEX_LOOKBACK    = 5       # today + 4 prior — "still recent within a week"
RSI_MIN          = 45
RSI_MAX          = 65
AO_SLIM_RATIO    = 0.40
MACD_LINE_MAX    = 5.0
NEO_MIN_SCORE    = 4
# Back-compat constant — pre-existing callers that imported LOOKBACK keep working
LOOKBACK         = STRICT_LOOKBACK


# ── series computers (self-contained — no reliance on registry output) ────

def _ao_series(h: pd.Series, l: pd.Series) -> pd.Series:
    """Bill Williams Awesome Oscillator: SMA5 − SMA34 of median price."""
    median = (h + l) / 2
    return median.rolling(5).mean() - median.rolling(34).mean()


def _vortex_series(h: pd.Series, l: pd.Series, c: pd.Series, period: int = 14):
    """Standard Vortex (VI+ and VI-, 14-period)."""
    h_prev = h.shift(1); l_prev = l.shift(1); c_prev = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
    vm_p = (h - l_prev).abs()
    vm_m = (l - h_prev).abs()
    tr_n = tr.rolling(period).sum()
    return vm_p.rolling(period).sum() / tr_n, vm_m.rolling(period).sum() / tr_n


def _supertrend_dir(h: pd.Series, l: pd.Series, c: pd.Series,
                    period: int = 7, mult: float = 3.0) -> pd.Series:
    # period/mult MUST match indicators/supertrend.py's default_params so that
    # what Neo Radar reports aligns with what the chart Supertrend overlay shows.
    """Return supertrend direction series (+1 bullish, -1 bearish)."""
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
    were ≤ threshold. The cross event must have happened on one of the last
    `lookback` bars inclusive (today, yesterday, …). To detect a cross
    landing on bar -k, we need bar -(k+1) to have been below threshold,
    so we look at `lookback` prior bars (positions -[lookback+1] .. -2)."""
    if s is None or len(s) < lookback + 1:
        return False
    vals = s.values
    if math.isnan(vals[-1]) or vals[-1] <= threshold:
        return False
    prior = vals[-(lookback + 1):-1]
    return any(not math.isnan(v) and v <= threshold for v in prior)


# ── 5 condition checks (parametrised on lookback) ─────────────────────────

def _c_macd(ind: Optional[dict], lookback: int) -> Tuple[bool, str]:
    label = "MACD"
    if not ind:
        return False, label
    c = ind.get("computed", {})
    hist_s = c.get("histogram_series")
    macd_s = c.get("macd_series")
    if hist_s is None or macd_s is None:
        return False, label
    if not _series_recently_crossed_up(hist_s, 0.0, lookback):
        return False, label
    if macd_s.values[-1] >= MACD_LINE_MAX:
        return False, label
    return True, label


def _c_ao(daily_df: Optional[pd.DataFrame], lookback: int) -> Tuple[bool, str]:
    label = "AO"
    if daily_df is None or len(daily_df) < 35:
        return False, label
    ao = _ao_series(daily_df["High"], daily_df["Low"])
    if _series_recently_crossed_up(ao, 0.0, lookback):
        return True, label
    vals = ao.values
    if len(vals) >= 2 and not math.isnan(vals[-1]) and not math.isnan(vals[-2]):
        curr, prev = vals[-1], vals[-2]
        if curr < 0 and prev < 0 and curr > prev:
            if abs(curr) / max(abs(prev), 1e-9) <= AO_SLIM_RATIO:
                return True, label
    return False, label


def _c_rsi(ind: Optional[dict]) -> Tuple[bool, str]:
    """RSI currently in [RSI_MIN, RSI_MAX] — band itself is the decay gate."""
    label = "RSI"
    if not ind:
        return False, label
    rsi = ind.get("computed", {}).get("rsi")
    if rsi is None:
        return False, label
    return RSI_MIN <= float(rsi) <= RSI_MAX, label


def _c_vortex(daily_df: Optional[pd.DataFrame], lookback: int) -> Tuple[bool, str]:
    """VI+ crossed above VI- within last `lookback` bars (inclusive of today).
       Currently bullish AND any of `lookback` prior bars had VI+ ≤ VI-.
       A cross on bar -k requires bar -(k+1) to have been bearish, so we
       check `lookback` prior bars: positions -[lookback+1] .. -2."""
    label = "Vortex"
    if daily_df is None or len(daily_df) < 20:
        return False, label
    vi_p, vi_m = _vortex_series(daily_df["High"], daily_df["Low"], daily_df["Close"])
    if len(vi_p) < lookback + 1:
        return False, label
    p = vi_p.values; m = vi_m.values
    if math.isnan(p[-1]) or math.isnan(m[-1]) or p[-1] <= m[-1]:
        return False, label
    for i in range(-(lookback + 1), -1):
        if not math.isnan(p[i]) and not math.isnan(m[i]) and p[i] <= m[i]:
            return True, label
    return False, label


def _c_supertrend(daily_df: Optional[pd.DataFrame], lookback: int) -> Tuple[bool, str]:
    """ANCHOR: Supertrend direction flipped -1 → +1 within last `lookback` bars
       (inclusive of today). A flip on bar -k requires bar -(k+1) to have been
       bearish, so we check `lookback` prior bars: positions -[lookback+1] .. -2."""
    label = "Supertrend"
    if daily_df is None or len(daily_df) < 20:
        return False, label
    dir_ = _supertrend_dir(daily_df["High"], daily_df["Low"], daily_df["Close"])
    if len(dir_) < lookback + 1:
        return False, label
    vals = dir_.values
    if vals[-1] != 1:
        return False, label
    for i in range(-(lookback + 1), -1):
        if vals[i] == -1:
            return True, label
    return False, label


# ── scoring core ──────────────────────────────────────────────────────────

def _score_one(indicator_results: list, daily_df: Optional[pd.DataFrame],
               lookback: int, profile_name: str) -> Dict:
    """Run the 5-condition scoring with the given lookback window."""
    checks: List[Tuple[bool, str]] = [
        _c_macd(_find(indicator_results, "MACD"), lookback),
        _c_ao(daily_df, lookback),
        _c_rsi(_find(indicator_results, "RSI")),
        _c_vortex(daily_df, lookback),
        _c_supertrend(daily_df, lookback),
    ]
    score   = sum(1 for ok, _ in checks if ok)
    missing = [lbl for ok, lbl in checks if not ok]
    conditions = {
        "macd":       bool(checks[0][0]),
        "ao":         bool(checks[1][0]),
        "rsi":        bool(checks[2][0]),
        "vortex":     bool(checks[3][0]),
        "supertrend": bool(checks[4][0]),
    }
    if not conditions["supertrend"]:
        tier = "below"
    elif score >= 5:
        tier = "perfect"
    elif score >= NEO_MIN_SCORE:
        tier = "watch" if "RSI" in missing else "strong"
    else:
        tier = "below"
    return {
        "score":      score,
        "label":      f"{score}/5",
        "is_neo":     tier in ("perfect", "strong", "watch"),
        "tier":       tier,
        "profile":    profile_name,
        "lookback":   lookback,
        "conditions": conditions,
        "missing":    missing,
    }


# ── main public function ──────────────────────────────────────────────────

def neo_score(indicator_results: list,
              daily_df: Optional[pd.DataFrame] = None,
              lookback: int = STRICT_LOOKBACK) -> Dict:
    """Default neo_score keeps backward-compat: single-profile result with
    the STRICT lookback. For Neo Radar's dual-window output, callers should
    use `neo_radar_score()` which returns both strict and flex tiers."""
    return _score_one(indicator_results, daily_df, lookback, f"strict_lb{lookback}")


def neo_radar_score(indicator_results: list,
                    daily_df: Optional[pd.DataFrame] = None) -> Dict:
    """
    Compute BOTH the strict (lookback=3) and flex (lookback=5) Neo scores
    for a Stage 2 stock.

    Returns:
        {
          "strict": { score, label, is_neo, tier, profile="strict", lookback=3, ... },
          "flex":   { score, label, is_neo, tier, profile="flex",   lookback=5, ... },
          "fresh_count": int  # how many indicators fired specifically on today's bar
        }

    fresh_count is the count of conditions passing with lookback=1 — i.e.
    the cross literally happened on the most recent bar. Used as a
    same-day-priority tiebreaker when sorting within a tier.
    """
    strict = _score_one(indicator_results, daily_df, STRICT_LOOKBACK, "strict")
    flex   = _score_one(indicator_results, daily_df, FLEX_LOOKBACK,   "flex")
    # fresh_count: how many fire when window collapses to today only
    today  = _score_one(indicator_results, daily_df, 1, "today")
    return {
        "strict":      strict,
        "flex":        flex,
        "fresh_count": today["score"],
    }
