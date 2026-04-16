"""Portfolio tracker: local-file positions + live P&L from history pickles."""
import os, json, pickle
from typing import List, Dict, Any

ROOT = os.path.dirname(os.path.dirname(__file__))
PORT_DIR = os.path.join(ROOT, "config")
PORT_F = os.path.join(PORT_DIR, "portfolio.json")
HIST = os.path.join(ROOT, "data_store", "history")
os.makedirs(PORT_DIR, exist_ok=True)


def _load_positions() -> List[Dict[str, Any]]:
    if not os.path.exists(PORT_F): return []
    try: return json.load(open(PORT_F))
    except Exception: return []


def _save_positions(positions: List[Dict[str, Any]]):
    json.dump(positions, open(PORT_F, "w"), indent=2)


def _last_two(sym):
    p = os.path.join(HIST, f"{sym}.pkl")
    if not os.path.exists(p): return None, None
    try:
        df = pickle.load(open(p, "rb"))
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else last
        return last, prev
    except Exception: return None, None


def list_positions() -> Dict[str, Any]:
    positions = _load_positions()
    enriched = []
    inv = cur = day = 0.0
    for p in positions:
        sym = p["symbol"]; qty = float(p["qty"]); buy = float(p["buy_price"])
        last, prev = _last_two(sym)
        ltp = last if last is not None else buy
        pchg = prev if prev is not None else ltp
        cur_val = ltp * qty; inv_val = buy * qty
        day_val = (ltp - pchg) * qty
        pnl = cur_val - inv_val; pnl_pct = (pnl / inv_val * 100) if inv_val else 0
        enriched.append({
            **p, "ltp": round(ltp, 2), "prev_close": round(pchg, 2),
            "invested": round(inv_val, 2), "current": round(cur_val, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
            "day_change": round(day_val, 2),
            "day_pct": round((ltp - pchg) / pchg * 100, 2) if pchg else 0,
        })
        inv += inv_val; cur += cur_val; day += day_val
    total_pnl = cur - inv
    return {
        "count": len(enriched),
        "positions": enriched,
        "totals": {
            "invested": round(inv, 2), "current": round(cur, 2),
            "pnl": round(total_pnl, 2),
            "pnl_pct": round(total_pnl / inv * 100, 2) if inv else 0,
            "day_change": round(day, 2),
            "day_pct": round(day / cur * 100, 2) if cur else 0,
        },
    }


def add_position(symbol: str, qty: float, buy_price: float, buy_date: str = "", notes: str = ""):
    symbol = symbol.strip().upper()
    positions = _load_positions()
    positions.append({
        "id": f"{symbol}-{int(__import__('time').time())}",
        "symbol": symbol, "qty": qty, "buy_price": buy_price,
        "buy_date": buy_date, "notes": notes,
    })
    _save_positions(positions)
    return {"ok": True, "count": len(positions)}


def delete_position(pos_id: str):
    positions = _load_positions()
    before = len(positions)
    positions = [p for p in positions if p.get("id") != pos_id]
    _save_positions(positions)
    return {"ok": True, "removed": before - len(positions)}
