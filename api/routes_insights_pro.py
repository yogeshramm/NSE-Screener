"""
Insights Pro: composite verdict (BUY/ACCUMULATE/HOLD/REDUCE/SELL) pulling
together technicals, multi-factor score, institutional flows, sector context,
news, upcoming events. Explainable — each score contribution is returned.
"""
import os, pickle
from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List

router = APIRouter()

HIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")
FA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "fundamentals")


def _load_hist(sym):
    p = os.path.join(HIST, f"{sym}.pkl")
    if not os.path.exists(p): return None
    try: return pickle.load(open(p, "rb"))
    except Exception: return None


def _load_fa(sym):
    p = os.path.join(FA, f"{sym}.pkl")
    if not os.path.exists(p): return {}
    try:
        fa = pickle.load(open(p, "rb"))
        return fa if isinstance(fa, dict) else {}
    except Exception: return {}


def _pct(a, b): return (a - b) / b * 100 if b else 0


def _technicals(df):
    """Quick technicals: RSI-14, SMA50/200, 52W pct, ATR%, trend."""
    import numpy as np
    close = df["Close"].astype(float)
    last = float(close.iloc[-1])
    # RSI-14
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = float((100 - 100 / (1 + rs)).iloc[-1]) if len(close) >= 14 else None
    sma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
    sma200 = float(close.tail(200).mean()) if len(close) >= 200 else None
    w52 = close.tail(252)
    w52h = float(w52.max()); w52l = float(w52.min())
    trend = "up" if sma50 and sma200 and sma50 > sma200 and last > sma50 else \
            "down" if sma50 and sma200 and sma50 < sma200 and last < sma50 else "side"
    atr = None
    if len(df) >= 14:
        h = df["High"].astype(float); l = df["Low"].astype(float); c = close
        tr = (h - l).combine(abs(h - c.shift()), max).combine(abs(l - c.shift()), max)
        atr = float(tr.tail(14).mean())
    return {
        "price": round(last, 2), "rsi": round(rsi, 1) if rsi else None,
        "sma50": round(sma50, 2) if sma50 else None,
        "sma200": round(sma200, 2) if sma200 else None,
        "w52_high": round(w52h, 2), "w52_low": round(w52l, 2),
        "pct_from_52wh": round(_pct(last, w52h), 1),
        "pct_from_52wl": round(_pct(last, w52l), 1),
        "trend": trend, "atr_pct": round(atr / last * 100, 2) if atr else None,
    }


def _scores_and_verdict(tech, mfs, sector_1m, fii_dii_net):
    """Explainable scoring. Returns (verdict, buckets, reasons)."""
    buckets = {}
    # Technical (0-25): RSI sweet-spot + trend + 52W position
    t = 0; tr = []
    if tech["rsi"] and 40 <= tech["rsi"] <= 70: t += 8; tr.append(f"RSI {tech['rsi']} in healthy range")
    elif tech["rsi"] and tech["rsi"] > 70: t += 3; tr.append(f"RSI {tech['rsi']} overbought")
    elif tech["rsi"] and tech["rsi"] < 40: t += 2; tr.append(f"RSI {tech['rsi']} weak")
    if tech["trend"] == "up": t += 10; tr.append("Uptrend (price > SMA50 > SMA200)")
    elif tech["trend"] == "down": t += 1; tr.append("Downtrend")
    else: t += 5
    if tech["pct_from_52wh"] > -8: t += 7; tr.append(f"Near 52W high ({tech['pct_from_52wh']}%)")
    elif tech["pct_from_52wh"] > -25: t += 4
    buckets["technical"] = {"score": t, "max": 25}
    # MFS (0-25): direct scale
    m = int(round((mfs or 50) * 0.25)) if mfs else 10
    buckets["multi_factor"] = {"score": m, "max": 25, "components": {"composite": mfs or None}}
    # Sector (0-15): momentum
    s = 7
    if sector_1m is not None:
        if sector_1m > 4: s = 15
        elif sector_1m > 1: s = 11
        elif sector_1m < -3: s = 2
        else: s = 7
    buckets["sector"] = {"score": s, "max": 15, "sector_1m_return": sector_1m}
    # Institutional flows (0-10): all-market directional proxy
    i = 5
    if fii_dii_net is not None:
        if fii_dii_net > 2000: i = 10
        elif fii_dii_net > 0: i = 7
        elif fii_dii_net < -2000: i = 2
        else: i = 5
    buckets["flows"] = {"score": i, "max": 10, "net_cr": fii_dii_net}
    total = t + m + s + i
    # Verdict bands out of 75
    if total >= 58: v = "BUY"
    elif total >= 48: v = "ACCUMULATE"
    elif total >= 35: v = "HOLD"
    elif total >= 25: v = "REDUCE"
    else: v = "SELL"
    return v, total, buckets, tr


@router.get("/stock/{symbol}/insights-pro")
def insights_pro(symbol: str):
    symbol = symbol.strip().upper()
    df = _load_hist(symbol)
    if df is None or len(df) < 30:
        raise HTTPException(404, f"No history for {symbol}")

    tech = _technicals(df)
    fa = _load_fa(symbol)

    # MFS (single-symbol percentile isn't meaningful; read from cache if present)
    mfs = None; mfs_bundle = None
    from engine.multi_factor import CACHE_F
    if os.path.exists(CACHE_F):
        try:
            cached = pickle.load(open(CACHE_F, "rb"))
            mfs_bundle = cached.get(symbol)
            if mfs_bundle: mfs = mfs_bundle.get("score")
        except Exception: pass

    # Sector momentum (1M)
    sector_1m = None; sector_name = None
    try:
        from data.sector_map import get_sector
        sector_name = get_sector(symbol)
        from engine.market_analytics import sector_heatmap
        all_syms = [f.replace(".pkl", "") for f in os.listdir(HIST) if f.endswith(".pkl")]
        heat = sector_heatmap(all_syms)
        for h in heat:
            if h["sector"] == sector_name: sector_1m = h.get("1M"); break
    except Exception: pass

    # FII/DII combined net (last session)
    fii_dii_net = None
    try:
        from data.nse_fii_dii import get_net_fii_dii_summary
        summ = get_net_fii_dii_summary(1)
        fii_dii_net = summ.get("combined_net")
    except Exception: pass

    verdict, total, buckets, tech_reasons = _scores_and_verdict(tech, mfs, sector_1m, fii_dii_net)

    # Reasons: top 5 bullets
    reasons = list(tech_reasons)
    if mfs_bundle and mfs_bundle.get("quality") and mfs_bundle["quality"] >= 70:
        reasons.append(f"Quality factor strong ({mfs_bundle['quality']})")
    if mfs_bundle and mfs_bundle.get("value") and mfs_bundle["value"] >= 70:
        reasons.append(f"Value factor strong ({mfs_bundle['value']})")
    if sector_1m is not None:
        reasons.append(f"{sector_name} sector 1M: {sector_1m:+.1f}%")
    if fii_dii_net is not None:
        dir = "inflow" if fii_dii_net > 0 else "outflow"
        reasons.append(f"FII+DII net {dir} ₹{abs(int(fii_dii_net))} Cr last session")
    reasons = reasons[:5]

    # Analyst signal (optional — 4-source composite)
    analyst = None
    try:
        from data.analyst_ratings import get_analyst_signal
        analyst = get_analyst_signal(symbol)
    except Exception: pass

    # News (top 3)
    news = []
    try:
        from data.stock_news import get_news
        news = get_news(symbol, limit=3)
    except Exception: pass

    # Upcoming events (next 2)
    events = []
    try:
        from data.nse_events import get_upcoming_events_for_symbol  # type: ignore
        events = get_upcoming_events_for_symbol(symbol)[:2]
    except Exception:
        try:
            from data.nse_events import get_upcoming_events
            events = [e for e in get_upcoming_events() if e.get("symbol", "").upper() == symbol][:2]
        except Exception: pass

    return {
        "symbol": symbol,
        "verdict": verdict,
        "score": total,
        "max_score": 75,
        "buckets": buckets,
        "why": reasons,
        "technicals": tech,
        "fundamentals": {
            "pe": fa.get("pe"), "pb": fa.get("pb"), "roe": fa.get("roe_pct") or fa.get("roe"),
            "debt_to_equity": fa.get("debt_to_equity"),
            "market_cap_cr": fa.get("market_cap"),
        },
        "multi_factor": mfs_bundle,
        "sector": {"name": sector_name, "return_1m": sector_1m},
        "flows": {"net_cr": fii_dii_net},
        "news": news,
        "events": events,
        "analyst": analyst,
    }
