"""
One-time historical backfill from Angel One.

Walks the Nifty 500 (or a custom symbol list) and fetches up to N years of
daily candles per symbol, merges with the existing data_store/history/{SYM}.pkl
(Angel wins on duplicate dates), saves the merged result.

Usage:
    python deploy/angel_backfill.py                         # Nifty 500, 10 years
    python deploy/angel_backfill.py --years 5               # 5 years instead
    python deploy/angel_backfill.py --limit 5               # first 5 stocks (test)
    python deploy/angel_backfill.py --symbols TCS,INFY      # explicit list
    python deploy/angel_backfill.py --dry-run               # no writes

Pacing: 0.4s between API calls (inside paginated fetcher) gives ~2.5 calls/sec,
safely under Angel's 3/sec historical cap. Nifty 500 × 2 calls each = ~7 min.

Resume-friendly: if a pkl already covers ≥ requested depth, the symbol is
skipped (override with --force).
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.angel_historical import get_candles_paginated  # noqa: E402
from data.angel_master import get_master_df, symbol_to_token  # noqa: E402

HIST_DIR = Path(__file__).resolve().parent.parent / "data_store" / "history"


def _load_existing(sym: str) -> pd.DataFrame | None:
    p = HIST_DIR / f"{sym}.pkl"
    if not p.exists():
        return None
    try:
        return pd.read_pickle(p)
    except Exception:
        return None


def _normalize_for_merge(df: pd.DataFrame) -> pd.DataFrame:
    """Convert Angel's tz-aware IST index to tz-naive Date index (matches
    existing data_store schema)."""
    if df.empty:
        return df
    out = df.copy()
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    out.index = out.index.normalize()
    out.index.name = "Date"
    out["Volume"] = out["Volume"].astype("float64")
    return out


def backfill_one(sym: str, years: int, force: bool, dry_run: bool) -> dict:
    """Returns a result dict: {symbol, status, rows_added, total_rows, oldest, newest}."""
    out = {"symbol": sym, "status": "?", "rows_added": 0, "total_rows": 0, "oldest": None, "newest": None}
    if not symbol_to_token(sym):
        out["status"] = "no-token"
        return out

    existing = _load_existing(sym)
    if existing is not None and not force:
        # Skip if already covers the requested depth
        oldest_existing = existing.index.min()
        target_oldest = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None) - pd.Timedelta(days=years * 365 - 30)
        if oldest_existing <= target_oldest:
            out["status"] = "already-deep"
            out["total_rows"] = len(existing)
            out["oldest"] = str(existing.index.min().date())
            out["newest"] = str(existing.index.max().date())
            return out

    try:
        from_date = pd.Timestamp.now(tz="Asia/Kolkata") - pd.Timedelta(days=years * 365)
        new_df = get_candles_paginated(sym, "ONE_DAY", from_date=from_date)
    except Exception as e:
        out["status"] = f"error: {e}"
        return out

    if new_df.empty:
        out["status"] = "no-data"
        return out

    new_df = _normalize_for_merge(new_df)

    if existing is not None:
        merged = pd.concat([existing, new_df]).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
        out["rows_added"] = len(merged) - len(existing)
    else:
        merged = new_df
        out["rows_added"] = len(merged)

    out["total_rows"] = len(merged)
    out["oldest"] = str(merged.index.min().date())
    out["newest"] = str(merged.index.max().date())

    if not dry_run:
        HIST_DIR.mkdir(parents=True, exist_ok=True)
        merged.to_pickle(HIST_DIR / f"{sym}.pkl")

    out["status"] = "OK"
    return out


def resolve_symbols(args) -> list[str]:
    if args.symbols:
        return [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if getattr(args, "all", False):
        df = get_master_df()
        syms = sorted(set(s.replace("-EQ", "") for s in df[df["exch_seg"] == "NSE"]["symbol"] if s.endswith("-EQ")))
        if args.limit:
            syms = syms[: args.limit]
        return syms
    # Default: Nifty 500
    try:
        from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK
        try:
            syms = list(get_nifty500_live())
        except Exception:
            syms = list(NIFTY_500_FALLBACK)
    except Exception:
        df = get_master_df()
        syms = sorted(set(s.replace("-EQ", "") for s in df[df["exch_seg"] == "NSE"]["symbol"] if s.endswith("-EQ")))
    if args.limit:
        syms = syms[: args.limit]
    return syms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--symbols", type=str, default=None, help="comma-separated (overrides Nifty 500)")
    ap.add_argument("--all", action="store_true", help="all NSE-EQ symbols from master (~2500), not just Nifty 500")
    ap.add_argument("--limit", type=int, default=None, help="first N symbols only (for testing)")
    ap.add_argument("--force", action="store_true", help="re-fetch even if existing pkl is already deep")
    ap.add_argument("--dry-run", action="store_true", help="no writes")
    args = ap.parse_args()

    syms = resolve_symbols(args)
    print(f"[backfill] {len(syms)} symbols, {args.years}y depth, dry-run={args.dry_run}, force={args.force}", flush=True)

    t0 = time.time()
    stats = {"OK": 0, "already-deep": 0, "no-token": 0, "no-data": 0, "errors": 0, "rows_added": 0}
    for i, sym in enumerate(syms, 1):
        r = backfill_one(sym, args.years, args.force, args.dry_run)
        time.sleep(0.25)  # 0.25s between symbols → ~4/s overall, well under 3/s API limit per-call
        if r["status"] == "OK":
            stats["OK"] += 1
            stats["rows_added"] += r["rows_added"]
        elif r["status"] == "already-deep":
            stats["already-deep"] += 1
        elif r["status"] in ("no-token", "no-data"):
            stats[r["status"]] += 1
        else:
            stats["errors"] += 1
        if i % 10 == 0 or i == len(syms):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(syms) - i) / rate if rate > 0 else 0
            print(f"  [{i:4d}/{len(syms)}] {sym:12s} {r['status']:14s} rows+={r['rows_added']:5d} total={r['total_rows']:5d} | rate={rate:.2f}/s eta={eta/60:.1f}min", flush=True)

    elapsed = time.time() - t0
    print(f"\n[backfill] DONE in {elapsed/60:.1f} min", flush=True)
    print(f"  OK: {stats['OK']}  already-deep: {stats['already-deep']}  no-token: {stats['no-token']}  no-data: {stats['no-data']}  errors: {stats['errors']}", flush=True)
    print(f"  rows added (cumulative): {stats['rows_added']:,}", flush=True)


if __name__ == "__main__":
    main()
