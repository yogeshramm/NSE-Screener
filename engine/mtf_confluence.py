"""
Multi-Timeframe Confluence — signal strength across 1D / 1W / 1M.

Per timeframe: check RSI band, MA-stack alignment, trend (HH-HL), close vs 20-period MA.
Each TF scored -3 … +3. Total -9 … +9 mapped to label (STRONG BUY, BUY, NEUTRAL, …).

Reuses daily history pickle; resamples to W/M.
Cached to data_store/mtf_confluence.pkl, 6h TTL.
"""
import os, pickle, time
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

HIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")
CACHE_F = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "mtf_confluence.pkl")
TTL = 6 * 3600


def _load(sym):
    p = os.path.join(HIST, f"{sym}.pkl")
    if not os.path.exists(p): return None
    try:
        df = pickle.load(open(p, "rb"))
        return df[~df.index.duplicated(keep="last")]
    except Exception: return None


def _rsi(c, n=14):
    d = c.diff(); g = d.clip(lower=0).rolling(n).mean(); l = -d.clip(upper=0).rolling(n).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _tf_score(df: pd.DataFrame) -> Dict[str, Any]:
    """Score a single timeframe's dataframe. -3..+3."""
    if df is None or len(df) < 12:
        return {"score": 0, "label": "—", "rsi": None, "trend": None}
    c = df["Close"].astype(float)
    last = float(c.iloc[-1])
    n20 = min(20, len(c)); n50 = min(50, len(c)); n200 = min(200, len(c))
    sma20 = float(c.tail(n20).mean())
    sma50 = float(c.tail(n50).mean())
    sma200 = float(c.tail(n200).mean())
    rsi = None
    if len(c) >= 14:
        rv = float(_rsi(c).iloc[-1])
        if not np.isnan(rv): rsi = rv
    s = 0
    # Stack
    if sma20 > sma50 > sma200 and last > sma20: s += 2
    elif sma20 < sma50 < sma200 and last < sma20: s -= 2
    elif last > sma50: s += 1
    elif last < sma50: s -= 1
    # RSI
    if rsi is not None:
        if 50 <= rsi <= 70: s += 1
        elif rsi > 70: s += 0
        elif 30 <= rsi < 50: s -= 1
        else: s -= 2
    trend = "up" if s >= 2 else "down" if s <= -2 else "side"
    return {"score": max(-3, min(3, s)), "label": trend, "rsi": round(rsi, 1) if rsi else None, "trend": trend}


def _resample(df, rule):
    if df is None or df.empty: return None
    r = df.resample(rule).agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    return r


def compute_mtf(sym: str) -> Optional[Dict[str, Any]]:
    df = _load(sym)
    if df is None: return None
    w = _resample(df, "W"); m = _resample(df, "ME")
    d = _tf_score(df); wk = _tf_score(w); mo = _tf_score(m)
    total = d["score"] + wk["score"] + mo["score"]
    if total >= 6: label = "STRONG BUY"
    elif total >= 3: label = "BUY"
    elif total >= 1: label = "MILD BUY"
    elif total <= -6: label = "STRONG SELL"
    elif total <= -3: label = "SELL"
    elif total <= -1: label = "MILD SELL"
    else: label = "NEUTRAL"
    return {"symbol": sym, "total": total, "label": label, "d1": d, "w1": wk, "m1": mo}


def compute_bulk(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    if os.path.exists(CACHE_F) and time.time() - os.path.getmtime(CACHE_F) < TTL:
        try:
            c = pickle.load(open(CACHE_F, "rb"))
            if set(symbols).issubset(c.keys()): return {s: c[s] for s in symbols if s in c}
        except Exception: pass
    out = {}
    for s in symbols:
        r = compute_mtf(s)
        if r is not None: out[s] = r
    try: pickle.dump(out, open(CACHE_F, "wb"))
    except Exception: pass
    return out
