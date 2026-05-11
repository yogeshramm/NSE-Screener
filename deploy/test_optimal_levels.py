#!/usr/bin/env python3
"""
Backtest harness for engine/optimal_levels.py.

For each stock, slides a window across historical data and simulates:
  - A "plan" is generated at bar N using history[:N]
  - We look forward max_bars bars:
      WIN  = price hits target before stop
      LOSS = price hits stop before target
      TIMEOUT = neither hit in max_bars (PnL at last bar)

Reports: win rate, avg R:R, expectancy (R multiple), distribution by regime/confidence.

Usage:
    python3 deploy/test_optimal_levels.py [--all] [--n 50] [--max-bars 45] [--skip 30]
    python3 deploy/test_optimal_levels.py --symbols RELIANCE TCS INFY HDFCBANK
"""

import os, sys, random, argparse, pickle, math
from datetime import date

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

HIST = os.path.join(PROJECT, "data_store", "history")

def load_all_symbols():
    return [f[:-4] for f in os.listdir(HIST) if f.endswith(".pkl")]

def run_backtest(symbols, max_bars=45, skip_last=30, min_bars=120, verbose=False):
    """
    For each symbol, pick ONE signal (at data[-skip_last-1] to avoid look-ahead)
    and simulate the forward outcome.
    """
    from engine.optimal_levels import _compute_from_df
    import pandas as pd

    results = []
    errors = 0

    for sym in symbols:
        p = os.path.join(HIST, f"{sym}.pkl")
        if not os.path.exists(p):
            continue
        try:
            df = pickle.load(open(p, "rb"))
            if not isinstance(df, pd.DataFrame) or len(df) < min_bars + skip_last + max_bars:
                continue
            # Signal date: skip_last bars from end (so we have forward data)
            signal_n = len(df) - skip_last - max_bars
            if signal_n < min_bars:
                continue

            df_signal = df.iloc[:signal_n]
            plan = _compute_from_df(df_signal, sym)
            if plan is None or not plan.get("tradeable"):
                results.append({
                    "symbol": sym, "tradeable": False,
                    "regime": plan.get("regime","?") if plan else "?",
                    "confidence": plan.get("confidence","?") if plan else "?",
                    "score": plan.get("score", 0) if plan else 0,
                    "outcome": "skip",
                })
                continue

            entry = plan["entry"]
            sl    = plan["stop_loss"]
            tgt   = plan["target"]
            if entry is None or sl is None or tgt is None:
                continue
            risk  = entry - sl
            if risk <= 0:
                continue

            # Forward walk from signal_n onward
            fwd = df.iloc[signal_n:signal_n + max_bars]
            outcome = "timeout"
            exit_price = float(fwd["Close"].iloc[-1])

            for _, bar in fwd.iterrows():
                lo = float(bar["Low"])
                hi = float(bar["High"])
                if lo <= sl:       # stop hit
                    outcome = "loss"
                    exit_price = sl
                    break
                if hi >= tgt:      # target hit
                    outcome = "win"
                    exit_price = tgt
                    break

            r_multiple = (exit_price - entry) / risk

            results.append({
                "symbol": sym,
                "tradeable": True,
                "regime": plan["regime"],
                "confidence": plan["confidence"],
                "score": plan["score"],
                "setup_type": plan["setup_type"],
                "entry": entry,
                "stop_loss": sl,
                "target": tgt,
                "risk_pct": plan["risk_pct"],
                "rr": plan["risk_reward"],
                "outcome": outcome,
                "exit_price": round(exit_price, 2),
                "r_multiple": round(r_multiple, 3),
            })
            if verbose:
                col = "\033[32m" if outcome == "win" else "\033[31m" if outcome == "loss" else "\033[33m"
                print(f"  {col}{sym:<16}\033[0m {plan['regime']:<18} {plan['confidence']:<12} score={plan['score']:>3} → {outcome:<8}  R={r_multiple:+.2f}")

        except Exception as e:
            errors += 1
            if verbose:
                print(f"  ERR {sym}: {e}")

    return results, errors


def print_report(results, max_bars):
    tradeable = [r for r in results if r["tradeable"]]
    if not tradeable:
        print("No tradeable setups found.")
        return

    wins    = [r for r in tradeable if r["outcome"] == "win"]
    losses  = [r for r in tradeable if r["outcome"] == "loss"]
    timeouts= [r for r in tradeable if r["outcome"] == "timeout"]

    win_rate  = len(wins)   / len(tradeable) * 100
    loss_rate = len(losses) / len(tradeable) * 100
    to_rate   = len(timeouts)/len(tradeable) * 100
    avg_r = sum(r["r_multiple"] for r in tradeable) / len(tradeable)
    avg_win_r  = sum(r["r_multiple"] for r in wins)   / len(wins)   if wins   else 0
    avg_loss_r = sum(r["r_multiple"] for r in losses) / len(losses) if losses else 0
    expectancy = avg_r  # E[R] per trade

    print(f"\n{'='*60}")
    print(f"  OPTIMAL LEVELS BACKTEST  ({len(tradeable)} tradeable setups, {max_bars}-bar forward window)")
    print(f"{'='*60}")
    print(f"  Win   rate : {win_rate:>5.1f}%  (n={len(wins)})")
    print(f"  Loss  rate : {loss_rate:>5.1f}%  (n={len(losses)})")
    print(f"  Timeout    : {to_rate:>5.1f}%  (n={len(timeouts)})")
    print(f"  Avg R/trade: {avg_r:>+.3f}R")
    print(f"  Avg Win  R : {avg_win_r:>+.3f}R")
    print(f"  Avg Loss R : {avg_loss_r:>+.3f}R")
    print(f"  Expectancy : {expectancy:>+.3f}R/trade  ({'POSITIVE ✓' if expectancy > 0 else 'NEGATIVE ✗'})")

    # By confidence
    print(f"\n  --- By Confidence ---")
    for conf in ("high", "moderate", "low", "very_low"):
        sub = [r for r in tradeable if r["confidence"] == conf]
        if not sub: continue
        sub_wins = sum(1 for r in sub if r["outcome"]=="win")
        sub_r = sum(r["r_multiple"] for r in sub) / len(sub)
        print(f"  {conf:<12}: n={len(sub):<4} WR={sub_wins/len(sub)*100:>5.1f}%  E={sub_r:>+.3f}R")

    # By regime
    print(f"\n  --- By Regime ---")
    for reg in ("uptrend", "early_uptrend", "sideways", "downtrend"):
        sub = [r for r in tradeable if r["regime"] == reg]
        if not sub: continue
        sub_wins = sum(1 for r in sub if r["outcome"]=="win")
        sub_r = sum(r["r_multiple"] for r in sub) / len(sub)
        print(f"  {reg:<20}: n={len(sub):<4} WR={sub_wins/len(sub)*100:>5.1f}%  E={sub_r:>+.3f}R")

    # By score band
    print(f"\n  --- By Score Band ---")
    bands = [(75,100,"high conf (≥75)"),(55,74,"moderate (55-74)"),(35,54,"low (35-54)"),(0,34,"very low (<35)")]
    for lo, hi, label in bands:
        sub = [r for r in tradeable if lo <= r["score"] <= hi]
        if not sub: continue
        sub_wins = sum(1 for r in sub if r["outcome"]=="win")
        sub_r = sum(r["r_multiple"] for r in sub) / len(sub)
        print(f"  {label:<24}: n={len(sub):<4} WR={sub_wins/len(sub)*100:>5.1f}%  E={sub_r:>+.3f}R")

    skipped = [r for r in results if not r["tradeable"]]
    total = len(results)
    print(f"\n  Skipped (not tradeable): {len(skipped)}/{total} ({len(skipped)/total*100:.0f}%)")
    if skipped:
        regime_counts = {}
        for r in skipped:
            regime_counts[r["regime"]] = regime_counts.get(r["regime"],0) + 1
        print("  Skip reasons (regime): " + ", ".join(f"{k}={v}" for k,v in sorted(regime_counts.items(), key=lambda x:-x[1])))


def main():
    ap = argparse.ArgumentParser(description="Backtest optimal_levels engine")
    ap.add_argument("--all", action="store_true", help="Test all available stocks")
    ap.add_argument("--n", type=int, default=100, help="Number of random stocks to test (default 100)")
    ap.add_argument("--max-bars", type=int, default=45, help="Forward bars to look for win/loss (default 45)")
    ap.add_argument("--skip", type=int, default=30, help="Bars to skip from end (default 30)")
    ap.add_argument("--symbols", nargs="+", help="Specific symbols to test")
    ap.add_argument("--verbose", "-v", action="store_true", help="Per-stock output")
    ap.add_argument("--min-score", type=int, default=0, help="Only test setups with score >= this")
    args = ap.parse_args()

    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
        print(f"Testing {len(symbols)} specific symbols…")
    elif args.all:
        symbols = load_all_symbols()
        print(f"Testing ALL {len(symbols)} symbols…")
    else:
        all_syms = load_all_symbols()
        # Filter to likely-valid liquid stocks (skip ETFs, indices, bond funds)
        # Simple heuristic: symbols with len >= 4 and no digit-heavy names
        def _is_stock(s):
            if len(s) < 3: return False
            if s.endswith(('BEES','ETF','NIFTY','FUND','GOLDBEES','SGBBEES')): return False
            return True
        filtered = [s for s in all_syms if _is_stock(s)]
        random.seed(42)  # reproducible
        symbols = random.sample(filtered, min(args.n, len(filtered)))
        print(f"Testing {len(symbols)} random stocks (seed=42)…")

    results, errors = run_backtest(
        symbols,
        max_bars=args.max_bars,
        skip_last=args.skip,
        verbose=args.verbose
    )

    if args.min_score > 0:
        print(f"\n[Filtering to score >= {args.min_score}]")
        results = [r for r in results if not r["tradeable"] or r["score"] >= args.min_score]

    print_report(results, args.max_bars)
    if errors:
        print(f"\n  ({errors} errors during processing)")


if __name__ == "__main__":
    main()
