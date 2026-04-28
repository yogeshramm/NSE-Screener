"""
Backtest harness for engine/optimal_levels.py methodology.

Walks history backwards: at each sample point, computes the trade plan using
ONLY the data available at that point, then watches the next 60 bars to see
which level was hit first — entry trigger? target? stop? hold-time expiry?

Aggregates win rate, expectancy, hit-rate by confidence band, by regime.
This tells us whether the methodology has edge — independent of any live UI.

Usage:
    from engine.optimal_levels_backtest import backtest_one, run_aggregate
    print(backtest_one("RELIANCE"))
    print(run_aggregate(["RELIANCE","TCS","INFY", ...]))
"""

from typing import List, Dict, Any, Optional
import os
import pandas as pd
from collections import defaultdict

from engine.optimal_levels import _compute_from_df
from data.nse_history import load_history


def _simulate_outcome(plan: Dict[str, Any], future_df) -> Dict[str, Any]:
    """Walk forward through `future_df` (the bars AFTER the as-of date)
    and determine outcome of the trade plan:

      • entry_hit  — did price reach the entry trigger?
      • exit_reason — 'target', 'stop', 'hold_expiry', 'never_entered'
      • bars_to_entry / bars_to_exit
      • realized_pnl_pct (relative to entry)
      • realized_r       (P&L in R-multiples)

    Long-only. Entry triggers when:
       — Pullback / continuation / range_low: when low ≤ entry (limit fill)
       — Range_breakout: when high ≥ entry (stop-buy)
    Exit:
       — Stop hit when low ≤ stop_loss
       — Target hit when high ≥ target
       — Both in same bar: assume STOP first (conservative)
       — Hold expiry: 60 bars
    """
    if not plan.get("tradeable") or plan.get("entry") is None:
        return {"exit_reason": "no_setup"}

    entry = plan["entry"]
    stop = plan["stop_loss"]
    target = plan["target"]
    setup = plan.get("setup_type", "")
    risk = entry - stop

    if future_df is None or len(future_df) == 0:
        return {"exit_reason": "no_future_data"}

    # 1. Find entry trigger
    entry_idx = None
    for i in range(len(future_df)):
        bar = future_df.iloc[i]
        if setup == "range_breakout":
            if float(bar["High"]) >= entry:
                entry_idx = i; break
        else:
            # Limit / market entry — triggers if price touches entry from above
            # (or already at/below from start)
            if float(bar["Low"]) <= entry <= float(bar["High"]):
                entry_idx = i; break
            # Some plans set entry above current price (e.g. just after pullback);
            # still trigger if open>entry and we're in a continuation context
            if i == 0 and float(bar["Open"]) <= entry:
                entry_idx = i; break

    if entry_idx is None:
        return {
            "exit_reason": "never_entered",
            "bars_observed": len(future_df),
            "entry": entry, "stop": stop, "target": target,
        }

    # 2. From entry_idx onward, watch for stop / target / expiry
    after_entry = future_df.iloc[entry_idx:]
    for j in range(len(after_entry)):
        bar = after_entry.iloc[j]
        h, l = float(bar["High"]), float(bar["Low"])
        stop_hit = l <= stop
        target_hit = h >= target
        if stop_hit and target_hit:
            # Assume stop first (conservative)
            return {
                "exit_reason": "stop_first_same_bar",
                "bars_to_entry": entry_idx,
                "bars_to_exit": j,
                "realized_pnl_pct": round((stop - entry) / entry * 100, 2),
                "realized_r": round((stop - entry) / risk, 2) if risk > 0 else None,
            }
        if stop_hit:
            return {
                "exit_reason": "stop",
                "bars_to_entry": entry_idx,
                "bars_to_exit": j,
                "realized_pnl_pct": round((stop - entry) / entry * 100, 2),
                "realized_r": -1.0,
            }
        if target_hit:
            return {
                "exit_reason": "target",
                "bars_to_entry": entry_idx,
                "bars_to_exit": j,
                "realized_pnl_pct": round((target - entry) / entry * 100, 2),
                "realized_r": round((target - entry) / risk, 2) if risk > 0 else None,
            }

    # 3. No exit hit within window → mark to last close
    last_close = float(after_entry.iloc[-1]["Close"])
    return {
        "exit_reason": "hold_expiry",
        "bars_to_entry": entry_idx,
        "bars_to_exit": len(after_entry) - 1,
        "realized_pnl_pct": round((last_close - entry) / entry * 100, 2),
        "realized_r": round((last_close - entry) / risk, 2) if risk > 0 else None,
    }


def backtest_one(symbol: str, samples: int = 8, sample_step: int = 12,
                 forward_window: int = 60, oldest_offset: int = 220) -> List[Dict[str, Any]]:
    """For one stock, generate `samples` historical plans + outcomes.

    Walks backwards from `oldest_offset` bars ago in steps of `sample_step`,
    skipping the most recent `forward_window` bars (so each plan has at
    least `forward_window` future bars to evaluate).
    """
    df = load_history(symbol)
    if df is None or len(df) < oldest_offset + forward_window + 60:
        return []

    out = []
    # Generate sample points: most-recent first (just past forward_window from end),
    # going backwards in time
    for k in range(samples):
        offset_from_end = forward_window + k * sample_step
        if offset_from_end + 60 > len(df):
            break
        history = df.iloc[: -offset_from_end] if offset_from_end > 0 else df
        future = df.iloc[-offset_from_end : -(offset_from_end - forward_window) if offset_from_end > forward_window else None]
        if len(future) < 10:
            continue
        plan = _compute_from_df(history, symbol)
        if plan is None:
            continue
        outcome = _simulate_outcome(plan, future)
        # Slim record (drop the big rationale list to keep aggregates compact)
        rec = {
            "symbol": symbol,
            "as_of": str(history.index[-1].date()) if len(history) else None,
            "regime": plan.get("regime"),
            "tradeable": plan.get("tradeable"),
            "confidence": plan.get("confidence"),
            "score": plan.get("score"),
            "setup_type": plan.get("setup_type"),
            "entry": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "target": plan.get("target"),
            "risk_reward": plan.get("risk_reward"),
            "risk_pct": plan.get("risk_pct"),
            **outcome,
        }
        out.append(rec)
    return out


def run_aggregate(symbols: List[str], samples_per_stock: int = 6,
                  forward_window: int = 60) -> Dict[str, Any]:
    """Run backtest_one across many stocks, return summary statistics."""
    all_plans = []
    for sym in symbols:
        all_plans.extend(backtest_one(sym, samples=samples_per_stock,
                                      forward_window=forward_window))

    tradeable = [p for p in all_plans if p.get("tradeable")]
    entered = [p for p in tradeable if p.get("exit_reason") not in ("never_entered", "no_future_data", "no_setup", None)]
    wins = [p for p in entered if p.get("realized_r") is not None and p["realized_r"] > 0]
    losses = [p for p in entered if p.get("realized_r") is not None and p["realized_r"] <= 0]

    def _avg(xs):
        return round(sum(xs) / len(xs), 2) if xs else None
    def _safe_r(p):
        r = p.get("realized_r")
        return r if r is not None else 0

    summary = {
        "stocks_tested": len(symbols),
        "plans_generated": len(all_plans),
        "tradeable_plans": len(tradeable),
        "trades_entered": len(entered),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": round(len(wins) / len(entered) * 100, 1) if entered else None,
        "avg_R": _avg([_safe_r(p) for p in entered]),
        "avg_R_winners": _avg([p["realized_r"] for p in wins if p.get("realized_r") is not None]),
        "avg_R_losers": _avg([p["realized_r"] for p in losses if p.get("realized_r") is not None]),
        "avg_pnl_pct": _avg([p.get("realized_pnl_pct") or 0 for p in entered]),
        "expectancy_R_per_trade": _avg([_safe_r(p) for p in entered]),
        "fill_rate_pct": round(len(entered) / len(tradeable) * 100, 1) if tradeable else None,
    }

    # Breakdown by regime
    by_regime = defaultdict(lambda: {"n": 0, "wins": 0, "avg_R": 0.0, "total_R": 0.0})
    for p in entered:
        b = by_regime[p.get("regime") or "?"]
        b["n"] += 1
        if p.get("realized_r", 0) > 0:
            b["wins"] += 1
        b["total_R"] += _safe_r(p)
    for k, v in by_regime.items():
        v["win_rate_pct"] = round(v["wins"] / v["n"] * 100, 1) if v["n"] else 0
        v["avg_R"] = round(v["total_R"] / v["n"], 2) if v["n"] else 0
        del v["total_R"]
    summary["by_regime"] = dict(by_regime)

    # Breakdown by confidence band
    by_conf = defaultdict(lambda: {"n": 0, "wins": 0, "total_R": 0.0})
    for p in entered:
        b = by_conf[p.get("confidence") or "?"]
        b["n"] += 1
        if p.get("realized_r", 0) > 0:
            b["wins"] += 1
        b["total_R"] += _safe_r(p)
    for k, v in by_conf.items():
        v["win_rate_pct"] = round(v["wins"] / v["n"] * 100, 1) if v["n"] else 0
        v["avg_R"] = round(v["total_R"] / v["n"], 2) if v["n"] else 0
        del v["total_R"]
    summary["by_confidence"] = dict(by_conf)

    # Exit-reason mix
    reasons = defaultdict(int)
    for p in entered:
        reasons[p.get("exit_reason", "?")] += 1
    summary["exit_reasons"] = dict(reasons)

    return summary
