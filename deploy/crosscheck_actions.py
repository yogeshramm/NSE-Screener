#!/usr/bin/env python3
"""Cross-check corporate actions against a second credible source.

NSE is the primary record. Where NSE reports no action but our stored prices
differ from NSE's by a constant factor, we ask an independent source before
concluding anything. If NO source knows of an action, the conclusion is that
there was no action — our stored price is simply wrong, and NSE's value stands.

Sources, in order of authority:
    1. NSE corporate-actions      (already fetched by fetch_corporate_actions.py)
    2. yfinance splits/bonuses    (structured, independent)

    python3 deploy/crosscheck_actions.py            # every affected symbol
    python3 deploy/crosscheck_actions.py --symbols M&MFIN,VEDL

Output: data_store/corporate_actions/_crosscheck.json
Read-only with respect to price data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DIFF = os.path.join(ROOT, "data_store", "diff_report")
CA = os.path.join(ROOT, "data_store", "corporate_actions")
OUT = os.path.join(CA, "_crosscheck.json")


def log(m):
    print(f"{datetime.now():%H:%M:%S}  {m}", flush=True)


def yf_actions(sym: str):
    """Splits/bonuses from yfinance as {date: ratio}. None if unavailable."""
    try:
        import yfinance as yf
        sp = yf.Ticker(f"{sym}.NS").splits
        if sp is None or not len(sp):
            return {}
        return {str(d)[:10]: float(v) for d, v in sp.items()}
    except Exception:
        return None


def nse_actions(sym: str):
    p = os.path.join(CA, f"{sym}.json")
    if not os.path.exists(p):
        return None
    r = json.load(open(p))
    out = [{"ex_date": a["ex_date"], "kind": a["kind"], "factor": a.get("factor")}
           for a in r["actions"]]
    out += [{"ex_date": u["ex_date"], "kind": u["kind"], "factor": None}
            for u in r.get("unparsed", []) if u.get("needs_derivation")]
    return sorted(out, key=lambda x: x["ex_date"])


def affected_symbols():
    out = []
    for f in os.listdir(DIFF):
        if not f.endswith(".json") or f == "summary.json":
            continue
        try:
            s = json.load(open(os.path.join(DIFF, f)))["summary"]
        except Exception:
            continue
        if (s.get("counts") or {}).get("mismatch"):
            out.append((s["symbol"], s["counts"]["mismatch"],
                        s.get("mismatch_ratios") or {}))
    return sorted(out, key=lambda x: -x[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols")
    ap.add_argument("--min-bars", type=int, default=1,
                    help="only cross-check symbols with at least this many mismatches")
    args = ap.parse_args()

    todo = affected_symbols()
    if args.symbols:
        want = {s.strip().upper() for s in args.symbols.split(",")}
        todo = [t for t in todo if t[0] in want]
    todo = [t for t in todo if t[1] >= args.min_bars]
    log(f"cross-checking {len(todo)} symbols")

    results = {}
    counts = {"nse_only": 0, "both": 0, "yf_only": 0, "neither": 0, "yf_unavailable": 0}
    for i, (sym, mm, ratios) in enumerate(todo, 1):
        nse = nse_actions(sym) or []
        yf = yf_actions(sym)
        if yf is None:
            verdict = "yf_unavailable"
        elif nse and yf:
            verdict = "both"
        elif nse and not yf:
            verdict = "nse_only"
        elif yf and not nse:
            verdict = "yf_only"
        else:
            verdict = "neither"
        counts[verdict] += 1
        results[sym] = {"mismatch_bars": mm, "ratios": ratios,
                        "nse_actions": nse, "yf_splits": yf, "verdict": verdict}
        if i % 25 == 0:
            log(f"  {i}/{len(todo)}")
        time.sleep(0.15)

    json.dump({"generated": datetime.now().isoformat(), "counts": counts,
               "symbols": results}, open(OUT, "w"), indent=1)

    print("\n" + "=" * 78)
    print("CROSS-CHECK: NSE vs an independent source")
    print("=" * 78)
    for k, v in counts.items():
        print(f"  {k:<18}{v:>5} symbols")
    neither = [(s, d["mismatch_bars"], d["ratios"]) for s, d in results.items()
               if d["verdict"] == "neither"]
    neither.sort(key=lambda x: -x[1])
    if neither:
        print(f"\n  NO SOURCE reports an action ({len(neither)} symbols) —")
        print("  these are stored-price errors, not corporate actions:")
        print(f"    {'SYMBOL':<14}{'BARS':>6}   RATIOS")
        for s, mm, r in neither[:20]:
            print(f"    {s:<14}{mm:>6}   {dict(list(r.items())[:3])}")
    yfonly = [(s, d) for s, d in results.items() if d["verdict"] == "yf_only"]
    if yfonly:
        print(f"\n  NSE missed an action the second source knows about ({len(yfonly)}):")
        for s, d in yfonly[:10]:
            print(f"    {s:<14}{d['mismatch_bars']:>6} bars   yf: {list(d['yf_splits'])[:3]}")
    print(f"\n  detail: {OUT}")


if __name__ == "__main__":
    main()
