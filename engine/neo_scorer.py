"""
Neo v1 — Multi-indicator inflection detector for Stage 2.

Catches stocks at the MOMENT 5 momentum indicators simultaneously
flip from bearish/neutral to bullish — the very start of a move,
not the confirmation the crowd sees 20–30% later.

5 conditions (±1 bar fuzzy window, Supertrend is the anchor):
  1. MACD        — histogram red→green in last 2 bars, MACD line still < 0
  2. AO          — just turned green OR at slimmest red (rising toward 0)
  3. RSI         — 45 ≤ RSI ≤ 60  (fresh momentum, not yet extended)
  4. Vortex      — VI+ just crossed above VI- OR within VORTEX_TOL tolerance
  5. Supertrend  — just flipped to bullish (close crossed above ST line recently)

Score 5/5 → Perfect Neo entry  (★★★)
Score 4/5 → Valid Neo entry    (missing condition logged)
Score ≤ 3 → No Neo signal

Rules per user-defined formula (Neo v1):
- Any 4/5 is acceptable; 5/5 is ideal
- Missing condition name is always surfaced so the UI can display it
- Conditions are designed to be extensible — add more in future iterations
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

# ── tunable constants ─────────────────────────────────────────────────────
LOOKBACK         = 2     # bar window meaning "just happened" (current + 1 prior bar)
RSI_MIN          = 45
RSI_MAX          = 60
AO_SLIM_RATIO    = 0.30  # AO counts as "slim red" when |ao| < ratio × |ao_prev|
VORTEX_TOL       = 0.02  # VI+ within this distance of VI- = "touching / about to cross"
ST_MAX_PCT_ABOVE = 8.0   # ST proxy: close must be within 8% above supertrend line
NEO_MIN_SCORE    = 4     # minimum conditions needed to be flagged as a Neo signal


# ── helpers ───────────────────────────────────────────────────────────────

def _find(indicator_results: list, name: str) -> Optional[dict]:
    """Return the first indicator result dict matching the registry name."""
    return next((r for r in indicator_results if r.get("indicator") == name), None)


# ── 5 condition checks ────────────────────────────────────────────────────

def _c_macd(ind: Optional[dict]) -> Tuple[bool, str]:
    """
    MACD histogram crossed red→green within last LOOKBACK bars,
    AND the MACD line itself is still below zero (not extended).
    """
    label = "MACD"
    if not ind:
        return False, label
    c = ind.get("computed", {})

    hist_s = c.get("histogram_series")
    macd_s = c.get("macd_series")

    if hist_s is not None and len(hist_s) >= LOOKBACK + 1:
        hist = hist_s.values
        macd = macd_s.values if macd_s is not None else None
        # Current bar must be green (positive)
        if hist[-1] <= 0:
            return False, label
        # At least one prior bar in window was red (negative)
        if not any(v <= 0 for v in hist[-(LOOKBACK + 1):-1]):
            return False, label
        # MACD line still below zero — not extended above centre
        if macd is not None and macd[-1] >= 0:
            return False, label
        return True, label

    # Fallback: use pre-computed scalar flags
    bullish_cross = c.get("bullish_crossover", False)
    imminent      = c.get("imminent_crossover", False)
    macd_val      = c.get("macd", 0) or 0
    hist_val      = c.get("histogram", 0) or 0
    crossed_recently = bullish_cross or (imminent and hist_val > 0)
    below_centre  = macd_val < 0
    return crossed_recently and below_centre, label


def _c_ao(ind: Optional[dict]) -> Tuple[bool, str]:
    """
    AO just turned green (prev ≤ 0, curr > 0), OR is at slimmest red
    (still negative but small and rising toward zero).
    """
    label = "AO"
    if not ind:
        return False, label
    c = ind.get("computed", {})

    curr      = c.get("ao", 0) or 0
    prev      = c.get("ao_prev", 0) or 0
    zero_x    = c.get("zero_line_crossover", False)
    rising    = c.get("rising", False)

    # Just turned green
    if zero_x or (curr > 0 and prev <= 0):
        return True, label

    # Slimmest red: negative but small and moving toward zero
    if curr < 0 and rising and prev < 0:
        ratio = abs(curr) / max(abs(prev), 1e-9)
        if ratio <= AO_SLIM_RATIO:   # current AO is ≤30% of previous (rapidly shrinking)
            return True, label

    return False, label


def _c_rsi(ind: Optional[dict]) -> Tuple[bool, str]:
    """RSI between 45 and 60 — momentum just started, not yet extended."""
    label = "RSI"
    if not ind:
        return False, label
    rsi = ind.get("computed", {}).get("rsi")
    if rsi is None:
        return False, label
    return RSI_MIN <= float(rsi) <= RSI_MAX, label


def _c_vortex(ind: Optional[dict]) -> Tuple[bool, str]:
    """
    VI+ just crossed above VI- (bullish_crossover flag is True),
    OR VI+ is within VORTEX_TOL of VI- (converging / touching),
    OR VI+ is already above VI- (crossed within last bar — bullish=True).
    """
    label = "Vortex"
    if not ind:
        return False, label
    c = ind.get("computed", {})

    if c.get("bullish_crossover", False):
        return True, label

    vi_plus  = c.get("vi_plus",  0) or 0
    vi_minus = c.get("vi_minus", 0) or 0

    # Touching or just crossed (within tolerance)
    if abs(vi_plus - vi_minus) <= VORTEX_TOL:
        return True, label

    # Currently bullish (VI+ > VI-) — valid if the gap is still small
    if c.get("bullish", False):
        spread = c.get("spread", vi_plus - vi_minus)
        if abs(spread) <= 0.08:   # fresh cross — gap hasn't widened yet
            return True, label

    return False, label


def _c_supertrend(
    ind: Optional[dict],
    daily_df: Optional[pd.DataFrame] = None,
) -> Tuple[bool, str]:
    """
    Supertrend just flipped to bullish (ANCHOR condition).

    Detection hierarchy:
      1. Price crossed above supertrend line within last LOOKBACK bars
         (checked against raw daily_df closes).
      2. Fallback: current direction == 1 AND close is within ST_MAX_PCT_ABOVE%
         above the supertrend value (proxy for a recent flip).
    """
    label = "Supertrend"
    if not ind:
        return False, label
    c = ind.get("computed", {})

    curr_dir = c.get("direction", 0)
    if curr_dir != 1:
        return False, label   # must currently be bullish

    st_val = c.get("supertrend")
    close  = c.get("close")

    # ── Method 1: check raw closes vs current ST level ────────────────────
    if st_val and daily_df is not None and len(daily_df) > LOOKBACK + 1:
        try:
            col = "Close" if "Close" in daily_df.columns else "close"
            closes = daily_df[col].values
            curr_close = closes[-1]
            prior      = closes[-(LOOKBACK + 2):-1]   # 2 bars before current
            # Current above ST, at least one prior was below ST (flip happened)
            if curr_close > st_val and any(p <= st_val for p in prior):
                return True, label
        except Exception:
            pass

    # ── Method 2: proximity proxy ─────────────────────────────────────────
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
    Compute the Neo v1 signal score for a Stage 2 stock.

    Args:
        indicator_results : list of indicator result dicts from Stage 1
        daily_df          : full daily OHLCV DataFrame (used for ST flip detection)

    Returns dict:
        {
            "score"     : int,        # 0–5
            "label"     : "5/5",      # display string
            "is_neo"    : bool,       # True when score >= NEO_MIN_SCORE
            "conditions": {           # per-condition pass/fail
                "macd": bool, "ao": bool, "rsi": bool,
                "vortex": bool, "supertrend": bool,
            },
            "missing"   : [str],      # names of failed conditions (empty when 5/5)
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

    return {
        "score":   score,
        "label":   f"{score}/5",
        "is_neo":  score >= NEO_MIN_SCORE,
        "conditions": {
            "macd":       checks[0][0],
            "ao":         checks[1][0],
            "rsi":        checks[2][0],
            "vortex":     checks[3][0],
            "supertrend": checks[4][0],
        },
        "missing": missing,
    }
