"""
Multi-Factor Score — Momentum + Quality + Value + Growth → 1-99 percentile.

Momentum: reuses RS (6M return) from market_analytics.
Quality:  ROE + (1 / (1+D/E)) + ROCE
Value:    inverse PE + inverse PB (percentile vs sector if possible, else universe)
Growth:   EPS if known, else 1M price return as proxy (EPS YoY not in current pickles)

Final score = equal-weighted average of factor percentiles, mapped to 1-99.
Cached to data_store/factor_scores.pkl, 24h TTL.
"""
import os, pickle, time
from typing import Dict, List, Any, Optional
import numpy as np

HIST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")
FA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "fundamentals")
CACHE_F = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "factor_scores.pkl")
TTL = 24 * 3600


def _load_hist(sym):
    p = os.path.join(HIST_DIR, f"{sym}.pkl")
    if not os.path.exists(p): return None
    try: return pickle.load(open(p, "rb"))
    except Exception: return None


def _load_fa(sym):
    p = os.path.join(FA_DIR, f"{sym}.pkl")
    if not os.path.exists(p): return {}
    try:
        fa = pickle.load(open(p, "rb"))
        return fa if isinstance(fa, dict) else {}
    except Exception: return {}


def _ret(df, bars):
    if df is None or len(df) < bars + 1: return None
    try:
        a = float(df["Close"].iloc[-1]); b = float(df["Close"].iloc[-bars - 1])
        return (a - b) / b * 100 if b > 0 else None
    except Exception: return None


def _pct_rank(values: Dict[str, Optional[float]]) -> Dict[str, int]:
    """Map raw values → 1-99 percentile. None → None."""
    valid = [(k, v) for k, v in values.items() if v is not None and not np.isnan(v)]
    if not valid: return {k: None for k in values}
    valid.sort(key=lambda x: x[1])
    n = len(valid)
    ranks = {}
    for i, (k, _) in enumerate(valid):
        ranks[k] = max(1, min(99, int(round((i + 1) / n * 99))))
    for k in values:
        if k not in ranks: ranks[k] = None
    return ranks


def _sector(sym):
    try:
        from data.sector_map import get_sector
        return get_sector(sym) or "Other"
    except Exception: return "Other"


def _universe_symbols() -> List[str]:
    if not os.path.isdir(HIST_DIR): return []
    return sorted(f[:-4] for f in os.listdir(HIST_DIR) if f.endswith(".pkl"))


def _raw_for(sym: str) -> Optional[Dict[str, Any]]:
    """Compute raw factor metrics for one symbol. None if history missing."""
    df = _load_hist(sym); fa = _load_fa(sym)
    if df is None: return None
    roe = fa.get("roe_pct") or fa.get("roe")
    de = fa.get("debt_to_equity")
    roce = fa.get("roce_pct") or fa.get("roce")
    pe = fa.get("pe") or fa.get("trailing_pe")
    pb = fa.get("pb")
    eps = fa.get("eps")
    r6 = _ret(df, 126); r1m = _ret(df, 21)
    quality = None
    q_parts = [v for v in [roe, (1.0 / (1.0 + de)) * 100 if isinstance(de, (int, float)) else None, roce] if isinstance(v, (int, float))]
    if q_parts: quality = float(np.mean(q_parts))
    value = None
    v_parts = [1.0 / pe if isinstance(pe, (int, float)) and pe > 0 else None,
               1.0 / pb if isinstance(pb, (int, float)) and pb > 0 else None]
    v_parts = [v for v in v_parts if v is not None]
    if v_parts: value = float(np.mean(v_parts))
    growth = eps if isinstance(eps, (int, float)) else r1m
    return {"momentum": r6, "quality": quality, "value": value, "growth": growth,
            "sector": _sector(sym)}


def _rank_in(v: Optional[float], dist: List[float]) -> Optional[int]:
    """Percentile (1-99) of v within sorted numeric dist."""
    if v is None or dist is None or not dist: return None
    try: v = float(v)
    except Exception: return None
    if np.isnan(v): return None
    n = len(dist)
    # dist is already sorted ascending
    import bisect
    pos = bisect.bisect_left(dist, v)
    return max(1, min(99, int(round((pos + 1) / n * 99))))


def _write_cache_atomic(obj):
    """Atomic write — a crash during pickle.dump can't leave a corrupted cache."""
    try:
        tmp = CACHE_F + ".tmp"
        pickle.dump(obj, open(tmp, "wb"))
        os.replace(tmp, CACHE_F)
    except Exception: pass


def _lazy_merge(missing: List[str], cached: Dict[str, Dict[str, Any]]) -> bool:
    """Compute raw factors for the missing symbols, re-rank them against the
    existing universe's raw distribution (stored in cache), merge into cache
    in-place. Returns True if merge path actually ran — False signals the
    caller to fall back to a full recompute (cache has no `raw` field yet)."""
    # Extract raw distributions from cache. Bail out if empty — old cache format.
    mom, qua, gro = [], [], []
    val_by_sec: Dict[str, List[float]] = {}
    for e in cached.values():
        raw = e.get("raw") if isinstance(e, dict) else None
        if not raw: continue
        if isinstance(raw.get("momentum"), (int, float)): mom.append(float(raw["momentum"]))
        if isinstance(raw.get("quality"), (int, float)): qua.append(float(raw["quality"]))
        if isinstance(raw.get("growth"), (int, float)): gro.append(float(raw["growth"]))
        if isinstance(raw.get("value"), (int, float)):
            sec = raw.get("sector") or "Other"
            val_by_sec.setdefault(sec, []).append(float(raw["value"]))
    if not mom:  # old cache format — no raw values anywhere
        return False
    mom.sort(); qua.sort(); gro.sort()
    for k in val_by_sec: val_by_sec[k].sort()

    for s in missing:
        r = _raw_for(s)
        if r is None:
            continue
        sec_dist = val_by_sec.get(r["sector"]) or val_by_sec.get("Other") or []
        ranks = {
            "momentum": _rank_in(r["momentum"], mom),
            "quality":  _rank_in(r["quality"],  qua),
            "value":    _rank_in(r["value"],    sec_dist),
            "growth":   _rank_in(r["growth"],   gro),
        }
        valid = [p for p in ranks.values() if p is not None]
        composite = int(round(sum(valid) / len(valid))) if valid else None
        cached[s] = {"score": composite, **ranks, "raw": r}
    _write_cache_atomic(cached)
    return True


def compute_factor_scores(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Returns {sym: {score, momentum, quality, value, growth}} as 1-99 percentiles.
    Percentiles always rank against the FULL universe (all stocks with history),
    not just the requested subset — so a 5-stock screen still gets meaningful scores.

    Three paths:
      1. Cache fresh + covers all requested → subset lookup (fast, O(N)).
      2. Cache fresh + missing some symbols → lazy partial update: compute raw
         factors for just the N missing and re-rank against the existing cached
         raw distribution, merge back. No full 2620-stock pass.
      3. Cache stale/missing → full universe recompute (existing 24h TTL path).
    """
    universe = _universe_symbols()
    cache_fresh = os.path.exists(CACHE_F) and time.time() - os.path.getmtime(CACHE_F) < TTL
    if cache_fresh:
        try:
            cached = pickle.load(open(CACHE_F, "rb"))
            if len(cached) >= max(100, int(0.8 * len(universe))):
                missing = [s for s in symbols if s not in cached]
                if missing:
                    # Path 2: lazy partial update. If the cache doesn't carry
                    # `raw` fields (pre-this-commit format), _lazy_merge returns
                    # False and we fall through to full recompute.
                    if _lazy_merge(missing, cached):
                        return {s: cached[s] for s in symbols if s in cached}
                else:
                    # Path 1: full subset hit.
                    return {s: cached[s] for s in symbols if s in cached}
        except Exception: pass

    # Path 3: full universe recompute + cache.
    raw = {}
    for s in universe:
        r = _raw_for(s)
        if r is not None: raw[s] = r

    momentum_rk = _pct_rank({k: v["momentum"] for k, v in raw.items()})
    quality_rk = _pct_rank({k: v["quality"] for k, v in raw.items()})
    growth_rk = _pct_rank({k: v["growth"] for k, v in raw.items()})
    by_sec = {}
    for k, v in raw.items():
        by_sec.setdefault(v["sector"], {})[k] = v["value"]
    value_rk = {}
    for sec, items in by_sec.items():
        value_rk.update(_pct_rank(items))

    out = {}
    for s in raw:
        parts = [momentum_rk.get(s), quality_rk.get(s), value_rk.get(s), growth_rk.get(s)]
        valid = [p for p in parts if p is not None]
        composite = int(round(sum(valid) / len(valid))) if valid else None
        out[s] = {
            "score": composite,
            "momentum": momentum_rk.get(s),
            "quality": quality_rk.get(s),
            "value": value_rk.get(s),
            "growth": growth_rk.get(s),
            "raw": raw[s],  # stored so lazy partial updates can re-rank next time
        }

    _write_cache_atomic(out)
    return {s: out[s] for s in symbols if s in out}
