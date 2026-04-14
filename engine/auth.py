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
    """Register a new user. Returns user dict (no password)."""
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
    }
    _save_users(users)
    return {"username": username, "display_name": users[username]["display_name"]}


def login(username: str, password: str) -> dict:
    """Authenticate and return JWT token. Raises ValueError on failure."""
    username = username.strip().lower()
    users = _load_users()

    if username not in users:
        raise ValueError("Invalid username or password")

    user = users[username]
    if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        raise ValueError("Invalid username or password")

    # Generate JWT
    payload = {
        "sub": username,
        "name": user["display_name"],
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS),
    }
    token = jwt.encode(payload, _get_secret(), algorithm="HS256")

    return {
        "token": token,
        "username": username,
        "display_name": user["display_name"],
        "expires_in": TOKEN_EXPIRY_HOURS * 3600,
    }


def verify_token(token: str) -> dict:
    """Verify JWT token. Returns user payload or raises."""
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=["HS256"])
        return {
            "username": payload["sub"],
            "display_name": payload.get("name", payload["sub"]),
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
        return {"username": u["username"], "display_name": u["display_name"],
                "created": u.get("created")}
    return None
