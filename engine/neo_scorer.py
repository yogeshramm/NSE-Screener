"""
Neo — Multi-indicator inflection detector for Stage 2.

Catches stocks at the MOMENT 5 momentum indicators simultaneously
flip from bearish/neutral to bullish — the start of a move, not the
confirmation the crowd sees 20–30% later.

Two profiles:
  v1 (strict)  — original tight thresholds. Designed to catch SLOW,
                 gradual inflections. Misses fast/gappy moves (OIL-type).
  v2 (default) — relaxed thresholds tuned to also catch explosive
                 gap-up inflections where conditions cross hard in 1-2
                 bars. v2 is the daily-use reference.

5 conditions (±1 bar fuzzy window, Supertrend is the anchor):
  1. MACD       hist red→green in last 2 bars, line still below MACD_LINE_MAX
  2. AO         just turned green OR slim red (curr/prev ratio ≤ AO_SLIM_RATIO)
  3. RSI        between RSI_MIN and RSI_MAX (fresh momentum, not yet extended)
  4. Vortex     VI+ crossed/touching VI- OR fresh cross within VORTEX_FRESH spread
  5. Supertrend just flipped bullish (price crossed ST line in last LOOKBACK
                bars, OR close within ST_MAX_PCT_ABOVE% above ST line)

Score ≥ 4 (with Supertrend present) → Neo signal.

Tier classification:
  perfect  — 5/5
  strong   — 4/5 with MACD/AO/Vortex missing (peers cross-confirm)
  watch    — 4/5 with RSI missing (sub-optimal but anchored)
  below    — anything else (or Supertrend missing)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd


# ── profile parameters ────────────────────────────────────────────────────
#
# v1 = strict (original Neo). v2 = relaxed (daily-use reference).
# Picked v2 thresholds against the May-13 OIL gap-up case study
# (close +13% above ST line, AO ratio 0.347, MACD line +1.66, Vortex
# spread 0.196, RSI 63.29 — all just outside v1's windows).

NEO_PARAMS_V1: Dict = {
    "LOOKBACK":         2,
    "RSI_MIN":         45,
    "RSI_MAX":         60,
    "AO_SLIM_RATIO":   0.30,
    "VORTEX_TOL":      0.02,
    "VORTEX_FRESH":    0.08,
    "ST_MAX_PCT_ABOVE": 8.0,
    "MACD_LINE_MAX":   0.0,
    "NEO_MIN_SCORE":   4,
}

NEO_PARAMS_V2: Dict = {
    "LOOKBACK":         2,
    "RSI_MIN":         45,
    "RSI_MAX":         65,
    "AO_SLIM_RATIO":   0.40,
    "VORTEX_TOL":      0.02,
    "VORTEX_FRESH":    0.20,
    "ST_MAX_PCT_ABOVE": 15.0,
    "MACD_LINE_MAX":   2.0,
    "NEO_MIN_SCORE":   4,
}

NEO_PROFILES: Dict[str, Dict] = {"v1": NEO_PARAMS_V1, "v2": NEO_PARAMS_V2}

# Backward-compat module constants (default to v1 — pre-existing callers
# that imported these by name keep their original behaviour).
LOOKBACK         = NEO_PARAMS_V1["LOOKBACK"]
RSI_MIN          = NEO_PARAMS_V1["RSI_MIN"]
RSI_MAX          = NEO_PARAMS_V1["RSI_MAX"]
AO_SLIM_RATIO    = NEO_PARAMS_V1["AO_SLIM_RATIO"]
VORTEX_TOL       = NEO_PARAMS_V1["VORTEX_TOL"]
ST_MAX_PCT_ABOVE = NEO_PARAMS_V1["ST_MAX_PCT_ABOVE"]
NEO_MIN_SCORE    = NEO_PARAMS_V1["NEO_MIN_SCORE"]


# ── helpers ───────────────────────────────────────────────────────────────

def _find(indicator_results: list, name: str) -> Optional[dict]:
    """Return the first indicator result dict matching the registry name."""
    return next((r for r in indicator_results if r.get("indicator") == name), None)


# ── 5 condition checks (parameterised) ────────────────────────────────────

def _c_macd(ind: Optional[dict], p: Dict) -> Tuple[bool, str]:
    """
    MACD histogram crossed red→green within last LOOKBACK bars, AND the
    MACD line itself is still below MACD_LINE_MAX (i.e. not yet extended
    far above the zero centre — v1 requires < 0, v2 allows < small positive
    so a same-bar histogram+line crossover still counts).
    """
    label = "MACD"
    if not ind:
        return False, label
    c = ind.get("computed", {})
    lookback = p["LOOKBACK"]; line_max = p["MACD_LINE_MAX"]

    hist_s = c.get("histogram_series")
    macd_s = c.get("macd_series")

    if hist_s is not None and len(hist_s) >= lookback + 1:
        hist = hist_s.values
        macd = macd_s.values if macd_s is not None else None
        if hist[-1] <= 0:
            return False, label
        if not any(v <= 0 for v in hist[-(lookback + 1):-1]):
            return False, label
        if macd is not None and macd[-1] >= line_max:
            return False, label
        return True, label

    # Fallback: scalar flags
    bullish_cross = c.get("bullish_crossover", False)
    imminent      = c.get("imminent_crossover", False)
    macd_val      = c.get("macd", 0) or 0
    hist_val      = c.get("histogram", 0) or 0
    crossed_recently = bullish_cross or (imminent and hist_val > 0)
    below_ceiling = macd_val < line_max
    return crossed_recently and below_ceiling, label


def _c_ao(ind: Optional[dict], p: Dict) -> Tuple[bool, str]:
    """
    AO just turned green (prev ≤ 0, curr > 0), OR is at slimmest red
    (still negative but small and rising toward zero, curr/prev ratio
    ≤ AO_SLIM_RATIO).
    """
    label = "AO"
    if not ind:
        return False, label
    c = ind.get("computed", {})
    slim = p["AO_SLIM_RATIO"]

    curr   = c.get("ao", 0) or 0
    prev   = c.get("ao_prev", 0) or 0
    zero_x = c.get("zero_line_crossover", False)
    rising = c.get("rising", False)

    if zero_x or (curr > 0 and prev <= 0):
        return True, label

    if curr < 0 and rising and prev < 0:
        ratio = abs(curr) / max(abs(prev), 1e-9)
        if ratio <= slim:
            return True, label

    return False, label


def _c_rsi(ind: Optional[dict], p: Dict) -> Tuple[bool, str]:
    """RSI between RSI_MIN and RSI_MAX — momentum just started, not yet extended."""
    label = "RSI"
    if not ind:
        return False, label
    rsi = ind.get("computed", {}).get("rsi")
    if rsi is None:
        return False, label
    return p["RSI_MIN"] <= float(rsi) <= p["RSI_MAX"], label


def _c_vortex(ind: Optional[dict], p: Dict) -> Tuple[bool, str]:
    """
    VI+ just crossed above VI- (bullish_crossover flag is True),
    OR VI+ is within VORTEX_TOL of VI- (converging / touching),
    OR VI+ is already above VI- with spread ≤ VORTEX_FRESH (recent cross).
    """
    label = "Vortex"
    if not ind:
        return False, label
    c = ind.get("computed", {})

    if c.get("bullish_crossover", False):
        return True, label

    vi_plus  = c.get("vi_plus",  0) or 0
    vi_minus = c.get("vi_minus", 0) or 0

    if abs(vi_plus - vi_minus) <= p["VORTEX_TOL"]:
        return True, label

    if c.get("bullish", False):
        spread = c.get("spread", vi_plus - vi_minus)
        if abs(spread) <= p["VORTEX_FRESH"]:
            return True, label

    return False, label


def _c_supertrend(
    ind: Optional[dict],
    daily_df: Optional[pd.DataFrame],
    p: Dict,
) -> Tuple[bool, str]:
    """
    Supertrend just flipped to bullish (ANCHOR condition).

    Detection hierarchy:
      1. Price crossed above the supertrend line within last LOOKBACK bars
         (checked against raw daily_df closes).
      2. Fallback: current direction == 1 AND close is within ST_MAX_PCT_ABOVE%
         above the supertrend value (proxy for a recent flip).
    """
    label = "Supertrend"
    if not ind:
        return False, label
    c = ind.get("computed", {})
    lookback = p["LOOKBACK"]; pct_cap = p["ST_MAX_PCT_ABOVE"]

    curr_dir = c.get("direction", 0)
    if curr_dir != 1:
        return False, label

    st_val = c.get("supertrend")
    close  = c.get("close")

    # Method 1: raw closes vs current ST level
    if st_val and daily_df is not None and len(daily_df) > lookback + 1:
        try:
            col = "Close" if "Close" in daily_df.columns else "close"
            closes = daily_df[col].values
            curr_close = closes[-1]
            prior      = closes[-(lookback + 2):-1]
            if curr_close > st_val and any(pp <= st_val for pp in prior):
                return True, label
        except Exception:
            pass

    # Method 2: proximity proxy — wider window for fast moves under v2
    if st_val and close and close > 0:
        pct_above = (close - st_val) / st_val * 100
        return 0 <= pct_above <= pct_cap, label

    return c.get("above_supertrend", False), label


# ── main public function ──────────────────────────────────────────────────

def neo_score(
    indicator_results: list,
    daily_df: Optional[pd.DataFrame] = None,
    profile: str = "v1",
) -> Dict:
    """
    Compute the Neo signal score for a Stage 2 stock.

    Args:
        indicator_results : list of indicator result dicts from Stage 1
        daily_df          : full daily OHLCV DataFrame (used for ST flip detection)
        profile           : "v1" (strict) or "v2" (relaxed, daily-use reference)

    Returns dict:
        {
            "score"     : int,         # 0–5
            "label"     : "5/5",       # display string
            "is_neo"    : bool,        # True when tier in (perfect, strong, watch)
            "tier"      : str,         # perfect | strong | watch | below
            "profile"   : str,         # "v1" | "v2"
            "conditions": {...},       # per-condition pass/fail
            "missing"   : [str],       # names of failed conditions
        }
    """
    p = NEO_PROFILES.get(profile, NEO_PARAMS_V1)
    checks: List[Tuple[bool, str]] = [
        _c_macd(_find(indicator_results, "MACD"), p),
        _c_ao(_find(indicator_results, "Awesome Oscillator"), p),
        _c_rsi(_find(indicator_results, "RSI"), p),
        _c_vortex(_find(indicator_results, "Vortex Indicator"), p),
        _c_supertrend(_find(indicator_results, "Supertrend"), daily_df, p),
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

    # Tier classification — Supertrend is the anchor and must be present.
    # Within 4/5 hits we separate "strong" (MACD/AO/Vortex missing — peers
    # cross-confirm) from "watch" (RSI missing — out of band, sub-optimal).
    if not conditions["supertrend"]:
        tier = "below"
    elif score >= 5:
        tier = "perfect"
    elif score >= p["NEO_MIN_SCORE"]:
        tier = "watch" if "RSI" in missing else "strong"
    else:
        tier = "below"

    return {
        "score":      score,
        "label":      f"{score}/5",
        "is_neo":     tier in ("perfect", "strong", "watch"),
        "tier":       tier,
        "profile":    profile,
        "conditions": conditions,
        "missing":    missing,
    }
