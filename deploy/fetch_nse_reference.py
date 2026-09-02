#!/usr/bin/env python3
"""Step 1 — build an authoritative RAW price reference straight from NSE.

Downloads one bhavcopy per trading day. Each file contains every listed
symbol for that day, so ~2,500 downloads cover the entire market for ten
years — the whole universe costs the same as one index.

The result is stored SEPARATELY from data_store/history and is never merged
into it. It is the reference we diff against, nothing more.

    python3 deploy/fetch_nse_reference.py --probe            # 20 spread dates
    python3 deploy/fetch_nse_reference.py --start 2016-01-01 --end 2026-09-01

Output: data_store/nse_reference/{YYYY}/{YYYY-MM-DD}.pkl
        each a DataFrame indexed by symbol with Open/High/Low/Close/Volume

Resumable: a date already on disk is skipped, so a crash costs nothing.
Read-only with respect to every existing data file.
"""

from __future__ import annotations

import argparse
import os
import pickle
import random
import sys
import time
from datetime import datetime, timedelta

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

REF_DIR = os.path.join(ROOT, "data_store", "nse_reference")
NODATA = os.path.join(REF_DIR, "_nodata.json")


def load_nodata() -> set:
    """Dates NSE genuinely has no bhavcopy for — public holidays.

    Without this every restart re-attempts every holiday from 2016 onwards,
    which wastes a minute and, worse, looks exactly like a run of failures.
    """
    import json
    try:
        with open(NODATA) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_nodata(s: set) -> None:
    import json
    tmp = NODATA + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sorted(s), f)
    os.replace(tmp, NODATA)


def log(m):
    print(f"{datetime.now():%H:%M:%S}  {m}", flush=True)


def path_for(day: datetime) -> str:
    return os.path.join(REF_DIR, f"{day.year}", f"{day:%Y-%m-%d}.pkl")


def have(day: datetime) -> bool:
    return os.path.exists(path_for(day))


def _session():
    import requests
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    for u in ("https://www.nseindia.com",
              "https://www.nseindia.com/all-reports"):
        try:
            s.get(u, timeout=10)
        except Exception:
            pass
    return s


def parse(df: pd.DataFrame) -> pd.DataFrame | None:
    """Normalise a bhavcopy frame to symbol-indexed OHLCV (EQ series only)."""
    cols = {c.upper().strip(): c for c in df.columns}

    def pick(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    sym = pick("SYMBOL", "TCKRSYMB")
    o = pick("OPEN_PRICE", "OPEN", "OPNPRIC")
    h = pick("HIGH_PRICE", "HIGH", "HGHPRIC")
    l = pick("LOW_PRICE", "LOW", "LWPRIC")
    c = pick("CLOSE_PRICE", "CLOSE", "CLSPRIC")
    v = pick("TTL_TRD_QNTY", "TOTTRDQTY", "TTLTRDQNTY")
    ser = pick("SERIES", "SCTYSRS")
    if not all([sym, o, h, l, c]):
        return None

    out = df.copy()
    if ser:
        out = out[out[ser].astype(str).str.strip().isin(["EQ", "BE"])]
    out = pd.DataFrame({
        "Symbol": out[sym].astype(str).str.strip(),
        "Open": pd.to_numeric(out[o], errors="coerce"),
        "High": pd.to_numeric(out[h], errors="coerce"),
        "Low": pd.to_numeric(out[l], errors="coerce"),
        "Close": pd.to_numeric(out[c], errors="coerce"),
        "Volume": pd.to_numeric(out[v], errors="coerce") if v else 0,
    }).dropna(subset=["Close"])
    out = out[~out["Symbol"].duplicated(keep="first")].set_index("Symbol")
    return out if len(out) else None


def _prev_stored(day: datetime):
    """The most recent reference file before `day`, if any."""
    for back in range(1, 12):
        d = day - timedelta(days=back)
        p = path_for(d)
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    return pickle.load(f)
            except Exception:
                return None
    return None


def fetch_day(sess, day: datetime):
    """Fetch one session. Returns None for holidays.

    NSE re-serves the PREVIOUS session's bhavcopy for some exchange holidays
    instead of returning nothing, which would otherwise be stored as a phantom
    trading day with duplicated prices. Two genuine consecutive sessions never
    repeat every close AND every traded volume across hundreds of symbols, so
    an exact match means the file was re-served — treat it as a holiday.
    """
    from setup_data import _download_bhavcopy_for_date
    raw = _download_bhavcopy_for_date(sess, day)
    if raw is None or len(raw) == 0:
        return None
    df = parse(raw)
    if df is None:
        return None
    prev = _prev_stored(day)
    if prev is not None:
        common = df.index.intersection(prev.index)
        if len(common) > 200:
            same_c = (df.loc[common, "Close"].round(4)
                      == prev.loc[common, "Close"].round(4)).mean()
            same_v = (df.loc[common, "Volume"].fillna(-1)
                      == prev.loc[common, "Volume"].fillna(-1)).mean()
            if same_c > 0.99 and same_v > 0.99:
                return None          # re-served file → exchange holiday
    return df


def trading_days(start: datetime, end: datetime):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--probe", action="store_true",
                    help="sample 20 dates across the range to measure feasibility")
    ap.add_argument("--sleep", type=float, default=0.6)
    args = ap.parse_args()

    os.makedirs(REF_DIR, exist_ok=True)
    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d") if args.end else datetime.now()
    days = list(trading_days(start, end))

    if args.probe:
        random.seed(7)
        step = max(1, len(days) // 20)
        days = days[::step][:20]
        log(f"PROBE: {len(days)} dates sampled from {start:%Y-%m-%d} → {end:%Y-%m-%d}")
    else:
        nodata = load_nodata()
        before = len(days)
        days = [d for d in days if not have(d) and f"{d:%Y-%m-%d}" not in nodata]
        log(f"{len(days)} trading days to fetch ({start:%Y-%m-%d} → {end:%Y-%m-%d}); "
            f"{before - len(days)} already done or known holidays")

    sess = _session()
    nodata_seen: set = set()
    ok = miss = err = 0
    since_refresh = 0
    consec_miss = 0
    refreshes = 0
    t0 = time.time()
    sizes = []
    for i, d in enumerate(days, 1):
        if have(d) and not args.probe:
            continue
        # NSE cookies go stale after a few hundred requests and the endpoint
        # starts returning empty rather than an error — which looks exactly
        # like a holiday. Refresh proactively, and immediately after a run of
        # misses, so a stale session can never be mistaken for missing data.
        if since_refresh >= 100 or consec_miss >= 5:
            sess = _session()
            since_refresh = 0
            consec_miss = 0
            refreshes += 1
            time.sleep(1.0)
        since_refresh += 1
        try:
            df = fetch_day(sess, d)
        except Exception as e:
            err += 1
            log(f"  {d:%Y-%m-%d}  ERROR {type(e).__name__}: {str(e)[:80]}")
            time.sleep(args.sleep * 3)
            continue
        if df is None:
            miss += 1
            consec_miss += 1
            nodata_seen.add(f"{d:%Y-%m-%d}")
            if len(nodata_seen) % 10 == 0:
                save_nodata(load_nodata() | nodata_seen)
            if args.probe:
                log(f"  {d:%Y-%m-%d}  no data (holiday / not published)")
        else:
            ok += 1
            consec_miss = 0
            sizes.append(len(df))
            os.makedirs(os.path.dirname(path_for(d)), exist_ok=True)
            tmp = path_for(d) + ".tmp"
            with open(tmp, "wb") as f:
                pickle.dump(df, f, protocol=4)
            os.replace(tmp, path_for(d))       # atomic — a crash never leaves a half file
            if args.probe:
                log(f"  {d:%Y-%m-%d}  {len(df):>5} symbols  "
                    f"(e.g. RELIANCE close "
                    f"{df.loc['RELIANCE','Close'] if 'RELIANCE' in df.index else 'n/a'})")
        if not args.probe and i % 25 == 0:
            el = time.time() - t0
            log(f"  {i}/{len(days)} · ok {ok} miss {miss} err {err} · "
                f"{refreshes} session refreshes · "
                f"{el/60:.1f} min · ~{(el/i)*(len(days)-i)/60:.0f} min left")
        time.sleep(args.sleep)

    if nodata_seen and not args.probe:
        save_nodata(load_nodata() | nodata_seen)
    el = time.time() - t0
    log(f"done: ok {ok} · no-data {miss} · errors {err} · {el/60:.1f} min")
    if sizes:
        log(f"  symbols per day: min {min(sizes)} median "
            f"{sorted(sizes)[len(sizes)//2]} max {max(sizes)}")
    if args.probe and ok:
        rate = el / max(1, ok + miss + err)
        total = len(list(trading_days(start, end)))
        log(f"  measured {rate:.2f}s per date → full run of {total} dates "
            f"≈ {rate*total/60:.0f} min")


if __name__ == "__main__":
    main()
