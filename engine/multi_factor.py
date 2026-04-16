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


def compute_factor_scores(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Returns {sym: {score, momentum, quality, value, growth}} as 1-99 percentiles."""
    # Cache check
    if os.path.exists(CACHE_F) and time.time() - os.path.getmtime(CACHE_F) < TTL:
        try:
            cached = pickle.load(open(CACHE_F, "rb"))
            if set(symbols).issubset(cached.keys()):
                return {s: cached[s] for s in symbols}
        except Exception: pass

    # Raw metrics per symbol
    raw = {}
    for s in symbols:
        df = _load_hist(s); fa = _load_fa(s)
        if df is None: continue
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
        raw[s] = {
            "momentum": r6, "quality": quality, "value": value, "growth": growth,
            "sector": _sector(s),
        }

    # Percentile rank each factor across universe
    momentum_rk = _pct_rank({k: v["momentum"] for k, v in raw.items()})
    quality_rk = _pct_rank({k: v["quality"] for k, v in raw.items()})
    growth_rk = _pct_rank({k: v["growth"] for k, v in raw.items()})
    # Value: sector-relative
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
        }

    # Cache entire computation (covers any subset next time)
    try: pickle.dump(out, open(CACHE_F, "wb"))
    except Exception: pass
    return out
