"""
Neo Radar v5 — upgraded multi-indicator inflection detector for Stage 2.

Five simultaneous inflection conditions:
  C1 Supertrend:  ST flipped to +1 within last 2 bars AND close within 10% of ST line
  C2 MACD:        Histogram positive + most recent hist neg→pos crossover was while
                  MACD line < 0 (50-bar lookback; or MACD currently ≤ 0 if no
                  crossover found — histogram has been continuously positive)
  C3 AO:          AO crossed zero within last 3 bars, OR slim-red rising (≤40% prior)
  C4 Vortex:      VI+ crossed above VI- within last 2 bars
  C5 RSI:         RSI 48–60

Score ≥ 4/5 → valid signal (Supertrend anchor; ST failing drops to PENDING).
Score = 5/5 → perfect (amber ★).

PENDING (pre-flip watchlist): ST still bearish but C2+C3+C4+C5 all aligned
within 3 bars — imminent flip expected.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ── tunable constants ─────────────────────────────────────────────────────
INFLECTION_LOOKBACK = 2    # ST flip + Vortex cross must be within 2 bars
EXTENDED_LOOKBACK   = 5    # extended window: ST flip + Vortex within 5 bars
PENDING_LOOKBACK    = 3    # non-ST indicators window for PENDING mode
RSI_MIN             = 48
RSI_MAX             = 60
AO_SLIM_RATIO       = 0.40
ST_PROX_MAX         = 0.10  # close within 10% of ST line (tight)
ST_PROX_EXTENDED    = 0.15  # close within 15% of ST line (extended)
MACD_CROSS_LOOKBACK = 50   # bars to look back for hist neg→pos crossover
NEO_MIN_SCORE       = 4
# Back-compat
LOOKBACK         = INFLECTION_LOOKBACK
STRICT_LOOKBACK  = INFLECTION_LOOKBACK
FLEX_LOOKBACK    = INFLECTION_LOOKBACK


# ── series computers ──────────────────────────────────────────────────────

def _ao_series(h: pd.Series, l: pd.Series) -> pd.Series:
    median = (h + l) / 2
    return median.rolling(5).mean() - median.rolling(34).mean()


def _vortex_series(h: pd.Series, l: pd.Series, c: pd.Series, period: int = 14):
    h_prev = h.shift(1); l_prev = l.shift(1); c_prev = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
    vm_p = (h - l_prev).abs()
    vm_m = (l - h_prev).abs()
    tr_n = tr.rolling(period).sum()
    return vm_p.rolling(period).sum() / tr_n, vm_m.rolling(period).sum() / tr_n


def _supertrend_dir_and_val(h: pd.Series, l: pd.Series, c: pd.Series,
                             period: int = 7, mult: float = 3.0):
    """Return (direction_series, value_array).
    direction: +1 bullish / -1 bearish.
    value_array: active ST band (lower band when bullish, upper when bearish)."""
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
    stv  = np.full(n, np.nan)
    atr_vals = atr.values
    for i in range(1, n):
        if math.isnan(atr_vals[i]):
            dir_[i] = dir_[i-1]
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
        stv[i] = fl[i] if dir_[i] == 1 else fu[i]
    return pd.Series(dir_, index=c.index), stv


def _supertrend_dir(h: pd.Series, l: pd.Series, c: pd.Series,
                    period: int = 7, mult: float = 3.0) -> pd.Series:
    dir_, _ = _supertrend_dir_and_val(h, l, c, period, mult)
    return dir_


# ── helpers ───────────────────────────────────────────────────────────────

def _find(indicator_results: list, name: str) -> Optional[dict]:
    return next((r for r in indicator_results if r.get("indicator") == name), None)


def _series_recently_crossed_up(s: pd.Series, threshold: float, lookback: int) -> bool:
    if s is None or len(s) < lookback + 1:
        return False
    vals = s.values
    if math.isnan(vals[-1]) or vals[-1] <= threshold:
        return False
    prior = vals[-(lookback + 1):-1]
    return any(not math.isnan(v) and v <= threshold for v in prior)


# ── per-condition checks ──────────────────────────────────────────────────

def _c_macd(ind: Optional[dict], lookback: int) -> bool:
    """C2: histogram currently positive + most recent neg→pos crossover was
    while MACD line < 0.  If no crossover found in MACD_CROSS_LOOKBACK bars
    (histogram has been continuously positive), accept if MACD line ≤ 0 now."""
    if not ind:
        return False
    c = ind.get("computed", {})
    hist_s = c.get("histogram_series")
    macd_s = c.get("macd_series")
    if hist_s is None or macd_s is None:
        return False
    hist = hist_s.values
    macd = macd_s.values
    n = len(hist)
    if n < 2 or math.isnan(hist[-1]) or hist[-1] <= 0:
        return False
    # Find most recent hist neg→pos crossover within MACD_CROSS_LOOKBACK bars
    for j in range(n - 1, max(n - MACD_CROSS_LOOKBACK - 1, 0), -1):
        if j > 0 and hist[j] > 0 and hist[j-1] <= 0:
            return not math.isnan(macd[j]) and macd[j] < 0
    # No crossover found — valid only if MACD line is currently ≤ 0
    return not math.isnan(macd[-1]) and macd[-1] <= 0


def _c_ao(daily_df: Optional[pd.DataFrame], lookback: int) -> bool:
    if daily_df is None or len(daily_df) < 35:
        return False
    ao = _ao_series(daily_df["High"], daily_df["Low"])
    if _series_recently_crossed_up(ao, 0.0, lookback):
        return True
    vals = ao.values
    for i in range(-1, -3, -1):
        curr, prev = vals[i], vals[i - 1]
        if not math.isnan(curr) and not math.isnan(prev):
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

def _st_currently_bullish_and_flip_age(
    daily_df: Optional[pd.DataFrame],
) -> Tuple[bool, Optional[int], float]:
    """Return (currently_bullish, bars_since_last_flip, st_value_at_last_bar).
    bars_since_flip counts current bar as 1.
    st_value is NaN if bearish or not computable."""
    if daily_df is None or len(daily_df) < 20:
        return False, None, math.nan
    dir_, stv = _supertrend_dir_and_val(
        daily_df["High"], daily_df["Low"], daily_df["Close"]
    )
    vals = dir_.values
    if vals[-1] != 1:
        return False, None, math.nan
    for i in range(len(vals) - 1, -1, -1):
        if vals[i] == -1:
            return True, len(vals) - 1 - i, float(stv[-1])
    return True, None, float(stv[-1])


# ── timing score ─────────────────────────────────────────────────────────

def _timing_score(indicator_results: list,
                  daily_df: Optional[pd.DataFrame],
                  conditions: dict,
                  bars_since_flip: Optional[int]) -> int:
    """0–10 timing score across the 5 conditions that passed.
    2 pts = perfect timing, 1 pt = good timing."""
    t = 0

    # C1: ST flipped today = 2, flipped 1 bar ago = 1
    if conditions.get("supertrend"):
        t += 2 if bars_since_flip == 1 else 1

    # C2: 1st green histogram bar = 2, 2nd–3rd = 1, >3 = 0
    if conditions.get("macd"):
        ind = _find(indicator_results, "MACD")
        if ind:
            hv = ind.get("computed", {}).get("histogram_series")
            if hv is not None:
                h = hv.values; n = len(h)
                if n >= 2 and not math.isnan(h[-1]) and h[-1] > 0:
                    if not math.isnan(h[-2]) and h[-2] <= 0:
                        t += 2
                    elif (n >= 3 and not math.isnan(h[-2]) and h[-2] > 0
                          and not math.isnan(h[-3]) and h[-3] <= 0):
                        t += 1
                    elif (n >= 4 and not math.isnan(h[-2]) and h[-2] > 0
                          and not math.isnan(h[-3]) and h[-3] > 0
                          and not math.isnan(h[-4]) and h[-4] <= 0):
                        t += 1

    # C3: AO crossed zero today = 2, ±2 bars or slim-red = 1
    if conditions.get("ao"):
        if daily_df is not None and len(daily_df) >= 35:
            av = _ao_series(daily_df["High"], daily_df["Low"]).values
            n = len(av)
            if (n >= 2 and not math.isnan(av[-1]) and not math.isnan(av[-2])
                    and av[-1] > 0 and av[-2] <= 0):
                t += 2
            else:
                t += 1

    # C4: Vortex crossed today = 2, 1 bar ago = 1
    if conditions.get("vortex"):
        if daily_df is not None and len(daily_df) >= 20:
            vp, vm = _vortex_series(daily_df["High"], daily_df["Low"], daily_df["Close"])
            p = vp.values; m = vm.values; n = len(p)
            if (n >= 2
                    and not math.isnan(p[-2]) and not math.isnan(m[-2])
                    and p[-2] <= m[-2] and p[-1] > m[-1]):
                t += 2
            else:
                t += 1

    # C5: RSI 50–56 = 2, 48–50 or 56–60 = 1
    if conditions.get("rsi"):
        ind = _find(indicator_results, "RSI")
        if ind:
            rsi = ind.get("computed", {}).get("rsi")
            if rsi is not None:
                t += 2 if 50 <= float(rsi) <= 56 else 1

    return t


# ── scoring ───────────────────────────────────────────────────────────────

def _score_inflection(indicator_results: list,
                      daily_df: Optional[pd.DataFrame],
                      _st: tuple = None) -> Dict:
    """Post-flip Inflection (Neo v5):
    C1 ST flip within 2 bars + proximity ≤ 10%
    C2 MACD crossover-while-negative (50-bar lookback)
    C3 AO zero-cross within ±2 bars or slim-red rising within ±2 bars
    C4 Vortex crossover within 2 bars
    C5 RSI 48–60
    Timing score 0–10: ≥9 perfect, 6–8 strong, ≤5 valid (all 5/5); 4/5 → watch"""
    st_bull, bars_since, st_val = _st if _st is not None else _st_currently_bullish_and_flip_age(daily_df)

    # C1: flip recency + proximity
    prox_ok = False
    if st_bull and bars_since is not None and not math.isnan(st_val) and st_val > 0:
        close = float(daily_df["Close"].values[-1])
        prox_ok = (close - st_val) / close <= ST_PROX_MAX
    st_ok = st_bull and bars_since is not None and bars_since <= INFLECTION_LOOKBACK and prox_ok

    lb = INFLECTION_LOOKBACK
    conditions = {
        "supertrend": bool(st_ok),
        "macd":       bool(_c_macd(_find(indicator_results, "MACD"), lb)),
        "ao":         bool(_c_ao(daily_df, 3)),
        "vortex":     bool(_c_vortex(daily_df, lb)),
        "rsi":        bool(_c_rsi(_find(indicator_results, "RSI"))),
    }
    score = sum(1 for v in conditions.values() if v)
    missing = [k.upper() for k, v in conditions.items() if not v]

    timing = _timing_score(indicator_results, daily_df, conditions, bars_since)

    if not conditions["supertrend"] or score < NEO_MIN_SCORE:
        tier = "below"
    elif score >= 5:
        tier = "perfect" if timing >= 9 else ("strong" if timing >= 6 else "valid")
    else:
        tier = "watch"

    return {
        "score":           score,
        "timing":          timing,
        "label":           f"{score}/5",
        "timing_label":    f"{timing}/10",
        "is_neo":          tier in ("perfect", "strong", "valid", "watch"),
        "tier":            tier,
        "profile":         "inflection",
        "conditions":      conditions,
        "missing":         missing,
        "bars_since_flip": bars_since if st_bull else None,
    }


def _score_inflection_extended(indicator_results: list,
                               daily_df: Optional[pd.DataFrame],
                               _st: tuple = None) -> Dict:
    """Extended-window Inflection (Neo Wide):
    Same 5 conditions as tight, proportionally scaled to 5-bar window.
    C1 ST flip within 5 bars + proximity ≤ 15%
    C2 MACD crossover-while-negative (50-bar lookback, unchanged)
    C3 AO zero-cross within ±5 bars or slim-red within ±2 bars
    C4 Vortex crossover within 5 bars
    C5 RSI 48–60 (unchanged)"""
    st_bull, bars_since, st_val = _st if _st is not None else _st_currently_bullish_and_flip_age(daily_df)

    prox_ok = False
    if st_bull and bars_since is not None and not math.isnan(st_val) and st_val > 0:
        close = float(daily_df["Close"].values[-1])
        prox_ok = (close - st_val) / close <= ST_PROX_EXTENDED
    st_ok = st_bull and bars_since is not None and bars_since <= EXTENDED_LOOKBACK and prox_ok

    lb = EXTENDED_LOOKBACK
    conditions = {
        "supertrend": bool(st_ok),
        "macd":       bool(_c_macd(_find(indicator_results, "MACD"), lb)),
        "ao":         bool(_c_ao(daily_df, lb)),
        "vortex":     bool(_c_vortex(daily_df, lb)),
        "rsi":        bool(_c_rsi(_find(indicator_results, "RSI"))),
    }
    score = sum(1 for v in conditions.values() if v)
    missing = [k.upper() for k, v in conditions.items() if not v]

    timing = _timing_score(indicator_results, daily_df, conditions, bars_since)

    if not conditions["supertrend"] or score < NEO_MIN_SCORE:
        tier = "below"
    elif score >= 5:
        tier = "perfect" if timing >= 9 else ("strong" if timing >= 6 else "valid")
    else:
        tier = "watch"

    return {
        "score":           score,
        "timing":          timing,
        "label":           f"{score}/5",
        "timing_label":    f"{timing}/10",
        "is_neo":          tier in ("perfect", "strong", "valid", "watch"),
        "tier":            tier,
        "profile":         "extended",
        "conditions":      conditions,
        "missing":         missing,
        "bars_since_flip": bars_since if st_bull else None,
    }


def _score_pending(indicator_results: list,
                   daily_df: Optional[pd.DataFrame],
                   _st: tuple = None) -> Dict:
    """Pre-flip Pending: ST still bearish but C2+C3+C4+C5 all aligned.
    Watchlist for an imminent flip."""
    st_bull, _, _ = _st if _st is not None else _st_currently_bullish_and_flip_age(daily_df)
    if st_bull:
        return {
            "score": 0, "label": "0/4", "is_pending": False,
            "tier": "below", "profile": "pending", "conditions": {}, "missing": [],
        }

    lb = PENDING_LOOKBACK
    conditions = {
        "macd":   bool(_c_macd(_find(indicator_results, "MACD"), lb)),
        "ao":     bool(_c_ao(daily_df, 3)),
        "rsi":    bool(_c_rsi(_find(indicator_results, "RSI"))),
        "vortex": bool(_c_vortex(daily_df, lb)),
    }
    score = sum(1 for v in conditions.values() if v)
    missing = [k.upper() for k, v in conditions.items() if not v]
    tier = "pending" if score >= 4 else "below"
    return {
        "score": score, "label": f"{score}/4",
        "is_pending": tier == "pending",
        "tier": tier, "profile": "pending",
        "conditions": conditions, "missing": missing,
    }


def _fresh_count(indicator_results: list, daily_df: Optional[pd.DataFrame],
                 _st: tuple = None) -> int:
    _, bars_since, st_val = _st if _st is not None else _st_currently_bullish_and_flip_age(daily_df)
    st_today = bars_since == 1
    return sum(1 for v in [
        _c_macd(_find(indicator_results, "MACD"), 1),
        _c_ao(daily_df, 1),
        _c_rsi(_find(indicator_results, "RSI")),
        _c_vortex(daily_df, 1),
        st_today,
    ] if v)


# ── public API ────────────────────────────────────────────────────────────

def neo_radar_score(indicator_results: list,
                    daily_df: Optional[pd.DataFrame] = None) -> Dict:
    st = _st_currently_bullish_and_flip_age(daily_df)
    infl = _score_inflection(indicator_results, daily_df, _st=st)
    ext  = _score_inflection_extended(indicator_results, daily_df, _st=st)
    pend = _score_pending(indicator_results, daily_df, _st=st)
    return {
        "inflection":          infl,
        "inflection_extended": ext,
        "pending":             pend,
        "bars_since_flip":     infl["bars_since_flip"],
        "fresh_count":         _fresh_count(indicator_results, daily_df, _st=st),
    }


def neo_score(indicator_results: list,
              daily_df: Optional[pd.DataFrame] = None,
              lookback: int = INFLECTION_LOOKBACK) -> Dict:
    """Back-compat shim."""
    return _score_inflection(indicator_results, daily_df)
