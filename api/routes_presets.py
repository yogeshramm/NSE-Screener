"""
Preset endpoints — DB-backed, ownership-aware, with sharing.

Backward-compatible URLs the frontend already calls:
  POST   /presets/save      — save (auth-optional; auth attaches owner)
  GET    /presets/list      — list everything the caller can see
  GET    /presets/{name}    — load by name (resolves with ownership rules)
  DELETE /presets/{name}    — delete (owner-only)

New endpoints (Phase 3):
  GET    /presets/public                  — community library
  GET    /presets/{name}/meta             — full row incl. visibility + shares
  POST   /presets/{id}/visibility         — set private | public | shared
  POST   /presets/{id}/share              — share with a specific username
  POST   /presets/{id}/unshare            — revoke a share
  GET    /presets/{id}/shares             — list recipients (owner-only)
"""

from typing import Optional, List
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from engine import presets_db
from engine.auth import verify_token, get_user

router = APIRouter()


# ─────────────── auth helpers (auth-optional for backward compat) ───────────────

def _maybe_user(authorization: Optional[str]) -> Optional[dict]:
    """Return JWT payload dict if a valid token is provided, else None.

    Never raises — preset endpoints stay accessible without auth so legacy
    behaviour (no-auth GET of legacy presets) keeps working."""
    if not authorization:
        return None
    tok = authorization[7:] if authorization.startswith("Bearer ") else authorization
    try:
        return verify_token(tok)
    except Exception:
        return None


def _user_id_from(authorization: Optional[str]) -> Optional[int]:
    p = _maybe_user(authorization)
    if not p:
        return None
    full = get_user(p.get("username", ""))
    if not full:
        return None
    # JWT payload doesn't include the DB-side user.id, so look it up here.
    from engine.db import get_conn
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (p["username"],)).fetchone()
    return row["id"] if row else None


def _require_user_id(authorization: Optional[str]) -> int:
    uid = _user_id_from(authorization)
    if uid is None:
        raise HTTPException(401, "Sign in to perform this action")
    return uid


# ─────────────── request models ───────────────

class SavePresetRequest(BaseModel):
    name: str
    config: dict
    description: Optional[str] = ""
    stages: Optional[dict] = None       # {"s1":bool,"s2":bool,"s3":bool}
    visibility: Optional[str] = "private"


class VisibilityRequest(BaseModel):
    visibility: str   # private | public | shared


class ShareRequest(BaseModel):
    username: str


# ─────────────── existing endpoints (backward-compatible) ───────────────

@router.post("/presets/save")
def save(request: SavePresetRequest, authorization: Optional[str] = Header(None)):
    """Save a preset. If signed in, the row is attributed to the user;
    otherwise it's saved as an ownerless system-default (legacy behaviour)."""
    if not request.name.strip():
        raise HTTPException(400, "Preset name cannot be empty")
    # Stage validation — S3 requires S2
    stages = request.stages or {}
    if stages.get("s3") and not stages.get("s2"):
        raise HTTPException(400, "Stage 3 requires Stage 2 to be enabled")
    visibility = request.visibility if request.visibility in ("private", "public", "shared") else "private"
    owner_id = _user_id_from(authorization)
    try:
        row = presets_db.save_preset(
            name=request.name,
            config=request.config,
            owner_id=owner_id,
            description=request.description or "",
            stages=stages,
            visibility=visibility,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "status": "saved",
        "name": row["name"],
        "id": row["id"],
        "visibility": row["visibility"],
        "stages": row["stages"],
    }


@router.get("/presets/list")
def list_all(authorization: Optional[str] = Header(None)):
    """List presets visible to the caller (own + shared-with + system)."""
    uid = _user_id_from(authorization)
    rows = presets_db.list_presets_for(uid)
    return {
        "total": len(rows),
        "presets": [r["name"] for r in rows],  # backward-compat shape
        "rows": rows,                           # richer payload for new UI
    }


@router.get("/presets/public")
def list_public(search: Optional[str] = None, limit: int = 200):
    """Community library — public presets."""
    rows = presets_db.list_public_presets(limit=limit, search=search)
    return {"total": len(rows), "rows": rows}


@router.get("/presets/{name}")
def load(name: str, authorization: Optional[str] = Header(None)):
    """Load a preset by name. Resolution honours ownership (own → public → shared → system)."""
    uid = _user_id_from(authorization)
    try:
        row = presets_db.load_preset_by_name(name.strip(), requester_id=uid)
    except FileNotFoundError:
        raise HTTPException(404, f"Preset '{name}' not found")
    # Bump use_count fire-and-forget — analytics for the community library
    presets_db.increment_use(row["id"])
    return {
        "name": row["name"],
        "config": row["config"],
        "stages": row["stages"],
        "visibility": row["visibility"],
        "description": row["description"],
        "id": row["id"],
        "owner_id": row["owner_id"],
    }


@router.delete("/presets/{name}")
def delete(name: str, authorization: Optional[str] = Header(None)):
    """Delete a preset you own. Legacy system presets cannot be deleted."""
    uid = _user_id_from(authorization)
    if uid is None:
        raise HTTPException(401, "Sign in to delete presets")
    deleted = presets_db.delete_preset(name.strip(), requester_id=uid)
    if not deleted:
        raise HTTPException(404, f"Preset '{name}' not found or not yours")
    return {"status": "deleted", "name": name}


# ─────────────── visibility + sharing (new) ───────────────

@router.post("/presets/{preset_id}/visibility")
def change_visibility(preset_id: int, req: VisibilityRequest, authorization: Optional[str] = Header(None)):
    uid = _require_user_id(authorization)
    try:
        row = presets_db.set_visibility(preset_id, req.visibility, uid)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "preset": row}


@router.post("/presets/{preset_id}/share")
def share(preset_id: int, req: ShareRequest, authorization: Optional[str] = Header(None)):
    uid = _require_user_id(authorization)
    try:
        out = presets_db.share_with_user(preset_id, req.username, uid)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", **out}


@router.post("/presets/{preset_id}/unshare")
def unshare(preset_id: int, req: ShareRequest, authorization: Optional[str] = Header(None)):
    uid = _require_user_id(authorization)
    try:
        presets_db.unshare(preset_id, req.username, uid)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return {"status": "ok"}


@router.get("/presets/{preset_id}/shares")
def list_shares(preset_id: int, authorization: Optional[str] = Header(None)):
    uid = _require_user_id(authorization)
    try:
        rows = presets_db.shares_for_preset(preset_id, uid)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return {"total": len(rows), "shares": rows}
