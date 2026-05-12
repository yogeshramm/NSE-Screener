"""
DB-backed preset management with ownership, visibility, and sharing.

Visibility model
----------------
- private  — only the owner can see / load / edit / delete (default)
- public   — listed in the Community Library; anyone logged in can load
- shared   — invisible to the public but visible to specific recipient users

Ownerless rows (owner_id IS NULL) are the legacy file-imported presets —
treated as system defaults, visible to everyone, owned by nobody, not
deletable through the standard API.

Stages
------
Each preset carries `stages_json = {"s1": bool, "s2": bool, "s3": bool}` so a
preset built for fundamentals-only can run S1 alone, and a breakout setup
can run S1+S2 without forcing S3. The S3 ⇒ S2 rule is enforced both client
and server side: turning S3 on without S2 is rejected (HTTP 400) and the UI
greys out the S3 toggle until S2 is selected.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Optional, List, Dict, Any

from engine.db import get_conn, now_ts


# ─────────────────────────── helpers ───────────────────────────

_SAFE_NAME = re.compile(r"[^a-z0-9_\-]")


def sanitize_name(raw: str) -> str:
    """Normalise preset name → lowercase, spaces→underscores, safe chars only."""
    n = (raw or "").strip().lower().replace(" ", "_")
    n = _SAFE_NAME.sub("", n)
    return n[:80] or "untitled"


def _normalise_stages(stages: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    """Coerce stages dict into clean {s1,s2,s3} bools, with the S3⇒S2 guard."""
    if not isinstance(stages, dict):
        stages = {}
    s1 = bool(stages.get("s1", True))
    s2 = bool(stages.get("s2", True))
    s3 = bool(stages.get("s3", False))
    if s3 and not s2:
        # Quietly drop S3 — caller can also choose to raise; the routes layer
        # surfaces this as a 400 before we get here.
        s3 = False
    return {"s1": s1, "s2": s2, "s3": s3}


def _row_to_dict(r: sqlite3.Row, with_config: bool = True) -> Dict[str, Any]:
    out = {
        "id": r["id"],
        "owner_id": r["owner_id"],
        "name": r["name"],
        "description": r["description"],
        "stages": json.loads(r["stages_json"]),
        "visibility": r["visibility"],
        "use_count": r["use_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }
    if with_config:
        try: out["config"] = json.loads(r["config_json"])
        except Exception: out["config"] = {}
    return out


# ─────────────────────────── public API ───────────────────────────

def save_preset(
    name: str,
    config: dict,
    owner_id: Optional[int] = None,
    description: str = "",
    stages: Optional[dict] = None,
    visibility: str = "private",
) -> Dict[str, Any]:
    """Create or update a preset.

    Uniqueness key is (owner_id, name) — a user can have one preset named
    "minervini", and another user can also have their own "minervini".
    Ownerless legacy presets are keyed by name alone.
    """
    safe = sanitize_name(name)
    if not safe:
        raise ValueError("Preset name cannot be empty")
    if visibility not in ("private", "public", "shared"):
        visibility = "private"
    stages_clean = _normalise_stages(stages)
    cfg_json = json.dumps(config or {})
    stages_json = json.dumps(stages_clean)
    now = now_ts()

    with get_conn() as conn:
        # Find existing row (same owner + name)
        if owner_id is None:
            existing = conn.execute(
                "SELECT id FROM presets WHERE owner_id IS NULL AND name = ?",
                (safe,),
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT id FROM presets WHERE owner_id = ? AND name = ?",
                (owner_id, safe),
            ).fetchone()
        if existing:
            conn.execute(
                """UPDATE presets
                      SET description = ?, config_json = ?, stages_json = ?,
                          visibility = ?, updated_at = ?
                    WHERE id = ?""",
                (description, cfg_json, stages_json, visibility, now, existing["id"]),
            )
            pid = existing["id"]
        else:
            cur = conn.execute(
                """INSERT INTO presets
                   (owner_id, name, description, config_json, stages_json,
                    visibility, use_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (owner_id, safe, description, cfg_json, stages_json, visibility, now, now),
            )
            pid = cur.lastrowid
        row = conn.execute("SELECT * FROM presets WHERE id = ?", (pid,)).fetchone()
    return _row_to_dict(row)


def load_preset_by_name(
    name: str,
    requester_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Resolve a preset by name. Search order:

    1. Owned by requester (private/public/shared all visible to owner)
    2. Public preset by that name (most-recent if multiple)
    3. Shared with requester
    4. Legacy ownerless preset
    Raises FileNotFoundError if none match — kept as FileNotFoundError so the
    routes layer that already catches it still works.
    """
    safe = sanitize_name(name)
    with get_conn() as conn:
        # 1. Owned by requester
        if requester_id is not None:
            row = conn.execute(
                "SELECT * FROM presets WHERE owner_id = ? AND name = ?",
                (requester_id, safe),
            ).fetchone()
            if row:
                return _row_to_dict(row)

        # 2. Public preset
        row = conn.execute(
            "SELECT * FROM presets WHERE visibility = 'public' AND name = ? ORDER BY updated_at DESC LIMIT 1",
            (safe,),
        ).fetchone()
        if row:
            return _row_to_dict(row)

        # 3. Shared with requester
        if requester_id is not None:
            row = conn.execute(
                """SELECT p.* FROM presets p
                   JOIN preset_shares s ON s.preset_id = p.id
                   WHERE s.recipient_id = ? AND p.name = ?
                   ORDER BY p.updated_at DESC LIMIT 1""",
                (requester_id, safe),
            ).fetchone()
            if row:
                return _row_to_dict(row)

        # 4. Legacy ownerless
        row = conn.execute(
            "SELECT * FROM presets WHERE owner_id IS NULL AND name = ?",
            (safe,),
        ).fetchone()
        if row:
            return _row_to_dict(row)

    raise FileNotFoundError(f"Preset '{name}' not found")


def list_presets_for(requester_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return everything the requester can see, deduplicated by name (own wins).

    For backward-compat with the existing frontend (which calls /presets/list
    and expects a flat list of names), this returns name + minimal metadata.
    The full row is fetched on load.
    """
    seen_names = set()
    out: List[Dict[str, Any]] = []
    with get_conn() as conn:
        if requester_id is not None:
            for r in conn.execute(
                "SELECT * FROM presets WHERE owner_id = ? ORDER BY updated_at DESC",
                (requester_id,),
            ):
                d = _row_to_dict(r, with_config=False)
                d["source"] = "mine"
                seen_names.add(r["name"])
                out.append(d)
            for r in conn.execute(
                """SELECT p.* FROM presets p
                   JOIN preset_shares s ON s.preset_id = p.id
                   WHERE s.recipient_id = ?
                   ORDER BY p.updated_at DESC""",
                (requester_id,),
            ):
                if r["name"] in seen_names: continue
                d = _row_to_dict(r, with_config=False)
                d["source"] = "shared"
                seen_names.add(r["name"])
                out.append(d)
        # Legacy ownerless (system defaults)
        for r in conn.execute(
            "SELECT * FROM presets WHERE owner_id IS NULL ORDER BY name"
        ):
            if r["name"] in seen_names: continue
            d = _row_to_dict(r, with_config=False)
            d["source"] = "system"
            seen_names.add(r["name"])
            out.append(d)
    return out


def list_public_presets(limit: int = 200, search: Optional[str] = None) -> List[Dict[str, Any]]:
    """Community library — public presets with author username + use count."""
    sql = """
        SELECT p.*, u.username AS author
          FROM presets p
          LEFT JOIN users u ON u.id = p.owner_id
         WHERE p.visibility = 'public'
    """
    params: list = []
    if search:
        sql += " AND (p.name LIKE ? OR p.description LIKE ?)"
        like = f"%{search.strip().lower()}%"
        params += [like, like]
    sql += " ORDER BY p.use_count DESC, p.updated_at DESC LIMIT ?"
    params.append(int(limit))
    out: List[Dict[str, Any]] = []
    with get_conn() as conn:
        for r in conn.execute(sql, params):
            d = _row_to_dict(r, with_config=False)
            d["author"] = r["author"] or "system"
            out.append(d)
    return out


def delete_preset(name: str, requester_id: Optional[int] = None) -> bool:
    """Delete a preset by name. Owner-only. Legacy ownerless presets cannot
    be deleted through this API (would orphan all users). Returns True if
    something was deleted."""
    safe = sanitize_name(name)
    with get_conn() as conn:
        if requester_id is None:
            return False
        cur = conn.execute(
            "DELETE FROM presets WHERE owner_id = ? AND name = ?",
            (requester_id, safe),
        )
        return cur.rowcount > 0


def set_visibility(
    preset_id: int,
    visibility: str,
    requester_id: int,
) -> Dict[str, Any]:
    """Change visibility of a preset the requester owns."""
    if visibility not in ("private", "public", "shared"):
        raise ValueError("visibility must be private | public | shared")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM presets WHERE id = ? AND owner_id = ?",
            (preset_id, requester_id),
        ).fetchone()
        if not row:
            raise PermissionError("Preset not found or you don't own it")
        conn.execute(
            "UPDATE presets SET visibility = ?, updated_at = ? WHERE id = ?",
            (visibility, now_ts(), preset_id),
        )
        row = conn.execute("SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone()
    return _row_to_dict(row, with_config=False)


def share_with_user(
    preset_id: int,
    recipient_username: str,
    requester_id: int,
) -> Dict[str, Any]:
    """Grant a specific user access to a preset the requester owns."""
    with get_conn() as conn:
        owner_row = conn.execute(
            "SELECT id FROM presets WHERE id = ? AND owner_id = ?",
            (preset_id, requester_id),
        ).fetchone()
        if not owner_row:
            raise PermissionError("Preset not found or you don't own it")
        recipient = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
            (recipient_username.strip(),),
        ).fetchone()
        if not recipient:
            raise ValueError(f"User '{recipient_username}' not found")
        if recipient["id"] == requester_id:
            raise ValueError("Cannot share a preset with yourself")
        try:
            conn.execute(
                "INSERT INTO preset_shares(preset_id, recipient_id, shared_at) VALUES(?,?,?)",
                (preset_id, recipient["id"], now_ts()),
            )
        except sqlite3.IntegrityError:
            # already shared — idempotent
            pass
        # Make sure visibility reflects that at least one share exists
        conn.execute(
            "UPDATE presets SET visibility = CASE WHEN visibility = 'private' THEN 'shared' ELSE visibility END, updated_at = ? WHERE id = ?",
            (now_ts(), preset_id),
        )
        # Return updated state + recipient list
        shares = conn.execute(
            """SELECT u.id, u.username, s.shared_at
                 FROM preset_shares s JOIN users u ON u.id = s.recipient_id
                WHERE s.preset_id = ? ORDER BY s.shared_at DESC""",
            (preset_id,),
        ).fetchall()
    return {"preset_id": preset_id, "shares": [dict(s) for s in shares]}


def unshare(preset_id: int, recipient_username: str, requester_id: int) -> None:
    """Revoke a previously granted share."""
    with get_conn() as conn:
        owner_row = conn.execute(
            "SELECT id FROM presets WHERE id = ? AND owner_id = ?",
            (preset_id, requester_id),
        ).fetchone()
        if not owner_row:
            raise PermissionError("Preset not found or you don't own it")
        recipient = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
            (recipient_username.strip(),),
        ).fetchone()
        if not recipient:
            return
        conn.execute(
            "DELETE FROM preset_shares WHERE preset_id = ? AND recipient_id = ?",
            (preset_id, recipient["id"]),
        )


def shares_for_preset(preset_id: int, requester_id: int) -> List[Dict[str, Any]]:
    """List recipients a preset is shared with (owner-only)."""
    with get_conn() as conn:
        owner_row = conn.execute(
            "SELECT id FROM presets WHERE id = ? AND owner_id = ?",
            (preset_id, requester_id),
        ).fetchone()
        if not owner_row:
            raise PermissionError("Preset not found or you don't own it")
        rows = conn.execute(
            """SELECT u.id, u.username, s.shared_at
                 FROM preset_shares s JOIN users u ON u.id = s.recipient_id
                WHERE s.preset_id = ? ORDER BY s.shared_at DESC""",
            (preset_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def increment_use(preset_id: int) -> None:
    """Bump use_count when someone loads a preset — fire-and-forget."""
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE presets SET use_count = use_count + 1 WHERE id = ?",
                (preset_id,),
            )
    except Exception:
        pass
