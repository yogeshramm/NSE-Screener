"""Chart Patterns API: advanced multi-bar breakout patterns."""
from fastapi import APIRouter
from pydantic import BaseModel
from engine.chart_patterns import list_patterns, scan, _DETECTORS, PATTERNS, _load

router = APIRouter()


@router.get("/chart-patterns/detect/{symbol}")
def chart_patterns_detect(symbol: str):
    """Run all 10 detectors on this symbol's current history. Return matches with accuracy."""
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
                hits.append({"key": k, "name": name.get(k, k), "accuracy": acc.get(k, 0), **r})
        except Exception:
            continue
    hits.sort(key=lambda h: h.get("confidence", 0), reverse=True)
    return {"symbol": symbol.upper(), "hits": hits}


@router.get("/chart-patterns/detect-history/{symbol}")
def chart_patterns_detect_history(symbol: str, days: int = 200, step: int = 2, cooldown: int = 8):
    """Scan history bar-by-bar (step apart), dedup consecutive same-pattern matches within
    `cooldown` bars. Returns list of {time, key, name, accuracy} sorted chronologically."""
    df = _load(symbol.upper())
    if df is None or len(df) < 40:
        return {"symbol": symbol.upper(), "hits": []}
    # Limit scan window to last `days` bars
    df = df.tail(max(60, days + 20))
    acc = {p["key"]: p["accuracy"] for p in PATTERNS}
    name = {p["key"]: p["name"] for p in PATTERNS}
    hits = []
    last_idx_for = {}  # key -> bar index of last recorded hit (for dedup cooldown)
    n = len(df)
    idxs = list(range(30, n, max(1, step)))
    if idxs and idxs[-1] != n - 1:
        idxs.append(n - 1)  # always include the latest bar
    for i in idxs:
        sub = df.iloc[:i + 1]
        for k, det in _DETECTORS.items():
            if i - last_idx_for.get(k, -999) < cooldown:
                continue
            try:
                r = det(sub)
                if r:
                    t = int(sub.index[-1].timestamp()) if hasattr(sub.index[-1], "timestamp") else 0
                    hits.append({"time": t, "key": k, "name": name.get(k, k), "accuracy": acc.get(k, 0), "confidence": r.get("confidence", 0)})
                    last_idx_for[k] = i
            except Exception:
                continue
    return {"symbol": symbol.upper(), "hits": hits}


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
