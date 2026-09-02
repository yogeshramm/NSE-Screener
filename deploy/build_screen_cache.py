#!/usr/bin/env python3
"""Pass 1 — build the screening cache.

The expensive half of the sim is running the real screener once per
(formula, trading day). That output never changes, so it is computed once
here and written to disk. Every later experiment — stop widths, regime gates,
proximity filters, template rules, thresholds — reads this cache and finishes
in seconds instead of hours.

    python3 deploy/build_screen_cache.py --years 2
    python3 deploy/build_screen_cache.py --start 2026-02-23 --end 2026-08-28 --workers 8

Progress is checkpointed every --checkpoint days, so a killed run resumes
from where it stopped instead of starting over (default on; --no-resume to
force a fresh build).

Isolation: writes only to data_store/sim_cache/, patches the indicator cache
and Sector Performance in-process (see engine/sim_patches.py), and modifies no
production file.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from datetime import datetime, timedelta
from multiprocessing import Pool, cpu_count

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CACHE_DIR = os.path.join(ROOT, "data_store", "sim_cache")
PRESET_DIR = os.path.join(ROOT, "config", "presets")
DEFAULT_FORMULAS = ["neo_radar", "neo_extended", "delay_f_rsi68", "original_formula"]

_UNI = None
# Trailing bars handed to the indicators. None = the whole history, which makes
# per-day cost grow with the series (9.5x from 2017 to 2026 — a 45-hour run).
# A cap makes cost constant, but only values that are numerically identical to
# the full-history result are acceptable, so any cap must be validated by
# comparing stage-2 output day for day before it is used.
WINDOW = int(os.environ.get("YOINTELL_SIM_WINDOW", "0")) or None
_CFG = None


def log(m):
    print(f"{datetime.now():%H:%M:%S}  {m}", flush=True)


ADJ_DIR = os.path.join(ROOT, "data_store", "history_adjusted")
USE_ADJUSTED = os.environ.get("YOINTELL_SIM_ADJUSTED") == "1"


def _load_universe(symbols):
    import pickle as _pk
    import pandas as pd
    from api.data_helper import get_stock_bundle
    uni = {}
    for s in symbols:
        try:
            b = get_stock_bundle(s)
        except Exception:
            continue
        if not b or b.get("daily_df") is None or len(b["daily_df"]) < 260:
            continue
        df = b["daily_df"]
        if USE_ADJUSTED:
            # Split/bonus-adjusted series. Raw prices step at every corporate
            # action, so a position held through a 1:2 bonus books a 33% loss
            # that never happened — the sim must read a continuous series.
            ap = os.path.join(ADJ_DIR, f"{s}.pkl")
            if os.path.exists(ap):
                try:
                    df = _pk.load(open(ap, "rb"))
                except Exception:
                    pass
        df = df[~df.index.duplicated(keep="last")].sort_index()
        # Drop the frames nested inside stock_data — get_stock_bundle returns the
        # full history there as well, so keeping it holds every symbol's bars
        # TWICE per worker. With 1,485-bar histories and 8 workers that exhausts
        # memory and the pool dies with BrokenPipeError.
        sd = {k: v for k, v in b["stock_data"].items()
              if not isinstance(v, (pd.DataFrame, pd.Series))}
        uni[s] = {"df": df, "stock_data": sd,
                  "pos": {d: i for i, d in enumerate(df.index)},
                  "sector": sd.get("sector")}
    return uni


def _init(symbols, formulas):
    """Runs once per worker: load universe, install sim-local patches."""
    global _UNI, _CFG
    import engine.sim_patches as P
    P.apply_all()
    _UNI = _load_universe(symbols)
    P.set_universe({s: u["df"] for s, u in _UNI.items()},
                   {s: u["sector"] for s, u in _UNI.items()})
    _CFG = formulas


def _rs_ranks(day):
    import math
    vals = {}
    for sym, u in _UNI.items():
        i = u["pos"].get(day)
        if i is None or i < 126:
            continue
        c = u["df"]["Close"]
        past = float(c.iloc[i - 126])
        if past <= 0:
            continue
        vals[sym] = (float(c.iloc[i]) - past) / past * 100
    if not vals:
        return {}
    order = sorted(vals.items(), key=lambda kv: kv[1])
    n = len(order)
    return {s: max(1, min(99, int(round((k + 1) / n * 99))))
            for k, (s, _) in enumerate(order)}


def _screen_day(day):
    """Screen every formula for one trading day. Returns compact rows.

    Calls stage 1 + stage 2 directly rather than run_full_screen: the cache
    only stores stage-2 rows, so the stage-3 monthly filter is pure waste here.
    """
    from engine.screener import screen_stock_stage1, screen_stock_stage2
    rs = _rs_ranks(day)
    stocks = []
    prox = {}
    for sym, u in _UNI.items():
        i = u["pos"].get(day)
        if i is None or i < 60:
            continue
        df = u["df"]
        px = float(df["Close"].iloc[i])
        sd = dict(u["stock_data"])
        sd["latest_close"] = px
        sd["current_price"] = px
        sd["latest_date"] = str(day.date())
        sd["rs_rank"] = rs.get(sym)
        lo = 0 if WINDOW is None else max(0, i + 1 - WINDOW)
        stocks.append({"symbol": sym, "daily_df": df.iloc[lo: i + 1],
                       "stock_data": sd, "df_4h": None})
        hi = float(df["High"].iloc[max(0, i - 252): i + 1].max())
        prox[sym] = (hi - px) / hi * 100 if hi > 0 else None

    out = {}
    for name, cfg in _CFG.items():
        try:
            s1_pass = 0
            s2_results = []
            for st in stocks:
                s1 = screen_stock_stage1(st["symbol"], st["daily_df"],
                                         st["stock_data"], cfg, None)
                if not s1["passed"]:
                    continue
                s1_pass += 1
                s2_results.append(screen_stock_stage2(
                    st["symbol"], st["daily_df"], st["stock_data"], s1, cfg))
            s2_results.sort(key=lambda x: x.get("score") or 0, reverse=True)
            res = {"stage2_results": s2_results, "n1": s1_pass}
        except Exception as e:
            out[name] = {"error": str(e), "rows": []}
            continue
        rows = []
        for r in res["stage2_results"]:
            rows.append({
                "symbol": r["symbol"], "passed": bool(r.get("passed")),
                "score": r.get("score"), "price": r.get("price"),
                "stop_loss": r.get("stop_loss"), "target": r.get("target"),
                "rr": r.get("risk_reward"), "atr": r.get("atr"),
                "neo": (r.get("neo") or {}).get("score"),
                "neo_ext": (r.get("neo_extended") or {}).get("score"),
                "neo_pending": bool((r.get("neo_pending") or {}).get("is_pending")),
                "rs_rank": rs.get(r["symbol"]),
                "prox52": prox.get(r["symbol"]),
                "late_entry": (r.get("late_entry") or {}).get("status"),
            })
        out[name] = {"rows": rows, "n_stage1_pass": res["n1"]}
    return str(day.date()), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="nifty200")
    ap.add_argument("--formulas", default=",".join(DEFAULT_FORMULAS))
    ap.add_argument("--years", type=float, default=2.0)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--workers", type=int, default=max(1, cpu_count() - 2))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--checkpoint", type=int, default=25,
                    help="flush partial results to disk every N days")
    ap.add_argument("--no-resume", action="store_true",
                    help="ignore any existing checkpoint and rebuild from scratch")
    args = ap.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)
    names = [x.strip() for x in args.formulas.split(",") if x.strip()]
    formulas = {n: json.load(open(os.path.join(PRESET_DIR, f"{n}.json"))) for n in names}

    from data.nse_symbols import (get_nifty50_live, get_nifty100_live,
                                  get_nifty200_live, get_nifty500_live,
                                  NIFTY_500_FALLBACK)
    fn = {"nifty50": get_nifty50_live, "nifty100": get_nifty100_live,
          "nifty200": get_nifty200_live, "nifty500": get_nifty500_live}.get(args.universe)
    syms = []
    if fn:
        try:
            syms = list(fn() or [])
        except Exception:
            syms = []
    if not syms:
        syms = list(NIFTY_500_FALLBACK)[:200]
    if args.limit:
        syms = syms[: args.limit]

    log(f"loading universe ({len(syms)} symbols) to build the calendar…")
    uni = _load_universe(syms)
    import pandas as pd
    counts = {}
    for u in uni.values():
        for d in u["df"].index:
            counts[d] = counts.get(d, 0) + 1
    need = max(3, len(uni) // 3)
    days = sorted(d for d, c in counts.items() if c >= need)

    end = pd.Timestamp(args.end) if args.end else days[-1]
    start = pd.Timestamp(args.start) if args.start else end - timedelta(days=int(args.years * 365))
    cal = [d for d in days if start <= d <= end]
    del uni

    log(f"universe {len(syms)} · {len(cal)} trading days {cal[0].date()} → {cal[-1].date()}"
        + ("  [ADJUSTED prices]" if USE_ADJUSTED else "  [RAW prices]"))
    log(f"formulas: {', '.join(names)} · {args.workers} workers")

    ckpt_path = os.path.join(CACHE_DIR, "_partial.pkl")
    store = {n: {} for n in names}
    if not args.no_resume and os.path.exists(ckpt_path):
        try:
            with open(ckpt_path, "rb") as f:
                prev = pickle.load(f)
            if prev.get("formulas") == names:
                store = prev["store"]
                already = len(next(iter(store.values())))
                log(f"resuming from checkpoint — {already} days already screened")
        except Exception as e:
            log(f"  ! checkpoint unreadable ({e}); starting fresh")

    have = set(next(iter(store.values())).keys()) if store[names[0]] else set()
    todo = [d for d in cal if str(d.date()) not in have]
    if len(todo) < len(cal):
        log(f"{len(cal) - len(todo)} days from checkpoint, {len(todo)} still to do")

    t0 = time.time()
    done = 0

    def flush():
        tmp = ckpt_path + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump({"formulas": names, "store": store}, f, protocol=4)
        os.replace(tmp, ckpt_path)

    if todo:
        with Pool(args.workers, initializer=_init, initargs=(syms, formulas)) as pool:
            for dstr, res in pool.imap_unordered(_screen_day, todo, chunksize=1):
                for n in names:
                    store[n][dstr] = res.get(n, {"rows": []})
                done += 1
                if done % args.checkpoint == 0:
                    flush()
                if done % 10 == 0 or done == len(todo):
                    el = time.time() - t0
                    rate = el / done
                    log(f"  {done}/{len(todo)} days · {el/60:.1f} min elapsed · "
                        f"~{rate*(len(todo)-done)/60:.1f} min left")
        flush()

    meta = {"universe": args.universe, "symbols": len(syms), "days": len(cal),
            "start": str(cal[0].date()), "end": str(cal[-1].date()),
            "formulas": names, "built_at": int(time.time()),
            "elapsed_s": round(time.time() - t0, 1),
            "notes": "point-in-time sector performance; indicator cache bypassed"}
    for n in names:
        with open(os.path.join(CACHE_DIR, f"{n}.pkl"), "wb") as f:
            pickle.dump({"meta": meta, "days": store[n]}, f, protocol=4)
    json.dump(meta, open(os.path.join(CACHE_DIR, "meta.json"), "w"), indent=2)
    if os.path.exists(ckpt_path):
        os.remove(ckpt_path)

    log(f"done in {(time.time()-t0)/60:.1f} min → {CACHE_DIR}")
    for n in names:
        tot = sum(len(v["rows"]) for v in store[n].values())
        pas = sum(sum(1 for r in v["rows"] if r["passed"]) for v in store[n].values())
        log(f"  {n:<18} {tot:>7,} stage2 rows · {pas:>6,} passers")


if __name__ == "__main__":
    main()
