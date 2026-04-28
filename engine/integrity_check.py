"""
Periodic data integrity check — find broken history pickles before they
poison downstream computations (indicator cache, screener, charts).

What it verifies for every data_store/history/{SYM}.pkl:

  ohlc_invalid         Low > High, Close outside [Low, High], Open outside [Low, High]
  zero_or_negative     any Open/High/Low/Close <= 0
  duplicate_dates      same trading date appears twice
  date_gap             > 7 calendar-day gap inside the time series (skips weekends)
  suspicious_jump      |close[t] / close[t-1] - 1| > 30% (single-day move)
  too_short            < 50 bars (not actionable for indicators)
  stale                latest bar older than 14 calendar days

The check is read-only; it never modifies a pickle. Output is written to
data_store/integrity_report.json with a per-symbol issues list and a
counts summary. /data/status surfaces the counts.

Designed to be cheap: ~2800 stocks finishes in ~30s on the droplet
(pickles are already memory-mapped by the filesystem cache after cron).

Usage:
    python -m engine.integrity_check                # full check, writes report
    python -m engine.integrity_check --quiet        # no per-issue prints
    python -m engine.integrity_check --max 100      # limit (smoke test)
"""

import argparse
import json
import pickle
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd


HISTORY_DIR = Path(__file__).parent.parent / "data_store" / "history"
REPORT_FILE = Path(__file__).parent.parent / "data_store" / "integrity_report.json"

# Tuneable thresholds — kept conservative so we don't drown in false positives.
JUMP_PCT = 0.30      # > 30% single-day close-to-close move flagged
GAP_DAYS = 7         # > 7 calendar days between consecutive bars (skips holiday weeks)
STALE_DAYS = 14      # latest bar older than 14 days
MIN_BARS = 50


def _check_one(symbol: str, df: pd.DataFrame) -> list[dict]:
    """Return a list of issue dicts for this symbol. Empty list = clean."""
    issues: list[dict] = []

    if df is None or len(df) == 0:
        return [{"kind": "empty", "detail": "pickle has no rows"}]

    if len(df) < MIN_BARS:
        issues.append({"kind": "too_short", "bars": int(len(df))})

    cols = {"Open", "High", "Low", "Close"}
    if not cols.issubset(df.columns):
        issues.append({"kind": "schema",
                       "detail": f"missing columns: {sorted(cols - set(df.columns))}"})
        return issues  # can't validate further without OHLC

    # OHLC consistency
    bad_oh = df[df["Open"] > df["High"]]
    bad_ol = df[df["Open"] < df["Low"]]
    bad_ch = df[df["Close"] > df["High"]]
    bad_cl = df[df["Close"] < df["Low"]]
    bad_lh = df[df["Low"] > df["High"]]
    bad_count = len(bad_oh) + len(bad_ol) + len(bad_ch) + len(bad_cl) + len(bad_lh)
    if bad_count:
        issues.append({"kind": "ohlc_invalid", "bars": bad_count})

    # Zero / negative prices
    nonpos = df[(df[["Open", "High", "Low", "Close"]] <= 0).any(axis=1)]
    if len(nonpos):
        issues.append({"kind": "zero_or_negative", "bars": int(len(nonpos))})

    # Duplicate dates (same index repeated)
    dup_count = int(df.index.duplicated().sum())
    if dup_count:
        issues.append({"kind": "duplicate_dates", "bars": dup_count})

    # Calendar gaps inside the series
    if len(df) >= 2:
        idx = pd.to_datetime(df.index)
        deltas = idx.to_series().diff().dt.days.dropna()
        big_gaps = deltas[deltas > GAP_DAYS]
        if len(big_gaps):
            issues.append({"kind": "date_gap", "count": int(len(big_gaps)),
                           "max_gap_days": int(big_gaps.max())})

    # Single-day jumps > JUMP_PCT
    if len(df) >= 2:
        chg = df["Close"].pct_change().abs()
        jumps = chg[chg > JUMP_PCT]
        if len(jumps):
            issues.append({"kind": "suspicious_jump",
                           "count": int(len(jumps)),
                           "max_pct": round(float(jumps.max()) * 100, 1)})

    # Stale latest bar
    try:
        last = pd.to_datetime(df.index[-1]).date()
        age = (datetime.now(timezone.utc).date() - last).days
        if age > STALE_DAYS:
            issues.append({"kind": "stale", "days_old": int(age),
                           "last_bar": str(last)})
    except Exception:
        pass

    return issues


def check_all(max_symbols: int | None = None, verbose: bool = True) -> dict:
    """Walk every history pickle, return a structured report."""
    if not HISTORY_DIR.exists():
        return {"error": f"history dir missing: {HISTORY_DIR}"}

    files = sorted(HISTORY_DIR.glob("*.pkl"))
    if max_symbols:
        files = files[:max_symbols]

    t0 = time.time()
    by_symbol: dict[str, list[dict]] = {}
    counts: dict[str, int] = {}
    errors: dict[str, str] = {}

    for i, p in enumerate(files, 1):
        sym = p.stem
        try:
            with open(p, "rb") as f:
                df = pickle.load(f)
            issues = _check_one(sym, df)
        except Exception as e:
            errors[sym] = str(e)[:200]
            continue
        if issues:
            by_symbol[sym] = issues
            for it in issues:
                counts[it["kind"]] = counts.get(it["kind"], 0) + 1

        if verbose and i % 500 == 0:
            print(f"    {i}/{len(files)} | with_issues={len(by_symbol)} "
                  f"errors={len(errors)} | {i/(time.time()-t0):.0f}/s")

    elapsed = time.time() - t0
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(elapsed, 1),
        "total_symbols": len(files),
        "with_issues": len(by_symbol),
        "load_errors": len(errors),
        "issue_counts": dict(sorted(counts.items())),
        "issues": by_symbol,
        "errors": errors,
        "thresholds": {
            "jump_pct": JUMP_PCT,
            "gap_days": GAP_DAYS,
            "stale_days": STALE_DAYS,
            "min_bars": MIN_BARS,
        },
    }
    return report


def write_report(report: dict) -> Path:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REPORT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str))
    tmp.replace(REPORT_FILE)
    return REPORT_FILE


def load_report() -> dict | None:
    if not REPORT_FILE.exists():
        return None
    try:
        return json.loads(REPORT_FILE.read_text())
    except Exception:
        return None


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Periodic data integrity check.")
    p.add_argument("--max", type=int, default=None,
                   help="Limit symbols processed (smoke test).")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    print(f"\n  Integrity check across {HISTORY_DIR}")
    rep = check_all(max_symbols=args.max, verbose=not args.quiet)
    if "error" in rep:
        print(f"  [ERROR] {rep['error']}")
        raise SystemExit(1)

    out = write_report(rep)
    print(f"\n  Done in {rep['duration_s']}s. "
          f"{rep['with_issues']}/{rep['total_symbols']} stocks have issues "
          f"(load_errors={rep['load_errors']}).")
    if rep['issue_counts']:
        print(f"  Issue breakdown:")
        for k, v in rep['issue_counts'].items():
            print(f"    {k}: {v}")
    print(f"  Report: {out}")
