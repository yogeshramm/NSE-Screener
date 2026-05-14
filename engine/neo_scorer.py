"""
Neo3 — Multi-indicator inflection detector for Stage 2.

Fires ONLY on stocks where all 5 indicators just turned bullish within
a tight 2-bar window. Signal must DECAY — a stock whose inflection was
weeks ago should NOT keep firing. Predecessors v1/v2 had "current state"
checks (AO positive+rising, Vortex bullish+spread continuation,
Supertrend proximity proxy) that never decayed; today's Neo3 removes
those and demands strict "just happened in last LOOKBACK bars" for
every condition.

5 conditions (Supertrend is the anchor):
  1. MACD       histogram crossed red→green within last LOOKBACK bars
                AND line still below MACD_LINE_MAX (not yet runaway).
  2. AO         crossed zero within last LOOKBACK bars (any prior bar
                in the window ≤ 0, current bar > 0)  OR  slim-red rising.
  3. RSI        currently in [RSI_MIN, RSI_MAX]  AND  was outside the
                lower bound within last LOOKBACK bars (fresh entry).
  4. Vortex     VI+ crossed above VI- within last LOOKBACK bars
                (currently bullish, any prior bar in window was bearish).
  5. Supertrend direction flipped from -1 to +1 within last LOOKBACK bars.

Indicator scalars in the registry output don't include time-series for
AO, Vortex, and Supertrend, so neo_scorer computes those series itself
from daily_df. This keeps the module self-sufficient and avoids touching
unrelated indicator code.

Score ≥ 4 (with Supertrend anchor present) → Neo3 signal.

Tier classification:
  perfect — 5/5
  strong  — 4/5 with MACD/AO/Vortex missing (peers cross-confirm)
  watch   — 4/5 with RSI missing
  below   — anything else (or Supertrend anchor missing)
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ── tunable constants ─────────────────────────────────────────────────────
# Calibrated to keep the signal moment-of-inflection only.
LOOKBACK         = 5       # 5-bar synchronization window — indicators don't
                           #   always flip on the same bar but should within ~1 week.
                           #   Decay still works because the window slides past
                           #   the cross point and the "prior bar was bearish"
                           #   check fails once the window is fully post-inflection.
RSI_MIN          = 45
RSI_MAX          = 65
AO_SLIM_RATIO    = 0.40
MACD_LINE_MAX    = 5.0     # filter runaway-trend stocks where line shot up hard
NEO_MIN_SCORE    = 4


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
                    period: int = 10, mult: float = 3.0) -> pd.Series:
    """Return supertrend direction series (+1 bullish, -1 bearish). Loops
    bar-by-bar because each bar's band depends on the previous bar's
    state — pandas can't vectorise this cleanly."""
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


def _series_recently_crossed_up(s: pd.Series, threshold: float = 0.0,
                                lookback: int = LOOKBACK) -> bool:
    """True iff series[-1] > threshold AND any of the prior lookback
    bars were ≤ threshold — i.e. the series just crossed up."""
    if s is None or len(s) < lookback + 1:
        return False
    vals = s.values
    if math.isnan(vals[-1]) or vals[-1] <= threshold:
        return False
    prior = vals[-(lookback + 1):-1]
    return any(not math.isnan(v) and v <= threshold for v in prior)


# ── 5 condition checks (strict "just happened" only) ──────────────────────

def _c_macd(ind: Optional[dict]) -> Tuple[bool, str]:
    """MACD histogram crossed red→green within last LOOKBACK bars,
       AND line still below MACD_LINE_MAX (filters runaway stocks)."""
    label = "MACD"
    if not ind:
        return False, label
    c = ind.get("computed", {})
    hist_s = c.get("histogram_series")
    macd_s = c.get("macd_series")

    if hist_s is None or macd_s is None:
        return False, label
    if not _series_recently_crossed_up(hist_s, 0.0):
        return False, label
    # Line not yet runaway
    if macd_s.values[-1] >= MACD_LINE_MAX:
        return False, label
    return True, label


def _c_ao(ind: Optional[dict], daily_df: Optional[pd.DataFrame]) -> Tuple[bool, str]:
    """AO crossed zero (red→green) within last LOOKBACK bars, OR
       slim-red rising (still negative but rapidly approaching zero).
       NO "positive and rising" continuation check — that never decays."""
    label = "AO"
    if daily_df is None or len(daily_df) < 35:
        return False, label
    ao = _ao_series(daily_df["High"], daily_df["Low"])
    if _series_recently_crossed_up(ao, 0.0):
        return True, label

    # Slim-red rising (curr < 0, prev < 0, ratio ≤ AO_SLIM_RATIO)
    vals = ao.values
    if len(vals) >= 2 and not math.isnan(vals[-1]) and not math.isnan(vals[-2]):
        curr, prev = vals[-1], vals[-2]
        if curr < 0 and prev < 0 and curr > prev:
            if abs(curr) / max(abs(prev), 1e-9) <= AO_SLIM_RATIO:
                return True, label
    return False, label


def _c_rsi(ind: Optional[dict]) -> Tuple[bool, str]:
    """RSI currently in [RSI_MIN, RSI_MAX]. The band itself acts as the
       decay gate — once RSI extends past RSI_MAX (overbought) or falls
       below RSI_MIN (weak), the condition naturally fails."""
    label = "RSI"
    if not ind:
        return False, label
    rsi = ind.get("computed", {}).get("rsi")
    if rsi is None:
        return False, label
    return RSI_MIN <= float(rsi) <= RSI_MAX, label


def _c_vortex(ind: Optional[dict], daily_df: Optional[pd.DataFrame]) -> Tuple[bool, str]:
    """VI+ crossed above VI- within last LOOKBACK bars — currently bullish
       AND any prior bar in window was bearish. NO continuation check."""
    label = "Vortex"
    if daily_df is None or len(daily_df) < 20:
        return False, label
    vi_p, vi_m = _vortex_series(daily_df["High"], daily_df["Low"], daily_df["Close"])
    if len(vi_p) < LOOKBACK + 1:
        return False, label
    p = vi_p.values; m = vi_m.values
    if math.isnan(p[-1]) or math.isnan(m[-1]):
        return False, label
    if p[-1] <= m[-1]:
        return False, label
    # Any of prior LOOKBACK bars had VI+ ≤ VI- (fresh cross)
    for i in range(-(LOOKBACK + 1), -1):
        if not math.isnan(p[i]) and not math.isnan(m[i]) and p[i] <= m[i]:
            return True, label
    return False, label


def _c_supertrend(ind: Optional[dict],
                  daily_df: Optional[pd.DataFrame]) -> Tuple[bool, str]:
    """ANCHOR: Supertrend direction flipped from -1 to +1 within last
       LOOKBACK bars. Uses our own direction-series computation so this
       check correctly fires when the flip just happened, regardless
       of how far price has moved away from the ST line."""
    label = "Supertrend"
    if daily_df is None or len(daily_df) < 20:
        return False, label
    dir_ = _supertrend_dir(daily_df["High"], daily_df["Low"], daily_df["Close"])
    if len(dir_) < LOOKBACK + 1:
        return False, label
    vals = dir_.values
    if vals[-1] != 1:
        return False, label
    # Any prior LOOKBACK bar was bearish (-1) → recent flip
    for i in range(-(LOOKBACK + 1), -1):
        if vals[i] == -1:
            return True, label
    return False, label


# ── main public function ──────────────────────────────────────────────────

def neo_score(
    indicator_results: list,
    daily_df: Optional[pd.DataFrame] = None,
) -> Dict:
    """
    Compute the Neo3 signal score for a Stage 2 stock.

    Returns:
        {
            "score":      int (0–5),
            "label":      "N/5",
            "is_neo":     bool (tier in {perfect, strong, watch}),
            "tier":       perfect | strong | watch | below,
            "profile":    "neo3",
            "conditions": {macd, ao, rsi, vortex, supertrend} → bool,
            "missing":    [labels of failed conditions],
        }
    """
    checks: List[Tuple[bool, str]] = [
        _c_macd(_find(indicator_results, "MACD")),
        _c_ao(_find(indicator_results, "Awesome Oscillator"), daily_df),
        _c_rsi(_find(indicator_results, "RSI")),
        _c_vortex(_find(indicator_results, "Vortex Indicator"), daily_df),
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
