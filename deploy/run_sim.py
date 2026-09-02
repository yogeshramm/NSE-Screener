#!/usr/bin/env python3
"""
Real Sim runner — CLI only. No API, no UI, nothing deployed.

    python3 deploy/run_sim.py --months 6
    python3 deploy/run_sim.py --months 6 --universe nifty200 \
        --formulas neo_radar,neo_extended,delay_f_rsi68,original_formula
    python3 deploy/run_sim.py --days 14 --limit 40 --formulas neo_radar   # smoke test

ISOLATION — this process cannot affect the live site:
  • writes only to data_store/real_sim.db (its own file, never yointell.db)
  • monkey-patches engine.indicator_cache IN THIS PROCESS ONLY so a
    historical replay can never overwrite the live warm cache on disk
  • no production module is modified; the app imports none of the sim code
  • history/fundamentals are opened read-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import engine.indicator_cache as _ic           # noqa: E402


def _isolate_indicator_cache() -> None:
    """Neutralise the warm-cache read/write for this process only.

    A replay screens the same symbols against ~126 historical `last_bar_date`
    values. Left alone it would overwrite every warm cache entry with a stale
    date and leave the production screener cold. Patched here rather than in
    engine/indicator_cache.py so no shared file changes on disk.
    """
    _ic.load_cached = lambda *a, **k: None
    _ic.save_cached = lambda *a, **k: None
    import engine.screener as _sc
    if hasattr(_sc, "load_cached"):
        _sc.load_cached = _ic.load_cached
    if hasattr(_sc, "save_cached"):
        _sc.save_cached = _ic.save_cached


_isolate_indicator_cache()

from engine import sim_db                      # noqa: E402
from engine.real_sim import run_sim, DEFAULTS  # noqa: E402

PRESET_DIR = os.path.join(ROOT, "config", "presets")
DEFAULT_FORMULAS = ["neo_radar", "neo_extended", "delay_f_rsi68", "original_formula"]


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S}  {msg}", flush=True)


def load_formulas(names):
    out = {}
    for n in names:
        p = os.path.join(PRESET_DIR, f"{n}.json")
        if not os.path.exists(p):
            raise SystemExit(f"preset not found: {p}")
        with open(p) as f:
            out[n] = json.load(f)
    return out


def load_universe_symbols(scope: str, limit: int | None):
    from data.nse_symbols import (get_nifty50_live, get_nifty100_live,
                                  get_nifty200_live, get_nifty500_live,
                                  NIFTY_500_FALLBACK)
    fn = {"nifty50": get_nifty50_live, "nifty100": get_nifty100_live,
          "nifty200": get_nifty200_live, "nifty500": get_nifty500_live}.get(scope)
    syms = []
    if fn:
        try:
            syms = list(fn() or [])
        except Exception as e:
            log(f"  ! live {scope} list failed ({e}); using fallback")
    if not syms:
        syms = list(NIFTY_500_FALLBACK)[:200 if scope == "nifty200" else 500]
    return syms[:limit] if limit else syms


# ────────────────────────────── report ──────────────────────────────

def _row(cells, widths):
    return "  ".join(str(c).ljust(w)[:w] if i == 0 else str(c).rjust(w)
                     for i, (c, w) in enumerate(zip(cells, widths)))


def print_report(summary, show_trades=12, show_cards=3):
    run_id = summary["run_id"]
    print("\n" + "=" * 96)
    print(f"REAL SIM — {run_id}")
    print(f"{summary['mode'].upper()}  ·  {summary['universe']}  ·  "
          f"{summary['start']} → {summary['end']}  ·  {summary['days']} trading days  ·  "
          f"{summary['symbols']} symbols  ·  {summary['elapsed_s']}s")
    print("=" * 96)

    la = summary["leak_audit"]
    print("\nLEAK AUDIT (what the sim could and could not see)")
    for k in ("point_in_time_clean", "soft_leaks", "disabled_in_replay"):
        print(f"  {k}:")
        for x in la[k]:
            print(f"    - {x}")
    print(f"  template denominator : {la['template_denominator']} checks")
    print(f"  entry fill           : {la['entry_fill']}")
    print(f"  same-bar SL+TP       : {la['same_bar_stop_and_target']}")

    w = [26, 8, 9, 7, 6, 6, 8, 8, 8, 7]
    head = ["BOOK", "P&L %", "P&L ₹", "TRADES", "WIN%", "PF", "MAXDD%", "SHARPE", "AVGWIN", "SKIPS"]
    print("\nRESULTS")
    print(_row(head, w))
    print("-" * 96)
    for b in sorted(summary["books"], key=lambda x: -x["pnl_pct"]):
        print(_row([f"{b['code']}/{b['arm']}", f"{b['pnl_pct']:+.2f}",
                    f"{b['pnl']:+,.0f}", b["total_trades"], b["win_rate"],
                    b["profit_factor"] if b["profit_factor"] is not None else "-",
                    b["max_dd_pct"],
                    b["sharpe"] if b["sharpe"] is not None else "-",
                    f"{b['avg_win']:,.0f}", b["vetoed_count"]], w))

    print("\nDOES THE RESEARCH LAYER ADD ANYTHING?  (BRAIN − RAW)")
    by_code = {}
    for b in summary["books"]:
        by_code.setdefault(b["code"], {})[b["arm"]] = b
    print(_row(["FORMULA", "RAW%", "BRAIN%", "EDGE", "RAWDD", "BRNDD", "RAWTR", "BRNTR", "SKIPPED", ""],
               [26, 8, 9, 7, 6, 6, 8, 8, 8, 7]))
    print("-" * 96)
    for code, arms in by_code.items():
        r, b = arms.get("RAW"), arms.get("BRAIN")
        if not r or not b:
            continue
        print(_row([f"{code}  {r['formula']}", f"{r['pnl_pct']:+.2f}",
                    f"{b['pnl_pct']:+.2f}", f"{b['pnl_pct'] - r['pnl_pct']:+.2f}",
                    r["max_dd_pct"], b["max_dd_pct"],
                    r["total_trades"], b["total_trades"], b["vetoed_count"], ""],
                   [26, 8, 9, 7, 6, 6, 8, 8, 8, 7]))

    # exit breakdown
    print("\nEXIT REASONS")
    for b in summary["books"]:
        eb = b.get("exit_breakdown") or {}
        if eb:
            print(f"  {b['code']}/{b['arm']:<5} " +
                  "  ".join(f"{k}={v}" for k, v in sorted(eb.items(), key=lambda x: -x[1])))

    # trades
    print(f"\nTRADES (worst and best {show_trades // 2} across all books)")
    trades = sim_db.trades_for_run(run_id)
    if trades:
        tw = [34, 11, 10, 10, 9, 8, 10, 18]
        print(_row(["TRADE", "SYMBOL", "ENTRY", "EXIT", "P&L%", "R", "NET ₹", "REASON"], tw))
        print("-" * 96)
        ordered = sorted(trades, key=lambda t: t["pnl_pct"] or 0)
        half = max(1, show_trades // 2)
        pick = ordered[:half]
        seen = {t["trade_id"] for t in pick}
        pick += [t for t in ordered[-half:] if t["trade_id"] not in seen]
        for t in pick:
            short = t["trade_id"].split("/", 1)[1] if "/" in t["trade_id"] else t["trade_id"]
            print(_row([short, t["symbol"],
                        f"{t['entry_date']} {t['entry_price']:.0f}",
                        f"{t['exit_date']} {t['exit_price']:.0f}",
                        f"{t['pnl_pct']:+.2f}",
                        t["r_multiple"] if t["r_multiple"] is not None else "-",
                        f"{t['net_pnl']:+,.0f}", t["exit_reason"]], tw))

    # decision cards — the automated research, in English
    print(f"\nSAMPLE DECISION CARDS ({show_cards} buys + {show_cards} skips)")
    brain_books = [b["book_id"] for b in summary["books"] if b["arm"] == "BRAIN"]
    for action in ("BUY", "SKIP"):
        pool = []
        for bid in brain_books:
            pool += sim_db.decisions_for(bid, action, limit=show_cards)
        pool.sort(key=lambda d: d["decision_date"], reverse=True)
        for d in pool[:show_cards]:
            print(f"\n  \u2500\u2500 {d['decision_date']}  {d['symbol']}  "
                  f"[{d['book_id'].split('/')[1]}]  {action} \u00b7 {d['conviction']} \u00b7 "
                  f"{d['template_score']}/{d['template_max']} checks")
            print(f"     {d['verdict']}")
            for line in (d["reasons"] or "").split("\n"):
                if line.strip():
                    print(f"       {line}")
    print("\n" + "=" * 96)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="replay", choices=["replay", "live"])
    ap.add_argument("--universe", default="nifty200")
    ap.add_argument("--formulas", default=",".join(DEFAULT_FORMULAS))
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--days", type=int, help="override --months with N calendar days")
    ap.add_argument("--end", help="YYYY-MM-DD (default: latest bar available)")
    ap.add_argument("--limit", type=int, help="cap universe size (smoke tests)")
    ap.add_argument("--purse", type=float, default=DEFAULTS["purse"])
    ap.add_argument("--max-positions", type=int, default=DEFAULTS["max_positions"])
    ap.add_argument("--buy-threshold", type=float, default=DEFAULTS["buy_threshold"])
    ap.add_argument("--dry-run", action="store_true", help="do not write to the database")
    ap.add_argument("--json-out", help="also dump the summary to this path")
    args = ap.parse_args()

    end = args.end
    if not end:
        from api.data_helper import get_stock_bundle
        b = get_stock_bundle("RELIANCE")
        end = str(b["daily_df"].index[-1].date())
    span = timedelta(days=args.days) if args.days else timedelta(days=args.months * 31)
    start = str((datetime.strptime(end, "%Y-%m-%d") - span).date())

    names = [x.strip() for x in args.formulas.split(",") if x.strip()]
    formulas = load_formulas(names)
    symbols = load_universe_symbols(args.universe, args.limit)

    log(f"Real Sim · {args.mode} · {args.universe} ({len(symbols)} symbols) · "
        f"{start} → {end}")
    log(f"Formulas: {', '.join(names)}  |  purse ₹{args.purse:,.0f}/formula  |  "
        f"db {sim_db.DB_PATH.name} \u00b7 warm cache isolated")

    summary = run_sim(
        symbols, formulas, start, end, mode=args.mode,
        cfg={"purse": args.purse, "max_positions": args.max_positions,
             "buy_threshold": args.buy_threshold},
        universe_name=args.universe, log=log, persist=not args.dry_run,
    )

    if not args.dry_run:
        print_report(summary)
    else:
        print(json.dumps({k: v for k, v in summary.items() if k != "leak_audit"},
                         indent=2, default=str))

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        log(f"summary → {args.json_out}")


if __name__ == "__main__":
    main()
