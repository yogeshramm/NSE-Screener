#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
# wait for the fetcher to settle (no new files for two consecutive checks)
prev=-1
for i in $(seq 1 60); do
  n=$(find data_store/nse_reference -name '*.pkl' | wc -l | tr -d ' ')
  alive=$(pgrep -f fetch_nse_reference >/dev/null && echo yes || echo no)
  if [ "$alive" = "no" ] && [ "$n" -eq "$prev" ]; then break; fi
  prev=$n; sleep 30
done
pkill -f supervise_fetch 2>/dev/null
echo "[$(date '+%F %T')] reference settled at $(find data_store/nse_reference -name '*.pkl' | wc -l | tr -d ' ') dates; starting full diff"
python3 deploy/diff_history_vs_nse.py > logs/sim/diff_report.txt 2>&1
echo "[$(date '+%F %T')] diff finished rc=$? ($(wc -l < logs/sim/diff_report.txt) lines)"
