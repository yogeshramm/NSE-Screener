"""
Real Sim persistence — SQLite tables for simulation runs, books, trades,
decisions and daily equity.

FULLY ISOLATED from the live app: its own database file at
data_store/real_sim.db, its own connection factory, zero imports from
engine/db.py. Nothing the sim writes can touch users, presets, forum,
practice sessions or the warm cache. Import is side-effect free; call
ensure_schema() before use.

Naming scheme (stable — the UI will read these ids later):
    run    RS-20260831-REPLAY-01
    book   RS-20260831-REPLAY-01/NEOR/BRAIN
    trade  RS-20260831-REPLAY-01/NEOR/BRAIN/TATACOMM/20260312-1
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

# Own file, deliberately NOT config/yointell.db — the sim must never be able
# to write into the live application database.
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("REAL_SIM_DB", ROOT / "data_store" / "real_sim.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """Short-lived connection to the sim's own database."""
    conn = sqlite3.connect(str(DB_PATH), isolation_level=None,
                           check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()

_SIM_SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS sim_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT UNIQUE NOT NULL,
    mode         TEXT NOT NULL,
    universe     TEXT NOT NULL,
    start_date   TEXT NOT NULL,
    end_date     TEXT NOT NULL,
    formulas     TEXT NOT NULL,
    purse        REAL NOT NULL,
    config_json  TEXT,
    leak_audit   TEXT,
    status       TEXT NOT NULL DEFAULT 'running',
    created_ts   INTEGER,
    finished_ts  INTEGER,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS sim_books (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    book_id       TEXT UNIQUE NOT NULL,
    formula       TEXT NOT NULL,
    formula_code  TEXT NOT NULL,
    arm           TEXT NOT NULL,
    start_cash    REAL,
    end_cash      REAL,
    end_equity    REAL,
    total_trades  INTEGER DEFAULT 0,
    wins          INTEGER DEFAULT 0,
    losses        INTEGER DEFAULT 0,
    pnl           REAL DEFAULT 0,
    pnl_pct       REAL DEFAULT 0,
    max_dd_pct    REAL DEFAULT 0,
    sharpe        REAL,
    profit_factor REAL,
    win_rate      REAL,
    vetoed_count  INTEGER DEFAULT 0,
    metrics_json  TEXT
);

CREATE TABLE IF NOT EXISTS sim_trades (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL,
    book_id        TEXT NOT NULL,
    trade_id       TEXT UNIQUE NOT NULL,
    symbol         TEXT NOT NULL,
    side           TEXT NOT NULL DEFAULT 'long',
    entry_date     TEXT,
    entry_price    REAL,
    qty            INTEGER,
    stop_loss      REAL,
    target         REAL,
    rr             REAL,
    exit_date      TEXT,
    exit_price     REAL,
    exit_reason    TEXT,
    gross_pnl      REAL,
    charges        REAL,
    net_pnl        REAL,
    pnl_pct        REAL,
    r_multiple     REAL,
    bars_held      INTEGER,
    formula_score  REAL,
    template_score REAL,
    template_max   REAL,
    conviction     TEXT,
    entry_reasons  TEXT,
    exit_reasons   TEXT
);

CREATE TABLE IF NOT EXISTS sim_decisions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL,
    book_id        TEXT NOT NULL,
    decision_date  TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    action         TEXT NOT NULL,
    template_score REAL,
    template_max   REAL,
    pct            REAL,
    conviction     TEXT,
    verdict        TEXT,
    checks_json    TEXT,
    dossier_json   TEXT,
    reasons        TEXT
);

CREATE TABLE IF NOT EXISTS sim_equity (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    book_id         TEXT NOT NULL,
    date            TEXT NOT NULL,
    cash            REAL,
    positions_value REAL,
    equity          REAL,
    open_positions  INTEGER
);

CREATE INDEX IF NOT EXISTS ix_sim_trades_book   ON sim_trades(book_id);
CREATE INDEX IF NOT EXISTS ix_sim_trades_sym    ON sim_trades(symbol);
CREATE INDEX IF NOT EXISTS ix_sim_trades_run    ON sim_trades(run_id);
CREATE INDEX IF NOT EXISTS ix_sim_dec_book      ON sim_decisions(book_id);
CREATE INDEX IF NOT EXISTS ix_sim_dec_sym       ON sim_decisions(symbol);
CREATE INDEX IF NOT EXISTS ix_sim_dec_date      ON sim_decisions(decision_date);
CREATE INDEX IF NOT EXISTS ix_sim_equity_book   ON sim_equity(book_id, date);
CREATE INDEX IF NOT EXISTS ix_sim_books_run     ON sim_books(run_id);
"""

_ensured = False


def ensure_schema() -> None:
    global _ensured
    if _ensured:
        return
    with get_conn() as conn:
        conn.executescript(_SIM_SCHEMA)
    _ensured = True


# ────────────────────────────── run / book ──────────────────────────────

def next_run_id(mode: str, day: str) -> str:
    """RS-{YYYYMMDD}-{MODE}-{NN} — NN increments per day+mode."""
    ensure_schema()
    prefix = f"RS-{day}-{mode.upper()}-"
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT run_id FROM sim_runs WHERE run_id LIKE ?", (prefix + "%",)
        ).fetchall()
    seq = 1
    for r in rows:
        try:
            seq = max(seq, int(r["run_id"].rsplit("-", 1)[1]) + 1)
        except Exception:
            pass
    return f"{prefix}{seq:02d}"


def create_run(run_id: str, mode: str, universe: str, start_date: str,
               end_date: str, formulas: List[str], purse: float,
               config: Dict[str, Any], leak_audit: Dict[str, Any]) -> None:
    ensure_schema()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sim_runs
               (run_id, mode, universe, start_date, end_date, formulas, purse,
                config_json, leak_audit, status, created_ts)
               VALUES (?,?,?,?,?,?,?,?,?,'running',?)""",
            (run_id, mode, universe, start_date, end_date, json.dumps(formulas),
             purse, json.dumps(config), json.dumps(leak_audit), int(time.time())),
        )


def finish_run(run_id: str, status: str = "done", notes: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sim_runs SET status=?, finished_ts=?, notes=? WHERE run_id=?",
            (status, int(time.time()), notes, run_id),
        )


def create_book(run_id: str, book_id: str, formula: str, formula_code: str,
                arm: str, start_cash: float) -> None:
    ensure_schema()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO sim_books
               (run_id, book_id, formula, formula_code, arm, start_cash)
               VALUES (?,?,?,?,?,?)""",
            (run_id, book_id, formula, formula_code, arm, start_cash),
        )


def update_book_metrics(book_id: str, m: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE sim_books SET
                 end_cash=?, end_equity=?, total_trades=?, wins=?, losses=?,
                 pnl=?, pnl_pct=?, max_dd_pct=?, sharpe=?, profit_factor=?,
                 win_rate=?, vetoed_count=?, metrics_json=?
               WHERE book_id=?""",
            (m.get("end_cash"), m.get("end_equity"), m.get("total_trades"),
             m.get("wins"), m.get("losses"), m.get("pnl"), m.get("pnl_pct"),
             m.get("max_dd_pct"), m.get("sharpe"), m.get("profit_factor"),
             m.get("win_rate"), m.get("vetoed_count"), json.dumps(m), book_id),
        )


# ────────────────────────────── writes ──────────────────────────────

def insert_trade(t: Dict[str, Any]) -> None:
    cols = ("run_id book_id trade_id symbol side entry_date entry_price qty "
            "stop_loss target rr exit_date exit_price exit_reason gross_pnl "
            "charges net_pnl pnl_pct r_multiple bars_held formula_score "
            "template_score template_max conviction entry_reasons exit_reasons").split()
    with get_conn() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO sim_trades ({','.join(cols)}) "
            f"VALUES ({','.join('?' * len(cols))})",
            tuple(t.get(c) for c in cols),
        )


def insert_decision(d: Dict[str, Any]) -> None:
    cols = ("run_id book_id decision_date symbol action template_score "
            "template_max pct conviction verdict checks_json dossier_json "
            "reasons").split()
    with get_conn() as conn:
        conn.execute(
            f"INSERT INTO sim_decisions ({','.join(cols)}) "
            f"VALUES ({','.join('?' * len(cols))})",
            tuple(d.get(c) for c in cols),
        )


def insert_equity_rows(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO sim_equity
               (run_id, book_id, date, cash, positions_value, equity, open_positions)
               VALUES (?,?,?,?,?,?,?)""",
            [(r["run_id"], r["book_id"], r["date"], r["cash"],
              r["positions_value"], r["equity"], r["open_positions"]) for r in rows],
        )


# ────────────────────────────── reads ──────────────────────────────

def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM sim_runs WHERE run_id=?", (run_id,)).fetchone()
    return dict(r) if r else None


def latest_run(mode: Optional[str] = None) -> Optional[Dict[str, Any]]:
    ensure_schema()
    q = "SELECT * FROM sim_runs"
    args: tuple = ()
    if mode:
        q += " WHERE mode=?"
        args = (mode,)
    q += " ORDER BY id DESC LIMIT 1"
    with get_conn() as conn:
        r = conn.execute(q, args).fetchone()
    return dict(r) if r else None


def books_for(run_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM sim_books WHERE run_id=? ORDER BY formula_code, arm", (run_id,))]


def trades_for(book_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM sim_trades WHERE book_id=? ORDER BY entry_date", (book_id,))]


def trades_for_run(run_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM sim_trades WHERE run_id=? ORDER BY book_id, entry_date", (run_id,))]


def equity_for(book_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT date, equity, cash, positions_value, open_positions "
            "FROM sim_equity WHERE book_id=? ORDER BY date", (book_id,))]


def decisions_for(book_id: str, action: Optional[str] = None,
                  limit: int = 500) -> List[Dict[str, Any]]:
    q = "SELECT * FROM sim_decisions WHERE book_id=?"
    args: list = [book_id]
    if action:
        q += " AND action=?"
        args.append(action)
    q += " ORDER BY decision_date DESC LIMIT ?"
    args.append(limit)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(q, tuple(args))]


def purge_run(run_id: str) -> None:
    """Delete a run and everything under it — for re-running a failed sim."""
    ensure_schema()
    with get_conn() as conn:
        for tbl in ("sim_equity", "sim_decisions", "sim_trades", "sim_books", "sim_runs"):
            conn.execute(f"DELETE FROM {tbl} WHERE run_id=?", (run_id,))
