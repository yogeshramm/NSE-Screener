"""
Angel One SmartAPI authentication.

Reads creds from environment (or .env file at project root). JWT tokens are
valid 24-28h per Angel's policy; we cache for 20h to stay safely inside that.
Cache lives at data_store/angel_session.pkl. Auto-refreshes on TTL miss.

Usage:
    from data.angel_auth import get_smart_connect
    sc = get_smart_connect()           # logged-in client, ready to use
    candle = sc.getCandleData(...)     # any SmartConnect method
"""
from __future__ import annotations
import os
import pickle
import time
from pathlib import Path
from typing import Optional

import pyotp
from SmartApi import SmartConnect

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SESSION_PATH = _PROJECT_ROOT / "data_store" / "angel_session.pkl"
_TTL_SECONDS = 20 * 3600  # 20 hours

_REQUIRED = ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_MPIN", "ANGEL_TOTP_SECRET")


def _load_env() -> dict:
    """Load creds from os.environ, falling back to .env file at repo root."""
    env = {k: os.environ.get(k) for k in _REQUIRED}
    if all(env.values()):
        return env
    env_file = _PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k in _REQUIRED and not env.get(k):
                env[k] = v.strip()
    missing = [k for k, v in env.items() if not v]
    if missing:
        raise RuntimeError(f"Missing Angel creds: {missing}. Set in env or .env at {env_file}")
    return env


def _load_cached() -> Optional[dict]:
    """Return cached session if fresh, else None."""
    if not _SESSION_PATH.exists():
        return None
    try:
        with open(_SESSION_PATH, "rb") as f:
            cached = pickle.load(f)
        if time.time() - cached["created_at"] > _TTL_SECONDS:
            return None
        return cached
    except Exception:
        return None


def _save_cache(session: dict, api_key: str) -> None:
    _SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": time.time(), "api_key": api_key, "session": session}
    with open(_SESSION_PATH, "wb") as f:
        pickle.dump(payload, f)
    os.chmod(_SESSION_PATH, 0o600)


def _login(env: dict) -> dict:
    """Fresh login. Returns the `data` block from generateSession."""
    sc = SmartConnect(api_key=env["ANGEL_API_KEY"])
    totp = pyotp.TOTP(env["ANGEL_TOTP_SECRET"]).now()
    resp = sc.generateSession(env["ANGEL_CLIENT_CODE"], env["ANGEL_MPIN"], totp)
    if not resp.get("status"):
        raise RuntimeError(f"Angel login failed: {resp.get('message') or resp}")
    return resp["data"]


def get_session(force_refresh: bool = False) -> dict:
    """Returns the session data dict (jwtToken, refreshToken, feedToken).
    Uses cached value if < 20h old unless force_refresh=True."""
    env = _load_env()
    if not force_refresh:
        cached = _load_cached()
        if cached and cached.get("api_key") == env["ANGEL_API_KEY"]:
            return cached["session"]
    session = _login(env)
    _save_cache(session, env["ANGEL_API_KEY"])
    return session


def get_smart_connect() -> SmartConnect:
    """Returns a logged-in SmartConnect instance ready for API calls.
    Always does a fresh generateSession() because the SDK doesn't safely
    rehydrate from cached tokens (double-prefixes 'Bearer '). The login is
    cheap (~700 ms) and rate-limited at 1/sec; cache the SDK at the caller
    if you make many calls in one process."""
    env = _load_env()
    sc = SmartConnect(api_key=env["ANGEL_API_KEY"])
    totp = pyotp.TOTP(env["ANGEL_TOTP_SECRET"]).now()
    resp = sc.generateSession(env["ANGEL_CLIENT_CODE"], env["ANGEL_MPIN"], totp)
    if not resp.get("status"):
        raise RuntimeError(f"Angel login failed: {resp.get('message') or resp}")
    # Persist the tokens for direct-HTTP callers that don't need the SDK
    _save_cache(resp["data"], env["ANGEL_API_KEY"])
    return sc


def get_authed_headers() -> dict:
    """Returns HTTP headers ready for direct REST calls (bypasses the SDK).
    Use this for endpoints where the SDK is buggy or where we want zero overhead."""
    env = _load_env()
    session = get_session()
    jwt = session["jwtToken"]
    if not jwt.startswith("Bearer "):
        jwt = f"Bearer {jwt}"
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-PrivateKey": env["ANGEL_API_KEY"],
        "Authorization": jwt,
        # Required by Angel; values don't have to be real for IP-whitelisted apps.
        "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00",
    }


if __name__ == "__main__":
    import requests
    s = get_session()
    print(f"✓ session ok, jwt: {s['jwtToken'][:30]}...")
    h = get_authed_headers()
    r = requests.post(
        "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/getLtpData",
        headers=h,
        json={"exchange": "NSE", "tradingsymbol": "RELIANCE-EQ", "symboltoken": "2885"},
        timeout=10,
    ).json()
    if r.get("status"):
        print(f"  RELIANCE LTP: ₹{r['data']['ltp']}")
    else:
        print(f"  ltpData failed: {r.get('message')}")
