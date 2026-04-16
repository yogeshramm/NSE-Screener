"""
Institutional Radar data: bulk deals, block deals, delivery % leaderboard, breadth.

NSE public JSON endpoints + local history pickles. 24h disk cache.
Gracefully degrades if NSE is geo-restricted.
"""
import os, pickle, time, requests
from datetime import datetime, timedelta
from typing import List, Dict, Any

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "institutional")
os.makedirs(CACHE_DIR, exist_ok=True)
TTL = 24 * 3600

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def _cp(name): return os.path.join(CACHE_DIR, f"{name}.pkl")


def _lc(name):
    p = _cp(name)
    if not os.path.exists(p): return None
    try:
        if time.time() - os.path.getmtime(p) > TTL: return None
        return pickle.load(open(p, "rb"))
    except Exception: return None


def _sc(name, data):
    try: pickle.dump(data, open(_cp(name), "wb"))
    except Exception: pass


def _session():
    s = requests.Session(); s.headers.update(_HEADERS)
    try: s.get("https://www.nseindia.com/", timeout=10)
    except Exception: pass
    return s


def _fetch_json(url, sess=None, tries=2):
    sess = sess or _session()
    for _ in range(tries):
        try:
            r = sess.get(url, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception: pass
    return None


def fetch_bulk_deals(days: int = 7) -> List[Dict[str, Any]]:
    """Bulk deals (>=0.5% of listed equity). Last N days."""
    cached = _lc(f"bulk_{days}")
    if cached is not None: return cached
    to_d = datetime.now(); from_d = to_d - timedelta(days=days)
    url = f"https://www.nseindia.com/api/historical/cm/bulk?from={from_d.strftime('%d-%m-%Y')}&to={to_d.strftime('%d-%m-%Y')}"
    data = _fetch_json(url)
    out = []
    if data and isinstance(data, dict):
        for r in data.get("data", []):
            try:
                out.append({
                    "date": r.get("BD_DT_DATE") or r.get("date", ""),
                    "symbol": r.get("BD_SYMBOL") or r.get("symbol", ""),
                    "client": r.get("BD_CLIENT_NAME") or r.get("clientName", ""),
                    "action": r.get("BD_BUY_SELL") or r.get("buySell", ""),
                    "qty": int(str(r.get("BD_QTY_TRD", r.get("qty", 0))).replace(",", "") or 0),
                    "price": float(str(r.get("BD_TP_WATP", r.get("price", 0))).replace(",", "") or 0),
                })
            except Exception: continue
    _sc(f"bulk_{days}", out)
    return out


def fetch_block_deals(days: int = 7) -> List[Dict[str, Any]]:
    cached = _lc(f"block_{days}")
    if cached is not None: return cached
    to_d = datetime.now(); from_d = to_d - timedelta(days=days)
    url = f"https://www.nseindia.com/api/historical/cm/block?from={from_d.strftime('%d-%m-%Y')}&to={to_d.strftime('%d-%m-%Y')}"
    data = _fetch_json(url)
    out = []
    if data and isinstance(data, dict):
        for r in data.get("data", []):
            try:
                out.append({
                    "date": r.get("BD_DT_DATE") or r.get("date", ""),
                    "symbol": r.get("BD_SYMBOL") or r.get("symbol", ""),
                    "client": r.get("BD_CLIENT_NAME") or r.get("clientName", ""),
                    "action": r.get("BD_BUY_SELL") or r.get("buySell", ""),
                    "qty": int(str(r.get("BD_QTY_TRD", r.get("qty", 0))).replace(",", "") or 0),
                    "price": float(str(r.get("BD_TP_WATP", r.get("price", 0))).replace(",", "") or 0),
                })
            except Exception: continue
    _sc(f"block_{days}", out)
    return out


def fetch_delivery_leaders(top_n: int = 25) -> List[Dict[str, Any]]:
    """High-delivery-% stocks today (conviction signal). NSE security-wise delivery."""
    cached = _lc("delivery")
    if cached is not None: return cached[:top_n]
    url = "https://www.nseindia.com/api/snapshot-capital-market-delivery"
    data = _fetch_json(url)
    out = []
    if data and isinstance(data, dict):
        items = data.get("data", [])
        for r in items:
            try:
                dp = float(str(r.get("deliveryToTradedQuantity", r.get("deliveryPercent", 0))).replace(",", "") or 0)
                if dp <= 0: continue
                out.append({
                    "symbol": r.get("symbol", ""),
                    "deliv_pct": round(dp, 2),
                    "deliv_qty": int(float(str(r.get("deliveryQuantity", 0)).replace(",", "") or 0)),
                    "traded_qty": int(float(str(r.get("tradedQuantity", 0)).replace(",", "") or 0)),
                    "ltp": float(str(r.get("lastPrice", 0)).replace(",", "") or 0),
                    "pchange": float(str(r.get("pChange", 0)).replace(",", "") or 0),
                })
            except Exception: continue
        out.sort(key=lambda x: x["deliv_pct"], reverse=True)
    _sc("delivery", out)
    return out[:top_n]


def compute_market_breadth() -> Dict[str, Any]:
    """From local history: % above 200-DMA, 52W H/L counts, advance/decline."""
    cached = _lc("breadth")
    if cached is not None: return cached
    HIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")
    if not os.path.exists(HIST):
        return {"total": 0, "above_200dma": 0, "above_200dma_pct": 0, "new_52w_high": 0, "new_52w_low": 0, "advances": 0, "declines": 0}
    total = above = hi = lo = adv = dec = 0
    for f in os.listdir(HIST):
        if not f.endswith(".pkl"): continue
        try:
            df = pickle.load(open(os.path.join(HIST, f), "rb"))
            if len(df) < 200: continue
            total += 1
            c = df["Close"]
            last = float(c.iloc[-1]); prev = float(c.iloc[-2])
            if last > c.tail(200).mean(): above += 1
            w52 = c.tail(252)
            if last >= w52.max() * 0.999: hi += 1
            if last <= w52.min() * 1.001: lo += 1
            if last > prev: adv += 1
            elif last < prev: dec += 1
        except Exception: continue
    out = {
        "total": total,
        "above_200dma": above,
        "above_200dma_pct": round(above / total * 100, 1) if total else 0,
        "new_52w_high": hi,
        "new_52w_low": lo,
        "advances": adv,
        "declines": dec,
        "ad_ratio": round(adv / dec, 2) if dec else 0,
    }
    _sc("breadth", out)
    return out
