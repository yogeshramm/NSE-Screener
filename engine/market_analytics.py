"""
Market analytics: Relative Strength (RS) and Sector Rotation Heatmap.

RS = percentile rank (1-99) of a stock's 6-month return vs the universe.
   Minervini's canonical metric — stocks with RS >= 80 are 3x more likely
   to keep outperforming.

Sector heatmap = average 1D/1W/1M/3M/6M returns per sector; ranked.
"""

import os
import pickle
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from functools import lru_cache


HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")
FA_DIR = os.path.join(os.path.dirname(HISTORY_DIR), "fundamentals")


def _load_df(sym: str):
    fpath = os.path.join(HISTORY_DIR, f"{sym}.pkl")
    if not os.path.exists(fpath):
        return None
    try:
        df = pickle.load(open(fpath, "rb"))
        df = df[~df.index.duplicated(keep="last")]
        return df
    except Exception:
        return None


def _get_return(sym: str, bars: int) -> Optional[float]:
    df = _load_df(sym)
    if df is None or len(df) < bars + 1:
        return None
    try:
        last = float(df["Close"].iloc[-1])
        past = float(df["Close"].iloc[-bars - 1])
        return (last - past) / past * 100 if past > 0 else None
    except Exception:
        return None


def compute_rs_ranks(symbols: List[str]) -> Dict[str, int]:
    """Compute RS (1-99 percentile rank) for each symbol using 6-month return (≈126 bars)."""
    returns: Dict[str, float] = {}
    for s in symbols:
        r = _get_return(s, 126)
        if r is not None:
            returns[s] = r
    if not returns:
        return {}
    sorted_syms = sorted(returns.items(), key=lambda x: x[1])
    n = len(sorted_syms)
    ranks = {}
    for i, (s, _) in enumerate(sorted_syms):
        pct = int(round((i + 1) / n * 99))
        ranks[s] = max(1, min(99, pct))
    return ranks


def _get_sector(sym: str) -> Optional[str]:
    # Primary: static sector map
    try:
        from data.sector_map import get_sector as _gs
        s = _gs(sym)
        if s and s != "Other":
            return s
    except Exception:
        pass
    # Fallback: fundamentals pickle (some tenants may have enriched)
    fpath = os.path.join(FA_DIR, f"{sym}.pkl")
    if os.path.exists(fpath):
        try:
            fa = pickle.load(open(fpath, "rb"))
            if isinstance(fa, dict):
                return fa.get("sector") or fa.get("industry")
        except Exception:
            pass
    return None


def sector_heatmap(symbols: List[str]) -> List[Dict[str, Any]]:
    """Group symbols by sector; compute avg returns across timeframes."""
    buckets: Dict[str, Dict[str, List[float]]] = {}
    tfs = [("1D", 1), ("1W", 5), ("1M", 21), ("3M", 63), ("6M", 126)]
    for sym in symbols:
        sector = _get_sector(sym)
        if not sector:
            continue
        if sector not in buckets:
            buckets[sector] = {k: [] for k, _ in tfs}
            buckets[sector]["count"] = 0
        buckets[sector]["count"] = buckets[sector].get("count", 0) + 1
        for k, bars in tfs:
            r = _get_return(sym, bars)
            if r is not None:
                buckets[sector][k].append(r)
    out = []
    for sector, data in buckets.items():
        if data.get("count", 0) < 2:
            continue
        row = {"sector": sector, "count": data["count"]}
        for k, _ in tfs:
            vals = data.get(k, [])
            row[k] = round(float(np.mean(vals)), 2) if vals else None
        out.append(row)
    # Rank by 1M return desc
    out.sort(key=lambda r: r.get("1M") or -9999, reverse=True)
    return out
