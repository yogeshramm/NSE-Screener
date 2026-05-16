"""
SQLite foundation for YOINTELL — single yointell.db file.

Tables: users, presets, preset_shares, forum_categories, forum_topics,
forum_posts, practice_sessions.

Auto-creates schema on import and runs idempotent migrations from the
legacy file-based stores (config/users.json and config/presets/*.json).

Sized for 200 concurrent users — WAL mode enabled for concurrent reads,
writes serialise but contention is negligible at this scale.

All callers use `with get_conn() as conn:` so connections close cleanly
even on exception. Public helpers (`get_user`, `save_preset` etc.) live
in the consuming modules — this file only owns the connection +
schema + one-time migration.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

# Single-file DB next to existing config/ — gitignored, runtime-only data
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "config" / "yointell.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Schema version is bumped manually when we add/alter tables. The
# `schema_version` row tracks what's been applied.
SCHEMA_VERSION = 3

_init_lock = threading.Lock()
_initialised = False


# ─────────────────────────── connection helpers ───────────────────────────

def _connect() -> sqlite3.Connection:
    """Thin connection factory — short-lived per call.

    Each call opens a fresh connection. SQLite is fast enough that
    re-connecting per request beats the complexity of a true connection
    pool, especially at 200-user scale.
    """
    conn = sqlite3.connect(
        str(DB_PATH),
        detect_types=sqlite3.PARSE_DECLTYPES,
        isolation_level=None,        # autocommit; we control txns explicitly
        check_same_thread=False,     # FastAPI uses threads, this is safe given short-lived conns
        timeout=10.0,                # wait up to 10s if another writer holds the lock
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """Yield a connection; commit + close on normal exit, rollback on error."""
    _ensure_initialised()
    conn = _connect()
    try:
        yield conn
    except Exception:
        try: conn.execute("ROLLBACK")
        except Exception: pass
        raise
    finally:
        conn.close()


def _ensure_initialised() -> None:
    """Run schema + migrations once per process. Idempotent."""
    global _initialised
    if _initialised:
        return
    with _init_lock:
        if _initialised:
            return
        _create_schema()
        _alter_users_v3()        # add status/display_name/password_changed if missing
        _migrate_legacy_users()  # upsert all users.json rows into SQLite
        _migrate_legacy_presets()
        _seed_forum_categories()
        _initialised = True


# ─────────────────────────── schema ───────────────────────────

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    username         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash    TEXT NOT NULL,
    role             TEXT NOT NULL DEFAULT 'user',        -- 'user' | 'admin'
    status           TEXT NOT NULL DEFAULT 'approved',   -- 'pending' | 'approved'
    display_name     TEXT NOT NULL DEFAULT '',
    created_at       INTEGER NOT NULL,                    -- unix epoch
    password_changed INTEGER,                             -- unix epoch, nullable
    public_profile   INTEGER NOT NULL DEFAULT 0,          -- 0/1 — opt-in for leaderboard
    extras_json      TEXT NOT NULL DEFAULT '{}'           -- forward-compat bag (nickname, prefs, etc.)
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

CREATE TABLE IF NOT EXISTS presets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    config_json  TEXT NOT NULL,                           -- the full filter config
    stages_json  TEXT NOT NULL DEFAULT '{"s1":true,"s2":true,"s3":false}',  -- which stages to run
    visibility   TEXT NOT NULL DEFAULT 'private',         -- 'private' | 'public' | 'shared'
    use_count    INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_presets_owner    ON presets(owner_id);
CREATE INDEX IF NOT EXISTS idx_presets_vis      ON presets(visibility);
CREATE INDEX IF NOT EXISTS idx_presets_name     ON presets(name);

CREATE TABLE IF NOT EXISTS preset_shares (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    preset_id    INTEGER NOT NULL REFERENCES presets(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    shared_at    INTEGER NOT NULL,
    UNIQUE(preset_id, recipient_id)
);
CREATE INDEX IF NOT EXISTS idx_pshares_recipient ON preset_shares(recipient_id);

CREATE TABLE IF NOT EXISTS forum_categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    sort_order      INTEGER NOT NULL DEFAULT 0,
    admin_only_post INTEGER NOT NULL DEFAULT 0,
    archived        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS forum_topics (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id    INTEGER NOT NULL REFERENCES forum_categories(id) ON DELETE CASCADE,
    author_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title          TEXT NOT NULL,
    body           TEXT NOT NULL,
    pinned         INTEGER NOT NULL DEFAULT 0,
    archived       INTEGER NOT NULL DEFAULT 0,
    reply_count    INTEGER NOT NULL DEFAULT 0,
    created_at     INTEGER NOT NULL,
    last_activity  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topics_cat       ON forum_topics(category_id, archived, pinned DESC, last_activity DESC);
CREATE INDEX IF NOT EXISTS idx_topics_author    ON forum_topics(author_id);

CREATE TABLE IF NOT EXISTS forum_posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id    INTEGER NOT NULL REFERENCES forum_topics(id) ON DELETE CASCADE,
    author_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    body        TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    edited_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_posts_topic ON forum_posts(topic_id, created_at);

CREATE TABLE IF NOT EXISTS practice_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER REFERENCES users(id) ON DELETE CASCADE,
    symbol        TEXT NOT NULL,
    max_days      INTEGER NOT NULL,
    mode          TEXT NOT NULL DEFAULT 'free',
    trades_json   TEXT NOT NULL DEFAULT '[]',
    summary_json  TEXT NOT NULL DEFAULT '{}',
    return_pct    REAL,                                 -- nullable until ended
    win_rate      REAL,
    trades_count  INTEGER,
    sharpe        REAL,
    profit_factor REAL,
    started_at    INTEGER NOT NULL,
    ended_at      INTEGER,
    public        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sess_user   ON practice_sessions(user_id, ended_at DESC);
CREATE INDEX IF NOT EXISTS idx_sess_public ON practice_sessions(public, ended_at DESC) WHERE public = 1;

CREATE TABLE IF NOT EXISTS tournaments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    name            TEXT NOT NULL,
    n_stocks        INTEGER NOT NULL DEFAULT 5,        -- 3 | 5 | 10
    days_per_stock  INTEGER NOT NULL DEFAULT 60,       -- simulation length
    window_minutes  INTEGER NOT NULL DEFAULT 45,       -- real-time window to complete
    min_players     INTEGER NOT NULL DEFAULT 2,
    universe        TEXT NOT NULL DEFAULT 'nifty500',
    -- lifecycle:
    --   'pending'   created, waiting for min_players
    --   'live'      started, accepting entries until ends_at
    --   'closed'    window elapsed, reveals + leaderboard visible
    status          TEXT NOT NULL DEFAULT 'pending',
    stocks_json     TEXT NOT NULL DEFAULT '[]',        -- ['RELIANCE','TCS',...] — hidden from clients until closed
    starts_at       INTEGER,                            -- ts the tournament went live (NULL until live)
    ends_at         INTEGER,                            -- ts when window closes (NULL until live)
    created_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tournaments_status ON tournaments(status, ends_at);

CREATE TABLE IF NOT EXISTS tournament_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id   INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    joined_at       INTEGER NOT NULL,
    submitted_at    INTEGER,                            -- when player finished all stocks
    return_pct      REAL,
    win_rate        REAL,
    trades_count    INTEGER,
    sharpe          REAL,
    profit_factor   REAL,
    per_stock_json  TEXT NOT NULL DEFAULT '[]',         -- [{slot:1, symbol:'RELIANCE', return_pct:...}, ...]
    UNIQUE(tournament_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_t_entries_tid ON tournament_entries(tournament_id, return_pct DESC);
"""


def _create_schema() -> None:
    conn = _connect()
    try:
        # executescript runs all statements; PRAGMA statements are honoured per-connection
        # so we issue WAL/synchronous PRAGMAs separately on each connect via get_conn,
        # but creating tables in one shot is fine here.
        conn.executescript(_SCHEMA)
        # Record schema version
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    finally:
        conn.close()


# ─────────────────────────── migrations from legacy stores ───────────────────────────

_LEGACY_USERS_FILE = ROOT / "config" / "users.json"
_LEGACY_PRESETS_DIR = ROOT / "config" / "presets"


def _alter_users_v3() -> None:
    """Idempotently add columns introduced in schema v3 to existing databases."""
    conn = _connect()
    try:
        for col, definition in [
            ("status",           "TEXT NOT NULL DEFAULT 'approved'"),
            ("display_name",     "TEXT NOT NULL DEFAULT ''"),
            ("password_changed", "INTEGER"),
        ]:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass  # column already exists — no-op
    finally:
        conn.close()


def _migrate_legacy_users() -> None:
    """Upsert all config/users.json rows into the SQLite users table.

    Runs every startup — idempotent via INSERT OR REPLACE. SQLite is now
    the single source of truth; users.json is kept as a read-only backup
    but is never written to by the new auth layer.
    """
    if not _LEGACY_USERS_FILE.exists():
        return
    try:
        data = json.loads(_LEGACY_USERS_FILE.read_text())
    except Exception:
        return
    if not isinstance(data, dict) or not data:
        return

    now = int(time.time())
    conn = _connect()
    try:
        for username, rec in data.items():
            if not isinstance(rec, dict):
                continue
            pw = rec.get("password_hash") or rec.get("password") or ""
            if not pw:
                continue
            role = rec.get("role", "user")
            status = rec.get("status", "approved")
            display_name = (rec.get("display_name") or username).strip()
            # Parse ISO created date from users.json
            created_at = now
            created_str = rec.get("created") or rec.get("created_at")
            if created_str:
                try:
                    from datetime import datetime as _dt
                    created_at = int(_dt.fromisoformat(str(created_str)).timestamp())
                except Exception:
                    try:
                        created_at = int(created_str)
                    except Exception:
                        pass
            conn.execute(
                """INSERT INTO users(username, password_hash, role, status, display_name, created_at)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(username) DO UPDATE SET
                     password_hash = excluded.password_hash,
                     role          = excluded.role,
                     status        = excluded.status,
                     display_name  = CASE WHEN display_name = '' THEN excluded.display_name ELSE display_name END""",
                (username, pw, role, status, display_name, created_at),
            )
    finally:
        conn.close()


def _migrate_legacy_presets() -> None:
    """Sync config/presets/*.json into the presets table.

    New JSON presets are auto-claimed for the primary user (resolved from
    YOINTELL_PRIMARY_USERNAME env var, falling back to 'yogesh') so they show
    up as MINE with edit/share/delete in the UI rather than as immutable
    SYSTEM rows. If the primary user can't be resolved, falls back to
    ownerless (the original behaviour).

    Idempotent: skips any name that already exists in the presets table
    (any owner), so user edits via the API survive a restart and we never
    double-import.
    """
    if not _LEGACY_PRESETS_DIR.exists():
        return
    now = int(time.time())
    conn = _connect()
    try:
        # Resolve primary user once
        primary = os.environ.get("YOINTELL_PRIMARY_USERNAME", "yogesh").strip().lower()
        owner_id: Optional[int] = None
        if primary:
            row = conn.execute(
                "SELECT id FROM users WHERE LOWER(username) = ?", (primary,)
            ).fetchone()
            if row:
                owner_id = row["id"]

        # Dedup against ALL preset rows (any owner) — a user-claimed preset
        # must not be re-imported as a SYSTEM duplicate on restart.
        rows = conn.execute(
            "SELECT name, description, config_json FROM presets"
        ).fetchall()
        existing = {r["name"]: r for r in rows}
        for f in sorted(_LEGACY_PRESETS_DIR.glob("*.json")):
            name = f.stem
            try:
                cfg = json.loads(f.read_text())
            except Exception:
                continue
            cfg_str = json.dumps(cfg)
            if name not in existing:
                conn.execute(
                    """INSERT INTO presets
                       (owner_id, name, description, config_json, stages_json, visibility, created_at, updated_at)
                       VALUES(?, ?, ?, ?, ?, 'private', ?, ?)""",
                    (
                        owner_id,
                        name,
                        "Imported from legacy config",
                        cfg_str,
                        json.dumps({"s1": True, "s2": True, "s3": False}),
                        now,
                        now,
                    ),
                )
            elif existing[name]["description"] == "Imported from legacy config":
                # Re-sync config from JSON for presets that haven't been
                # user-edited (description unchanged). This lets JSON edits
                # propagate on restart without wiping user-created presets.
                if existing[name]["config_json"] != cfg_str:
                    conn.execute(
                        "UPDATE presets SET config_json=?, updated_at=? WHERE name=?",
                        (cfg_str, now, name),
                    )
    finally:
        conn.close()


_DEFAULT_CATEGORIES = [
    ("general",      "General",          "Anything goes — markets, life, off-topic.",        0, 0),
    ("findings",     "Stock Findings",   "Setups, breakouts, anomalies others should see.",  10, 0),
    ("game-results", "Game Results",     "Practice rounds, replays, lessons learned.",       20, 0),
    ("ipo-watch",    "IPO Watch",        "GMP, subscription, listing-day talk.",             30, 0),
    ("questions",    "Questions",        "Ask anything — beginners welcome.",                40, 0),
    ("announcements","Announcements",    "Updates from the admins.",                         99, 1),
]


def _seed_forum_categories() -> None:
    conn = _connect()
    try:
        existing = conn.execute("SELECT COUNT(*) FROM forum_categories").fetchone()[0]
        if existing:
            return
        for slug, name, desc, order, admin_only in _DEFAULT_CATEGORIES:
            conn.execute(
                "INSERT OR IGNORE INTO forum_categories(slug, name, description, sort_order, admin_only_post) VALUES(?,?,?,?,?)",
                (slug, name, desc, order, admin_only),
            )
    finally:
        conn.close()


# ─────────────────────────── public utility ───────────────────────────

def now_ts() -> int:
    """Current unix epoch — single source of truth for timestamps."""
    return int(time.time())


def healthcheck() -> dict:
    """Quick state probe — used by tests and /data/status."""
    try:
        with get_conn() as conn:
            users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            presets = conn.execute("SELECT COUNT(*) FROM presets").fetchone()[0]
            topics = conn.execute("SELECT COUNT(*) FROM forum_topics").fetchone()[0]
            posts = conn.execute("SELECT COUNT(*) FROM forum_posts").fetchone()[0]
            sessions = conn.execute("SELECT COUNT(*) FROM practice_sessions").fetchone()[0]
        return {
            "ok": True, "path": str(DB_PATH),
            "users": users, "presets": presets,
            "forum_topics": topics, "forum_posts": posts,
            "practice_sessions": sessions,
            "schema_version": SCHEMA_VERSION,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
