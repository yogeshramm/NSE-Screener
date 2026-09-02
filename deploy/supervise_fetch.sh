#!/bin/bash
# Supervisor for the NSE reference fetch. The fetcher skips dates already on
# disk, so any restart resumes automatically and a crash costs one file at most.
cd "$(dirname "$0")/.." || exit 1
LOG="logs/sim/nse_reference.log"
say(){ echo "[$(date '+%F %T')] SUPERVISOR: $*"; }
for attempt in $(seq 1 40); do
    say "attempt $attempt"
    python3 deploy/fetch_nse_reference.py --start 2016-01-01 --end 2026-09-01 --sleep 0.6 >> "$LOG" 2>&1
    n=$(find data_store/nse_reference -name '*.pkl' 2>/dev/null | wc -l | tr -d ' ')
    say "attempt $attempt ended; $n date files on disk"
    # A pass that fetched nothing new means everything left is a known holiday
    # or already on disk — that is completion, not failure.
    if [ "$n" -gt 2000 ] && [ "$n" -eq "${last_n:-0}" ]; then
        say "COMPLETE with $n date files (no new dates in a full pass)"
        touch data_store/nse_reference/_done
        break
    fi
    last_n=$n
    sleep 20
done
