"""
Neo3 — Multi-indicator early-trend detector for Stage 2.

Predecessors v1 (strict inflection-moment) and v2 (OIL-tuned) were both
miscalibrated to one-bar synchronization. In reality the 5 indicators
flip within a 3-7 bar window, not the same bar. Neo3 widens the "just
happened" window to 5 bars and relaxes the magnitude bounds to match
the actual reference set (HINDALCO 4/7, CROMPTON 4/16, USHAMART 4/10,
ASIANPAINT 4/10 — all real "fresh-trend entries" 1-3 weeks into a
Supertrend-confirmed move).

5 conditions (Supertrend is the anchor):
  1. MACD       histogram crossed red→green within last LOOKBACK bars,
                line still below MACD_LINE_MAX (not yet runaway).
  2. AO         positive-and-rising  OR  crossed zero within last LOOKBACK
                bars  OR  slim red rising (curr/prev ratio ≤ AO_SLIM_RATIO).
  3. RSI        between RSI_MIN and RSI_MAX (fresh trend, not yet extended).
  4. Vortex     VI+ crossed/touching VI-  OR  bullish with spread ≤ VORTEX_FRESH.
  5. Supertrend just flipped bullish (price crossed ST line within last
                LOOKBACK bars  OR  close within ST_MAX_PCT_ABOVE% above ST).

Score ≥ 4 (with Supertrend anchor present) → Neo3 signal.

Tier classification:
  perfect  — 5/5
  strong   — 4/5 with MACD/AO/Vortex missing (peers cross-confirm)
  watch    — 4/5 with RSI missing (sub-optimal but anchored)
  below    — anything else (or Supertrend missing)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

# ── tunable constants ─────────────────────────────────────────────────────
# Calibrated to the reference inflection bars: HINDALCO 2026-04-07,
# CROMPTON 2026-04-16, USHAMART 2026-04-10, ASIANPAINT 2026-04-10.
# Each constant is wider than v1/v2 by design — 5-bar window for the
# "just happened" semantics, generous magnitude bounds.
LOOKBACK         = 5       # bar window meaning "just happened" (current + 4 prior bars)
RSI_MIN          = 45
RSI_MAX          = 70
AO_SLIM_RATIO    = 0.40    # AO "slim red" if |ao| ≤ ratio × |ao_prev|
VORTEX_TOL       = 0.02    # VI+ within this distance of VI- = touching / about to cross
VORTEX_FRESH     = 0.30    # spread cap for "fresh cross" detection
ST_MAX_PCT_ABOVE = 18.0    # ST proximity proxy: close within X% above ST line
MACD_LINE_MAX    = 5.0     # MACD line allowed up to this many points above zero
NEO_MIN_SCORE    = 4


# ── helpers ───────────────────────────────────────────────────────────────

def _find(indicator_results: list, name: str) -> Optional[dict]:
    """Return the first indicator result dict matching the registry name."""
    return next((r for r in indicator_results if r.get("indicator") == name), None)


# ── 5 condition checks ────────────────────────────────────────────────────

def _c_macd(ind: Optional[dict]) -> Tuple[bool, str]:
    """MACD histogram crossed red→green within last LOOKBACK bars AND line ≤
    MACD_LINE_MAX (i.e. crossing happened recently AND line hasn't yet run
    away). LOOKBACK=5 lets indicators synchronize over a week-ish window."""
    label = "MACD"
    if not ind:
        return False, label
    c = ind.get("computed", {})

    hist_s = c.get("histogram_series")
    macd_s = c.get("macd_series")

    if hist_s is not None and len(hist_s) >= LOOKBACK + 1:
        hist = hist_s.values
        macd = macd_s.values if macd_s is not None else None
        if hist[-1] <= 0:
            return False, label
        # Any of the last LOOKBACK prior bars was red → recent crossover
        if not any(v <= 0 for v in hist[-(LOOKBACK + 1):-1]):
            return False, label
        if macd is not None and macd[-1] >= MACD_LINE_MAX:
            return False, label
        return True, label

    # Fallback: scalar flags only
    bullish_cross = c.get("bullish_crossover", False)
    imminent      = c.get("imminent_crossover", False)
    macd_val      = c.get("macd", 0) or 0
    hist_val      = c.get("histogram", 0) or 0
    crossed_recently = bullish_cross or (imminent and hist_val > 0)
    below_ceiling = macd_val < MACD_LINE_MAX
    return crossed_recently and below_ceiling, label


def _c_ao(ind: Optional[dict]) -> Tuple[bool, str]:
    """AO bullish — any of:
       - positive AND rising (in trend, not yet exhausted), OR
       - crossed zero within last LOOKBACK bars (just turned green), OR
       - slim red rising (ratio ≤ AO_SLIM_RATIO)."""
    label = "AO"
    if not ind:
        return False, label
    c = ind.get("computed", {})

    curr   = c.get("ao", 0) or 0
    prev   = c.get("ao_prev", 0) or 0
    rising = c.get("rising", False)

    # Positive and rising — handles "AO went green a few bars ago, still expanding"
    if curr > 0 and curr >= prev:
        return True, label

    # Crossed zero within the LOOKBACK window — uses ao_series if available
    ao_s = c.get("ao_series")
    if ao_s is not None and len(ao_s) >= LOOKBACK + 1:
        vals = ao_s.values
        recent = vals[-(LOOKBACK + 1):]
        # Was any prior bar ≤ 0 and the latest bar > 0?
        if recent[-1] > 0 and any(v <= 0 for v in recent[:-1]):
            return True, label

    # Fallback: explicit zero_line_crossover flag (1-bar window)
    if c.get("zero_line_crossover", False):
        return True, label

    # Slim red rising
    if curr < 0 and rising and prev < 0:
        ratio = abs(curr) / max(abs(prev), 1e-9)
        if ratio <= AO_SLIM_RATIO:
            return True, label

    return False, label


def _c_rsi(ind: Optional[dict]) -> Tuple[bool, str]:
    """RSI between RSI_MIN and RSI_MAX — fresh trend, not yet overbought."""
    label = "RSI"
    if not ind:
        return False, label
    rsi = ind.get("computed", {}).get("rsi")
    if rsi is None:
        return False, label
    return RSI_MIN <= float(rsi) <= RSI_MAX, label


def _c_vortex(ind: Optional[dict]) -> Tuple[bool, str]:
    """VI+ crossed above VI-, touching, OR bullish with spread ≤ VORTEX_FRESH."""
    label = "Vortex"
    if not ind:
        return False, label
    c = ind.get("computed", {})

    if c.get("bullish_crossover", False):
        return True, label

    vi_plus  = c.get("vi_plus",  0) or 0
    vi_minus = c.get("vi_minus", 0) or 0

    if abs(vi_plus - vi_minus) <= VORTEX_TOL:
        return True, label

    if c.get("bullish", False):
        spread = c.get("spread", vi_plus - vi_minus)
        if abs(spread) <= VORTEX_FRESH:
            return True, label

    return False, label


def _c_supertrend(
    ind: Optional[dict],
    daily_df: Optional[pd.DataFrame] = None,
) -> Tuple[bool, str]:
    """ANCHOR: Supertrend bullish — flipped within last LOOKBACK bars OR
       close within ST_MAX_PCT_ABOVE% above ST line."""
    label = "Supertrend"
    if not ind:
        return False, label
    c = ind.get("computed", {})

    curr_dir = c.get("direction", 0)
    if curr_dir != 1:
        return False, label

    st_val = c.get("supertrend")
    close  = c.get("close")

    # Method 1: raw closes vs current ST level — recent flip detection
    if st_val and daily_df is not None and len(daily_df) > LOOKBACK + 1:
        try:
            col = "Close" if "Close" in daily_df.columns else "close"
            closes = daily_df[col].values
            curr_close = closes[-1]
            prior      = closes[-(LOOKBACK + 2):-1]
            if curr_close > st_val and any(pp <= st_val for pp in prior):
                return True, label
        except Exception:
            pass

    # Method 2: proximity proxy
    if st_val and close and close > 0:
        pct_above = (close - st_val) / st_val * 100
        return 0 <= pct_above <= ST_MAX_PCT_ABOVE, label

    return c.get("above_supertrend", False), label


# ── main public function ──────────────────────────────────────────────────

def neo_score(
    indicator_results: list,
    daily_df: Optional[pd.DataFrame] = None,
) -> Dict:
    """
    Compute the Neo3 signal score for a Stage 2 stock.

    Returns dict:
        {
            "score"     : int,        # 0–5
            "label"     : "5/5",      # display string
            "is_neo"    : bool,       # True when tier in (perfect, strong, watch)
            "tier"      : str,        # perfect | strong | watch | below
            "profile"   : "neo3",     # name of active profile
            "conditions": {...},      # per-condition pass/fail
            "missing"   : [str],      # names of failed conditions
        }
    """
    checks: List[Tuple[bool, str]] = [
        _c_macd(_find(indicator_results, "MACD")),
        _c_ao(_find(indicator_results, "Awesome Oscillator")),
        _c_rsi(_find(indicator_results, "RSI")),
        _c_vortex(_find(indicator_results, "Vortex Indicator")),
        _c_supertrend(_find(indicator_results, "Supertrend"), daily_df),
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
        "profile":    "neo3",
        "conditions": conditions,
        "missing":    missing,
    }
