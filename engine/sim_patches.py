"""Sim-local patches — applied IN THE SIM PROCESS ONLY.

Nothing here modifies a file on disk. The live app imports none of it, so the
website's behaviour is unchanged; these swaps exist purely so a historical
replay is fast and free of lookahead.

Two patches:

1. indicator cache — a replay screens the same symbols against hundreds of
   historical `last_bar_date` values. Left alone it would overwrite every warm
   cache entry with a stale date and leave the production screener cold.

2. Sector Performance — `indicators/sector_performance.py` calls
   `yf.Ticker(...).history(period="40d")`, which fetches the last 40 days
   FROM TODAY regardless of the bar being simulated. In a replay of March that
   silently supplies September data, and it costs ~200s per screen in network
   wait. Replaced with a point-in-time calculation from the local universe:

       sector return = mean return of same-sector peers over the lookback
       market return = mean return of the whole universe over the lookback

   both measured strictly at or before the as-of bar.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

# {symbol: sector} and {symbol: DataFrame} for the point-in-time sector calc
_SECTORS: Dict[str, str] = {}
_FRAMES: Dict[str, pd.DataFrame] = {}
_POS: Dict[str, Dict[Any, int]] = {}
_CACHE: Dict[tuple, tuple] = {}


def set_universe(frames: Dict[str, pd.DataFrame], sectors: Dict[str, str]) -> None:
    """Give the patched sector indicator the local universe to measure against."""
    global _SECTORS, _FRAMES, _POS, _CACHE
    _FRAMES = frames
    _SECTORS = sectors
    _POS = {s: {d: i for i, d in enumerate(df.index)} for s, df in frames.items()}
    _CACHE = {}


def _returns_for(day, lookback: int):
    """(per-sector mean return, whole-universe mean return) as of `day`."""
    key = (day, lookback)
    if key in _CACHE:
        return _CACHE[key]
    by_sector: Dict[str, list] = {}
    allr: list = []
    for sym, df in _FRAMES.items():
        i = _POS[sym].get(day)
        if i is None or i < lookback:
            continue
        past = float(df["Close"].iloc[i - lookback])
        if past <= 0:
            continue
        r = (float(df["Close"].iloc[i]) - past) / past * 100
        allr.append(r)
        sec = _SECTORS.get(sym)
        if sec:
            by_sector.setdefault(sec, []).append(r)
    out = ({k: float(np.mean(v)) for k, v in by_sector.items() if len(v) >= 3},
           float(np.mean(allr)) if allr else 0.0)
    _CACHE[key] = out
    return out


def _patched_sector_compute(self, df: pd.DataFrame, params: dict,
                            sector: Optional[str] = None) -> dict:
    lookback = params.get("sector_lookback", 30)

    if len(df) > lookback:
        stock_return = (df["Close"].iloc[-1] / df["Close"].iloc[-lookback] - 1) * 100
    else:
        stock_return = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
    stock_return = float(stock_return)

    if sector is None or not _FRAMES:
        return {"stock_return": round(stock_return, 2), "sector_return": None,
                "nifty_return": None, "outperforming": False,
                "reason": "No sector provided", "sector": sector}

    day = df.index[-1]
    sec_map, mkt = _returns_for(day, lookback)
    sector_return = sec_map.get(sector)
    if sector_return is None:
        sector_return = stock_return          # same fallback as the original

    return {
        "stock_return": round(stock_return, 2),
        "sector_return": round(float(sector_return), 2),
        "nifty_return": round(float(mkt), 2),
        "outperforming": float(sector_return) > float(mkt),
        "sector": sector,
        "point_in_time": True,
    }


def apply_all() -> None:
    """Install every sim-local patch. Safe to call more than once."""
    import engine.indicator_cache as ic
    ic.load_cached = lambda *a, **k: None
    ic.save_cached = lambda *a, **k: None
    import engine.screener as sc
    sc.load_cached = ic.load_cached
    sc.save_cached = ic.save_cached

    from indicators.sector_performance import SectorPerformanceIndicator
    SectorPerformanceIndicator.compute = _patched_sector_compute

    # Supertrend and OBV were 98% of a screening day (204.7s and 72.5s of 282s)
    # purely through pandas .iloc access in their loops. These replacements do
    # the same arithmetic over numpy and are gated on exact equality by
    # deploy/verify_fastind.py (878 comparisons, 0 mismatches).
    import engine.sim_fastind as fastind
    fastind.apply()
