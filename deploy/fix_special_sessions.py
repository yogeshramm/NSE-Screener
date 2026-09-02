#!/usr/bin/env python3
"""Repair raw bars on Muhurat / special sessions.

On a handful of dates the stored raw file holds SPLIT-ADJUSTED prices instead
of the prices NSE actually printed. The signature is unmistakable: a one-day
collapse that instantly recovers, where the bad close equals the NEXT session's
price divided by that symbol's cumulative split factor. VBL 2021-11-04 sat at
Rs124.93 between two Rs930 sessions, and a sim bought it and "made" 605%.

Two cases:
  authoritative bhavcopy exists -> overwrite the bar with NSE's own OHLCV
  NSE re-serves the previous day -> that session never happened; DROP the bar

Backs up every touched file, writes atomically, verifies afterwards.

    python3 deploy/fix_special_sessions.py --dry-run
    python3 deploy/fix_special_sessions.py
"""
from __future__ import annotations
import argparse, os, pickle, shutil, sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import pandas as pd

HIST = os.path.join(ROOT, "data_store", "history")
REF = os.path.join(ROOT, "data_store", "nse_reference")
BAK = os.path.join(ROOT, "data_store", "history_presession_fix")
COLS = ["Open", "High", "Low", "Close", "Volume"]
TOL = 0.011
SEED_DATES = ["2019-09-27", "2019-09-30", "2020-04-01", "2020-11-14",
              "2021-11-04", "2023-11-12", "2024-01-20", "2024-03-02", "2025-02-01"]


def detect_dates(min_symbols: int = 5):
    """Find the dates that carry the corruption instead of hardcoding them.

    Signature: a close that collapses (or spikes) on one bar and reverses on
    the next. A real price never does this across dozens of symbols at once,
    so any date where many symbols show it is a bad session, not a bad stock.
    """
    import collections
    hits = collections.Counter()
    for f in sorted(os.listdir(HIST)):
        if not f.endswith(".pkl"):
            continue
        try:
            d = pickle.load(open(os.path.join(HIST, f), "rb"))
            d = d[~d.index.duplicated(keep="last")].sort_index()
        except Exception:
            continue
        c = d["Close"].astype(float)
        if len(c) < 30:
            continue
        prev, nxt = c.shift(), c.shift(-1)
        m = (((c / prev < 0.55) & (nxt / c > 1.7))
             | ((c / prev > 1.8) & (nxt / c < 0.6))).fillna(False)
        for dt in c.index[m]:
            hits[str(dt.date())] += 1
    found = sorted(d for d, n in hits.items() if n >= min_symbols)
    return sorted(set(found) | set(SEED_DATES)), hits


def log(m): print(f"{datetime.now():%H:%M:%S}  {m}", flush=True)


def authority(day: str):
    """NSE's own bhavcopy for a date: reference first, then a live fetch."""
    for r, _, fs in os.walk(REF):
        if f"{day}.pkl" in fs:
            return pickle.load(open(os.path.join(r, f"{day}.pkl"), "rb")), "reference"
    import importlib.util, requests
    spec = importlib.util.spec_from_file_location("FR", os.path.join(ROOT, "deploy", "fetch_nse_reference.py"))
    FR = importlib.util.module_from_spec(spec); spec.loader.exec_module(FR)
    s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0"})
    try: s.get("https://www.nseindia.com", timeout=10)
    except Exception: pass
    df = FR.fetch_day(s, datetime.strptime(day, "%Y-%m-%d"))
    return (df, "fetched") if df is not None else (None, "no-session")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    DATES, hits = detect_dates()
    log(f"detected {len(DATES)} suspect sessions: " + ", ".join(DATES))
    for d in DATES:
        if hits.get(d):
            log(f"   {d}: {hits[d]} symbols affected")
    auth = {}
    for d in DATES:
        df, src = authority(d)
        auth[d] = df
        log(f"{d}: {src}" + (f" · {len(df)} rows" if df is not None else " · bar will be DROPPED"))

    syms = sorted(f[:-4] for f in os.listdir(HIST) if f.endswith(".pkl"))
    log(f"scanning {len(syms)} symbols")
    fixed = dropped = touched = 0
    for s in syms:
        p = os.path.join(HIST, f"{s}.pkl")
        try:
            d = pickle.load(open(p, "rb"))
        except Exception:
            continue
        d = d[~d.index.duplicated(keep="last")].sort_index()
        out = d.copy(); changed = False
        for day in DATES:
            ts = pd.Timestamp(day)
            if ts not in out.index:
                continue
            a = auth[day]
            if a is None:
                # NSE serves no standard bhavcopy for this date. That is either a
                # phantom session (the previous day's file re-served) or a real
                # special session — Muhurat trades for one hour and publishes
                # genuine, low-volume prices. Only the former may be deleted:
                # dropping the latter would destroy real NSE data.
                i = out.index.get_indexer([ts])[0]
                if i > 0:
                    pv = out.iloc[i - 1]
                    dup = (abs(float(out.at[ts, "Close"]) - float(pv["Close"])) < 0.011
                           and abs(float(out.at[ts, "Volume"] or 0)
                                   - float(pv["Volume"] or 0)) < 1)
                    if not dup:
                        continue          # real session — keep it
                out = out.drop(index=ts); dropped += 1; changed = True
                continue
            if s not in a.index:
                continue
            ours = out.loc[ts, ["Open", "High", "Low", "Close"]].astype(float)
            theirs = a.loc[s, ["Open", "High", "Low", "Close"]].astype(float)
            if (ours - theirs).abs().max() > TOL:
                for c in COLS:
                    if c in a.columns:
                        out.at[ts, c] = float(a.at[s, c])
                fixed += 1; changed = True
        if changed:
            touched += 1
            if not args.dry_run:
                os.makedirs(BAK, exist_ok=True)
                bk = os.path.join(BAK, f"{s}.pkl")
                if not os.path.exists(bk):
                    shutil.copy(p, bk)
                tmp = p + ".tmp"
                with open(tmp, "wb") as fh:
                    pickle.dump(out, fh, protocol=4)
                os.replace(tmp, p)

    # Final pass: a close that moves >80% and fully reverses on the next
    # session cannot be a real print. NSE's own file for 2019-09-30 mixes pre-
    # and post-adjustment rows (HDFCBANK Rs2,462 between two Rs1,245 sessions),
    # so "it came from NSE" is not sufficient here. Drop what is impossible.
    impossible = 0
    for s_ in syms:
        p_ = os.path.join(HIST, f"{s_}.pkl")
        try:
            d = pickle.load(open(p_, "rb"))
        except Exception:
            continue
        d = d[~d.index.duplicated(keep="last")].sort_index()
        c = d["Close"].astype(float)
        if len(c) < 30:
            continue
        prev, nxt = c.shift(), c.shift(-1)
        m = (((c / prev < 0.55) & (nxt / c > 1.7))
             | ((c / prev > 1.8) & (nxt / c < 0.6))).fillna(False)
        if not m.any():
            continue
        impossible += int(m.sum())
        if not args.dry_run:
            os.makedirs(BAK, exist_ok=True)
            bk = os.path.join(BAK, f"{s_}.pkl")
            if not os.path.exists(bk):
                shutil.copy(p_, bk)
            out2 = d.drop(index=c.index[m])
            tmp = p_ + ".tmp"
            with open(tmp, "wb") as fh:
                pickle.dump(out2, fh, protocol=4)
            os.replace(tmp, p_)

    print("\n" + "=" * 68)
    print("SPECIAL-SESSION REPAIR" + (" (DRY RUN)" if args.dry_run else ""))
    print("=" * 68)
    print(f"  bars corrected from NSE   {fixed:>8,}")
    print(f"  phantom bars dropped      {dropped:>8,}")
    print(f"  symbols touched           {touched:>8,}")
    print(f"  impossible bars dropped   {impossible:>8,}")
    if not args.dry_run:
        print(f"  backups                   {BAK}")


if __name__ == "__main__":
    main()
