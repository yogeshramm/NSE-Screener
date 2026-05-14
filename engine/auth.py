"""
Authentication Engine
JWT-based auth. Single source of truth: SQLite users table (config/yointell.db).

config/users.json is kept as a read-only bootstrap — _migrate_legacy_users()
in engine/db.py upserts it into SQLite on every startup, then this module
ignores it entirely.
"""

import bcrypt
import jwt
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from engine.db import get_conn, now_ts

SECRET_KEY = None  # cached in memory after first read
SECRET_FILE = Path(__file__).parent.parent / "config" / ".auth_secret"
TOKEN_EXPIRY_HOURS = 72


# ─── JWT secret ──────────────────────────────────────────────────────────────

def _get_secret() -> str:
    """Get or create a persistent JWT signing key."""
    global SECRET_KEY
    if SECRET_KEY:
        return SECRET_KEY
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SECRET_FILE.exists():
        SECRET_KEY = SECRET_FILE.read_text().strip()
    else:
        SECRET_KEY = secrets.token_hex(32)
        SECRET_FILE.write_text(SECRET_KEY)
    return SECRET_KEY


# ─── helpers ─────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    """Convert a SQLite Row to a public user dict (no password hash)."""
    keys = row.keys()
    return {
        "username":         row["username"],
        "display_name":     row["display_name"] if "display_name" in keys else row["username"],
        "role":             row["role"],
        "status":           row["status"] if "status" in keys else "approved",
        "created":          row["created_at"],
        "password_changed": row["password_changed"] if "password_changed" in keys else None,
    }


# ─── public API ──────────────────────────────────────────────────────────────

def register(username: str, password: str, display_name: str = "") -> dict:
    """Register a new user. Status is 'pending' until an admin approves."""
    username = username.strip().lower()
    if not username or not password:
        raise ValueError("Username and password required")
    if len(password) < 4:
        raise ValueError("Password must be at least 4 characters")

    display_name = (display_name or username).strip()
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if existing:
            raise ValueError(f"Username '{username}' already exists")
        conn.execute(
            """INSERT INTO users(username, password_hash, role, status, display_name, created_at)
               VALUES(?,?,?,?,?,?)""",
            (username, hashed, "user", "pending", display_name, now_ts()),
        )
    return {"username": username, "display_name": display_name, "status": "pending"}


def login(username: str, password: str) -> dict:
    """Authenticate and return a JWT token. Raises ValueError on failure."""
    username = username.strip().lower()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()

    if not row:
        raise ValueError("Invalid username or password")

    # Guard against shadow rows inserted by _ensure_user_in_db (presets_db fallback)
    if row["password_hash"] == "json-auth-shadow":
        raise ValueError("Invalid username or password")

    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        raise ValueError("Invalid username or password")

    role = row["role"]
    keys = row.keys()
    status = row["status"] if "status" in keys else "approved"
    if role != "admin" and status != "approved":
        raise ValueError("Your account is pending admin approval. Please wait.")

    display_name = row["display_name"] if ("display_name" in keys and row["display_name"]) else username
    payload = {
        "sub":  username,
        "name": display_name,
        "role": role,
        "iat":  datetime.utcnow(),
        "exp":  datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS),
    }
    token = jwt.encode(payload, _get_secret(), algorithm="HS256")
    return {
        "token":      token,
        "username":   username,
        "display_name": display_name,
        "role":       role,
        "expires_in": TOKEN_EXPIRY_HOURS * 3600,
    }


def verify_token(token: str) -> dict:
    """Verify JWT. Returns user payload or raises ValueError."""
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=["HS256"])
        return {
            "username":     payload["sub"],
            "display_name": payload.get("name", payload["sub"]),
            "role":         payload.get("role", "user"),
        }
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired — please login again")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")


def get_user(username: str) -> dict | None:
    """Get public user info (no password hash). Returns None if not found."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def ensure_admin(username: str):
    """Idempotently promote a user to admin+approved. No-op if user doesn't exist."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, role, status FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if not row:
            return
        if row["role"] != "admin" or row["status"] != "approved":
            conn.execute(
                "UPDATE users SET role = 'admin', status = 'approved' WHERE username = ? COLLATE NOCASE",
                (username,),
            )


def list_users() -> list:
    """Return all users sorted pending-first, then by created_at."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM users
               ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, created_at"""
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def approve_user(username: str) -> dict:
    """Set a pending user's status to 'approved'."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if not row:
            raise ValueError(f"User '{username}' not found")
        conn.execute(
            "UPDATE users SET status = 'approved' WHERE username = ? COLLATE NOCASE", (username,)
        )
    return {"username": username, "status": "approved"}


def delete_user(username: str, requesting_admin: str) -> bool:
    """Delete a non-admin user. Cannot delete self or another admin."""
    if username.lower() == requesting_admin.lower():
        raise ValueError("Cannot delete your own account")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT role FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if not row:
            raise ValueError(f"User '{username}' not found")
        if row["role"] == "admin":
            raise ValueError("Cannot delete another admin account")
        conn.execute(
            "DELETE FROM users WHERE username = ? COLLATE NOCASE", (username,)
        )
    return True


def change_password(username: str, current_password: str, new_password: str) -> bool:
    """Change a user's password. Verifies current password first."""
    username = username.strip().lower()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if not row:
            raise ValueError("User not found")
        if not bcrypt.checkpw(current_password.encode(), row["password_hash"].encode()):
            raise ValueError("Current password is incorrect")
        if not new_password or len(new_password) < 4:
            raise ValueError("New password must be at least 4 characters")
        if current_password == new_password:
            raise ValueError("New password must be different from current")
        new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "UPDATE users SET password_hash = ?, password_changed = ? WHERE username = ? COLLATE NOCASE",
            (new_hash, now_ts(), username),
        )
    return True


def update_display_name(username: str, display_name: str) -> dict:
    """Update a user's display name."""
    username = username.strip().lower()
    display_name = (display_name or "").strip()
    if not display_name:
        raise ValueError("Display name cannot be empty")
    if len(display_name) > 60:
        raise ValueError("Display name too long (max 60 characters)")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if not row:
            raise ValueError("User not found")
        conn.execute(
            "UPDATE users SET display_name = ? WHERE username = ? COLLATE NOCASE",
            (display_name, username),
        )
    return {"username": username, "display_name": display_name}
