"""Portfolio tracker: local-file positions + live P&L from history pickles.

Each user gets their own file: config/portfolio_{username}.json
Falls back to the legacy config/portfolio.json for unauthenticated access.
"""
import os, json, pickle, time
from typing import List, Dict, Any, Optional

ROOT = os.path.dirname(os.path.dirname(__file__))
PORT_DIR = os.path.join(ROOT, "config")
PORT_F = os.path.join(PORT_DIR, "portfolio.json")  # legacy global file
HIST = os.path.join(ROOT, "data_store", "history")
os.makedirs(PORT_DIR, exist_ok=True)


def _port_file(username: Optional[str] = None) -> str:
    """Return the portfolio file path for a user (or legacy global file)."""
    if username:
        return os.path.join(PORT_DIR, f"portfolio_{username}.json")
    return PORT_F


def _load_positions(username: Optional[str] = None) -> List[Dict[str, Any]]:
    f = _port_file(username)
    if not os.path.exists(f):
        return []
    try:
        return json.load(open(f))
    except Exception:
        return []


def _save_positions(positions: List[Dict[str, Any]], username: Optional[str] = None):
    json.dump(positions, open(_port_file(username), "w"), indent=2)


def _last_two(sym):
    p = os.path.join(HIST, f"{sym}.pkl")
    if not os.path.exists(p): return None, None
    try:
        df = pickle.load(open(p, "rb"))
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else last
        return last, prev
    except Exception: return None, None


def list_positions(username: Optional[str] = None) -> Dict[str, Any]:
    positions = _load_positions(username)
    enriched = []
    open_inv = open_cur = open_day = 0.0
    realized_pnl = 0.0

    for p in positions:
        sym = p["symbol"]; qty = float(p["qty"]); buy = float(p["buy_price"])
        status = p.get("status", "open")

        if status == "closed":
            sell_price = float(p.get("sell_price", buy))
            inv_val = buy * qty
            realized = (sell_price - buy) * qty
            realized_pct = (sell_price - buy) / buy * 100 if buy else 0
            realized_pnl += realized
            enriched.append({
                **p,
                "status": "closed",
                "ltp": sell_price,
                "invested": round(inv_val, 2),
                "current": round(sell_price * qty, 2),
                "pnl": round(realized, 2),
                "pnl_pct": round(realized_pct, 2),
                "day_change": 0.0,
                "day_pct": 0.0,
                "prev_close": sell_price,
            })
        else:
            last, prev = _last_two(sym)
            ltp = last if last is not None else buy
            pchg = prev if prev is not None else ltp
            cur_val = ltp * qty; inv_val = buy * qty
            day_val = (ltp - pchg) * qty
            pnl = cur_val - inv_val; pnl_pct = (pnl / inv_val * 100) if inv_val else 0
            enriched.append({
                **p,
                "status": "open",
                "ltp": round(ltp, 2), "prev_close": round(pchg, 2),
                "invested": round(inv_val, 2), "current": round(cur_val, 2),
                "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
                "day_change": round(day_val, 2),
                "day_pct": round((ltp - pchg) / pchg * 100, 2) if pchg else 0,
            })
            open_inv += inv_val; open_cur += cur_val; open_day += day_val

    open_pnl = open_cur - open_inv
    return {
        "count": len(enriched),
        "positions": enriched,
        "totals": {
            "invested": round(open_inv, 2),
            "current": round(open_cur, 2),
            "pnl": round(open_pnl, 2),
            "pnl_pct": round(open_pnl / open_inv * 100, 2) if open_inv else 0,
            "day_change": round(open_day, 2),
            "day_pct": round(open_day / open_cur * 100, 2) if open_cur else 0,
            "realized_pnl": round(realized_pnl, 2),
        },
    }


def add_position(symbol: str, qty: float, buy_price: float,
                 buy_date: str = "", notes: str = "",
                 stop_loss: Optional[float] = None,
                 target: Optional[float] = None,
                 username: Optional[str] = None):
    symbol = symbol.strip().upper()
    positions = _load_positions(username)
    pos: Dict[str, Any] = {
        "id": f"{symbol}-{int(time.time())}",
        "symbol": symbol, "qty": qty, "buy_price": buy_price,
        "buy_date": buy_date, "notes": notes,
        "status": "open",
    }
    if stop_loss is not None: pos["stop_loss"] = stop_loss
    if target is not None:    pos["target"] = target
    positions.append(pos)
    _save_positions(positions, username)
    return {"ok": True, "count": len(positions)}


def close_position(pos_id: str, sell_price: float, sell_date: str = "",
                   username: Optional[str] = None):
    positions = _load_positions(username)
    found = False
    for p in positions:
        if p.get("id") == pos_id:
            p["status"] = "closed"
            p["sell_price"] = sell_price
            p["sell_date"] = sell_date or ""
            found = True
            break
    if not found:
        return {"ok": False, "error": "Position not found"}
    _save_positions(positions, username)
    return {"ok": True}


def update_position(pos_id: str, username: Optional[str] = None, **kwargs):
    """Update any fields on a position (notes, stop_loss, target, qty, etc.)."""
    allowed = {"notes", "stop_loss", "target", "qty", "buy_price", "buy_date"}
    positions = _load_positions(username)
    found = False
    for p in positions:
        if p.get("id") == pos_id:
            for k, v in kwargs.items():
                if k in allowed:
                    p[k] = v
            found = True
            break
    if not found:
        return {"ok": False, "error": "Position not found"}
    _save_positions(positions, username)
    return {"ok": True}


def delete_position(pos_id: str, username: Optional[str] = None):
    positions = _load_positions(username)
    before = len(positions)
    positions = [p for p in positions if p.get("id") != pos_id]
    _save_positions(positions, username)
    return {"ok": True, "removed": before - len(positions)}
