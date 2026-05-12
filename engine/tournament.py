"""
Tournament Mode — same stocks, own pace, same clock.

Lifecycle
---------
1. pending  — host created tournament, waiting for `min_players` entries.
              Stocks are picked at this point but stored hidden.
2. live     — `min_players` reached → status flips to live, `starts_at` /
              `ends_at` set, players can fetch hidden-name candles and trade.
3. closed   — `ends_at` passed (or any sweep call after that). Stock
              names revealed, leaderboard frozen.

The "clock" is real-world time (window_minutes after going live). Each
player plays the simulation at their own speed inside that window.

Anti-cheat
----------
- `stocks_json` is set when the tournament is *created* (so all players
  see the same set), but never returned to clients until status='closed'.
- Sector + sub-sector are also stripped from the candle response while
  live, so players can't deduce the stock from industry classification.
- The slot index (1..n_stocks) is the only identifier clients see;
  internally we map slot → real symbol.
"""

from __future__ import annotations

import json
import random
import time
from typing import Optional, List, Dict, Any

from engine.db import get_conn, now_ts


# ─────────────────────────── helpers ───────────────────────────

def _pick_random_stocks(universe: str, n: int) -> List[str]:
    """Sample `n` random symbols from the configured universe."""
    try:
        from data.nse_symbols import get_nifty_universe
        pool = get_nifty_universe(universe if universe in ("nifty50","nifty100","nifty200","nifty500") else "nifty500")
    except Exception:
        pool = []
    if not pool:
        # Fallback to a small hand-picked liquid list
        pool = ["RELIANCE","TCS","INFY","HDFCBANK","ICICIBANK","SBIN","ITC","LT","BHARTIARTL","BAJFINANCE",
                "AXISBANK","KOTAKBANK","MARUTI","ASIANPAINT","HCLTECH","WIPRO","SUNPHARMA","TITAN","ULTRACEMCO","NTPC"]
    n = max(1, min(n, len(pool)))
    return random.sample(list(pool), n)


def _strip_hidden(t: Dict[str, Any]) -> Dict[str, Any]:
    """Remove stock names from a tournament row when status != 'closed'."""
    if t.get("status") != "closed":
        t = dict(t)
        t["stocks"] = None  # signal explicitly that names are hidden
    else:
        try: t["stocks"] = json.loads(t.get("stocks_json", "[]"))
        except Exception: t["stocks"] = []
    return t


def _row_to_dict(r) -> Dict[str, Any]:
    d = dict(r)
    return _strip_hidden(d)


# ─────────────────────────── tournament lifecycle ───────────────────────────

def create_tournament(
    host_id: int,
    name: str,
    n_stocks: int = 5,
    days_per_stock: int = 60,
    window_minutes: int = 45,
    min_players: int = 2,
    universe: str = "nifty500",
) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required")
    if n_stocks not in (3, 5, 10):
        raise ValueError("n_stocks must be 3, 5, or 10")
    if days_per_stock < 20 or days_per_stock > 250:
        raise ValueError("days_per_stock out of range")
    if window_minutes < 5 or window_minutes > 240:
        raise ValueError("window_minutes out of range (5-240)")
    if min_players < 2:
        min_players = 2

    stocks = _pick_random_stocks(universe, n_stocks)
    now = now_ts()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tournaments
               (host_id, name, n_stocks, days_per_stock, window_minutes, min_players,
                universe, status, stocks_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (host_id, name, n_stocks, days_per_stock, window_minutes, min_players,
             universe, json.dumps(stocks), now),
        )
        tid = cur.lastrowid
        row = conn.execute("SELECT * FROM tournaments WHERE id = ?", (tid,)).fetchone()
    return _row_to_dict(row)


def list_tournaments(status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List tournaments. status: pending | live | closed | None=all."""
    # Run a passive sweep so stale 'live' rows get marked 'closed' on read.
    _sweep_expired()
    sql = "SELECT t.*, u.username AS host, (SELECT COUNT(*) FROM tournament_entries e WHERE e.tournament_id = t.id) AS players FROM tournaments t LEFT JOIN users u ON u.id = t.host_id"
    params: list = []
    if status:
        sql += " WHERE t.status = ?"
        params.append(status)
    sql += " ORDER BY t.created_at DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_tournament(tid: int) -> Optional[Dict[str, Any]]:
    _sweep_expired()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT t.*, u.username AS host FROM tournaments t LEFT JOIN users u ON u.id = t.host_id WHERE t.id = ?",
            (tid,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def join_tournament(tid: int, user_id: int) -> Dict[str, Any]:
    now = now_ts()
    with get_conn() as conn:
        t = conn.execute("SELECT * FROM tournaments WHERE id = ?", (tid,)).fetchone()
        if not t:
            raise ValueError("Tournament not found")
        if t["status"] == "closed":
            raise PermissionError("Tournament has already closed")
        # Insert entry (idempotent thanks to UNIQUE)
        try:
            conn.execute(
                "INSERT INTO tournament_entries(tournament_id, user_id, joined_at) VALUES (?,?,?)",
                (tid, user_id, now),
            )
        except Exception:
            pass
        # Flip to live if threshold met
        count = conn.execute(
            "SELECT COUNT(*) FROM tournament_entries WHERE tournament_id = ?", (tid,)
        ).fetchone()[0]
        if t["status"] == "pending" and count >= t["min_players"]:
            ends = now + t["window_minutes"] * 60
            conn.execute(
                "UPDATE tournaments SET status = 'live', starts_at = ?, ends_at = ? WHERE id = ?",
                (now, ends, tid),
            )
    return get_tournament(tid)


def get_my_entry(tid: int, user_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tournament_entries WHERE tournament_id = ? AND user_id = ?",
            (tid, user_id),
        ).fetchone()
    return dict(row) if row else None


def get_slot_symbol(tid: int, slot: int) -> Optional[str]:
    """Return the real symbol for a given slot — used server-side only by the
    candle-fetching endpoint. Slots are 1-indexed."""
    with get_conn() as conn:
        row = conn.execute("SELECT stocks_json, status, ends_at FROM tournaments WHERE id = ?", (tid,)).fetchone()
    if not row:
        return None
    try:
        stocks = json.loads(row["stocks_json"])
    except Exception:
        return None
    if slot < 1 or slot > len(stocks):
        return None
    return stocks[slot - 1]


def submit_entry(
    tid: int,
    user_id: int,
    per_stock_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate per-stock results into a single entry summary."""
    if not per_stock_results:
        raise ValueError("per_stock_results is empty")
    valid = [r for r in per_stock_results if r.get("trades_count", 0) >= 1]
    if not valid:
        raise ValueError("At least 1 trade required across all stocks to submit")
    avg_return = sum(r.get("return_pct", 0) for r in per_stock_results) / len(per_stock_results)
    total_trades = sum(r.get("trades_count", 0) for r in per_stock_results)
    avg_win_rate = (
        sum(r.get("win_rate", 0) for r in per_stock_results) / len(per_stock_results)
    )
    sharpes = [r.get("sharpe") for r in per_stock_results if r.get("sharpe") is not None]
    avg_sharpe = sum(sharpes) / len(sharpes) if sharpes else None
    pfs = [r.get("profit_factor") for r in per_stock_results if r.get("profit_factor") is not None]
    avg_pf = sum(pfs) / len(pfs) if pfs else None
    now = now_ts()
    with get_conn() as conn:
        conn.execute(
            """UPDATE tournament_entries
                  SET submitted_at = ?, return_pct = ?, win_rate = ?, trades_count = ?,
                      sharpe = ?, profit_factor = ?, per_stock_json = ?
                WHERE tournament_id = ? AND user_id = ?""",
            (now, round(avg_return, 2), round(avg_win_rate, 2), total_trades,
             round(avg_sharpe, 2) if avg_sharpe is not None else None,
             round(avg_pf, 2) if avg_pf is not None else None,
             json.dumps(per_stock_results),
             tid, user_id),
        )
        row = conn.execute(
            "SELECT * FROM tournament_entries WHERE tournament_id = ? AND user_id = ?",
            (tid, user_id),
        ).fetchone()
    return dict(row) if row else {}


def leaderboard(tid: int) -> Dict[str, Any]:
    """Live or final leaderboard for a tournament. Stock names visible only
    once the tournament has closed."""
    _sweep_expired()
    t = get_tournament(tid)
    if not t:
        return {}
    closed = t["status"] == "closed"
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT e.*, u.username
                 FROM tournament_entries e
                 JOIN users u ON u.id = e.user_id
                WHERE e.tournament_id = ?
             ORDER BY e.return_pct DESC NULLS LAST, e.submitted_at""",
            (tid,),
        ).fetchall()
    entries: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if not closed:
            d["per_stock_json"] = None
        entries.append(d)
    return {"tournament": t, "entries": entries, "revealed": closed}


def _sweep_expired() -> None:
    """Mark any live tournaments past their ends_at as closed."""
    now = now_ts()
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE tournaments SET status = 'closed' WHERE status = 'live' AND ends_at IS NOT NULL AND ends_at < ?",
                (now,),
            )
    except Exception:
        pass


def cancel_tournament(tid: int, requester_id: int, is_admin: bool = False) -> None:
    """Host or admin can cancel a pending tournament. Refuses if live or closed."""
    with get_conn() as conn:
        t = conn.execute("SELECT * FROM tournaments WHERE id = ?", (tid,)).fetchone()
        if not t:
            raise ValueError("Not found")
        if not is_admin and t["host_id"] != requester_id:
            raise PermissionError("Only the host or admin can cancel")
        if t["status"] != "pending":
            raise PermissionError("Can only cancel pending tournaments")
        conn.execute("DELETE FROM tournaments WHERE id = ?", (tid,))
