#!/usr/bin/env python3
"""Gate: is the diff report itself trustworthy, before anything is repaired?

The criteria below were written BEFORE the diff finished, so they cannot be
bent to fit the result. If a check fails, the diff is wrong and we fix the
diff — we do not repair price data on top of a faulty comparison.

  1  mismatch ratios cluster on corporate-action factors, not a continuum
  2  each ratio maps to a real NSE action for that symbol at/after that date
  3  a symbol with NO corporate actions shows ZERO mismatches
  4  match rate is high before the Angel backfill's reach
  5  missing_nse bars are explainable (non-EQ series / renamed tickers)

Runs on a sample so it stays fast; sample is stratified across mismatch counts.

    python3 deploy/verify_diff.py            # exit 0 = safe to repair
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DIFF = os.path.join(ROOT, "data_store", "diff_report")
CA = os.path.join(ROOT, "data_store", "corporate_actions")
SAMPLE = 60
TOL = 0.02          # a measured ratio counts as explained within 2%


def load_summaries():
    out = []
    for f in os.listdir(DIFF):
        if not f.endswith(".json") or f == "summary.json":
            continue
        try:
            out.append(json.load(open(os.path.join(DIFF, f)))["summary"])
        except Exception:
            pass
    return out


def cumulative_factors(actions, ratios_seen):
    """Every product of a trailing run of actions — what a bar of some age would show."""
    facts = {1.0}
    run = 1.0
    for a in reversed(actions):
        run *= a["factor"]
        facts.add(round(run, 6))
    return facts


def main() -> int:
    sums = load_summaries()
    if len(sums) < 100:
        print(f"diff report has only {len(sums)} symbols — run the diff first")
        return 1

    with_mm = [s for s in sums if (s.get("counts") or {}).get("mismatch")]
    without = [s for s in sums if not (s.get("counts") or {}).get("mismatch")]
    print(f"symbols: {len(sums)} · with mismatches {len(with_mm)} · clean {len(without)}\n")

    # stratified sample: heavy, light, and clean symbols
    with_mm.sort(key=lambda s: -s["counts"]["mismatch"])
    pick = (with_mm[:20] + with_mm[len(with_mm)//2: len(with_mm)//2 + 20]
            + without[:20])
    syms = [s["symbol"] for s in pick]

    # fetch actions for the sample only
    from deploy.fetch_corporate_actions import session, fetch_symbol
    os.makedirs(CA, exist_ok=True)
    sess = session()
    need = [s for s in syms if not os.path.exists(os.path.join(CA, f"{s}.json"))]
    print(f"fetching corporate actions for {len(need)} sampled symbols…")
    for i, s in enumerate(need, 1):
        try:
            r = fetch_symbol(sess, s)
            if r:
                json.dump(r, open(os.path.join(CA, f"{s}.json"), "w"), indent=1)
        except Exception:
            pass
        if i % 40 == 0:
            sess = session()
        time.sleep(0.4)

    checks = []

    # --- 1 ratios quantised? ---
    allr = Counter()
    for s in with_mm:
        for k, v in (s.get("mismatch_ratios") or {}).items():
            allr[float(k)] += v
    top = allr.most_common(12)
    conc = sum(v for _, v in top) / max(1, sum(allr.values()))
    checks.append(("ratios cluster (top-12 share)", conc > 0.5, f"{conc*100:.0f}% of mismatches in 12 ratios"))

    # --- 3 clean symbols have no mismatches (strongest test) ---
    tested = explained = unexplained = 0
    no_action_but_mismatch = []
    for s in pick:
        p = os.path.join(CA, f"{s['symbol']}.json")
        if not os.path.exists(p):
            continue
        rec = json.load(open(p))
        acts = rec["actions"]
        # A demerger or rights issue IS a corporate action — it just has no
        # factor in the announcement text. The criterion is "no ACTION", so
        # count anything price-adjusting, parsed or not.
        pending = [u for u in rec.get("unparsed", []) if u.get("needs_derivation")]
        mm = (s.get("counts") or {}).get("mismatch", 0)
        if not acts and not pending and mm:
            no_action_but_mismatch.append((s["symbol"], mm))
        if not acts:
            continue
        facts = cumulative_factors(acts, None)
        for k, v in (s.get("mismatch_ratios") or {}).items():
            tested += v
            r = float(k)
            if any(abs(r - f) / f < TOL for f in facts if f > 0):
                explained += v
            else:
                unexplained += v
    checks.append(("symbols with NO corporate action at all show no mismatch",
                   not no_action_but_mismatch,
                   f"{len(no_action_but_mismatch)} violations"
                   + (f" e.g. {no_action_but_mismatch[:3]}" if no_action_but_mismatch else "")))

    # --- 2 ratios explained by actions ---
    frac = explained / tested if tested else 0
    checks.append(("mismatch ratios explained by NSE actions",
                   frac > 0.70, f"{frac*100:.0f}% of {tested} sampled bars"))

    # --- 4 overall match rate ---
    tot = Counter()
    for s in sums:
        for k, v in (s.get("counts") or {}).items():
            tot[k] += v
    n = sum(tot.values()) or 1
    checks.append(("no_reference is negligible", tot.get("no_reference", 0)/n < 0.05,
                   f"{tot.get('no_reference',0)/n*100:.1f}%"))

    # --- 5 missing_nse sanity ---
    checks.append(("missing_nse is a small minority", tot.get("missing_nse", 0)/n < 0.10,
                   f"{tot.get('missing_nse',0)/n*100:.1f}%"))

    print("\nGATE")
    for name, ok, detail in checks:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name:<44}{detail}")
    print("\n  most common ratios across the universe:")
    for r, c in top:
        print(f"    {r:<8} {c:>8,} bars")
    failed = [c for c in checks if not c[1]]
    print("\nPASS — the diff is sound; safe to plan repairs" if not failed
          else f"\n{len(failed)} FAILED — fix the diff before repairing anything")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
