#!/usr/bin/env python3
"""Full-span test — neo_radar vs neo_extended, flat 15% vs flat 20%.

Runs on the cache built by deploy/build_screen_cache.py. Reports:

  1. Independent ~1-year windows, each a fresh Rs1,00,000 book, so no
     conclusion rests on a single regime. Only the final window overlaps
     anything used to choose a parameter.
  2. The continuous full-span compounding book.
  3. Compounding vs fixed sizing.
  4. A monthly withdrawal schedule — profit taken ONLY from closed trades,
     never by liquidating an open position, so it is grouped by exit month.

    python3 deploy/sim_report.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.sim_fast import run, benchmark, CACHE_DIR   # noqa: E402

FORMULAS = ["neo_radar", "neo_extended"]
STOPS = {
    "flat 15%": {"stop_mode": "flat", "stop_flat_pct": 15,
                 "use_target": False, "max_hold_bars": 60},
    "flat 20%": {"stop_mode": "flat", "stop_flat_pct": 20,
                 "use_target": False, "max_hold_bars": 60},
}


def discover():
    """Span and one-year windows taken from the cache the build actually made.

    Hardcoding the dates here once cost us a whole run: the build covered nine
    years and this report silently read only the last four. The cache is the
    authority on what was screened.
    """
    import pickle
    from datetime import datetime
    with open(os.path.join(CACHE_DIR, f"{FORMULAS[0]}.pkl"), "rb") as f:
        days = sorted(pickle.load(f)["days"].keys())
    lo, hi = days[0], days[-1]
    years = max(0.01, (datetime.fromisoformat(hi)
                       - datetime.fromisoformat(lo)).days / 365.25)
    windows, n = [], 0
    y0 = int(lo[:4])
    while True:                       # anniversary windows from the first bar
        a = f"{y0 + n}-{lo[5:7]}-01"
        b = f"{y0 + n + 1}-{lo[5:7]}-01"
        if a > hi:
            break
        b = min(b, hi)
        if (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days >= 120:
            n_lab = f"W{len(windows)+1} {a[:7]}→{b[:7]}"
            windows.append((n_lab, a, b))
        n += 1
    return (lo, hi), years, windows, days


def main():
    FULL, YEARS, WINDOWS, ALL_DAYS = discover()
    print(f"cache span {FULL[0]} → {FULL[1]}  ·  {len(ALL_DAYS)} screened days"
          f"  ·  {YEARS:.2f} years  ·  {len(WINDOWS)} one-year windows\n")
    from data.nse_symbols import get_nifty200_live, NIFTY_500_FALLBACK
    syms = list(get_nifty200_live() or []) or list(NIFTY_500_FALLBACK)[:200]
    cols = [(f, s) for f in FORMULAS for s in STOPS]

    print("=" * 108)
    print("INDEPENDENT ONE-YEAR WINDOWS — fresh Rs1,00,000 book each, 3 slots, compounding within the window")
    print("=" * 108)
    bms = {lab: benchmark(a, b, syms) for lab, a, b in WINDOWS}
    hdr = f"  {'WINDOW':<22}{'BENCH':>9}"
    for f, s in cols:
        hdr += f"{(f.split('_')[1][:4] + '/' + s[5:]):>14}"
    print(hdr)
    print("-" * 108)

    res = {c: [] for c in cols}
    tr = {c: 0 for c in cols}
    for lab, a, b in WINDOWS:
        row = f"  {lab:<22}{bms[lab]:>+8.2f}%"
        for c in cols:
            try:
                r = run(c[0], a, b, STOPS[c[1]])
                res[c].append(r["pnl_pct"])
                tr[c] += r["trades"]
                row += f"{r['pnl_pct']:>+13.2f}%"
            except Exception as e:
                res[c].append(float("nan"))
                row += f"{'n/a':>14}"
        print(row)
    print("-" * 108)

    def summary_row(label, fn):
        row = f"  {label:<22}{'':>9}"
        for c in cols:
            row += f"{fn(c):>14}"
        print(row)

    print(f"  {'MEAN':<22}{np.mean(list(bms.values())):>+8.2f}%"
          + "".join(f"{np.nanmean(res[c]):>+13.2f}%" for c in cols))
    summary_row("WINDOWS POSITIVE",
                lambda c: f"{sum(1 for x in res[c] if x > 0)}/{len(res[c])}")
    summary_row("BEAT BENCHMARK",
                lambda c: f"{sum(1 for (lab, _, _), x in zip(WINDOWS, res[c]) if x > bms[lab])}/{len(res[c])}")
    summary_row("TOTAL TRADES", lambda c: str(tr[c]))
    summary_row("WORST WINDOW", lambda c: f"{np.nanmin(res[c]):+.2f}%")

    print("\n" + "=" * 108)
    print(f"SCENARIO A — COMPOUNDING   {FULL[0]} → {FULL[1]} ({YEARS:.2f} years)")
    print("  Every rupee of profit is reinvested. Nothing is ever taken out.")
    print("=" * 108)
    print(f"  {'FORMULA':<14}{'STOP':<10}{'P&L%':>10}{'FINAL Rs':>12}"
          f"{'CAGR%':>8}{'MAXDD':>7}{'TR':>5}{'WIN%':>7}{'t':>7}")
    keep = {}
    for f in FORMULAS:
        for s_lab, cfg in STOPS.items():
            for mode, fx in (("compounding", False), ("fixed size", True)):
                try:
                    r = run(f, FULL[0], FULL[1], {**cfg, "fixed_sizing": fx})
                except Exception as e:
                    if mode == "compounding":
                        print(f"  {f:<14}{s_lab:<10}  FAILED: {e}")
                    continue
                keep[(f, s_lab, mode)] = r
            r = keep.get((f, s_lab, "compounding"))
            if not r:
                continue
            cagr = (((1 + r["pnl_pct"] / 100) ** (1 / YEARS) - 1) * 100
                    if r["pnl_pct"] > -100 else -100.0)
            t = f"{r['t_stat']:+.2f}" if r["t_stat"] is not None else "  -  "
            print(f"  {f:<14}{s_lab:<10}{r['pnl_pct']:>+10.2f}"
                  f"{100000 + r['pnl']:>12,.0f}{cagr:>+8.2f}{r['max_dd']:>7.1f}"
                  f"{r['trades']:>5}{r['win_rate']:>7.1f}{t:>7}")

    print("\n" + "=" * 108)
    print("SCENARIO B — NO COMPOUNDING, nothing withdrawn")
    print("  Every trade risks the same fixed rupee amount. Profit piles up as idle")
    print("  cash and is never redeployed, so gains stay linear instead of exponential.")
    print("=" * 108)
    print(f"  {'FORMULA':<14}{'STOP':<10}{'P&L%':>10}{'FINAL Rs':>12}"
          f"{'CAGR%':>8}{'MAXDD':>7}{'TR':>5}{'WIN%':>7}{'t':>7}")
    for f in FORMULAS:
        for s_lab in STOPS:
            r = keep.get((f, s_lab, "fixed size"))
            if not r:
                continue
            cagr = (((1 + r["pnl_pct"] / 100) ** (1 / YEARS) - 1) * 100
                    if r["pnl_pct"] > -100 else -100.0)
            t = f"{r['t_stat']:+.2f}" if r["t_stat"] is not None else "  -  "
            print(f"  {f:<14}{s_lab:<10}{r['pnl_pct']:>+10.2f}"
                  f"{100000 + r['pnl']:>12,.0f}{cagr:>+8.2f}{r['max_dd']:>7.1f}"
                  f"{r['trades']:>5}{r['win_rate']:>7.1f}{t:>7}")

    print("\n  A vs B — what compounding alone is worth:")
    print(f"  {'FORMULA':<14}{'STOP':<10}{'A compounding':>16}{'B flat':>12}{'difference':>13}")
    for f in FORMULAS:
        for s_lab in STOPS:
            a = keep.get((f, s_lab, "compounding")); b = keep.get((f, s_lab, "fixed size"))
            if not a or not b:
                continue
            print(f"  {f:<14}{s_lab:<10}{a['pnl_pct']:>+15.2f}%{b['pnl_pct']:>+11.2f}%"
                  f"{a['pnl_pct']-b['pnl_pct']:>+12.2f}%")

    bm_full = benchmark(FULL[0], FULL[1], syms)
    print(f"\n  benchmark — equal-weight Nifty 200 buy & hold, {YEARS:.2f} years: {bm_full:+.2f}% "
          f"({((1 + bm_full/100) ** (1/YEARS) - 1) * 100:+.2f}% CAGR)")

    print("\n" + "=" * 108)
    print("YEAR BY YEAR — each calendar year a fresh Rs1,00,000 book")
    print("=" * 108)
    cal = sorted({d[:4] for d in ALL_DAYS})
    for f in FORMULAS:
        for s_lab, cfg in STOPS.items():
            rows = []
            for y in cal:
                ds = [d for d in ALL_DAYS if d[:4] == y]
                if len(ds) < 60:
                    continue
                try:
                    r = run(f, ds[0], ds[-1], cfg)
                    b = benchmark(ds[0], ds[-1], syms)
                except Exception:
                    continue
                rows.append((y, len(ds), r["pnl_pct"], b, r["trades"], r["win_rate"]))
            if not rows:
                continue
            print(f"\n  {f} · {s_lab}")
            print(f"    {'YEAR':<7}{'DAYS':>6}{'P&L%':>9}{'BENCH%':>9}{'vs BM':>9}"
                  f"{'TRADES':>8}{'WIN%':>7}")
            for y, n, pl, b, t, w in rows:
                print(f"    {y:<7}{n:>6}{pl:>+9.2f}{b:>+9.2f}{pl-b:>+9.2f}{t:>8}{w:>7.1f}")
            pos = sum(1 for r in rows if r[2] > 0)
            beat = sum(1 for r in rows if r[2] > r[3])
            print(f"    {'':<7}{'':<6}  positive {pos}/{len(rows)} years · "
                  f"beat index {beat}/{len(rows)} years")

    print("\n" + "=" * 108)
    print("SCENARIO C — NO COMPOUNDING + MONTHLY CASH-OUT")
    print("  Fixed sizing, and each month the realised profit is taken out of the")
    print("  account. Only CLOSED trades contribute — an open position is never")
    print("  liquidated to fund a withdrawal, so profit is booked in its EXIT month.")
    print("=" * 108)
    months = pd.period_range(FULL[0][:7], FULL[1][:7], freq="M").astype(str)
    for f in FORMULAS:
        for s in STOPS:
            r = keep.get((f, s, "fixed size"))
            if not r or not r["trade_list"]:
                continue
            df = pd.DataFrame({"net": [t["net"] for t in r["trade_list"]],
                               "m": [t["exit_date"][:7] for t in r["trade_list"]]})
            m = df.groupby("m")["net"].sum().reindex(months, fill_value=0.0)
            print(f"\n  {f} · {s}   total {m.sum():+,.0f} over {len(m)} months "
                  f"= {m.sum() / len(m):+,.0f}/month average")
            print(f"    median {m.median():+,.0f} · best {m.max():+,.0f} · worst {m.min():+,.0f}")
            print(f"    profitable {int((m > 0).sum())} months · losing {int((m < 0).sum())}"
                  f" · nothing closed {int((m == 0).sum())}")
            longest = cur = 0
            for x in m:
                cur = cur + 1 if x <= 0 else 0
                longest = max(longest, cur)
            print(f"    longest run with no income: {longest} months")
            best_w = 0
            for w in range(0, 15001, 250):
                bal, ok = 100000.0, True
                for x in m:
                    bal += x - w
                    if bal < 75000:
                        ok = False
                        break
                if ok and bal >= 100000:
                    best_w = w
            print(f"    largest sustainable draw (capital intact, never below Rs75k): "
                  f"Rs{best_w:,}/month")

    print("\n" + "=" * 108)
    print("TRADES — best configuration by mean window return")
    print("=" * 108)
    usable = [c for c in cols if not all(np.isnan(x) for x in res[c])]
    if not usable:
        print("  no usable configuration")
        return
    best = max(usable, key=lambda c: np.nanmean(res[c]))
    print(f"  {best[0]} · {best[1]}\n")
    try:
        r = run(best[0], FULL[0], FULL[1], STOPS[best[1]])
    except Exception as e:
        print(f"  failed: {e}")
        return
    nets = np.array([t["net"] for t in r["trade_list"]])
    for t in sorted(r["trade_list"], key=lambda x: x["entry_date"]):
        print(f"    {t['symbol']:<12}{t['entry_date']}→{t['exit_date']}  {t['bars']:>3}d  "
              f"{t['pct']:>+7.2f}%  {t['net']:>+9,.0f}  {t['reason']}")
    if len(nets):
        srt = np.sort(nets)
        print(f"\n    total {nets.sum():+,.0f} · best trade {srt[-1]:+,.0f} "
              f"({srt[-1] / nets.sum() * 100:.0f}% of total)")
        print(f"    without best: {nets.sum() - srt[-1]:+,.0f} · "
              f"without top 3: {nets.sum() - srt[-3:].sum():+,.0f}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        print("\nReport failed. The cache is still on disk — rerun with:")
        print("  python3 deploy/sim_report.py")
