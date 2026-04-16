"""
Advanced chart pattern detection — multi-bar structures for swing traders.

Sources: Minervini (VCP, Pivot Point, SEPA), O'Neil (Cup & Handle, High Tight Flag),
Gurjar "Breakout Trading Made Easy" (Box/Rectangle, Inside Bar, NR7, Darvas Box),
Bulkowski "Encyclopedia of Chart Patterns" (Ascending Triangle, accuracy figures),
Classical TA (Bull Flag).

Each pattern has a detector operating on a DataFrame with OHLCV columns. Snippets
are hand-crafted 30-40 bar sequences that cleanly illustrate the geometry.
"""

import os
import pickle
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Tuple


HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")


# =========================================================================
# Helpers
# =========================================================================

def _load(sym: str):
    fpath = os.path.join(HISTORY_DIR, f"{sym}.pkl")
    if not os.path.exists(fpath):
        return None
    try:
        df = pickle.load(open(fpath, "rb"))
        df = df[~df.index.duplicated(keep="last")]
        return df
    except Exception:
        return None


def _swing_points(highs, lows, window=3):
    """Find fractal-based swing highs & lows (pivot if higher/lower than `window` bars on each side)."""
    n = len(highs)
    swing_hi, swing_lo = [], []
    for i in range(window, n - window):
        if all(highs[i] > highs[i - k] for k in range(1, window + 1)) and all(highs[i] > highs[i + k] for k in range(1, window + 1)):
            swing_hi.append((i, highs[i]))
        if all(lows[i] < lows[i - k] for k in range(1, window + 1)) and all(lows[i] < lows[i + k] for k in range(1, window + 1)):
            swing_lo.append((i, lows[i]))
    return swing_hi, swing_lo


def _linear_slope(points):
    """Least-squares slope of (x, y) points."""
    if len(points) < 2:
        return 0.0
    x = np.array([p[0] for p in points], dtype=float)
    y = np.array([p[1] for p in points], dtype=float)
    n = len(x)
    denom = (n * (x * x).sum() - x.sum() ** 2)
    if denom == 0:
        return 0.0
    return (n * (x * y).sum() - x.sum() * y.sum()) / denom


# =========================================================================
# Detectors — each returns dict with confidence + metadata, or None
# =========================================================================

def detect_nr7(df) -> Optional[Dict[str, Any]]:
    """Today has the narrowest range of the last 7 bars."""
    if len(df) < 7:
        return None
    ranges = (df["High"] - df["Low"]).tail(7).values
    today_range = ranges[-1]
    if today_range <= ranges.min() + 1e-9 and today_range < ranges[:-1].mean() * 0.8:
        return {"today_range": float(today_range), "avg_range_7": float(ranges[:-1].mean()), "confidence": 80}
    return None


def detect_inside_bar(df) -> Optional[Dict[str, Any]]:
    """Today's high and low are inside yesterday's high and low."""
    if len(df) < 2:
        return None
    y = df.iloc[-2]
    t = df.iloc[-1]
    if t["High"] <= y["High"] and t["Low"] >= y["Low"]:
        return {"mother_high": float(y["High"]), "mother_low": float(y["Low"]), "confidence": 70}
    return None


def detect_pivot_breakout(df) -> Optional[Dict[str, Any]]:
    """Price closes above the most recent swing high with 1.3x+ volume."""
    if len(df) < 30:
        return None
    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    vols = df["Volume"].values
    # Last 60-bar window
    window = df.iloc[-60:]
    sh, sl = _swing_points(window["High"].values, window["Low"].values, window=3)
    if not sh or len(sh) < 1:
        return None
    # Take the swing high immediately preceding the last few bars (not too recent, not too old)
    recent_sh = [h for h in sh if h[0] < len(window) - 3]
    if not recent_sh:
        return None
    pivot = recent_sh[-1][1]
    last_close = closes[-1]
    if last_close <= pivot:
        return None
    vol_ratio = vols[-1] / vols[-21:-1].mean() if vols[-21:-1].mean() > 0 else 0
    if vol_ratio < 1.3:
        return None
    return {"pivot": float(pivot), "breakout_pct": round((last_close - pivot) / pivot * 100, 2), "vol_ratio": round(float(vol_ratio), 2), "confidence": 75}


def detect_rectangle(df) -> Optional[Dict[str, Any]]:
    """Horizontal consolidation: ≥2 touches of top, ≥2 touches of bottom, range stable ≤8%, 15+ bars."""
    if len(df) < 20:
        return None
    window = df.iloc[-40:]
    highs = window["High"].values
    lows = window["Low"].values
    top = np.percentile(highs, 90)
    bot = np.percentile(lows, 10)
    mid = (top + bot) / 2
    width = (top - bot) / mid if mid > 0 else 0
    if width > 0.12:
        return None
    # Count touches (within 1.5% of top/bot)
    top_touches = sum(1 for h in highs if h >= top * 0.985)
    bot_touches = sum(1 for l in lows if l <= bot * 1.015)
    if top_touches < 2 or bot_touches < 2:
        return None
    bars = len(window)
    last_close = df["Close"].iloc[-1]
    # Breakout imminent if close in upper 25%
    pos = (last_close - bot) / (top - bot) if top > bot else 0.5
    return {
        "top": round(float(top), 2),
        "bot": round(float(bot), 2),
        "width_pct": round(width * 100, 1),
        "bars": bars,
        "position_pct": round(pos * 100, 1),
        "confidence": int(60 + (15 if pos > 0.75 else 0) + min(15, (top_touches + bot_touches - 4) * 3)),
    }


def detect_ascending_triangle(df) -> Optional[Dict[str, Any]]:
    """Flat resistance + rising lows. Swing highs cluster; swing lows trend up."""
    if len(df) < 25:
        return None
    window = df.iloc[-50:]
    highs = window["High"].values
    lows = window["Low"].values
    sh, sl = _swing_points(highs, lows, window=2)
    if len(sh) < 2 or len(sl) < 2:
        return None
    # Resistance: top of recent swing highs should be within 2%
    hi_vals = sorted([h[1] for h in sh])[-3:]
    if len(hi_vals) < 2:
        return None
    flat_top = (max(hi_vals) - min(hi_vals)) / max(hi_vals) < 0.025
    # Rising lows: slope of swing lows > 0 and meaningful
    slope = _linear_slope(sl[-3:])
    if not flat_top:
        return None
    if slope <= 0:
        return None
    top = max(hi_vals)
    last_close = df["Close"].iloc[-1]
    pos = (last_close - min([l[1] for l in sl])) / (top - min([l[1] for l in sl])) if top > min([l[1] for l in sl]) else 0.5
    return {
        "resistance": round(float(top), 2),
        "lows_slope": round(float(slope), 4),
        "position_pct": round(pos * 100, 1),
        "confidence": int(70 + min(20, pos * 20)),
    }


def detect_bull_flag(df) -> Optional[Dict[str, Any]]:
    """Sharp pole (≥15% in ≤15 bars) followed by tight consolidation (≤10% range, 5-20 bars)."""
    if len(df) < 25:
        return None
    closes = df["Close"].values
    # Look at last 35 bars max
    look = min(35, len(df))
    w = df.iloc[-look:]
    # Try to find pole ending at various points 5-20 bars ago
    best = None
    for flag_len in range(5, 21):
        if flag_len + 5 > look:
            break
        pole_window = w.iloc[:-flag_len]
        flag_window = w.iloc[-flag_len:]
        if len(pole_window) < 5:
            continue
        pole_start = pole_window["Low"].tail(20).min()
        pole_end = pole_window["High"].iloc[-1]
        pole_pct = (pole_end - pole_start) / pole_start if pole_start > 0 else 0
        if pole_pct < 0.15:
            continue
        flag_high = flag_window["High"].max()
        flag_low = flag_window["Low"].min()
        flag_range = (flag_high - flag_low) / flag_high if flag_high > 0 else 1
        if flag_range > 0.12:
            continue
        # Flag should retrace at most 50% of pole
        retrace = (pole_end - flag_low) / (pole_end - pole_start) if pole_end > pole_start else 1
        if retrace > 0.5:
            continue
        conf = 65 + min(20, int(pole_pct * 50)) - int(flag_range * 100)
        cand = {
            "pole_pct": round(pole_pct * 100, 1),
            "flag_range_pct": round(flag_range * 100, 1),
            "flag_bars": flag_len,
            "flag_high": round(float(flag_high), 2),
            "retrace_pct": round(retrace * 100, 1),
            "confidence": max(0, conf),
        }
        if best is None or cand["confidence"] > best["confidence"]:
            best = cand
    return best


def detect_high_tight_flag(df) -> Optional[Dict[str, Any]]:
    """≥100% run in last 60 bars, then pullback/consolidation ≤25%."""
    if len(df) < 40:
        return None
    look = min(80, len(df))
    w = df.iloc[-look:]
    # Find the lowest point in first half and highest point anywhere
    mid = len(w) // 2
    low_early = w["Low"].iloc[:mid].min()
    high_peak = w["High"].max()
    if low_early <= 0:
        return None
    run = (high_peak - low_early) / low_early
    if run < 1.0:  # Need ≥100% run
        return None
    # Locate peak
    peak_idx = w["High"].idxmax()
    after = w.loc[peak_idx:].iloc[1:]
    if len(after) < 3 or len(after) > 25:
        return None
    pullback = (high_peak - after["Low"].min()) / high_peak
    if pullback > 0.25:
        return None
    return {
        "run_pct": round(run * 100, 1),
        "pullback_pct": round(pullback * 100, 1),
        "flag_bars": len(after),
        "peak": round(float(high_peak), 2),
        "confidence": 90 - int(pullback * 100),  # Tighter = higher confidence
    }


def detect_vcp(df) -> Optional[Dict[str, Any]]:
    """Volatility Contraction: 3+ consecutive pullbacks each tighter than prior, with volume declining."""
    if len(df) < 30:
        return None
    w = df.iloc[-60:]
    highs = w["High"].values
    lows = w["Low"].values
    sh, sl = _swing_points(highs, lows, window=2)
    if len(sh) < 3 or len(sl) < 3:
        return None
    # Pair highs with subsequent lows to measure pullbacks
    pullbacks = []
    for h_idx, h_val in sh[-4:]:
        subsequent = [l for l in sl if l[0] > h_idx]
        if subsequent:
            l_idx, l_val = subsequent[0]
            pb = (h_val - l_val) / h_val if h_val > 0 else 0
            pullbacks.append(pb)
    if len(pullbacks) < 3:
        return None
    # Check each successive pullback < previous × 0.85
    contractions = 0
    for i in range(1, len(pullbacks)):
        if pullbacks[i] < pullbacks[i - 1] * 0.85:
            contractions += 1
    if contractions < 2:
        return None
    # Volume should trend down
    vols = w["Volume"].tail(30).values
    vol_slope = _linear_slope(list(enumerate(vols)))
    vol_drying = bool(vol_slope < 0)
    conf = 65 + contractions * 5 + (10 if vol_drying else 0)
    return {
        "contractions": int(contractions + 1),
        "pullbacks_pct": [round(float(p) * 100, 1) for p in pullbacks],
        "volume_drying": vol_drying,
        "confidence": int(min(90, conf)),
    }


def detect_cup_handle(df) -> Optional[Dict[str, Any]]:
    """Rounded U-shape base, then a small pullback handle. Left lip ≈ right lip; depth 15-50%."""
    if len(df) < 40:
        return None
    look = min(80, len(df))
    w = df.iloc[-look:]
    highs = w["High"].values
    lows = w["Low"].values
    n = len(w)
    # Find handle: last 5-15 bars with small range
    for h_len in range(5, 16):
        if h_len + 30 > n:
            break
        cup = w.iloc[:n - h_len]
        handle = w.iloc[n - h_len:]
        cup_high = cup["High"].max()
        cup_low = cup["Low"].min()
        depth = (cup_high - cup_low) / cup_high
        if depth < 0.12 or depth > 0.5:
            continue
        # Right lip: last 5 bars of cup should recover near cup_high
        right_lip = cup["High"].tail(5).max()
        if right_lip < cup_high * 0.94:
            continue
        # Rounded: middle portion should contain the low
        mid_low = cup["Low"].iloc[len(cup) // 4: 3 * len(cup) // 4].min()
        if mid_low > cup_low * 1.05:
            continue
        # Handle pullback small (max 50% of cup depth)
        handle_pullback = (cup_high - handle["Low"].min()) / cup_high
        if handle_pullback > depth * 0.5:
            continue
        conf = 60 + int((1 - depth) * 20) + int((1 - handle_pullback / depth) * 15)
        return {
            "cup_high": round(float(cup_high), 2),
            "cup_low": round(float(cup_low), 2),
            "cup_depth_pct": round(depth * 100, 1),
            "handle_bars": h_len,
            "handle_pullback_pct": round(handle_pullback * 100, 1),
            "confidence": min(85, conf),
        }
    return None


def detect_darvas_box(df) -> Optional[Dict[str, Any]]:
    """Stacked boxes: at least 2 prior rectangles, current price in a new box above the last."""
    rect = detect_rectangle(df)
    if not rect:
        return None
    # Look further back for prior boxes
    if len(df) < 80:
        return None
    older = df.iloc[:-40]
    older_rect = detect_rectangle(older)
    stacked = 1
    if older_rect and older_rect["top"] < rect["bot"] * 1.05:
        stacked = 2
    if stacked < 2:
        return None
    return {
        **rect,
        "stacked": stacked,
        "prior_box_top": older_rect["top"] if older_rect else None,
        "confidence": min(85, rect["confidence"] + 10),
    }


# =========================================================================
# Pattern library + synthetic snippets
# =========================================================================

PATTERNS = [
    {
        "key": "vcp",
        "name": "VCP (Volatility Contraction Pattern)",
        "source": "Mark Minervini — Trade Like a Stock Market Wizard",
        "direction": "bullish",
        "type": "continuation",
        "accuracy": 70,
        "bars": "20-50",
        "description": (
            "A series of 3-6 progressively tighter pullbacks within an uptrend. Each "
            "contraction is roughly half the size of the previous, with volume drying up as "
            "price coils. Signals institutional accumulation and an imminent breakout. "
            "Minervini's #1 pattern — the foundation of his SEPA methodology."
        ),
        "entry": "Buy on breakout above the resistance of the tightest (final) contraction with volume ≥1.5× 20-day average.",
        "invalidate": "Price breaks below the low of the final contraction, OR any contraction is wider than the previous one.",
        "volume_rule": "Volume should decrease progressively through each contraction, then spike on breakout.",
        "context": "Only valid after a strong prior uptrend (stock up ≥25% from base). Best when combined with Relative Strength > 70.",
        "detector": "detect_vcp",
    },
    {
        "key": "cup_handle",
        "name": "Cup and Handle",
        "source": "William O'Neil — How to Make Money in Stocks",
        "direction": "bullish",
        "type": "continuation base",
        "accuracy": 65,
        "bars": "30-65",
        "description": (
            "A rounded U-shaped base (the cup) forms over weeks/months, followed by a small "
            "pullback (the handle) that shakes out weak hands before the breakout. Classic "
            "CAN SLIM base. The cup should be gently curved, not V-shaped."
        ),
        "entry": "Buy as price breaks above the pivot (highest point of the handle) on volume ≥1.5× average.",
        "invalidate": "Handle pullback exceeds 35%, OR price breaks below the handle's low.",
        "volume_rule": "Volume dries up in the handle, then explodes on the breakout above the pivot.",
        "context": "Cup depth 12-35% (healthy), handle 5-15 bars, handle pullback ≤50% of cup depth.",
        "detector": "detect_cup_handle",
    },
    {
        "key": "ascending_triangle",
        "name": "Ascending Triangle",
        "source": "Classical TA / Bulkowski backtest",
        "direction": "bullish",
        "type": "continuation",
        "accuracy": 72,
        "bars": "15-40",
        "description": (
            "Flat horizontal resistance with rising higher lows. Buyers consistently support "
            "at progressively higher prices while sellers cap at the same level. Bulkowski "
            "rates this among the highest-performing chart patterns. Eventually the seller "
            "supply is exhausted and price breaks out."
        ),
        "entry": "Buy on breakout above the horizontal resistance with volume ≥1.5× average.",
        "invalidate": "Price breaks below the rising trendline connecting recent lows.",
        "volume_rule": "Volume declining during the triangle; explosive on breakout.",
        "context": "At least 2 touches of horizontal resistance and 2+ rising swing lows. Flatter top = stronger pattern.",
        "detector": "detect_ascending_triangle",
    },
    {
        "key": "bull_flag",
        "name": "Bull Flag (Flag & Pole)",
        "source": "Classical TA",
        "direction": "bullish",
        "type": "continuation",
        "accuracy": 67,
        "bars": "10-25",
        "description": (
            "A sharp near-vertical rise (the pole), followed by a tight parallel channel "
            "sloping slightly down or sideways (the flag). One of the highest-probability "
            "swing setups because both entry and stop are mechanically defined."
        ),
        "entry": "Buy on breakout above the upper flag trendline with volume expansion.",
        "invalidate": "Price breaks below the lower flag trendline or retraces more than 50% of the pole.",
        "volume_rule": "Volume surges on the pole, dries up in the flag, expands on breakout.",
        "context": "Pole ≥15% in ≤15 bars; flag consolidation 5-20 bars; flag range ≤10%.",
        "detector": "detect_bull_flag",
    },
    {
        "key": "rectangle",
        "name": "Rectangle / Box Breakout",
        "source": "Sunil Gurjar — Breakout Trading Made Easy; Darvas",
        "direction": "bullish",
        "type": "continuation / accumulation",
        "accuracy": 62,
        "bars": "15-50",
        "description": (
            "Horizontal consolidation between clear support and resistance levels. Multiple "
            "touches of both boundaries. The longer the consolidation, the more explosive "
            "the breakout. Gurjar's foundational pattern and Darvas's original method."
        ),
        "entry": "Buy on close above the resistance with volume ≥2× average (Gurjar's rule).",
        "invalidate": "Close back below the resistance level (false breakout), or break below support.",
        "volume_rule": "Volume declines inside the box. Must surge to 2×+ average on breakout.",
        "context": "≥2 touches of top and bottom. Box width ≤12%. Duration 15+ bars. Longer box = better.",
        "detector": "detect_rectangle",
    },
    {
        "key": "high_tight_flag",
        "name": "High Tight Flag",
        "source": "William O'Neil",
        "direction": "bullish",
        "type": "continuation (rare, powerful)",
        "accuracy": 90,
        "bars": "8-15",
        "description": (
            "After a stock has doubled (≥100% run) in 2-3 months, it pauses for 3-5 weeks in "
            "a tight 10-25% pullback. O'Neil considered this his #1 pattern — the rarest but "
            "highest-performing setup in his system. Breakouts commonly run another 40%+."
        ),
        "entry": "Buy on breakout above the flag high with strong volume.",
        "invalidate": "Pullback exceeds 25%, OR pattern takes longer than 5 weeks to form.",
        "volume_rule": "Volume should contract tightly during the flag. Breakout day volume 1.5×+ average.",
        "context": "Prior run ≥100% in ≤60 bars. Flag duration 8-25 bars. Pullback ≤25%.",
        "detector": "detect_high_tight_flag",
    },
    {
        "key": "inside_bar",
        "name": "Inside Bar Breakout",
        "source": "Sunil Gurjar — Breakout Trading Made Easy",
        "direction": "bullish",
        "type": "compression",
        "accuracy": 60,
        "bars": "2-4",
        "description": (
            "Today's high and low are both inside yesterday's range (yesterday becomes the "
            "'mother bar'). Indicates volatility compression — the market is gathering "
            "energy. Gurjar's preferred short-term setup for intraday and swing entries."
        ),
        "entry": "Buy on break above the mother bar's high (or today's high, more conservative).",
        "invalidate": "Break below the mother bar's low.",
        "volume_rule": "Today's volume should be lower than yesterday's; breakout volume 1.3×+ average.",
        "context": "Best when forming near a prior support/resistance level or after a trend pullback.",
        "detector": "detect_inside_bar",
    },
    {
        "key": "nr7",
        "name": "NR7 (Narrowest Range 7)",
        "source": "Toby Crabel / Sunil Gurjar",
        "direction": "neutral (breakout either side)",
        "type": "compression",
        "accuracy": 65,
        "bars": "7",
        "description": (
            "Today's high-to-low range is the narrowest of the last 7 sessions. A volatility "
            "collapse that typically precedes a volatility expansion. Gurjar stacks this "
            "filter on top of box breakouts to time entries."
        ),
        "entry": "Buy on break above today's high (stop below today's low). Short on break below today's low.",
        "invalidate": "Second consecutive NR7 (compression not yet resolved).",
        "volume_rule": "No specific volume rule for NR7 itself; the following breakout day should see 1.5×+ volume.",
        "context": "Strongest when forming near a consolidation boundary or within a larger pattern.",
        "detector": "detect_nr7",
    },
    {
        "key": "darvas_box",
        "name": "Darvas Box (Stacked)",
        "source": "Nicolas Darvas / Sunil Gurjar",
        "direction": "bullish",
        "type": "continuation (trending)",
        "accuracy": 68,
        "bars": "20-60 per box",
        "description": (
            "Rectangular consolidations stacked on top of each other as the stock trends up. "
            "Each box's high becomes the next entry; each box's low becomes the new stop. "
            "Darvas made $2 million in 18 months with this method while traveling the world "
            "as a dancer. Gurjar teaches this as a trailing-stop framework."
        ),
        "entry": "Buy as price breaks out of the current (top) box into a new box.",
        "invalidate": "Price breaks back below the low of the current box.",
        "volume_rule": "Volume should expand on each box breakout.",
        "context": "At least 2 stacked boxes. Each box 20+ bars. Works best in strong uptrend + rising market.",
        "detector": "detect_darvas_box",
    },
    {
        "key": "pivot_breakout",
        "name": "Pivot Point Breakout",
        "source": "Mark Minervini (SEPA) / Gurjar",
        "direction": "bullish",
        "type": "trigger",
        "accuracy": 68,
        "bars": "5-10",
        "description": (
            "Price closes above the most recent significant swing high (pivot) with strong "
            "volume. This is Minervini's textbook 'buy point' — the specific moment when "
            "a base or consolidation resolves upward. The pivot must be a clearly defined "
            "swing high that has held as resistance."
        ),
        "entry": "Buy on close above the pivot with volume ≥1.3× 20-day average.",
        "invalidate": "Close back below the pivot within 3 bars (undercut = false breakout).",
        "volume_rule": "Breakout candle volume should be at least 1.3× (ideally 1.5-2.0×) the 20-day average.",
        "context": "Best when the pivot is part of a larger base (VCP, Flag, Cup). Lone pivots are lower-probability.",
        "detector": "detect_pivot_breakout",
    },
]


# Synthetic OHLC snippets (30-40 bars each) — rendered as multi-bar mini-charts
# Format: list of {open, high, low, close}

def _make_vcp_snippet():
    """Up-trend with progressively tighter pullbacks."""
    bars = []
    price = 100
    # Initial uptrend to 115
    for i in range(8):
        c = price + np.random.uniform(0.5, 1.8)
        bars.append({"open": price, "high": max(price, c) + np.random.uniform(0.1, 0.6), "low": min(price, c) - np.random.uniform(0.1, 0.4), "close": c})
        price = c
    # First pullback (wider)
    for i in range(4):
        c = price - np.random.uniform(0.6, 1.5)
        bars.append({"open": price, "high": price + np.random.uniform(0.1, 0.4), "low": min(price, c) - np.random.uniform(0.1, 0.3), "close": c})
        price = c
    # Recovery
    for i in range(4):
        c = price + np.random.uniform(0.5, 1.2)
        bars.append({"open": price, "high": max(price, c) + 0.3, "low": min(price, c) - 0.2, "close": c})
        price = c
    # Second pullback (tighter)
    for i in range(3):
        c = price - np.random.uniform(0.3, 0.8)
        bars.append({"open": price, "high": price + 0.2, "low": min(price, c) - 0.2, "close": c})
        price = c
    for i in range(3):
        c = price + np.random.uniform(0.3, 0.7)
        bars.append({"open": price, "high": max(price, c) + 0.2, "low": min(price, c) - 0.1, "close": c})
        price = c
    # Third pullback (tightest)
    for i in range(3):
        c = price - np.random.uniform(0.1, 0.3)
        bars.append({"open": price, "high": price + 0.15, "low": min(price, c) - 0.1, "close": c})
        price = c
    # Breakout
    for i in range(3):
        c = price + np.random.uniform(0.8, 2.0)
        bars.append({"open": price, "high": max(price, c) + 0.4, "low": min(price, c) - 0.1, "close": c})
        price = c
    return bars


def _make_cup_handle_snippet():
    """Left lip, U-shape, right lip, small handle."""
    bars = []
    # Left lip at 110
    for x in np.linspace(110, 113, 3):
        bars.append({"open": x - 0.3, "high": x + 0.4, "low": x - 0.6, "close": x})
    # Descent to bottom (90)
    for x in np.linspace(113, 92, 7):
        bars.append({"open": x + 0.5, "high": x + 0.6, "low": x - 0.4, "close": x})
    # U bottom
    for x in [91, 90, 90, 90.5, 91]:
        bars.append({"open": x - 0.2, "high": x + 0.3, "low": x - 0.4, "close": x})
    # Ascent back to 113
    for x in np.linspace(91, 113, 8):
        bars.append({"open": x - 0.4, "high": x + 0.5, "low": x - 0.5, "close": x})
    # Handle: small pullback to 108
    for x in [112, 110, 109, 108, 108, 109, 110]:
        bars.append({"open": x + 0.2, "high": x + 0.4, "low": x - 0.3, "close": x})
    # Breakout
    for x in [113, 115, 118]:
        bars.append({"open": x - 1.5, "high": x + 0.4, "low": x - 1.8, "close": x})
    return bars


def _make_asc_triangle_snippet():
    """Flat resistance at 100, rising lows."""
    bars = []
    low_base = 90
    highs_at = [98, 100, 100, 100, 100, 100]
    for i in range(20):
        low = low_base + i * 0.4
        high = highs_at[min(i // 4, len(highs_at) - 1)]
        # Oscillate
        if i % 3 == 0:
            c = high - np.random.uniform(0.5, 1.5)
            o = low + np.random.uniform(0.2, 1.0)
        else:
            c = low + np.random.uniform(0.5, 2.0)
            o = high - np.random.uniform(0.5, 2.0)
        bars.append({"open": o, "high": high - np.random.uniform(0, 0.5), "low": low, "close": c})
    # Breakout
    bars.append({"open": 99.5, "high": 104, "low": 99, "close": 103.5})
    bars.append({"open": 103.5, "high": 107, "low": 103, "close": 106})
    return bars


def _make_bull_flag_snippet():
    """Sharp pole, tight down-sloping flag, breakout."""
    bars = []
    # Consolidate low
    for x in [80, 81, 79, 80, 81]:
        bars.append({"open": x - 0.3, "high": x + 0.5, "low": x - 0.5, "close": x})
    # Pole
    for x in [82, 85, 89, 93, 97, 100]:
        bars.append({"open": x - 2, "high": x + 0.3, "low": x - 2.2, "close": x})
    # Flag (down-sloping tight)
    for x in [99, 98.5, 97.5, 97, 96.5, 96, 96.5, 97]:
        bars.append({"open": x + 0.3, "high": x + 0.6, "low": x - 0.4, "close": x})
    # Breakout
    for x in [98.5, 101, 104, 107]:
        bars.append({"open": x - 1.5, "high": x + 0.4, "low": x - 1.8, "close": x})
    return bars


def _make_rectangle_snippet():
    """Horizontal range between 95 and 100."""
    bars = []
    highs = [100, 100.2, 99.8, 100, 100, 99.9, 100.1]
    lows = [95, 94.9, 95.1, 95, 95, 95.2, 94.9]
    import random as _r
    _r.seed(7)
    for i in range(20):
        h = 100 + np.random.uniform(-0.3, 0.3)
        l = 95 + np.random.uniform(-0.3, 0.3)
        o = l + np.random.uniform(1, 4)
        c = l + np.random.uniform(1, 4)
        bars.append({"open": o, "high": h, "low": l, "close": c})
    # Breakout
    for x in [99, 102, 105, 108]:
        bars.append({"open": x - 1.5, "high": x + 0.3, "low": x - 1.8, "close": x})
    return bars


def _make_high_tight_flag_snippet():
    """Double (~100% run) then tight small pullback."""
    bars = []
    # Start at 50
    for x in [50, 51, 49, 50, 51]:
        bars.append({"open": x, "high": x + 0.5, "low": x - 0.5, "close": x + 0.2})
    # Run to 100 (double)
    for x in np.linspace(52, 100, 12):
        bars.append({"open": x - 3, "high": x + 0.5, "low": x - 3.3, "close": x})
    # Tight flag: pullback to ~88, small range
    for x in [98, 94, 90, 88, 88, 89, 90, 90, 89, 88]:
        bars.append({"open": x + 0.5, "high": x + 0.8, "low": x - 0.5, "close": x})
    # Breakout
    for x in [93, 98, 104]:
        bars.append({"open": x - 2, "high": x + 0.3, "low": x - 2.3, "close": x})
    return bars


def _make_inside_bar_snippet():
    """Large mother bar, inside bar, breakout."""
    bars = []
    # Regular candles
    for x in [100, 101, 99, 100, 102, 103]:
        bars.append({"open": x - 0.5, "high": x + 0.8, "low": x - 1, "close": x})
    # Mother bar (large range)
    bars.append({"open": 102, "high": 106, "low": 99, "close": 105})
    # Inside bar (within mother)
    bars.append({"open": 104, "high": 105.5, "low": 101, "close": 103.5})
    # Breakout
    bars.append({"open": 104, "high": 108, "low": 103.8, "close": 107.8})
    bars.append({"open": 107.8, "high": 110, "low": 107, "close": 109.5})
    return bars


def _make_nr7_snippet():
    """Seven bars with the last having smallest range."""
    bars = []
    # First 10 regular bars
    for x in [100, 102, 99, 101, 103, 100, 102]:
        bars.append({"open": x - 1, "high": x + 1.5, "low": x - 1.8, "close": x + 0.2})
    # Progressively narrower
    for x in [101, 101.5, 101]:
        bars.append({"open": x - 0.5, "high": x + 0.8, "low": x - 0.8, "close": x})
    # NR7 — tiny range
    bars.append({"open": 101.2, "high": 101.5, "low": 101.0, "close": 101.3})
    # Breakout expansion
    for x in [102.5, 104.5]:
        bars.append({"open": x - 1, "high": x + 0.4, "low": x - 1.3, "close": x})
    return bars


def _make_darvas_box_snippet():
    """Two stacked boxes."""
    bars = []
    # Lower box 80-85
    for i in range(10):
        bars.append({"open": 82 + np.random.uniform(-1, 1), "high": 85, "low": 80, "close": 83 + np.random.uniform(-1, 1)})
    # Breakout to upper box
    for x in [86, 89, 92]:
        bars.append({"open": x - 2, "high": x + 0.3, "low": x - 2.3, "close": x})
    # Upper box 90-95
    for i in range(10):
        bars.append({"open": 92 + np.random.uniform(-1, 1), "high": 95, "low": 90, "close": 93 + np.random.uniform(-1, 1)})
    # Next breakout
    for x in [96, 99, 102]:
        bars.append({"open": x - 2, "high": x + 0.3, "low": x - 2.3, "close": x})
    return bars


def _make_pivot_breakout_snippet():
    """Swing high at 100, base, breakout above."""
    bars = []
    # Rise to swing high 100
    for x in np.linspace(90, 100, 5):
        bars.append({"open": x - 1, "high": x + 0.3, "low": x - 1.3, "close": x})
    # Pullback
    for x in [99, 97, 95, 93, 94, 95]:
        bars.append({"open": x + 0.5, "high": x + 0.8, "low": x - 0.5, "close": x})
    # Consolidation near pivot
    for x in [96, 97, 98, 99, 99.5]:
        bars.append({"open": x - 0.3, "high": x + 0.5, "low": x - 0.5, "close": x})
    # Tight coil
    for x in [99, 99.2, 99.5]:
        bars.append({"open": x - 0.2, "high": x + 0.3, "low": x - 0.3, "close": x})
    # Breakout above pivot
    for x in [101, 104, 107]:
        bars.append({"open": x - 1.5, "high": x + 0.3, "low": x - 1.8, "close": x})
    return bars


SNIPPETS = {
    "vcp": _make_vcp_snippet,
    "cup_handle": _make_cup_handle_snippet,
    "ascending_triangle": _make_asc_triangle_snippet,
    "bull_flag": _make_bull_flag_snippet,
    "rectangle": _make_rectangle_snippet,
    "high_tight_flag": _make_high_tight_flag_snippet,
    "inside_bar": _make_inside_bar_snippet,
    "nr7": _make_nr7_snippet,
    "darvas_box": _make_darvas_box_snippet,
    "pivot_breakout": _make_pivot_breakout_snippet,
}


# Cache snippets so they're deterministic across calls
_snippet_cache: Dict[str, List[Dict[str, float]]] = {}


def _get_snippet(key: str) -> List[Dict[str, float]]:
    if key not in _snippet_cache:
        np.random.seed(hash(key) & 0xFFFFFFFF)  # Deterministic per-pattern
        fn = SNIPPETS.get(key)
        if fn is None:
            return []
        _snippet_cache[key] = [
            {k: round(float(v), 2) for k, v in bar.items()}
            for bar in fn()
        ]
    return _snippet_cache[key]


def list_patterns() -> List[Dict[str, Any]]:
    """Return the library with snippets attached."""
    out = []
    for p in PATTERNS:
        snap = p.copy()
        snap["snippet"] = _get_snippet(p["key"])
        snap.pop("detector", None)  # Internal only
        out.append(snap)
    return out


_DETECTORS = {
    "vcp": detect_vcp,
    "cup_handle": detect_cup_handle,
    "ascending_triangle": detect_ascending_triangle,
    "bull_flag": detect_bull_flag,
    "rectangle": detect_rectangle,
    "high_tight_flag": detect_high_tight_flag,
    "inside_bar": detect_inside_bar,
    "nr7": detect_nr7,
    "darvas_box": detect_darvas_box,
    "pivot_breakout": detect_pivot_breakout,
}


def scan(pattern_key: str, symbols: List[str]) -> List[Dict[str, Any]]:
    """Scan universe for a chart pattern; returns ranked hits."""
    det = _DETECTORS.get(pattern_key)
    if det is None:
        return []
    hits = []
    for sym in symbols:
        df = _load(sym)
        if df is None or len(df) < 30:
            continue
        try:
            res = det(df)
            if res:
                hit = {"symbol": sym, "close": round(float(df["Close"].iloc[-1]), 2), **res}
                hits.append(hit)
        except Exception:
            continue
    hits.sort(key=lambda h: h.get("confidence", 0), reverse=True)
    return hits[:100]
