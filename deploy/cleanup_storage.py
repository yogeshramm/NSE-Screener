#!/usr/bin/env python3
"""Reclaim disk: prune the indicator cache and the dated snapshot folders.

Two things grow without bound:

  indicator_cache/   one file per (symbol, config_hash). A cache entry is only
                     ever readable when its stored last_bar_date matches the
                     current bar date AND its hash still belongs to a live
                     preset — anything else is unreachable forever. Tuning a
                     formula orphans a whole generation of files this way.

  data_store/<date>/ per-day snapshots, ~22 MB each, nothing prunes them.

Run this immediately BEFORE the scheduled warm (02:15 UTC), never mid-session:
clearing the cache while someone is scanning makes their scan slow.

    python3 deploy/cleanup_storage.py --dry-run
    python3 deploy/cleanup_storage.py
    python3 deploy/cleanup_storage.py --snapshot-days 3
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import shutil
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

STORE = os.path.join(ROOT, "data_store")
CACHE = os.path.join(STORE, "indicator_cache")
HIST = os.path.join(STORE, "history")


def log(m):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {m}", flush=True)


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def current_bar_date() -> str | None:
    """Latest trading date we hold, from a liquid symbol."""
    for sym in ("RELIANCE", "TCS", "INFY", "HDFCBANK"):
        p = os.path.join(HIST, f"{sym}.pkl")
        if os.path.exists(p):
            try:
                d = pickle.load(open(p, "rb"))
                return str(d.index.max().date())
            except Exception:
                continue
    return None


def live_hashes() -> set:
    """Config hashes of presets that still exist."""
    out = set()
    try:
        from engine.indicator_cache import _config_hash
    except Exception:
        return out
    pdir = os.path.join(ROOT, "config", "presets")
    if os.path.isdir(pdir):
        for f in os.listdir(pdir):
            if f.endswith(".json"):
                try:
                    out.add(_config_hash(json.load(open(os.path.join(pdir, f)))))
                except Exception:
                    pass
    try:                                    # presets stored in the database
        import sqlite3
        db = os.path.join(ROOT, "config", "yointell.db")
        if os.path.exists(db):
            c = sqlite3.connect(db)
            for (blob,) in c.execute("SELECT config FROM presets"):
                try:
                    out.add(_config_hash(json.loads(blob)))
                except Exception:
                    pass
    except Exception:
        pass
    try:
        from engine.default_config import get_default_config
        out.add(_config_hash(get_default_config()))
    except Exception:
        pass
    return out


def warm_symbols() -> set | None:
    """The universe the scheduled warm actually rebuilds (Nifty 500)."""
    try:
        from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK
        return set(get_nifty500_live() or []) or set(NIFTY_500_FALLBACK)
    except Exception:
        return None


def prune_cache(dry: bool, keep_hashes: set, bar_date: str | None,
                warm: set | None = None):
    if not os.path.isdir(CACHE):
        return 0, 0
    freed = removed = 0
    kept = 0
    for f in os.listdir(CACHE):
        if not f.endswith(".pkl"):
            continue
        path = os.path.join(CACHE, f)
        size = os.path.getsize(path)
        stem = f[:-4]
        parts = stem.rsplit("_", 1)
        reason = None
        if len(parts) != 2:
            reason = "old filename format"
        else:
            sym, h = parts
            if warm is not None and sym.upper() not in warm:
                # Outside the warmed universe: the twice-daily warm will never
                # rebuild it, so it only survives if someone repeats the exact
                # same wide scan. Not worth the disk at this traffic level.
                reason = "outside warm universe"
            elif keep_hashes and h not in keep_hashes:
                reason = "config no longer exists"
            elif bar_date:
                try:
                    e = pickle.load(open(path, "rb"))
                    if e.get("last_bar_date") != bar_date:
                        reason = "stale bar date"
                except Exception:
                    reason = "unreadable"
        if reason:
            removed += 1
            freed += size
            if not dry:
                try:
                    os.remove(path)
                except Exception:
                    pass
        else:
            kept += 1
    log(f"  indicator_cache: {'would remove' if dry else 'removed'} {removed:,} files "
        f"({human(freed)}), kept {kept:,}")
    return removed, freed


def prune_snapshots(dry: bool, days: int):
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    freed = removed = 0
    kept = []
    for name in sorted(os.listdir(STORE)):
        p = os.path.join(STORE, name)
        if not os.path.isdir(p) or len(name) != 10 or not name[:4].isdigit():
            continue
        if name >= cutoff:
            kept.append(name)
            continue
        size = sum(os.path.getsize(os.path.join(r, f))
                   for r, _, fs in os.walk(p) for f in fs)
        removed += 1
        freed += size
        if not dry:
            shutil.rmtree(p, ignore_errors=True)
    log(f"  snapshots: {'would remove' if dry else 'removed'} {removed} folders "
        f"({human(freed)}), kept {len(kept)} ({', '.join(kept[-3:]) if kept else '-'})")
    return removed, freed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--snapshot-days", type=int, default=3)
    ap.add_argument("--keep-all-symbols", action="store_true",
                    help="keep cached symbols outside the warmed universe")
    ap.add_argument("--skip-cache", action="store_true")
    ap.add_argument("--skip-snapshots", action="store_true")
    args = ap.parse_args()

    bar = current_bar_date()
    hashes = live_hashes()
    log(f"cleanup{' (DRY RUN)' if args.dry_run else ''} · current bar date {bar} · "
        f"{len(hashes)} live config hashes")

    total = 0
    warm = None if args.keep_all_symbols else warm_symbols()
    if warm:
        log(f"  warmed universe: {len(warm)} symbols (others are not persisted)")
    if not args.skip_cache:
        _, f = prune_cache(args.dry_run, hashes, bar, warm)
        total += f
    if not args.skip_snapshots:
        _, f = prune_snapshots(args.dry_run, args.snapshot_days)
        total += f
    log(f"  total {'reclaimable' if args.dry_run else 'reclaimed'}: {human(total)}")

    try:
        st = os.statvfs(ROOT)
        log(f"  disk free now: {human(st.f_bavail * st.f_frsize)}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
