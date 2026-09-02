#!/usr/bin/env python3
"""Build a split/bonus-adjusted price series alongside the raw one.

Raw NSE prices are what actually traded, and they step at every corporate
action. A backtest reading raw data books MOTHERSON's 1:2 bonus as a 33%
loss that never happened. Indicators, 52-week highs and returns all need a
continuous series; charts and audit need the raw one. So we keep both,
never mixed:

    data_store/history/           raw, exactly as NSE printed it
    data_store/history_adjusted/  raw x cumulative factor  (this script)

Factor sources, in order of authority:

    bonus / split   EXACT, parsed from NSE's own announcement text.
                    "Bonus 1:2" -> hold 2, get 1 -> factor 2/3.
    rights          Derived from the announced ratio and subscription price
                    together with the cum-date market price.
    demerger        NSE publishes the event but never a value split, so the
                    factor is MEASURED at the ex-date NSE published, with the
                    day's whole-market move netted out. We never infer that an
                    event happened from a price gap — only its size.

A bar is multiplied by the product of the factors of every action dated after
it, putting the whole history on today's share basis. Volume is divided by the
same factor so turnover stays consistent.

Verification: after adjustment the step at each ex-date must vanish. Any
symbol where it does not is reported, not silently accepted.

    python3 deploy/build_adjusted_history.py --dry-run
    python3 deploy/build_adjusted_history.py --symbols TCS,RELIANCE
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

RAW = os.path.join(ROOT, "data_store", "history")
ADJ = os.path.join(ROOT, "data_store", "history_adjusted")
CA = os.path.join(ROOT, "data_store", "corporate_actions")
REPORT = os.path.join(CA, "_adjustment_report.json")


def log(m):
    print(f"{datetime.now():%H:%M:%S}  {m}", flush=True)


_market_cache: dict = {}


def market_move(day: pd.Timestamp, prev: pd.Timestamp, universe: dict) -> float:
    """Median open/prev-close move across the universe — the day's drift."""
    key = (str(day.date()), str(prev.date()))
    if key in _market_cache:
        return _market_cache[key]
    r = []
    for df in universe.values():
        if day in df.index and prev in df.index:
            pc = float(df.at[prev, "Close"])
            op = float(df.at[day, "Open"])
            if pc > 0 and op > 0:
                r.append(op / pc)
    out = float(np.median(r)) if len(r) >= 30 else 1.0
    _market_cache[key] = out
    return out


def derive_factor(df: pd.DataFrame, ex_date: str, universe: dict):
    """Measure the factor at an ex-date NSE published. Returns (factor, note)."""
    ts = pd.Timestamp(ex_date)
    idx = df.index
    after = idx[idx >= ts]
    before = idx[idx < ts]
    if len(after) == 0 or len(before) == 0:
        return None, "ex-date outside the series"
    d1, d0 = after[0], before[-1]
    c0 = float(df.at[d0, "Close"])
    o1 = float(df.at[d1, "Open"])
    if c0 <= 0 or o1 <= 0:
        return None, "bad prices at ex-date"
    mkt = market_move(d1, d0, universe)
    f = (o1 / c0) / (mkt if mkt > 0 else 1.0)
    if not (0.05 < f < 1.02):
        return None, f"measured {f:.4f} outside plausible range"
    return float(f), f"measured at {ex_date}: {c0:.2f} -> {o1:.2f}, market {mkt:.4f}"


def actions_for(sym: str):
    p = os.path.join(CA, f"{sym}.json")
    if not os.path.exists(p):
        return [], []
    r = json.load(open(p))
    exact = [a for a in r.get("actions", []) if a.get("factor")]
    pending = [u for u in r.get("unparsed", []) if u.get("needs_derivation")]
    return exact, pending


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    os.makedirs(ADJ, exist_ok=True)
    syms = ([s.strip().upper() for s in args.symbols.split(",")] if args.symbols
            else sorted(f[:-4] for f in os.listdir(RAW) if f.endswith(".pkl")))

    log(f"loading {len(syms)} symbols")
    universe = {}
    for s in syms:
        try:
            d = pickle.load(open(os.path.join(RAW, f"{s}.pkl"), "rb"))
        except Exception:
            continue
        universe[s] = d[~d.index.duplicated(keep="last")].sort_index()

    report = {"generated": datetime.now().isoformat(), "symbols": {},
              "unresolved": [], "verify_failed": []}
    adjusted = passthrough = 0
    n_exact = n_derived = n_failed = 0

    for s in syms:
        df = universe.get(s)
        if df is None or df.empty:
            continue
        exact, pending = actions_for(s)
        factors = []                       # (ex_date, factor, kind, source)
        for a in exact:
            factors.append((a["ex_date"], float(a["factor"]), a["kind"], "announcement"))
            n_exact += 1
        for u in pending:
            f, note = derive_factor(df, u["ex_date"], universe)
            if f is None:
                n_failed += 1
                report["unresolved"].append(
                    {"symbol": s, "ex_date": u["ex_date"], "kind": u["kind"], "why": note})
                continue
            factors.append((u["ex_date"], f, u["kind"], "measured"))
            n_derived += 1

        if not factors:
            out = df.copy()
            passthrough += 1
        else:
            factors.sort()
            out = df.copy().astype({c: "float64" for c in ("Open", "High", "Low", "Close")})
            cum = np.ones(len(out))
            dates = out.index.values
            for ex, f, _k, _src in factors:
                cum = np.where(dates < np.datetime64(pd.Timestamp(ex)), cum * f, cum)
            for c in ("Open", "High", "Low", "Close"):
                out[c] = out[c].values * cum
            if "Volume" in out.columns:
                out["Volume"] = out["Volume"].values / np.where(cum == 0, 1, cum)
            adjusted += 1

            # verification: the step at each ex-date must be gone
            for ex, f, kind, src in factors:
                ts = pd.Timestamp(ex)
                a = out.index[out.index < ts]
                b = out.index[out.index >= ts]
                if len(a) == 0 or len(b) == 0:
                    continue
                step = float(out.at[b[0], "Open"]) / float(out.at[a[-1], "Close"])
                mkt = market_move(b[0], a[-1], universe)
                resid = step / (mkt if mkt > 0 else 1.0)
                if not (0.85 < resid < 1.18):
                    report["verify_failed"].append(
                        {"symbol": s, "ex_date": ex, "kind": kind, "source": src,
                         "residual_step": round(resid, 4)})

            report["symbols"][s] = [
                {"ex_date": e, "factor": round(f, 6), "kind": k, "source": sr}
                for e, f, k, sr in factors]

        if not args.dry_run:
            p = os.path.join(ADJ, f"{s}.pkl")
            tmp = p + ".tmp"
            with open(tmp, "wb") as fh:
                pickle.dump(out, fh, protocol=4)
            os.replace(tmp, p)

    if not args.dry_run:
        json.dump(report, open(REPORT, "w"), indent=1)

    print("\n" + "=" * 76)
    print("ADJUSTED HISTORY" + (" (DRY RUN)" if args.dry_run else ""))
    print("=" * 76)
    print(f"  symbols adjusted            {adjusted}")
    print(f"  symbols with no actions     {passthrough}")
    print(f"  factors from announcement   {n_exact}   (exact — bonus / split)")
    print(f"  factors measured at ex-date {n_derived}   (rights / demerger)")
    print(f"  could not resolve           {n_failed}")
    print(f"  ex-date step NOT removed    {len(report['verify_failed'])}")
    for v in report["verify_failed"][:8]:
        print(f"     {v['symbol']:<12}{v['ex_date']}  {v['kind']:<10}"
              f"residual {v['residual_step']}")
    for u in report["unresolved"][:5]:
        print(f"     unresolved {u['symbol']:<12}{u['ex_date']}  {u['why']}")
    if not args.dry_run:
        print(f"\n  written to {ADJ}")
        print(f"  report     {REPORT}")


if __name__ == "__main__":
    main()
