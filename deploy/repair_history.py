#!/usr/bin/env python3
"""Repair stored price history against the official NSE reference.

NSE bhavcopy is the authority. Every stored bar is compared to it and:

  mismatch        -> overwritten with NSE's OHLCV (CLOSE_PRICE is the canonical
                     close; a stored LAST_PRICE is standardised away)
  missing_local   -> inserted from NSE
  missing_nse     -> KEPT, if the symbol was renamed and the bar verifies under
                     its former ticker. Renamed history is real data.
  no_reference    -> left untouched; we have nothing to judge it by

Everything else is left exactly as it is.

    python3 deploy/repair_history.py --dry-run       # report only, no writes
    python3 deploy/repair_history.py                 # repair
    python3 deploy/repair_history.py --symbols TCS   # a subset

Backs every touched file up to data_store/history_prerepair/ first, writes
atomically, and is resumable — a symbol already repaired is skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import shutil
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

HIST = os.path.join(ROOT, "data_store", "history")
REF = os.path.join(ROOT, "data_store", "nse_reference")
BAK = os.path.join(ROOT, "data_store", "history_prerepair")
CA = os.path.join(ROOT, "data_store", "corporate_actions")
STATE = os.path.join(ROOT, "data_store", "repair_state.json")
COLS = ["Open", "High", "Low", "Close", "Volume"]
TOL = 0.005


def log(m):
    print(f"{datetime.now():%H:%M:%S}  {m}", flush=True)


def ref_files():
    return {f[:-4]: os.path.join(r, f)
            for r, _, fs in os.walk(REF) for f in fs if f.endswith(".pkl")}


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"done": [], "stats": {}}


def save_state(s):
    tmp = STATE + ".tmp"
    json.dump(s, open(tmp, "w"))
    os.replace(tmp, STATE)


def build_series(symbols: set, files: dict, renames: dict) -> dict:
    """One pass over the reference, collecting per-symbol OHLCV.

    A renamed ticker also collects rows filed under its former name, so its
    pre-rename history is recovered rather than deleted.
    """
    want = set(symbols)
    alias = {}                       # old ticker -> new ticker
    for new, old in renames.items():
        if new in want:
            alias[old] = new
            want.add(old)
    rows = defaultdict(list)
    for n, (day, path) in enumerate(sorted(files.items()), 1):
        try:
            df = pickle.load(open(path, "rb"))
        except Exception:
            continue
        hit = df.index.intersection(want)
        if len(hit) == 0:
            continue
        sub = df.loc[hit, COLS]
        for sym, r in sub.iterrows():
            tgt = alias.get(sym, sym)
            rows[tgt].append((day, float(r["Open"]), float(r["High"]),
                              float(r["Low"]), float(r["Close"]),
                              float(r["Volume"]) if pd.notna(r["Volume"]) else 0.0))
        if n % 500 == 0:
            log(f"    scanned {n}/{len(files)} reference days")
    out = {}
    for sym, rs in rows.items():
        if not rs:
            continue
        d = pd.DataFrame(rs, columns=["Date"] + COLS)
        d["Date"] = pd.to_datetime(d["Date"])
        d = d.drop_duplicates("Date", keep="last").set_index("Date").sort_index()
        out[sym] = d
    return out


def repair_symbol(sym: str, nse: pd.DataFrame, dry: bool):
    p = os.path.join(HIST, f"{sym}.pkl")
    if not os.path.exists(p):
        return None
    try:
        ours = pickle.load(open(p, "rb"))
    except Exception:
        return None
    ours = ours[~ours.index.duplicated(keep="last")].sort_index()
    if not len(ours) or nse is None or not len(nse):
        return None

    lo, hi = ours.index.min(), ours.index.max()
    nse_win = nse.loc[(nse.index >= lo) & (nse.index <= hi)]

    fixed = inserted = kept = 0
    out = ours.copy()
    for c in COLS:
        if c not in out.columns:
            out[c] = np.nan

    common = out.index.intersection(nse_win.index)
    if len(common):
        a = out.loc[common, COLS].astype(float)
        b = nse_win.loc[common, COLS].astype(float)
        dev = (a[["Open", "High", "Low", "Close"]]
               - b[["Open", "High", "Low", "Close"]]).abs() / b[["Open", "High", "Low", "Close"]].replace(0, np.nan)
        bad = (dev > TOL).any(axis=1)
        idx = common[bad.values]
        fixed = int(len(idx))
        if fixed:
            out.loc[idx, COLS] = nse_win.loc[idx, COLS].values

    add = nse_win.index.difference(out.index)
    inserted = int(len(add))
    if inserted:
        out = pd.concat([out, nse_win.loc[add, COLS]]).sort_index()

    kept = int(len(out.index.difference(nse_win.index)))

    if not dry and (fixed or inserted):
        os.makedirs(BAK, exist_ok=True)
        bk = os.path.join(BAK, f"{sym}.pkl")
        if not os.path.exists(bk):
            shutil.copy(p, bk)
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump(out, f, protocol=4)
        os.replace(tmp, p)
    return {"fixed": fixed, "inserted": inserted, "kept_not_in_nse": kept,
            "bars_before": int(len(ours)), "bars_after": int(len(out))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch", type=int, default=400)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    files = ref_files()
    if len(files) < 500:
        log("reference too thin — run deploy/fetch_nse_reference.py first")
        return
    renames = {}
    rp = os.path.join(CA, "_renames.json")
    if os.path.exists(rp):
        renames = json.load(open(rp))
        renames.pop("JSWENERGY", None)      # single-sample false positive
    log(f"reference {len(files)} days · {len(renames)} known ticker renames")

    syms = ([s.strip().upper() for s in args.symbols.split(",")] if args.symbols
            else sorted(f[:-4] for f in os.listdir(HIST) if f.endswith(".pkl")))
    state = {"done": [], "stats": {}} if args.reset else load_state()
    done = set(state["done"])
    todo = [s for s in syms if s not in done]
    log(f"{len(todo)} symbols to repair ({len(done)} already done)"
        + ("  [DRY RUN — no writes]" if args.dry_run else ""))

    tot = defaultdict(int)
    for i in range(0, len(todo), args.batch):
        chunk = todo[i: i + args.batch]
        log(f"  batch {i//args.batch + 1}: building NSE series for {len(chunk)} symbols…")
        series = build_series(set(chunk), files, renames)
        for sym in chunk:
            r = repair_symbol(sym, series.get(sym), args.dry_run)
            if r:
                for k, v in r.items():
                    if k in ("fixed", "inserted"):
                        tot[k] += v
                if r["fixed"] or r["inserted"]:
                    state["stats"][sym] = r
            done.add(sym)
        state["done"] = sorted(done)
        if not args.dry_run:
            save_state(state)
        log(f"  batch done · cumulative fixed {tot['fixed']:,} · inserted {tot['inserted']:,}")

    print("\n" + "=" * 74)
    print("REPAIR " + ("(DRY RUN)" if args.dry_run else "COMPLETE"))
    print("=" * 74)
    print(f"  bars corrected  {tot['fixed']:>10,}")
    print(f"  bars inserted   {tot['inserted']:>10,}")
    print(f"  symbols touched {len(state['stats']):>10,}")
    if not args.dry_run:
        print(f"  backups         {BAK}")
    worst = sorted(state["stats"].items(),
                   key=lambda kv: -(kv[1]["fixed"] + kv[1]["inserted"]))[:12]
    print(f"\n  {'SYMBOL':<14}{'FIXED':>8}{'INSERTED':>10}{'BEFORE':>9}{'AFTER':>8}")
    for s, r in worst:
        print(f"  {s:<14}{r['fixed']:>8,}{r['inserted']:>10,}"
              f"{r['bars_before']:>9,}{r['bars_after']:>8,}")


if __name__ == "__main__":
    main()
