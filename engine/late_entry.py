"""
Late Entry Correction Layers
Prevents chasing extended stocks. Prefers fresh breakouts and retests.
"""

import pandas as pd
import numpy as np


def check_stage1_late_entry(df: pd.DataFrame, config: dict) -> dict:
    """
    Stage 1 Late Entry Correction.
    Checks if entry timing is favorable after passing all Stage 1 filters.

    Returns dict with status and details.
    """
    cfg = config.get("late_entry_stage1", {})
    if not cfg.get("enabled", True):
        return {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    max_ext = cfg.get("max_extension_from_breakout", 6)
    max_exp_candles = cfg.get("max_expansion_candles_without_pause", 2)
    proximity_max = cfg.get("entry_proximity_max", 3)

    close = df["Close"]
    high = df["High"]
    latest = close.iloc[-1]
    issues = []
    bonuses = []

    # 1. Check extension from recent breakout zone
    #    Breakout zone = highest resistance broken in last 20 bars
    lookback_20 = close.iloc[-21:-1]
    breakout_level = lookback_20.max()
    extension_pct = ((latest - breakout_level) / breakout_level) * 100

    if extension_pct > max_ext:
        # Check for visible retest
        recent_lows = df["Low"].iloc[-5:]
        retest_visible = any(low <= breakout_level * 1.01 for low in recent_lows)
        if not retest_visible:
            issues.append(f"Extended {extension_pct:.1f}% above breakout (max {max_ext}%), no retest")

    # 2. Check for strong expansion candles without pause
    body_sizes = []
    for i in range(-5, 0):
        body = abs(close.iloc[i] - df["Open"].iloc[i])
        avg_body = abs(close.iloc[i-20:i] - df["Open"].iloc[i-20:i]).mean()
        if avg_body > 0 and body > avg_body * 1.5:
            body_sizes.append(True)
        else:
            body_sizes.append(False)

    consecutive_expansion = 0
    max_consecutive = 0
    for is_expansion in body_sizes:
        if is_expansion:
            consecutive_expansion += 1
            max_consecutive = max(max_consecutive, consecutive_expansion)
        else:
            consecutive_expansion = 0

    if max_consecutive > max_exp_candles:
        issues.append(f"{max_consecutive} expansion candles without pause (max {max_exp_candles})")

    # 3. Check proximity to 52-week high
    high_52w = high.iloc[-252:].max() if len(high) >= 252 else high.max()
    proximity_pct = ((high_52w - latest) / high_52w) * 100

    if 0 <= proximity_pct <= proximity_max:
        bonuses.append(f"Within {proximity_pct:.1f}% of 52W high (good entry zone)")

    # 4. Prefer stocks from consolidation (low volatility in last 10 bars)
    recent_range = (high.iloc[-10:].max() - df["Low"].iloc[-10:].min()) / latest * 100
    if recent_range < 5:
        bonuses.append(f"Emerging from tight consolidation ({recent_range:.1f}% range)")

    # Determine status
    if len(issues) == 0:
        status = "PASS"
    elif len(issues) == 1 and len(bonuses) > 0:
        status = "BORDERLINE"
    else:
        status = "FAIL"

    return {
        "status": status,
        "value": f"{len(issues)} issues, {len(bonuses)} bonuses",
        "threshold": "No late entry issues",
        "details": "; ".join(issues + bonuses) if (issues or bonuses) else "Clean entry timing",
        "issues": issues,
        "bonuses": bonuses,
        "extension_pct": round(extension_pct, 2),
        "proximity_to_high": round(proximity_pct, 2),
    }


def check_stage2_late_entry(df: pd.DataFrame, config: dict) -> dict:
    """
    Stage 2 Late Entry Correction.
    Ensures breakout entry is fresh and not stale/extended.
    """
    cfg = config.get("late_entry_stage2", {})
    if not cfg.get("enabled", True):
        return {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    max_ext = cfg.get("stage2_max_extension", 4)
    stale_sessions = cfg.get("stale_breakout_sessions", 2)

    close = df["Close"]
    high = df["High"]
    latest = close.iloc[-1]
    issues = []

    # 1. Check if breakout is stale (already moved too much)
    recent_high = high.iloc[-stale_sessions-1:-1].max()
    lookback_high = high.iloc[-20:-stale_sessions-1].max()
    if recent_high > lookback_high:
        extension = ((latest - lookback_high) / lookback_high) * 100
        if extension > max_ext:
            # Check for clean retest
            recent_lows = df["Low"].iloc[-3:]
            retest = any(low <= lookback_high * 1.01 for low in recent_lows)
            if not retest:
                issues.append(f"Extended {extension:.1f}% above breakout (max {max_ext}%), no retest")

    # 2. Check breakout candle quality (close near high, no long upper wick)
    last_candle = df.iloc[-1]
    candle_range = last_candle["High"] - last_candle["Low"]
    if candle_range > 0:
        upper_wick = (last_candle["High"] - max(last_candle["Close"], last_candle["Open"])) / candle_range
        close_position = (last_candle["Close"] - last_candle["Low"]) / candle_range
        if upper_wick > 0.4:
            issues.append(f"Long upper wick ({upper_wick:.0%} of range)")
        if close_position < 0.5:
            issues.append(f"Weak close position ({close_position:.0%} of range)")

    # 3. Risk-reward check
    if len(close) >= 14:
        tr = pd.concat([
            high - df["Low"],
            (high - close.shift()).abs(),
            (df["Low"] - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.iloc[-14:].mean()
        sl = latest - 1.3 * atr
        target = latest + 1.8 * atr
        risk = latest - sl
        reward = target - latest
        rr = reward / risk if risk > 0 else 0
        if rr < 1.0:
            issues.append(f"Unfavorable R:R = 1:{rr:.1f}")

    if len(issues) == 0:
        status = "PASS"
    elif len(issues) == 1:
        status = "BORDERLINE"
    else:
        status = "FAIL"

    return {
        "status": status,
        "value": f"{len(issues)} issues",
        "threshold": "Fresh breakout, clean entry",
        "details": "; ".join(issues) if issues else "Clean breakout entry",
        "issues": issues,
    }
