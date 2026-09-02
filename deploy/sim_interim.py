#!/usr/bin/env python3
"""Run the sims on whatever the cache build has finished so far.

The build checkpoints completed days, so partial results are real results for
the window covered — not an estimate. Each run reports the actual span, so a
number is never read as though it covered more than it does.

    python3 deploy/sim_interim.py
"""
from __future__ import annotations
import os, pickle, shutil, sys, json
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PARTIAL = os.path.join(ROOT, "data_store", "sim_cache", "_partial.pkl")
SNAP = os.path.join(ROOT, "data_store", "sim_cache_interim")

STOPS = {"flat 15%": {"stop_mode": "flat", "stop_flat_pct": 15,
                      "use_target": False, "max_hold_bars": 60},
         "flat 20%": {"stop_mode": "flat", "stop_flat_pct": 20,
                      "use_target": False, "max_hold_bars": 60}}


def main():
    if not os.path.exists(PARTIAL):
        print("no checkpoint yet"); return
    d = pickle.load(open(PARTIAL, "rb"))
    store = d["store"]; names = d["formulas"]
    days = sorted(store[names[0]].keys())
    if len(days) < 60:
        print(f"only {len(days)} days screened — too few to simulate yet"); return

    os.makedirs(SNAP, exist_ok=True)
    meta = {"universe": "nifty200", "days": len(days),
            "start": days[0], "end": days[-1], "formulas": names, "partial": True}
    for n in names:
        pickle.dump({"meta": meta, "days": store[n]},
                    open(os.path.join(SNAP, f"{n}.pkl"), "wb"), protocol=4)

    import engine.sim_fast as SF
    SF.CACHE_DIR = SNAP
    from engine.sim_fast import run, benchmark
    from data.nse_symbols import get_nifty200_live, NIFTY_500_FALLBACK
    syms = list(get_nifty200_live() or []) or list(NIFTY_500_FALLBACK)[:200]
    bm = benchmark(days[0], days[-1], syms)
    yrs = max(0.01, (datetime.fromisoformat(days[-1]) - datetime.fromisoformat(days[0])).days / 365.25)

    print("=" * 88)
    print(f"INTERIM · {len(days)} days screened · {days[0]} → {days[-1]}  ({yrs:.2f} yrs)")
    print(f"benchmark, equal-weight Nifty 200 buy & hold: {bm:+.2f}%")
    print("=" * 88)
    print(f"  {'BOOK':<24}{'P&L%':>9}{'CAGR%':>8}{'TRADES':>8}{'WIN%':>7}"
          f"{'MAXDD':>8}{'t':>7}  vs BM")
    for f in names:
        for lab, cfg in STOPS.items():
            try:
                r = run(f, days[0], days[-1], cfg)
            except Exception as e:
                print(f"  {f+' / '+lab:<24}  failed: {e}"); continue
            cagr = ((1 + r["pnl_pct"] / 100) ** (1 / yrs) - 1) * 100 if r["pnl_pct"] > -100 else -100
            t = f"{r['t_stat']:+.2f}" if r["t_stat"] is not None else "  -  "
            print(f"  {f+' / '+lab:<24}{r['pnl_pct']:>+9.2f}{cagr:>+8.2f}{r['trades']:>8}"
                  f"{r['win_rate']:>7.1f}{r['max_dd']:>8.1f}{t:>7}"
                  f"{r['pnl_pct']-bm:>+8.2f}")
    # ── year by year ────────────────────────────────────────────────────────
    # A single aggregate hides whether an edge persists. Running each calendar
    # year as its own fresh Rs1L book shows which years actually worked and
    # whether one year is carrying the whole result.
    years = sorted({d[:4] for d in days})
    for f in names:
        for lab, cfg in STOPS.items():
            rows = []
            for y in years:
                yd = [d for d in days if d[:4] == y]
                if len(yd) < 40:
                    continue
                try:
                    r = run(f, yd[0], yd[-1], cfg)
                except Exception:
                    continue
                b = benchmark(yd[0], yd[-1], syms)
                rows.append((y, r, b, len(yd)))
            if not rows:
                continue
            print(f"\n  {f} / {lab} — year by year (fresh Rs1,00,000 each year)")
            print(f"    {'YEAR':<7}{'DAYS':>6}{'P&L%':>9}{'BENCH%':>9}{'vs BM':>8}"
                  f"{'TRADES':>8}{'WIN%':>7}{'MAXDD':>7}")
            beat = 0
            for y, r, b, nd in rows:
                beat += r["pnl_pct"] > b
                print(f"    {y:<7}{nd:>6}{r['pnl_pct']:>+9.2f}{b:>+9.2f}"
                      f"{r['pnl_pct']-b:>+8.2f}{r['trades']:>8}{r['win_rate']:>7.1f}"
                      f"{r['max_dd']:>7.1f}")
            pos = sum(1 for _, r, _, _ in rows if r["pnl_pct"] > 0)
            print(f"    {'':<7}{'':<6}  positive {pos}/{len(rows)} years · "
                  f"beat index {beat}/{len(rows)} years")

    print(f"\n  (partial — {len(days)} of 2,294 days. Early years are a different")
    print("   regime from recent ones, so these will move as the build advances.)")


if __name__ == "__main__":
    main()
