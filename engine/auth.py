"""
Authentication Engine
Simple JWT-based auth with file-based user storage.
Storage: config/users.json
"""

import json
import bcrypt
import jwt
import secrets
from pathlib import Path
from datetime import datetime, timedelta

USERS_FILE = Path(__file__).parent.parent / "config" / "users.json"
SECRET_KEY = None  # Generated once and persisted
SECRET_FILE = Path(__file__).parent.parent / "config" / ".auth_secret"
TOKEN_EXPIRY_HOURS = 72


def _get_secret() -> str:
    """Get or create persistent JWT secret key."""
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


def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)


def _save_users(users: dict):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2, default=str)


def register(username: str, password: str, display_name: str = "") -> dict:
    """Register a new user. Status is 'pending' until an admin approves."""
    username = username.strip().lower()
    if not username or not password:
        raise ValueError("Username and password required")
    if len(password) < 4:
        raise ValueError("Password must be at least 4 characters")

    users = _load_users()
    if username in users:
        raise ValueError(f"Username '{username}' already exists")

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users[username] = {
        "username": username,
        "display_name": display_name or username,
        "password_hash": hashed,
        "created": datetime.now().isoformat(),
        "role": "user",
        "status": "pending",
    }
    _save_users(users)
    return {"username": username, "display_name": users[username]["display_name"], "status": "pending"}


def login(username: str, password: str) -> dict:
    """Authenticate and return JWT token. Raises ValueError on failure."""
    username = username.strip().lower()
    users = _load_users()

    if username not in users:
        raise ValueError("Invalid username or password")

    user = users[username]
    if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        raise ValueError("Invalid username or password")

    # Pending users cannot log in (admins always bypass this check)
    role = user.get("role", "user")
    status = user.get("status", "approved")  # legacy users without status default approved
    if role != "admin" and status != "approved":
        raise ValueError("Your account is pending admin approval. Please wait.")

    # Generate JWT — embed role so admin endpoints don't need a DB hit per request
    payload = {
        "sub": username,
        "name": user["display_name"],
        "role": role,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS),
    }
    token = jwt.encode(payload, _get_secret(), algorithm="HS256")

    return {
        "token": token,
        "username": username,
        "display_name": user["display_name"],
        "role": role,
        "expires_in": TOKEN_EXPIRY_HOURS * 3600,
    }


def verify_token(token: str) -> dict:
    """Verify JWT token. Returns user payload or raises."""
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=["HS256"])
        return {
            "username": payload["sub"],
            "display_name": payload.get("name", payload["sub"]),
            "role": payload.get("role", "user"),
        }
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired — please login again")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")


def get_user(username: str) -> dict | None:
    """Get user info (no password)."""
    users = _load_users()
    if username in users:
        u = users[username]
        return {
            "username": u["username"],
            "display_name": u["display_name"],
            "created": u.get("created"),
            "password_changed": u.get("password_changed"),
            "role": u.get("role", "user"),
            "status": u.get("status", "approved"),  # legacy users default approved
        }
    return None


def ensure_admin(username: str):
    """Idempotently promote a user to admin with approved status.
    Called from app lifespan. No-op if the user doesn't exist yet."""
    users = _load_users()
    if username not in users:
        return
    changed = False
    if users[username].get("role") != "admin":
        users[username]["role"] = "admin"
        changed = True
    if users[username].get("status") != "approved":
        users[username]["status"] = "approved"
        changed = True
    if changed:
        _save_users(users)


def list_users() -> list:
    """Return all users (no password hashes), sorted pending-first then by created."""
    users = _load_users()
    result = []
    for u in users.values():
        result.append({
            "username": u["username"],
            "display_name": u.get("display_name", u["username"]),
            "role": u.get("role", "user"),
            "status": u.get("status", "approved"),
            "created": u.get("created"),
        })
    # Pending first, then sorted by created date
    result.sort(key=lambda x: (x["status"] != "pending", x["created"] or ""))
    return result


def approve_user(username: str) -> dict:
    """Set a pending user's status to 'approved'."""
    users = _load_users()
    if username not in users:
        raise ValueError(f"User '{username}' not found")
    users[username]["status"] = "approved"
    _save_users(users)
    return {"username": username, "status": "approved"}


def delete_user(username: str, requesting_admin: str) -> bool:
    """Delete a non-admin user. Cannot delete self or another admin."""
    if username == requesting_admin:
        raise ValueError("Cannot delete your own account")
    users = _load_users()
    if username not in users:
        raise ValueError(f"User '{username}' not found")
    if users[username].get("role") == "admin":
        raise ValueError("Cannot delete another admin account")
    del users[username]
    _save_users(users)
    return True


def change_password(username: str, current_password: str, new_password: str) -> bool:
    """Change a user's password. Verifies current password first.
    Raises ValueError on any failure (wrong current, too short, same as current)."""
    username = username.strip().lower()
    users = _load_users()
    if username not in users:
        raise ValueError("User not found")
    user = users[username]
    if not bcrypt.checkpw(current_password.encode(), user["password_hash"].encode()):
        raise ValueError("Current password is incorrect")
    if not new_password or len(new_password) < 4:
        raise ValueError("New password must be at least 4 characters")
    if current_password == new_password:
        raise ValueError("New password must be different from current")
    user["password_hash"] = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    user["password_changed"] = datetime.now().isoformat()
    _save_users(users)
    return True


def update_display_name(username: str, display_name: str) -> dict:
    """Update a user's display name. Returns updated user dict (no password)."""
    username = username.strip().lower()
    display_name = (display_name or "").strip()
    if not display_name:
        raise ValueError("Display name cannot be empty")
    if len(display_name) > 60:
        raise ValueError("Display name too long (max 60 characters)")
    users = _load_users()
    if username not in users:
        raise ValueError("User not found")
    users[username]["display_name"] = display_name
    _save_users(users)
    return {"username": username, "display_name": display_name}
