"""
Forum endpoints — categories, topics, posts.

Feature-flagged: if the `forum_enabled` env var is unset/false, every
endpoint returns 503. Flip it on by setting FORUM_ENABLED=true in
/etc/yointell.env and restarting.

  GET    /forum/categories                — list categories
  GET    /forum/categories/{slug}         — category detail (echo)
  GET    /forum/topics/{slug}             — topics in a category
  POST   /forum/topics/{slug}             — create new topic
  GET    /forum/topic/{topic_id}          — topic + replies
  POST   /forum/topic/{topic_id}/reply    — post a reply
  POST   /forum/post/{post_id}/edit       — edit your own post
  DELETE /forum/post/{post_id}            — delete your own post (admin: any)
  POST   /forum/topic/{topic_id}/admin    — admin pin/archive/delete
"""

import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from engine import forum
from engine.auth import verify_token
from engine.db import get_conn

router = APIRouter()


def _feature_enabled() -> bool:
    return os.getenv("FORUM_ENABLED", "true").lower() in ("1", "true", "yes", "on")


def _require_user(authorization: Optional[str]) -> dict:
    if not _feature_enabled():
        raise HTTPException(503, "Forum is currently disabled")
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


def _require_admin(authorization: Optional[str]) -> dict:
    u = _require_user(authorization)
    if u["role"] != "admin":
        raise HTTPException(403, "Admin only")
    return u


# Request models
class TopicCreate(BaseModel):
    title: str
    body: str


class ReplyCreate(BaseModel):
    body: str


class PostEdit(BaseModel):
    body: str


class AdminAction(BaseModel):
    pinned: Optional[bool] = None
    archived: Optional[bool] = None
    delete: Optional[bool] = None


# ─────────────── public reads ───────────────

@router.get("/forum/categories")
def get_categories():
    if not _feature_enabled():
        raise HTTPException(503, "Forum is currently disabled")
    return {"categories": forum.list_categories()}


@router.get("/forum/topics/{slug}")
def get_topics(slug: str, limit: int = 100):
    if not _feature_enabled():
        raise HTTPException(503, "Forum is currently disabled")
    cat = forum.get_category(slug)
    if not cat:
        raise HTTPException(404, "Category not found")
    return {"category": cat, "topics": forum.list_topics(slug, limit=limit)}


@router.get("/forum/topic/{topic_id}")
def get_topic(topic_id: int):
    if not _feature_enabled():
        raise HTTPException(503, "Forum is currently disabled")
    t = forum.get_topic(topic_id)
    if not t:
        raise HTTPException(404, "Topic not found")
    return {"topic": t, "posts": forum.list_posts(topic_id)}


# ─────────────── authenticated writes ───────────────

@router.post("/forum/topics/{slug}")
def create_topic(slug: str, req: TopicCreate, authorization: Optional[str] = Header(None)):
    u = _require_user(authorization)
    try:
        t = forum.create_topic(slug, u["id"], req.title, req.body, is_admin=(u["role"] == "admin"))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"topic": t}


@router.post("/forum/topic/{topic_id}/reply")
def reply_to_topic(topic_id: int, req: ReplyCreate, authorization: Optional[str] = Header(None)):
    u = _require_user(authorization)
    try:
        p = forum.add_post(topic_id, u["id"], req.body)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"post": p}


@router.post("/forum/post/{post_id}/edit")
def edit_post(post_id: int, req: PostEdit, authorization: Optional[str] = Header(None)):
    u = _require_user(authorization)
    try:
        p = forum.update_post(post_id, u["id"], req.body, is_admin=(u["role"] == "admin"))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"post": p}


@router.delete("/forum/post/{post_id}")
def remove_post(post_id: int, authorization: Optional[str] = Header(None)):
    u = _require_user(authorization)
    try:
        forum.delete_post(post_id, u["id"], is_admin=(u["role"] == "admin"))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return {"status": "deleted"}


# ─────────────── admin moderation ───────────────

@router.post("/forum/topic/{topic_id}/admin")
def admin_topic(topic_id: int, req: AdminAction, authorization: Optional[str] = Header(None)):
    _require_admin(authorization)
    if req.delete:
        forum.delete_topic(topic_id)
        return {"status": "deleted"}
    forum.update_topic_meta(topic_id, pinned=req.pinned, archived=req.archived)
    return {"status": "ok"}
