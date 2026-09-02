#!/bin/bash
# Supervisor for the sim cache build on ADJUSTED prices.
# Checkpoints every 25 days, so a crash resumes rather than restarting.
# Steps workers down on repeated failure — memory is what kills it.
cd "$(dirname "$0")/.." || exit 1
LOG="logs/sim/cache_build.log"
CACHE="data_store/sim_cache"
START="2017-06-01"; END="2026-08-28"
FORMULAS="neo_radar,neo_extended"
export YOINTELL_SIM_ADJUSTED=1
# One BLAS thread per worker. Each worker otherwise spawns 8 more threads and
# 6 workers put 55 threads on 8 cores — the machine then spends its time
# context-switching (18% idle at load 78) instead of computing.
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
say(){ echo "[$(date '+%F %T')] SUPERVISOR: $*"; }
done_yet(){ [ -f "$CACHE/neo_radar.pkl" ] && [ -f "$CACHE/neo_extended.pkl" ] && [ -f "$CACHE/meta.json" ]; }
workers=6
for attempt in $(seq 1 80); do
    if done_yet; then say "cache COMPLETE"; break; fi
    if   [ $attempt -ge 10 ]; then workers=2
    elif [ $attempt -ge 5  ]; then workers=4
    fi
    say "attempt $attempt with $workers workers (adjusted prices)"
    python3 deploy/build_screen_cache.py --start "$START" --end "$END" \
        --formulas "$FORMULAS" --workers "$workers" --checkpoint 25 >> "$LOG" 2>&1
    if done_yet; then say "cache COMPLETE after $attempt attempt(s)"; break; fi
    n=$(python3 -c "import pickle,os;p='data_store/sim_cache/_partial.pkl';print(len(pickle.load(open(p,'rb'))['store']['neo_radar']) if os.path.exists(p) else 0)" 2>/dev/null)
    say "ended without finishing; ${n:-0} days checkpointed; retry in 30s"
    sleep 30
done
if done_yet; then
    say "running sims -> logs/sim/report.txt"
    python3 deploy/sim_report.py > logs/sim/report.txt 2>&1
    say "sims finished rc=$?"
fi
