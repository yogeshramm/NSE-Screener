"""
Leaderboard endpoints — personal history + opt-in public board.

  GET  /leaderboard/personal             — your own ended rounds
  GET  /leaderboard/personal/stats       — your aggregate stats
  GET  /leaderboard/public               — public, month-windowed
  POST /leaderboard/profile              — toggle public_profile (master switch)
  GET  /leaderboard/profile              — read the toggle
  POST /leaderboard/session/{id}/public  — per-session opt-in (owner-only)
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from engine import leaderboard
from engine.auth import verify_token

router = APIRouter()


def _user_id(authorization: Optional[str]) -> int:
    if not authorization:
        raise HTTPException(401, "Sign in required")
    tok = authorization[7:] if authorization.startswith("Bearer ") else authorization
    try:
        payload = verify_token(tok)
    except Exception:
        raise HTTPException(401, "Invalid token")
    from engine.db import get_conn
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
            (payload.get("username", ""),),
        ).fetchone()
    if not row:
        raise HTTPException(401, "User not found")
    return row["id"]


class ProfileToggle(BaseModel):
    enabled: bool


class SessionPublicToggle(BaseModel):
    public: bool


@router.get("/leaderboard/personal")
def get_personal(limit: int = 50, authorization: Optional[str] = Header(None)):
    uid = _user_id(authorization)
    return {
        "total": None,
        "rows": leaderboard.personal_history(uid, limit=limit),
    }


@router.get("/leaderboard/personal/stats")
def get_personal_stats(authorization: Optional[str] = Header(None)):
    uid = _user_id(authorization)
    return leaderboard.personal_stats(uid)


@router.get("/leaderboard/public")
def get_public(
    period: Optional[str] = None,
    sort: str = "return_pct",
    limit: int = 50,
):
    """Public board — no auth required, anyone can browse."""
    return leaderboard.public_leaderboard(period=period, sort=sort, limit=limit)


@router.get("/leaderboard/profile")
def get_profile(authorization: Optional[str] = Header(None)):
    uid = _user_id(authorization)
    return {"public_profile": leaderboard.get_public_profile(uid)}


@router.post("/leaderboard/profile")
def set_profile(req: ProfileToggle, authorization: Optional[str] = Header(None)):
    uid = _user_id(authorization)
    leaderboard.set_public_profile(uid, req.enabled)
    return {"public_profile": req.enabled}


@router.post("/leaderboard/session/{session_id}/public")
def set_session_public(session_id: int, req: SessionPublicToggle, authorization: Optional[str] = Header(None)):
    uid = _user_id(authorization)
    ok = leaderboard.set_session_public(session_id, uid, req.public)
    if not ok:
        raise HTTPException(404, "Session not found or not yours")
    return {"session_id": session_id, "public": req.public}
