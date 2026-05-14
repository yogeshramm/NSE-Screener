"""
Leaderboard — personal + opt-in public, with month-on-month windows.

Public eligibility rules
------------------------
- user must have opted in (`users.public_profile = 1`)
- session must have ended (`ended_at IS NOT NULL`)
- session must be marked public (`practice_sessions.public = 1`)
- at least 1 trade — pure no-trade lurkers don't rank

Ranking metrics
---------------
We surface return_pct, win_rate, profit_factor, sharpe so the UI can
re-rank locally without re-querying. Default sort is return_pct DESC.

The "month" of a leaderboard row is the YYYY-MM string of `ended_at`
(server-side UTC). Querying `?period=2026-05` returns May 2026 only;
omitting period returns the current month.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from engine.db import get_conn, now_ts


def _month_window(period: Optional[str]) -> Tuple[int, int, str]:
    """Return (start_ts, end_ts, 'YYYY-MM') for a calendar month period.

    period=None → current UTC month
    period='all' → (0, far-future, 'all')
    period='2026-05' → May 2026 UTC
    """
    if period == "all":
        return 0, 4_102_444_800, "all"   # year 2100 sentinel
    if period:
        try:
            year, month = period.split("-")
            y, m = int(year), int(month)
        except Exception:
            now = datetime.now(timezone.utc)
            y, m = now.year, now.month
    else:
        now = datetime.now(timezone.utc)
        y, m = now.year, now.month
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return int(start.timestamp()), int(end.timestamp()), f"{y:04d}-{m:02d}"


def record_session(
    user_id: Optional[int],
    symbol: str,
    summary: Dict[str, Any],
    trades: List[Dict[str, Any]],
    max_days: int,
    mode: str = "free",
    public: bool = False,
) -> int:
    """Persist a finished practice round. Returns the new row id.

    summary is the dict returned by `engine.practice.end_round`.
    public is the user's choice — only public sessions appear on the
    public leaderboard (independent of users.public_profile, which is
    the master opt-in flag at user level).
    """
    now = now_ts()
    return_pct = summary.get("total_pnl_pct")
    win_rate = summary.get("win_rate")
    trades_count = summary.get("total_trades")
    sharpe = summary.get("sharpe")
    profit_factor = summary.get("profit_factor")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO practice_sessions
               (user_id, symbol, max_days, mode, trades_json, summary_json,
                return_pct, win_rate, trades_count, sharpe, profit_factor,
                started_at, ended_at, public)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                user_id, symbol, max_days, mode,
                json.dumps(trades or []),
                json.dumps(summary or {}),
                return_pct, win_rate, trades_count, sharpe, profit_factor,
                now, now, 1 if public else 0,
            ),
        )
        return cur.lastrowid


def personal_history(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """All ended sessions for a user — newest first."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, symbol, max_days, mode, return_pct, win_rate,
                      trades_count, sharpe, profit_factor, started_at,
                      ended_at, public
                 FROM practice_sessions
                WHERE user_id = ? AND ended_at IS NOT NULL
             ORDER BY ended_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def personal_stats(user_id: int) -> Dict[str, Any]:
    """Aggregate stats for the user's own dashboard."""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS rounds,
                      AVG(return_pct)   AS avg_return,
                      AVG(win_rate)     AS avg_win_rate,
                      MAX(return_pct)   AS best_return,
                      SUM(trades_count) AS total_trades
                 FROM practice_sessions
                WHERE user_id = ? AND ended_at IS NOT NULL""",
            (user_id,),
        ).fetchone()
    if not row or row["rounds"] == 0:
        return {"rounds": 0, "avg_return": None, "avg_win_rate": None,
                "best_return": None, "total_trades": 0}
    return {
        "rounds": row["rounds"],
        "avg_return":   round(row["avg_return"] or 0, 2),
        "avg_win_rate": round(row["avg_win_rate"] or 0, 1),
        "best_return":  round(row["best_return"] or 0, 2),
        "total_trades": row["total_trades"] or 0,
    }


def public_leaderboard(
    period: Optional[str] = None,
    sort: str = "return_pct",
    limit: int = 50,
) -> Dict[str, Any]:
    """Opt-in public leaderboard for a month (or 'all')."""
    if sort not in ("return_pct", "win_rate", "profit_factor", "sharpe", "trades_count"):
        sort = "return_pct"
    start, end, label = _month_window(period)
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT u.username, u.display_name, s.return_pct, s.win_rate, s.profit_factor,
                       s.sharpe, s.trades_count, s.symbol, s.ended_at, s.id
                  FROM practice_sessions s
                  JOIN users u ON u.id = s.user_id
                 WHERE s.public = 1
                   AND u.public_profile = 1
                   AND s.ended_at IS NOT NULL
                   AND s.trades_count >= 1
                   AND s.ended_at >= ? AND s.ended_at < ?
              ORDER BY s.{sort} DESC NULLS LAST
                 LIMIT ?""",
            (start, end, limit),
        ).fetchall()
    return {
        "period": label,
        "sort": sort,
        "total": len(rows),
        "rows": [dict(r) for r in rows],
    }


# ─────────── opt-in toggles ───────────

def set_public_profile(user_id: int, enabled: bool) -> None:
    """Master switch — when off, none of the user's sessions appear publicly."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET public_profile = ? WHERE id = ?",
            (1 if enabled else 0, user_id),
        )


def get_public_profile(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT public_profile FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["public_profile"])


def set_session_public(session_id: int, user_id: int, public: bool) -> bool:
    """Per-session opt-in — owner only. Returns True if updated."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM practice_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row or row["user_id"] != user_id:
            return False
        conn.execute(
            "UPDATE practice_sessions SET public = ? WHERE id = ?",
            (1 if public else 0, session_id),
        )
    return True
