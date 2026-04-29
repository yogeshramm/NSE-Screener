"""
Angel One daily refresh job.

Run by cron at 07:30 IST (02:00 UTC) Mon-Fri:
  - Refresh the instrument master (~50 MB JSON, picked up by all callers)
  - Pre-warm the login JWT so the first user-facing call doesn't pay login latency

Idempotent and safe to re-run. Logs to stdout for journalctl/cron mail.
"""
from __future__ import annotations
import sys
import time
from datetime import datetime
from pathlib import Path

# Allow `python deploy/angel_daily.py` to import from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    print(f"[angel_daily] {datetime.now().isoformat(timespec='seconds')} starting", flush=True)

    try:
        from data.angel_master import get_master_df, get_nse_equity_df
        t0 = time.time()
        df = get_master_df(force_refresh=True)
        nse_eq = len(get_nse_equity_df())
        print(f"[angel_daily] master: {len(df):,} rows ({nse_eq:,} NSE equities) in {time.time()-t0:.1f}s", flush=True)
    except Exception as e:
        print(f"[angel_daily] MASTER REFRESH FAILED: {e}", file=sys.stderr, flush=True)
        return 1

    try:
        from data.angel_auth import get_session
        t0 = time.time()
        sess = get_session(force_refresh=True)
        print(f"[angel_daily] login: jwt obtained in {time.time()-t0:.1f}s", flush=True)
    except Exception as e:
        print(f"[angel_daily] LOGIN FAILED: {e}", file=sys.stderr, flush=True)
        return 1

    print(f"[angel_daily] OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
