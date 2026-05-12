"""
Tournament endpoints.

  GET    /tournaments?status=pending|live|closed
  POST   /tournaments                          — create (auth required)
  GET    /tournaments/{id}                     — detail (hidden stocks until closed)
  POST   /tournaments/{id}/join                — enroll
  GET    /tournaments/{id}/my-entry            — your entry state
  GET    /tournaments/{id}/slot/{slot}/data    — anonymised candle data (live only)
  POST   /tournaments/{id}/submit              — submit aggregated per-stock results
  GET    /tournaments/{id}/leaderboard         — current rankings + reveal once closed
  DELETE /tournaments/{id}                     — host cancel (pending only)

Feature-flagged via TOURNAMENT_ENABLED env (default ON).
"""

import os
import json
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from engine import tournament
from engine.auth import verify_token
from engine.db import get_conn

router = APIRouter()


def _feature_enabled() -> bool:
    return os.getenv("TOURNAMENT_ENABLED", "true").lower() in ("1", "true", "yes", "on")


def _require_user(authorization: Optional[str]) -> dict:
    if not _feature_enabled():
        raise HTTPException(503, "Tournament mode is currently disabled")
    if not authorization:
        raise HTTPException(401, "Sign in required")
    tok = authorization[7:] if authorization.startswith("Bearer ") else authorization
    try:
        payload = verify_token(tok)
    except Exception:
        raise HTTPException(401, "Invalid token")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, role FROM users WHERE username = ? COLLATE NOCASE",
            (payload.get("username", ""),),
        ).fetchone()
    if not row:
        raise HTTPException(401, "User not found")
    return {"id": row["id"], "role": row["role"], "username": payload.get("username")}


# ─────────── request models ───────────

class CreateTournament(BaseModel):
    name: str
    n_stocks: int = 5
    days_per_stock: int = 60
    window_minutes: int = 45
    min_players: int = 2
    universe: str = "nifty500"


class SubmitEntry(BaseModel):
    per_stock_results: List[dict]


# ─────────── reads ───────────

@router.get("/tournaments")
def list_all(status: Optional[str] = None, limit: int = 50):
    if not _feature_enabled():
        raise HTTPException(503, "Tournament mode is currently disabled")
    return {"tournaments": tournament.list_tournaments(status=status, limit=limit)}


@router.get("/tournaments/{tid}")
def get_one(tid: int):
    if not _feature_enabled():
        raise HTTPException(503, "Tournament mode is currently disabled")
    t = tournament.get_tournament(tid)
    if not t:
        raise HTTPException(404, "Not found")
    return t


@router.get("/tournaments/{tid}/leaderboard")
def get_leaderboard(tid: int):
    if not _feature_enabled():
        raise HTTPException(503, "Tournament mode is currently disabled")
    out = tournament.leaderboard(tid)
    if not out:
        raise HTTPException(404, "Not found")
    return out


# ─────────── auth writes ───────────

@router.post("/tournaments")
def create(req: CreateTournament, authorization: Optional[str] = Header(None)):
    u = _require_user(authorization)
    try:
        t = tournament.create_tournament(
            host_id=u["id"],
            name=req.name,
            n_stocks=req.n_stocks,
            days_per_stock=req.days_per_stock,
            window_minutes=req.window_minutes,
            min_players=req.min_players,
            universe=req.universe,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return t


@router.post("/tournaments/{tid}/join")
def join(tid: int, authorization: Optional[str] = Header(None)):
    u = _require_user(authorization)
    try:
        return tournament.join_tournament(tid, u["id"])
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/tournaments/{tid}/my-entry")
def my_entry(tid: int, authorization: Optional[str] = Header(None)):
    u = _require_user(authorization)
    entry = tournament.get_my_entry(tid, u["id"])
    if not entry:
        raise HTTPException(404, "Not enrolled")
    return entry


@router.get("/tournaments/{tid}/slot/{slot}/data")
def slot_data(tid: int, slot: int, days: int = 60, authorization: Optional[str] = Header(None)):
    """Anonymised candle data for a tournament slot. Returns warmup_candles +
    warmup_volumes ready for the practice engine, with metadata stripped."""
    u = _require_user(authorization)
    t = tournament.get_tournament(tid)
    if not t:
        raise HTTPException(404, "Tournament not found")
    if t["status"] != "live":
        raise HTTPException(409, "Tournament is not live")
    # Ensure the user is enrolled
    entry = tournament.get_my_entry(tid, u["id"])
    if not entry:
        raise HTTPException(403, "Not enrolled")
    symbol = tournament.get_slot_symbol(tid, slot)
    if not symbol:
        raise HTTPException(404, "Invalid slot")
    # Fetch candles via practice engine helpers
    try:
        from engine.practice import _load
        df = _load(symbol)
        if df is None or df.empty:
            raise HTTPException(404, "No data for slot")
        # Use the last `days` of revealed data (mirrors free practice rounds)
        win = df.tail(days + 260)  # +warmup
        candles = [
            {"time": int(idx.timestamp()), "open": float(r["Open"]), "high": float(r["High"]),
             "low": float(r["Low"]), "close": float(r["Close"])}
            for idx, r in win.iterrows()
        ]
        volumes = [
            {"time": int(idx.timestamp()),
             "value": int(r["Volume"]),
             "color": '#00e5a0' if r["Close"] >= r["Open"] else '#ff4757'}
            for idx, r in win.iterrows()
        ]
        return {
            "slot": slot,
            "label": f"Stock {chr(64+slot)}",   # 'Stock A', 'Stock B', ...
            "candles": candles,
            "volumes": volumes,
            "days": days,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Data load failed: {e}")


@router.post("/tournaments/{tid}/submit")
def submit(tid: int, req: SubmitEntry, authorization: Optional[str] = Header(None)):
    u = _require_user(authorization)
    try:
        return tournament.submit_entry(tid, u["id"], req.per_stock_results)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/tournaments/{tid}")
def cancel(tid: int, authorization: Optional[str] = Header(None)):
    u = _require_user(authorization)
    try:
        tournament.cancel_tournament(tid, u["id"], is_admin=(u["role"] == "admin"))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"status": "cancelled"}
