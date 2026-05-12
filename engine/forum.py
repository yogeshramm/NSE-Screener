"""
Forum — categories, topics, posts, admin moderation.

Sized for ~200 users — no real-time, no pagination cursors, just plain
queries + a last_activity index. WAL mode handles concurrent reads
without contention.

Permission model
----------------
- Any authenticated user can create topics + post replies in non-archived
  topics, edit their own posts, delete their own posts.
- Admin (users.role = 'admin') can pin, archive, delete anything.
- The "Announcements" category has `admin_only_post = 1` — only admins can
  start topics there. Regular users can still reply.
"""

from __future__ import annotations

import json
from typing import List, Dict, Any, Optional

from engine.db import get_conn, now_ts


# ─────────────────────────── categories ───────────────────────────

def list_categories() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.*, (SELECT COUNT(*) FROM forum_topics t WHERE t.category_id = c.id AND t.archived = 0) AS topic_count
                 FROM forum_categories c
                WHERE c.archived = 0
             ORDER BY c.sort_order, c.name"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_category(slug: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM forum_categories WHERE slug = ?", (slug,)
        ).fetchone()
    return dict(row) if row else None


# ─────────────────────────── topics ───────────────────────────

def list_topics(category_slug: str, limit: int = 100) -> List[Dict[str, Any]]:
    """List non-archived topics in a category, pinned first then by activity."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT t.*, u.username AS author
                 FROM forum_topics t
                 LEFT JOIN users u ON u.id = t.author_id
                 JOIN forum_categories c ON c.id = t.category_id
                WHERE c.slug = ? AND t.archived = 0
             ORDER BY t.pinned DESC, t.last_activity DESC
                LIMIT ?""",
            (category_slug, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def create_topic(
    category_slug: str,
    author_id: int,
    title: str,
    body: str,
    is_admin: bool = False,
) -> Dict[str, Any]:
    title = (title or "").strip()
    body = (body or "").strip()
    if not title:
        raise ValueError("Title is required")
    if len(title) > 200:
        title = title[:200]
    if not body:
        raise ValueError("Body is required")
    cat = get_category(category_slug)
    if not cat:
        raise ValueError(f"Category '{category_slug}' not found")
    if cat["admin_only_post"] and not is_admin:
        raise PermissionError("Only admins can post in this category")
    now = now_ts()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO forum_topics
               (category_id, author_id, title, body, created_at, last_activity)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cat["id"], author_id, title, body, now, now),
        )
        tid = cur.lastrowid
        row = conn.execute("SELECT * FROM forum_topics WHERE id = ?", (tid,)).fetchone()
    return dict(row)


def get_topic(topic_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT t.*, u.username AS author, c.slug AS category_slug, c.name AS category_name
                 FROM forum_topics t
                 LEFT JOIN users u ON u.id = t.author_id
                 JOIN forum_categories c ON c.id = t.category_id
                WHERE t.id = ?""",
            (topic_id,),
        ).fetchone()
    return dict(row) if row else None


def update_topic_meta(topic_id: int, *, pinned: Optional[bool] = None, archived: Optional[bool] = None) -> None:
    """Admin moderation hook."""
    sets, params = [], []
    if pinned is not None:
        sets.append("pinned = ?"); params.append(1 if pinned else 0)
    if archived is not None:
        sets.append("archived = ?"); params.append(1 if archived else 0)
    if not sets:
        return
    params.append(topic_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE forum_topics SET {', '.join(sets)} WHERE id = ?", params)


def delete_topic(topic_id: int) -> None:
    """Hard delete — cascades to posts via FK."""
    with get_conn() as conn:
        conn.execute("DELETE FROM forum_topics WHERE id = ?", (topic_id,))


# ─────────────────────────── posts (replies) ───────────────────────────

def list_posts(topic_id: int) -> List[Dict[str, Any]]:
    """List replies for a topic, oldest first. The topic body itself is shown
    separately by the UI as the first 'post'."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT p.*, u.username AS author
                 FROM forum_posts p
                 LEFT JOIN users u ON u.id = p.author_id
                WHERE p.topic_id = ?
             ORDER BY p.created_at""",
            (topic_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_post(topic_id: int, author_id: int, body: str) -> Dict[str, Any]:
    body = (body or "").strip()
    if not body:
        raise ValueError("Reply body is required")
    now = now_ts()
    with get_conn() as conn:
        topic = conn.execute(
            "SELECT id, archived FROM forum_topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if not topic:
            raise ValueError("Topic not found")
        if topic["archived"]:
            raise PermissionError("Topic is archived — no new replies")
        cur = conn.execute(
            """INSERT INTO forum_posts(topic_id, author_id, body, created_at)
               VALUES (?, ?, ?, ?)""",
            (topic_id, author_id, body, now),
        )
        pid = cur.lastrowid
        conn.execute(
            "UPDATE forum_topics SET reply_count = reply_count + 1, last_activity = ? WHERE id = ?",
            (now, topic_id),
        )
        row = conn.execute("SELECT * FROM forum_posts WHERE id = ?", (pid,)).fetchone()
    return dict(row)


def update_post(post_id: int, author_id: int, body: str, is_admin: bool = False) -> Dict[str, Any]:
    """Edit your own post (or any if admin)."""
    body = (body or "").strip()
    if not body:
        raise ValueError("Body is required")
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM forum_posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            raise ValueError("Post not found")
        if row["author_id"] != author_id and not is_admin:
            raise PermissionError("Not your post")
        conn.execute(
            "UPDATE forum_posts SET body = ?, edited_at = ? WHERE id = ?",
            (body, now_ts(), post_id),
        )
        row = conn.execute("SELECT * FROM forum_posts WHERE id = ?", (post_id,)).fetchone()
    return dict(row)


def delete_post(post_id: int, author_id: int, is_admin: bool = False) -> None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM forum_posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return
        if row["author_id"] != author_id and not is_admin:
            raise PermissionError("Not your post")
        conn.execute("DELETE FROM forum_posts WHERE id = ?", (post_id,))
        # Decrement reply_count on the parent topic — keeps the badge correct
        conn.execute(
            "UPDATE forum_topics SET reply_count = MAX(reply_count - 1, 0) WHERE id = ?",
            (row["topic_id"],),
        )
