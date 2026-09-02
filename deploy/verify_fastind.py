#!/usr/bin/env python3
"""Gate: the fast Supertrend/OBV must equal the originals EXACTLY.

Compares the two implementations across many symbols and many truncation
points, because the sim calls compute() on df[:i+1] for every i. Any single
mismatch fails the gate and the sim keeps the original code.

    python3 deploy/verify_fastind.py
"""
from __future__ import annotations
import os, pickle, random, sys

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_k] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import json
from indicators.supertrend import SupertrendIndicator
from indicators.obv import OBVIndicator

ORIG = {"Supertrend": SupertrendIndicator.compute, "OBV": OBVIndicator.compute}
import engine.sim_fastind as F
F.apply()
FAST = {"Supertrend": SupertrendIndicator.compute, "OBV": OBVIndicator.compute}

HIST = os.path.join(ROOT, "data_store", "history_adjusted")
cfg = json.load(open(os.path.join(ROOT, "config", "presets", "neo_radar.json")))


def main():
    random.seed(20260903)
    syms = sorted(f[:-4] for f in os.listdir(HIST) if f.endswith(".pkl"))
    random.shuffle(syms)
    syms = syms[:40]

    st_i, obv_i = SupertrendIndicator(), OBVIndicator()
    st_p = st_i.get_params(cfg.get("supertrend", {}))
    obv_p = obv_i.get_params(cfg.get("obv", {}))

    checked = mismatch = 0
    bad = []
    for s in syms:
        try:
            df = pickle.load(open(os.path.join(HIST, f"{s}.pkl"), "rb"))
        except Exception:
            continue
        df = df[~df.index.duplicated(keep="last")].sort_index()
        if len(df) < 300:
            continue
        # random truncation points + the boundaries that matter
        pts = sorted(set(
            [60, 61, len(df) - 1, len(df) // 2]
            + [random.randint(60, len(df) - 1) for _ in range(7)]))
        for i in pts:
            sub = df.iloc[: i + 1]
            for name, inst, prm in (("Supertrend", st_i, st_p), ("OBV", obv_i, obv_p)):
                a = ORIG[name](inst, sub, prm)
                b = FAST[name](inst, sub, prm)
                checked += 1
                if a != b:
                    mismatch += 1
                    if len(bad) < 8:
                        bad.append((s, i, name, a, b))

    print("=" * 74)
    print("FAST INDICATOR GATE — fast vs original, exact equality")
    print("=" * 74)
    print(f"  symbols            {len(syms)}")
    print(f"  comparisons        {checked:,}")
    print(f"  mismatches         {mismatch:,}")
    for s, i, n, a, b in bad:
        print(f"\n  {s} @ bar {i} [{n}]\n    original {a}\n    fast     {b}")
    ok = mismatch == 0 and checked > 500
    print(f"\n  RESULT: {'PASS — safe to use' if ok else 'FAIL — do NOT use'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
