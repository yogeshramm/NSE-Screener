"""
Optimal Entry / Stop / Target levels for a screened stock — v2.

Forward-looking trade-plan analyzer. Synthesizes:

  • Trend regime         (price vs EMA21 / EMA50 / SMA200)
  • Trend strength       (ADX 14 — only "strong" setups marked high-confidence)
  • Volatility           (ATR14 sized stops)
  • Recent swing levels  (20-day high/low, 52-week range)
  • Volume context       (5-day avg vs 20-day avg → contraction = clean base)
  • Higher-timeframe     (weekly EMA10 alignment)
  • VCP / base detection (volatility-contraction pattern)
  • R:R discipline       (≥2.0 baseline, 2.5 default, capped near 52W high)

Output: a single trade plan with entry / stop / target / R:R + a 0–100
confidence score and a rationale list explaining every number. Each
component contributes points to the score, so users can see *why* a setup
is high or low conviction.

This is a DECISION-SUPPORT tool — not investment advice. Always cross-check
with the chart's INFO panel (briefing + 52W lines) and EVENTS overlay
(earnings + corporate actions) before acting.
"""

from typing import Optional, Dict, Any, List
import pandas as pd
import numpy as np

from data.nse_history import load_history

# Optional platform-signal imports — degrade gracefully if any module is
# unavailable in the current build (e.g. running unit tests in isolation).
try:
    from engine.multi_factor import compute_factor_scores as _mfs_compute
except Exception:
    _mfs_compute = None
try:
    from engine.mtf_confluence import compute_mtf as _mtf_compute
except Exception:
    _mtf_compute = None
try:
    from engine.chart_patterns import (
        detect_vcp as _cp_vcp, detect_bull_flag as _cp_flag,
        detect_cup_handle as _cp_cup, detect_ascending_triangle as _cp_tri,
        detect_pivot_breakout as _cp_pivbo, detect_high_tight_flag as _cp_htf,
        detect_inside_bar as _cp_inside, detect_nr7 as _cp_nr7,
    )
    _CHART_PATTERN_DETECTORS = {
        "VCP": _cp_vcp, "Bull Flag": _cp_flag, "Cup & Handle": _cp_cup,
        "Ascending Triangle": _cp_tri, "Pivot Breakout": _cp_pivbo,
        "High Tight Flag": _cp_htf, "Inside Bar": _cp_inside, "NR7": _cp_nr7,
    }
except Exception:
    _CHART_PATTERN_DETECTORS = {}
try:
    from data.nse_institutional import deals_for_symbol as _deals
except Exception:
    _deals = None


# ───────────────────────── Indicator helpers ─────────────────────────

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range over the most recent `period` bars."""
    h, l, c = df["High"].astype(float), df["Low"].astype(float), df["Close"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return float(tr.tail(period).mean())


def _adx(df: pd.DataFrame, period: int = 14) -> float:
    """Average Directional Index — measures trend strength regardless of direction.
    ADX > 25 = strong trend, > 20 = trending, < 20 = chop."""
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    c = df["Close"].astype(float)
    pc = c.shift(1)

    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    up_move = h.diff()
    dn_move = -l.diff()
    plus_dm = ((up_move > dn_move) & (up_move > 0)) * up_move
    minus_dm = ((dn_move > up_move) & (dn_move > 0)) * dn_move

    atr_s = tr.rolling(period).mean()
    plus_di = 100 * plus_dm.rolling(period).mean() / atr_s
    minus_di = 100 * minus_dm.rolling(period).mean() / atr_s
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_series = dx.rolling(period).mean()
    val = adx_series.iloc[-1]
    return float(val) if pd.notna(val) else 0.0


def _vcp_score(df: pd.DataFrame) -> int:
    """Volatility Contraction Pattern score 0–10. Looks at how the daily-range
    volatility of the last 20 bars compares to the prior 20 bars. Lower recent
    volatility = tighter base = higher score (cleaner setup)."""
    if len(df) < 40:
        return 5
    recent = df.tail(20)
    prior = df.iloc[-40:-20]
    recent_vol = ((recent["High"] - recent["Low"]) / recent["Close"]).mean()
    prior_vol = ((prior["High"] - prior["Low"]) / prior["Close"]).mean()
    if prior_vol == 0:
        return 5
    ratio = recent_vol / prior_vol
    # ratio < 0.7 = strong contraction → 10; ratio > 1.3 = expansion → 0
    if ratio < 0.6: return 10
    if ratio < 0.7: return 9
    if ratio < 0.8: return 8
    if ratio < 0.9: return 7
    if ratio < 1.0: return 6
    if ratio < 1.1: return 5
    if ratio < 1.2: return 4
    if ratio < 1.4: return 2
    return 0


def _trend_regime(last: float, ema21: float, ema50: float, sma200: Optional[float]) -> str:
    """4-bucket trend classification."""
    if last > ema21 > ema50 and (sma200 is None or ema50 > sma200):
        return "uptrend"
    if last < ema21 < ema50:
        return "downtrend"
    if last > ema21 and last > ema50:
        return "early_uptrend"
    return "sideways"


def _weekly_aligned(df: pd.DataFrame) -> bool:
    """True if weekly close > weekly EMA10 (higher-TF uptrend confirmation)."""
    if len(df) < 60:
        return False
    weekly = df["Close"].resample("W").last() if isinstance(df.index, pd.DatetimeIndex) else None
    if weekly is None or len(weekly) < 12:
        # Fallback: compare current close to 50-day MA (rough HTF proxy)
        return float(df["Close"].iloc[-1]) > float(df["Close"].rolling(50).mean().iloc[-1])
    ema10 = weekly.ewm(span=10).mean().iloc[-1]
    return float(weekly.iloc[-1]) > float(ema10)


def _consensus_signals(df: pd.DataFrame, symbol: str, regime: str) -> Dict[str, Any]:
    """Pull ancillary signals already produced by the platform.

    Returns a dict with keys:
      mfs_percentile : 1-99 Multi-Factor Score (Mom + Quality + Value + Growth)
      mtf            : {"score": 0-3, "labels": ["1D up", "1W up", "1M up"]}
      chart_pattern  : list of detected pattern names (last few bars)
      institutional  : {"buy_days": int, "sell_days": int, "last_5_buys": int}
      net_score_bonus: 0-25 points to add to the base methodology score
      rationale_lines: human-readable lines to append to the plan rationale

    Each component degrades gracefully — if a module isn't available, that
    contribution is 0 and no penalty is applied.
    """
    bonus = 0
    rationale_lines: List[str] = []

    # 1. Multi-Factor Score (Mom+Quality+Value+Growth percentile)
    mfs_pct: Optional[int] = None
    if _mfs_compute is not None:
        try:
            mfs_data = _mfs_compute([symbol])
            row = mfs_data.get(symbol) if isinstance(mfs_data, dict) else None
            if row and isinstance(row, dict):
                mfs_pct = row.get("composite") or row.get("score")
        except Exception:
            mfs_pct = None
    if mfs_pct is not None:
        if mfs_pct >= 80:
            bonus += 10
            rationale_lines.append(f"✓ Multi-Factor Score {mfs_pct}/99 — top quintile (Mom+Quality+Value+Growth).")
        elif mfs_pct >= 60:
            bonus += 5
            rationale_lines.append(f"✓ Multi-Factor Score {mfs_pct}/99 — above-average composite quality.")
        elif mfs_pct < 30:
            bonus -= 5
            rationale_lines.append(f"⚠ Multi-Factor Score {mfs_pct}/99 — bottom tier; low composite quality.")
        else:
            rationale_lines.append(f"Multi-Factor Score {mfs_pct}/99 — neutral.")

    # 2. Multi-Timeframe Confluence (1D / 1W / 1M)
    mtf_info = None
    if _mtf_compute is not None:
        try:
            mtf_info = _mtf_compute(symbol)
        except Exception:
            mtf_info = None
    if mtf_info and isinstance(mtf_info, dict):
        # compute_mtf returns keys "d1", "w1", "m1" each with {trend: up/side/down}
        bull_count = sum(1 for v in [mtf_info.get("d1"), mtf_info.get("w1"), mtf_info.get("m1")]
                         if isinstance(v, dict) and v.get("trend") == "up")
        if bull_count >= 3:
            bonus += 8
            rationale_lines.append("✓ MTF confluence 3/3 — daily, weekly, AND monthly trends all up.")
        elif bull_count == 2:
            bonus += 4
            rationale_lines.append(f"✓ MTF confluence 2/3 timeframes aligned bullish.")
        elif bull_count == 0 and regime in ("uptrend", "early_uptrend"):
            bonus -= 5
            rationale_lines.append("⚠ MTF confluence 0/3 — daily uptrend not confirmed by W/M.")

    # 3. Chart pattern at end (VCP / Bull Flag / Cup-Handle / etc.)
    detected_patterns: List[str] = []
    if _CHART_PATTERN_DETECTORS and len(df) >= 30:
        for pname, detector in _CHART_PATTERN_DETECTORS.items():
            try:
                hit = detector(df)
                if hit:
                    detected_patterns.append(pname)
            except Exception:
                continue
    bullish_priority = ["High Tight Flag", "VCP", "Cup & Handle", "Bull Flag",
                        "Ascending Triangle", "Pivot Breakout", "Inside Bar", "NR7"]
    top_pattern = next((p for p in bullish_priority if p in detected_patterns), None)
    if top_pattern:
        # Higher-priority patterns get more bonus
        rank = bullish_priority.index(top_pattern)
        pattern_pts = max(8 - rank, 2)  # HTF=8, VCP=7, ... NR7=2
        bonus += pattern_pts
        rationale_lines.append(f"✓ Chart pattern detected: {top_pattern} (+{pattern_pts} pts).")
    if len(detected_patterns) > 1:
        rationale_lines.append(f"  Other patterns also formed: {', '.join(p for p in detected_patterns if p != top_pattern)[:80]}.")

    # 4. Institutional flows (bulk + block deals last 7 days)
    inst_summary = None
    if _deals is not None:
        try:
            d = _deals(symbol)
            bulk_buys = sum(1 for r in d.get("bulk", []) if r.get("action") in ("BUY", "B"))
            bulk_sells = sum(1 for r in d.get("bulk", []) if r.get("action") in ("SELL", "S"))
            block_buys = sum(1 for r in d.get("block", []) if r.get("action") in ("BUY", "B"))
            block_sells = sum(1 for r in d.get("block", []) if r.get("action") in ("SELL", "S"))
            net_buys = bulk_buys + block_buys
            net_sells = bulk_sells + block_sells
            inst_summary = {"buys": net_buys, "sells": net_sells}
            if net_buys >= 2 and net_buys > net_sells * 1.5:
                bonus += 6
                rationale_lines.append(f"✓ Institutional buying: {net_buys} bulk/block BUYs (vs {net_sells} sells) recently.")
            elif net_sells >= 2 and net_sells > net_buys * 1.5:
                bonus -= 4
                rationale_lines.append(f"⚠ Institutional distribution: {net_sells} bulk/block SELLs (vs {net_buys} buys).")
            elif net_buys + net_sells == 0:
                pass  # no signal — no rationale line
        except Exception:
            inst_summary = None

    return {
        "mfs_percentile": mfs_pct,
        "mtf": mtf_info,
        "chart_patterns": detected_patterns,
        "top_pattern": top_pattern,
        "institutional": inst_summary,
        "net_score_bonus": int(round(bonus)),
        "rationale_lines": rationale_lines,
    }


def _volume_context(df: pd.DataFrame) -> Dict[str, float]:
    """Recent (5d) avg volume vs 20-day avg. Ratio < 1 = contraction (clean
    base); > 1.3 = expansion (potential breakout or exhaustion depending on
    price action)."""
    if "Volume" not in df.columns or len(df) < 25:
        return {"ratio": 1.0, "note": "no volume data"}
    v = df["Volume"].astype(float)
    recent = float(v.tail(5).mean())
    base = float(v.tail(20).mean())
    if base <= 0:
        return {"ratio": 1.0, "note": "zero base volume"}
    ratio = recent / base
    if ratio < 0.8:
        note = "contracting (constructive base)"
    elif ratio > 1.3:
        note = "expanding (interest building)"
    else:
        note = "neutral"
    return {"ratio": round(ratio, 2), "note": note}


# ───────────────────────── Main analyzer ─────────────────────────

def compute_optimal_levels(symbol: str) -> Optional[Dict[str, Any]]:
    """Public entry-point — loads history and computes plan for `symbol`."""
    df = load_history(symbol)
    return _compute_from_df(df, symbol)


def _compute_from_df(df, symbol: str) -> Optional[Dict[str, Any]]:
    """Compute the trade plan from a pre-loaded dataframe.
    Separate from `compute_optimal_levels` so the backtest harness can pass
    historical slices (df.iloc[:N]) to simulate an "as of N days ago" plan.

    All return paths share the SAME key shape so the frontend never has to
    special-case missing fields. Non-tradeable cases (downtrend, etc.) have
    `tradeable=False` and `entry/stop_loss/target=None`.
    """
    if df is None or len(df) < 60:
        return None

    last = float(df["Close"].iloc[-1])
    last_high_20 = float(df["High"].iloc[-20:].max())
    last_low_20 = float(df["Low"].iloc[-20:].min())
    high_52w = float(df["High"].iloc[-252:].max()) if len(df) >= 252 else float(df["High"].max())
    low_52w = float(df["Low"].iloc[-252:].min()) if len(df) >= 252 else float(df["Low"].min())

    # Momentum filter: 20-day return. Backtest showed setups with negative
    # 20-day momentum produced too many losers — skip them as a coarse filter.
    ret_20 = (last / float(df["Close"].iloc[-21]) - 1) * 100 if len(df) >= 21 else 0.0
    ret_60 = (last / float(df["Close"].iloc[-61]) - 1) * 100 if len(df) >= 61 else 0.0
    # Avoid chasing — if 60d return > 25%, the move is mature and likely
    # exhausting. Backtest confirmed "high confidence" extended setups were
    # WORSE than low-confidence ones — classic late-entry trap.
    extended = ret_60 > 25

    ema21 = float(df["Close"].ewm(span=21).mean().iloc[-1])
    ema50 = float(df["Close"].ewm(span=50).mean().iloc[-1])
    sma200 = float(df["Close"].rolling(200).mean().iloc[-1]) if len(df) >= 200 else None

    atr = _atr(df, 14)
    if atr <= 0:
        return None
    adx = _adx(df, 14)
    vcp = _vcp_score(df)
    htf_aligned = _weekly_aligned(df)
    vol_ctx = _volume_context(df)

    regime = _trend_regime(last, ema21, ema50, sma200)
    rationale: List[str] = []

    # ───────────── Entry selection ─────────────
    pct_above_ema21 = (last - ema21) / ema21 * 100 if ema21 else 0
    tradeable = True
    entry: Optional[float]
    setup_type = ""

    if regime == "downtrend":
        rationale.append(
            f"Downtrend: price ₹{last:.2f} < EMA21 ₹{ema21:.2f} < EMA50 ₹{ema50:.2f}. "
            f"No long-side setup — wait for trend change."
        )
        tradeable = False
        entry = None
        setup_type = "no_setup"
    elif regime == "uptrend":
        if extended:
            # Backtest insight: extended uptrends (60d > +25%) underperform.
            # Force a pullback-only entry (no chasing).
            entry = round(ema21 * 1.005, 2)
            setup_type = "extended_pullback_only"
            rationale.append(
                f"Uptrend but EXTENDED ({ret_60:+.0f}% in 60d). "
                f"Only pullback entry near ₹{entry:.2f} (EMA21). Don't chase."
            )
        elif pct_above_ema21 > 7:
            entry = round(ema21 * 1.005, 2)
            setup_type = "pullback_to_ema21"
            rationale.append(
                f"Uptrend, extended {pct_above_ema21:.1f}% above EMA21. "
                f"Wait for pullback entry near ₹{entry:.2f}."
            )
        elif pct_above_ema21 > 3:
            entry = round(last, 2)
            setup_type = "trend_continuation"
            rationale.append(
                f"Uptrend, healthy {pct_above_ema21:.1f}% above EMA21. "
                f"Entry at current ₹{entry:.2f}."
            )
        else:
            entry = round(last, 2)
            setup_type = "uptrend_pullback_complete"
            rationale.append(
                f"Uptrend, just pulled back to EMA21. Entry at ₹{entry:.2f} — favorable."
            )
    elif regime == "early_uptrend":
        # Backtest showed early_uptrend has the worst win rate (~19%) — too
        # many false starts. Require additional confirmation: positive 20-day
        # momentum AND non-negative 60-day return. Otherwise mark un-tradeable.
        if ret_20 > 0 and ret_60 >= -3:
            entry = round(last, 2)
            setup_type = "early_uptrend_confirmed"
            rationale.append(
                f"Early uptrend (price reclaiming EMAs) + momentum confirmed "
                f"(20d {ret_20:+.1f}%, 60d {ret_60:+.1f}%). Entry ₹{entry:.2f}, size 50%."
            )
        else:
            tradeable = False
            entry = None
            setup_type = "no_setup"
            rationale.append(
                f"Early uptrend but momentum weak (20d {ret_20:+.1f}%, 60d {ret_60:+.1f}%). "
                f"Wait for confirmation."
            )
    else:  # sideways
        # Buy near recent low support OR near consolidation midpoint
        consol_mid = (last_high_20 + last_low_20) / 2
        if last <= consol_mid * 1.01:
            entry = round(min(last, last_low_20 * 1.02), 2)
            setup_type = "range_low"
            rationale.append(
                f"Sideways consolidation, near range low. Entry ₹{entry:.2f} "
                f"(20d low ₹{last_low_20:.2f})."
            )
        else:
            # Wait for breakout above range high
            entry = round(last_high_20 * 1.01, 2)
            setup_type = "range_breakout"
            rationale.append(
                f"Sideways, near upper range. Wait for breakout entry above ₹{entry:.2f} "
                f"(₹{last_high_20:.2f} +1%)."
            )

    # ───────────── ADX strength gate ─────────────
    if regime in ("uptrend", "early_uptrend") and adx < 18:
        rationale.append(
            f"⚠ ADX {adx:.1f} < 18 — trend lacks strength. Treat as range-bound; "
            f"smaller size or skip."
        )

    # ───────────── Higher-timeframe alignment ─────────────
    if regime in ("uptrend", "early_uptrend"):
        if htf_aligned:
            rationale.append("✓ Weekly trend aligned (close > weekly EMA10).")
        else:
            rationale.append("⚠ Weekly trend NOT aligned — daily uptrend without HTF support is fragile.")

    # ───────────── Volume context ─────────────
    rationale.append(
        f"Volume: 5d/20d ratio {vol_ctx['ratio']:.2f} — {vol_ctx['note']}."
    )
    if vcp >= 7:
        rationale.append(f"✓ VCP score {vcp}/10 — tight consolidation (constructive base).")
    elif vcp <= 3:
        rationale.append(f"⚠ VCP score {vcp}/10 — volatility expanding (no clean base).")

    # ───────────── Non-tradeable early return ─────────────
    if entry is None:
        # Still pull consensus so we surface signals even when un-tradeable
        # (lets user see *why* a stock is downtrend-flagged with full context)
        consensus_early = _consensus_signals(df, symbol, regime)
        rationale.extend(consensus_early["rationale_lines"])
        return _empty_plan(
            symbol, regime, last, ema21, ema50, sma200, atr, adx, vcp, htf_aligned, vol_ctx,
            high_52w, low_52w, last_low_20, last_high_20, rationale,
            consensus=consensus_early,
        )

    # ───────────── Stop placement ─────────────
    sl_atr = entry - 1.5 * atr
    sl_swing = last_low_20 * 0.99
    sl_ema50 = ema50 * 0.97 if regime in ("uptrend", "early_uptrend") else None

    candidates = [sl_atr, sl_swing]
    if sl_ema50 is not None and sl_ema50 < entry:
        candidates.append(sl_ema50)
    valid = [c for c in candidates if c is not None and 0 < c < entry]
    if not valid:
        return None
    stop_loss = round(max(valid), 2)
    risk = entry - stop_loss
    risk_pct = risk / entry * 100

    if risk_pct > 8:
        rationale.append(
            f"⚠ Stop is {risk_pct:.1f}% wide — high volatility (ATR ₹{atr:.2f}). "
            f"Halve position size, or wait for tighter consolidation."
        )
    else:
        sl_parts = [f"ATR×1.5 ₹{sl_atr:.2f}", f"20d-low−1% ₹{sl_swing:.2f}"]
        if sl_ema50:
            sl_parts.append(f"EMA50−3% ₹{sl_ema50:.2f}")
        rationale.append(
            f"Stop ₹{stop_loss:.2f} ({risk_pct:.1f}% below entry). Tightest of: "
            + ", ".join(sl_parts) + "."
        )

    # ───────────── Target ─────────────
    # Backtest showed 2.5R targets had 25% win rate over 45 bars (rarely
    # reached). Dropped to 2.0R — improves fill rate while keeping positive
    # expectancy at ~33% win rate threshold.
    target_rr = entry + 2.0 * risk
    target_capped = high_52w * 1.02

    if target_rr <= target_capped:
        target = round(target_rr, 2)
        rationale.append(f"Target ₹{target:.2f} — 2.0:1 R:R against ₹{stop_loss:.2f} stop.")
    else:
        target = round(target_capped * 0.995, 2)
        actual_rr = round((target - entry) / risk, 2) if risk > 0 else None
        rationale.append(
            f"Target ₹{target:.2f} (capped near 52W high ₹{high_52w:.2f}). "
            f"R:R reduced to {actual_rr}:1 — consider lighter size."
        )

    rr = round((target - entry) / risk, 2) if risk > 0 else None

    # ───────────── Confidence score (0–100) ─────────────
    score = 0
    score_breakdown = []

    # 1. Trend regime (0–25)
    regime_pts = {"uptrend": 25, "early_uptrend": 15, "sideways": 8, "downtrend": 0}.get(regime, 0)
    score += regime_pts
    score_breakdown.append((f"Regime ({regime})", regime_pts, 25))

    # 2. ADX strength (0–20)
    if adx >= 30: adx_pts = 20
    elif adx >= 25: adx_pts = 17
    elif adx >= 20: adx_pts = 12
    elif adx >= 15: adx_pts = 6
    else: adx_pts = 0
    score += adx_pts
    score_breakdown.append((f"ADX {adx:.1f}", adx_pts, 20))

    # 3. R:R quality (0–15)
    if rr is None: rr_pts = 0
    elif rr >= 3: rr_pts = 15
    elif rr >= 2.5: rr_pts = 12
    elif rr >= 2: rr_pts = 8
    elif rr >= 1.5: rr_pts = 4
    else: rr_pts = 0
    score += rr_pts
    score_breakdown.append((f"R:R {rr}:1" if rr else "R:R n/a", rr_pts, 15))

    # 4. Risk size (0–10) — narrower stop = better
    if risk_pct < 3: risk_pts = 10
    elif risk_pct < 5: risk_pts = 7
    elif risk_pct < 7: risk_pts = 4
    elif risk_pct < 10: risk_pts = 1
    else: risk_pts = 0
    score += risk_pts
    score_breakdown.append((f"Risk {risk_pct:.1f}%", risk_pts, 10))

    # 5. VCP base quality (0–10)
    vcp_pts = vcp
    score += vcp_pts
    score_breakdown.append((f"VCP {vcp}/10", vcp_pts, 10))

    # 6. HTF alignment (0–10)
    htf_pts = 10 if htf_aligned else 0
    score += htf_pts
    score_breakdown.append(("Weekly trend aligned" if htf_aligned else "Weekly NOT aligned", htf_pts, 10))

    # 7. Volume context (0–10) — contraction is best for entries
    vr = vol_ctx["ratio"]
    if 0.7 <= vr <= 1.0: vol_pts = 10  # tight base
    elif 0.5 <= vr < 0.7: vol_pts = 7  # very dry
    elif 1.0 < vr <= 1.3: vol_pts = 7  # mild expansion
    elif vr > 1.3 and regime == "uptrend": vol_pts = 4  # expansion in uptrend = noise vs breakout
    else: vol_pts = 2
    score += vol_pts
    score_breakdown.append((f"Volume {vr:.2f}x", vol_pts, 10))

    # 8. Consensus signals (MFS + MTF + chart patterns + institutional)
    # These ride on top of the base 100; add bonus, then cap at 100.
    consensus = _consensus_signals(df, symbol, regime)
    bonus = consensus["net_score_bonus"]
    score += bonus
    if bonus != 0:
        score_breakdown.append((f"Consensus signals", bonus, 25))
    rationale.extend(consensus["rationale_lines"])

    # 9. EXHAUSTION PENALTY — backtest insight: setups scoring "high" tended
    # to be late-stage moves with mature trends. Subtract up to 25 points
    # when 60-day return is parabolic, and an extra penalty if RSI(14) is
    # already in overbought territory. Goal: shift the high-conviction band
    # towards EARLY-trend setups that empirically had +0.13R expectancy in
    # the 100-stock 4-sample backtest.
    rsi14 = float(_rsi(df["Close"], 14).iloc[-1]) if len(df) >= 15 else 50.0
    exhaustion_pen = 0
    if ret_60 > 40:        exhaustion_pen += 15
    elif ret_60 > 25:      exhaustion_pen += 10
    elif ret_60 > 15:      exhaustion_pen += 4
    if rsi14 >= 75:        exhaustion_pen += 8
    elif rsi14 >= 70:      exhaustion_pen += 4
    if exhaustion_pen > 0:
        score -= exhaustion_pen
        score_breakdown.append((f"Exhaustion penalty (60d {ret_60:+.0f}%, RSI {rsi14:.0f})", -exhaustion_pen, 0))
        rationale.append(
            f"⚠ Exhaustion check: 60d return {ret_60:+.0f}%, RSI {rsi14:.0f} → −{exhaustion_pen} pts. "
            f"Late-stage setups historically underperform — lighter size or skip."
        )

    score = max(0, min(100, score))  # clamp 0–100

    # Confidence bands (after consensus + exhaustion adjustment)
    if score >= 75: confidence = "high"
    elif score >= 55: confidence = "moderate"
    elif score >= 35: confidence = "low"
    else: confidence = "very_low"

    return {
        "symbol": symbol,
        "tradeable": tradeable,
        "regime": regime,
        "setup_type": setup_type,
        "current_price": round(last, 2),
        "entry": entry,
        "stop_loss": stop_loss,
        "target": target,
        "risk_amount": round(risk, 2),
        "reward_amount": round(target - entry, 2),
        "risk_pct": round(risk_pct, 2),
        "risk_reward": rr,
        "confidence": confidence,
        "score": score,
        "score_max": 100,
        "score_breakdown": [
            {"factor": label, "points": pts, "max": maxp}
            for (label, pts, maxp) in score_breakdown
        ],
        "rationale": rationale,
        "ema21": round(ema21, 2),
        "ema50": round(ema50, 2),
        "sma200": round(sma200, 2) if sma200 else None,
        "atr14": round(atr, 2),
        "adx14": round(adx, 1),
        "vcp_score": vcp,
        "htf_aligned": htf_aligned,
        "volume_5_20_ratio": vol_ctx["ratio"],
        "volume_note": vol_ctx["note"],
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "swing_low_20d": round(last_low_20, 2),
        "swing_high_20d": round(last_high_20, 2),
        # Consensus from existing platform signals
        "mfs_percentile": consensus.get("mfs_percentile"),
        "mtf_confluence": consensus.get("mtf"),
        "chart_patterns_detected": consensus.get("chart_patterns") or [],
        "top_chart_pattern": consensus.get("top_pattern"),
        "institutional_summary": consensus.get("institutional"),
        "consensus_bonus": consensus.get("net_score_bonus"),
    }


def _empty_plan(symbol, regime, last, ema21, ema50, sma200, atr, adx, vcp, htf_aligned,
                vol_ctx, high_52w, low_52w, last_low_20, last_high_20, rationale,
                consensus=None):
    """Same shape as a tradeable plan but with None for actionable fields."""
    return {
        "symbol": symbol,
        "tradeable": False,
        "regime": regime,
        "setup_type": "no_setup",
        "current_price": round(last, 2),
        "entry": None,
        "stop_loss": None,
        "target": None,
        "risk_amount": None,
        "reward_amount": None,
        "risk_pct": None,
        "risk_reward": None,
        "confidence": "no_setup",
        "score": 0,
        "score_max": 100,
        "score_breakdown": [],
        "rationale": rationale,
        "ema21": round(ema21, 2),
        "ema50": round(ema50, 2),
        "sma200": round(sma200, 2) if sma200 else None,
        "atr14": round(atr, 2),
        "adx14": round(adx, 1),
        "vcp_score": vcp,
        "htf_aligned": htf_aligned,
        "volume_5_20_ratio": vol_ctx["ratio"],
        "volume_note": vol_ctx["note"],
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "swing_low_20d": round(last_low_20, 2),
        "swing_high_20d": round(last_high_20, 2),
        "mfs_percentile": (consensus or {}).get("mfs_percentile"),
        "mtf_confluence": (consensus or {}).get("mtf"),
        "chart_patterns_detected": (consensus or {}).get("chart_patterns") or [],
        "top_chart_pattern": (consensus or {}).get("top_pattern"),
        "institutional_summary": (consensus or {}).get("institutional"),
        "consensus_bonus": (consensus or {}).get("net_score_bonus"),
    }
