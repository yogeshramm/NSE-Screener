#!/usr/bin/env python3
"""Subprocess warm helper — called by /data/warm endpoint.
Runs warm_cache() in its own process so uvicorn stays responsive (no GIL contention).
Usage: python warm_scope.py [nifty50|nifty200|nifty500|all]
Prints a JSON stats line on stdout when done.
"""
import sys, json
from pathlib import Path

# Make sure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

scope = sys.argv[1] if len(sys.argv) > 1 else "nifty500"

try:
    from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK
    all500 = get_nifty500_live() or list(NIFTY_500_FALLBACK)
except Exception:
    all500 = []

if scope == "nifty50":
    syms = all500[:50] if all500 else None
elif scope == "nifty200":
    syms = all500[:200] if all500 else None
elif scope == "nifty500":
    syms = all500 if all500 else None
else:
    syms = None  # all NSE

from engine.precompute import warm_cache
stats = warm_cache(symbols=syms, verbose=False)
print(json.dumps(stats))
