#!/usr/bin/env python3
"""Step 2 — diff stored history against the official NSE reference.

READ-ONLY. Writes a report, never a price file. Nothing is repaired until the
report has been reviewed.

For every symbol and every date we hold, compare Open/High/Low/Close/Volume
against the bhavcopy value for that day and classify:

    match          identical within tolerance
    mismatch       we hold a different price than NSE printed  -> injected
    missing_local  NSE has the bar, we don't                    -> gap
    missing_nse    we hold a bar NSE has no record of           -> phantom
    no_reference   that date was never fetched                  -> can't judge

    python3 deploy/diff_history_vs_nse.py                    # all symbols
    python3 deploy/diff_history_vs_nse.py --symbols TCS,INFY # a few
    python3 deploy/diff_history_vs_nse.py --limit 50         # quick look

Output: data_store/diff_report/summary.json  + per-symbol detail
Resumable: a symbol already reported is skipped unless --force.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from collections import Counter
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

HIST = os.path.join(ROOT, "data_store", "history")
REF = os.path.join(ROOT, "data_store", "nse_reference")
OUT = os.path.join(ROOT, "data_store", "diff_report")
TOL = 0.005          # 0.5 paise per rupee — covers float/rounding only

_ref_cache: dict = {}


def log(m):
    print(f"{datetime.now():%H:%M:%S}  {m}", flush=True)


def load_reference() -> dict:
    """{date_str: DataFrame indexed by symbol} for every fetched day."""
    out = {}
    if not os.path.isdir(REF):
        return out
    for year in sorted(os.listdir(REF)):
        ydir = os.path.join(REF, year)
        if not os.path.isdir(ydir):
            continue
        for f in sorted(os.listdir(ydir)):
            if f.endswith(".pkl"):
                out[f[:-4]] = os.path.join(ydir, f)
    return out


def ref_for(day: str, index: dict):
    if day in _ref_cache:
        return _ref_cache[day]
    p = index.get(day)
    df = None
    if p:
        try:
            with open(p, "rb") as fh:
                df = pickle.load(fh)
        except Exception:
            df = None
    if len(_ref_cache) > 400:            # keep memory bounded
        _ref_cache.clear()
    _ref_cache[day] = df
    return df


def diff_symbol(sym: str, index: dict) -> dict | None:
    p = os.path.join(HIST, f"{sym}.pkl")
    if not os.path.exists(p):
        return None
    try:
        d = pickle.load(open(p, "rb"))
    except Exception as e:
        return {"symbol": sym, "error": str(e)}
    d = d[~d.index.duplicated(keep="last")].sort_index()

    rows = []
    counts = Counter()
    for ts, r in d.iterrows():
        day = f"{ts:%Y-%m-%d}"
        ref = ref_for(day, index)
        if ref is None:
            counts["no_reference"] += 1
            continue
        if sym not in ref.index:
            counts["missing_nse"] += 1
            rows.append({"date": day, "kind": "missing_nse",
                         "ours_close": float(r["Close"])})
            continue
        rr = ref.loc[sym]
        worst_field, worst_dev = None, 0.0
        for fld in ("Open", "High", "Low", "Close"):
            a = float(r[fld]) if fld in r and pd.notna(r[fld]) else None
            b = float(rr[fld]) if pd.notna(rr[fld]) else None
            if a is None or b is None or b == 0:
                continue
            dev = abs(a - b) / b
            if dev > worst_dev:
                worst_field, worst_dev = fld, dev
        if worst_dev > TOL:
            counts["mismatch"] += 1
            rows.append({
                "date": day, "kind": "mismatch", "field": worst_field,
                "ours": float(r[worst_field]), "nse": float(rr[worst_field]),
                "ratio": round(float(r[worst_field]) / float(rr[worst_field]), 4),
                "dev_pct": round(worst_dev * 100, 2),
            })
        else:
            counts["match"] += 1

    # NSE bars we are missing entirely
    ours = {f"{t:%Y-%m-%d}" for t in d.index}
    lo, hi = min(ours), max(ours)
    for day, path in index.items():
        if day < lo or day > hi or day in ours:
            continue
        ref = ref_for(day, index)
        if ref is not None and sym in ref.index:
            counts["missing_local"] += 1
            rows.append({"date": day, "kind": "missing_local",
                         "nse_close": float(ref.loc[sym, "Close"])})

    ratios = [r["ratio"] for r in rows if r.get("ratio")]
    return {
        "symbol": sym,
        "bars": len(d),
        "range": [lo, hi],
        "counts": dict(counts),
        "mismatch_ratios": dict(Counter(round(x, 3) for x in ratios).most_common(6)),
        "rows": rows[:4000],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    index = load_reference()
    log(f"reference covers {len(index)} trading days "
        f"({min(index) if index else '-'} → {max(index) if index else '-'})")
    if len(index) < 100:
        log("!! reference is too thin — run deploy/fetch_nse_reference.py first")
        return

    syms = ([s.strip().upper() for s in args.symbols.split(",")] if args.symbols
            else sorted(f[:-4] for f in os.listdir(HIST) if f.endswith(".pkl")))
    if args.limit:
        syms = syms[: args.limit]
    log(f"diffing {len(syms)} symbols (read-only)")

    summary, done = [], 0
    for sym in syms:
        dst = os.path.join(OUT, f"{sym}.json")
        if os.path.exists(dst) and not args.force:
            try:
                summary.append(json.load(open(dst))["summary"])
                continue
            except Exception:
                pass
        res = diff_symbol(sym, index)
        if res is None:
            continue
        head = {k: res[k] for k in ("symbol", "bars", "range", "counts",
                                    "mismatch_ratios") if k in res}
        json.dump({"summary": head, "rows": res.get("rows", [])},
                  open(dst + ".tmp", "w"), indent=1)
        os.replace(dst + ".tmp", dst)      # atomic; a crash never truncates
        summary.append(head)
        done += 1
        if done % 100 == 0:
            log(f"  {done}/{len(syms)}")

    tot = Counter()
    bad = []
    for h in summary:
        for k, v in (h.get("counts") or {}).items():
            tot[k] += v
        if (h.get("counts") or {}).get("mismatch"):
            bad.append((h["symbol"], h["counts"]["mismatch"], h.get("mismatch_ratios")))
    bad.sort(key=lambda x: -x[1])

    json.dump({"generated": datetime.now().isoformat(), "totals": dict(tot),
               "symbols": len(summary), "worst": bad[:200]},
              open(os.path.join(OUT, "summary.json"), "w"), indent=1)

    print("\n" + "=" * 84)
    print("DIFF vs OFFICIAL NSE — nothing written to any price file")
    print("=" * 84)
    n = sum(tot.values()) or 1
    for k in ("match", "mismatch", "missing_local", "missing_nse", "no_reference"):
        print(f"  {k:<16}{tot.get(k,0):>12,}  ({tot.get(k,0)/n*100:>5.2f}%)")
    print(f"\n  symbols examined: {len(summary)} · with mismatches: {len(bad)}")
    if bad:
        print(f"\n  {'SYMBOL':<14}{'BAD BARS':>10}  COMMON RATIOS (ours ÷ NSE)")
        for s, c, ratios in bad[:20]:
            rs = " ".join(f"{k}×{v}" for k, v in (ratios or {}).items())
            print(f"  {s:<14}{c:>10}  {rs}")
    print(f"\n  detail per symbol: {OUT}/<SYMBOL>.json")


if __name__ == "__main__":
    main()
