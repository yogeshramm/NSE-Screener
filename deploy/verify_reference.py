#!/usr/bin/env python3
"""Gate: nothing consumes the NSE reference until these checks pass.

Written after a run of avoidable mistakes — phantom holiday sessions were
stored because 255 trading days a year looked plausible and went unchecked.
Every check compares against an EXTERNAL expectation, not against itself.

    python3 deploy/verify_reference.py        # exit 0 = safe to consume
"""
import os, sys, json, pickle, datetime as dt
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "data_store", "nse_reference")


def main() -> int:
    files = {f[:-4]: os.path.join(r, f)
             for r, _, fs in os.walk(REF) for f in fs if f.endswith(".pkl")}
    if len(files) < 500:
        print("FAIL: reference too small"); return 1
    days = sorted(files)
    nod = set(json.load(open(os.path.join(REF, "_nodata.json"))))
    yrs = (dt.date.fromisoformat(days[-1]) - dt.date.fromisoformat(days[0])).days / 365.25

    checks = []
    checks.append(("trading days/year", 240 <= len(days)/yrs <= 252, f"{len(days)/yrs:.1f} vs ~246"))
    checks.append(("holidays/year", 11 <= len(nod)/yrs <= 17, f"{len(nod)/yrs:.1f} vs 12-15"))
    checks.append(("no weekend sessions",
                   not [d for d in days if dt.date.fromisoformat(d).weekday() >= 5], ""))

    d0, miss = dt.date.fromisoformat(days[0]), []
    while d0 <= dt.date.fromisoformat(days[-1]):
        s = str(d0)
        if d0.weekday() < 5 and s not in files and s not in nod:
            miss.append(s)
        d0 += dt.timedelta(days=1)
    checks.append(("no unexplained weekday gaps", not miss, f"{len(miss)}"))

    rng = np.random.default_rng(3)
    samp = [days[i] for i in rng.choice(len(days), min(120, len(days)), replace=False)]
    bad = neg = dup = 0; counts = []; dupsess = 0; prev = None
    for s in sorted(samp):
        df = pickle.load(open(files[s], "rb")); counts.append(len(df))
        bad += int(((df["High"] < df["Low"]) | (df["High"] < df["Close"]) |
                    (df["Low"] > df["Close"])).sum())
        neg += int((df[["Open", "High", "Low", "Close"]] <= 0).sum().sum())
        dup += int(df.index.duplicated().sum())
        if prev is not None:
            c = df.index.intersection(prev.index)
            if len(c) > 200 and (df.loc[c, "Close"].round(4) == prev.loc[c, "Close"].round(4)).mean() > 0.99:
                dupsess += 1
        prev = df
    checks += [("OHLC internally consistent", bad == 0, str(bad)),
               ("no non-positive prices", neg == 0, str(neg)),
               ("no duplicate symbols per day", dup == 0, str(dup)),
               ("symbol counts plausible", min(counts) > 1000, f"min {min(counts)}"),
               ("no duplicate sessions", dupsess == 0, str(dupsess))]

    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name:<34}{detail}")
    print(("\nPASS — safe to consume" if not failed
           else f"\n{len(failed)} CHECK(S) FAILED — do not consume"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
