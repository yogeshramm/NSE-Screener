"""Chart Patterns API: advanced multi-bar breakout patterns."""
from fastapi import APIRouter
from pydantic import BaseModel
from engine.chart_patterns import list_patterns, scan, _DETECTORS, PATTERNS, _load

router = APIRouter()


# Per-pattern "breakout trigger" field — the price level that confirms the breakout.
TRIG_FIELDS = {
    "rectangle": "top",
    "ascending_triangle": "resistance",
    "bull_flag": "flag_high",
    "cup_handle": "cup_high",
    "high_tight_flag": "peak",
    "darvas_box": "top",
    "pivot_breakout": "pivot",
}


@router.get("/chart-patterns/detect/{symbol}")
def chart_patterns_detect(symbol: str):
    """Run all 10 detectors on current history. Include breakout trigger level."""
    df = _load(symbol.upper())
    if df is None or len(df) < 30:
        return {"symbol": symbol.upper(), "hits": []}
    acc = {p["key"]: p["accuracy"] for p in PATTERNS}
    name = {p["key"]: p["name"] for p in PATTERNS}
    hits = []
    for k, det in _DETECTORS.items():
        try:
            r = det(df)
            if r:
                trig = r.get(TRIG_FIELDS.get(k, "")) if k in TRIG_FIELDS else None
                hits.append({"key": k, "name": name.get(k, k), "accuracy": acc.get(k, 0), "trigger": trig, **r})
        except Exception:
            continue
    hits.sort(key=lambda h: h.get("confidence", 0), reverse=True)
    return {"symbol": symbol.upper(), "hits": hits}


@router.get("/chart-patterns/detect-history/{symbol}")
def chart_patterns_detect_history(symbol: str, days: int = 200, step: int = 2, cooldown: int = 8,
                                   forward_bars: int = 10, win_pct: float = 3.0):
    """Historical scan + forward-walk outcome + stock-specific accuracy per pattern."""
    df = _load(symbol.upper())
    if df is None or len(df) < 40:
        return {"symbol": symbol.upper(), "hits": [], "stock_accuracy": {}}
    df = df.tail(max(60, days + 20))
    n = len(df)
    acc = {p["key"]: p["accuracy"] for p in PATTERNS}
    name = {p["key"]: p["name"] for p in PATTERNS}
    hits = []
    last_idx_for = {}
    idxs = list(range(30, n, max(1, step)))
    if idxs and idxs[-1] != n - 1:
        idxs.append(n - 1)
    for i in idxs:
        sub = df.iloc[:i + 1]
        for k, det in _DETECTORS.items():
            if i - last_idx_for.get(k, -999) < cooldown:
                continue
            try:
                r = det(sub)
                if r:
                    t = int(sub.index[-1].timestamp()) if hasattr(sub.index[-1], "timestamp") else 0
                    # Forward-walk outcome over next `forward_bars` bars
                    outcome = "pending"
                    if i + forward_bars < n:
                        entry = float(df["Close"].iloc[i])
                        fh = float(df["High"].iloc[i+1:i+1+forward_bars].max())
                        fl = float(df["Low"].iloc[i+1:i+1+forward_bars].min())
                        up_pct = (fh - entry) / entry * 100 if entry else 0
                        down_pct = (fl - entry) / entry * 100 if entry else 0
                        if up_pct >= win_pct:
                            outcome = "win"
                        elif down_pct <= -win_pct:
                            outcome = "loss"
                        else:
                            outcome = "neutral"
                    hits.append({"time": t, "key": k, "name": name.get(k, k),
                                 "accuracy": acc.get(k, 0), "confidence": r.get("confidence", 0),
                                 "outcome": outcome})
                    last_idx_for[k] = i
            except Exception:
                continue
    # Stock-specific accuracy (skip "pending" outcomes that lack forward data)
    buckets = {}
    for h in hits:
        if h["outcome"] == "pending":
            continue
        b = buckets.setdefault(h["key"], [0, 0, 0])  # w, l, n
        if h["outcome"] == "win": b[0] += 1
        elif h["outcome"] == "loss": b[1] += 1
        else: b[2] += 1
    stock_acc = {}
    for k, (w, l, nn) in buckets.items():
        tot = w + l + nn
        if tot >= 3:
            stock_acc[k] = {"wins": w, "losses": l, "neutral": nn, "rate": round(w / tot * 100, 1), "n": tot}
    return {"symbol": symbol.upper(), "hits": hits, "stock_accuracy": stock_acc}


class ScanReq(BaseModel):
    pattern: str
    universe: str = "nifty500"


@router.get("/chart-patterns/list")
def chart_patterns_list():
    return {"patterns": list_patterns()}


@router.post("/chart-patterns/scan")
def chart_patterns_scan(req: ScanReq):
    from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK
    import os
    HIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")
    all_h = sorted(f.replace(".pkl", "") for f in os.listdir(HIST) if f.endswith(".pkl")) if os.path.exists(HIST) else []
    try:
        nifty = set(get_nifty500_live())
    except Exception:
        nifty = set(NIFTY_500_FALLBACK)
    syms = [s for s in all_h if s in nifty] if req.universe == "nifty500" else [s for s in all_h if s not in nifty] if req.universe == "next500" else all_h
    hits = scan(req.pattern, syms)
    return {"pattern": req.pattern, "universe": req.universe, "count": len(hits), "hits": hits}
