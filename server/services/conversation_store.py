"""Durable assistant conversations: the transcript, its turns, and pruning.

The drawer used to own the transcript in React state, which meant a browser
reload started over and the runtime had to be handed the history on every turn.
Three things pushed it server-side:

  * the app runs multiple uvicorn workers, so nothing can be cached in process
    memory and a client-supplied transcript was the only shared state;
  * attached files are rows in `chat_uploads`, and a browser-only transcript
    could hold nothing but dangling references to them;
  * the client-built history shape silently dropped assistant turns (it labelled
    them `agent`, which the runtime's role filter discarded), so the model never
    saw its own answers. Reading history from here removes that whole class of
    bug — the runtime asks the database, not the browser.

Turn ordering is assigned by the database (`seq` from a `MAX(seq) + 1` subquery in
the INSERT) rather than by the caller, so two tabs open on one conversation cannot
claim the same slot.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# A title is only ever a label in a dropdown; the first line of the opening
# question makes a better one than anything we could ask the user to type.
MAX_TITLE_CHARS = 80

# How many prior turns to replay to the model. The same bound the client used to
# apply, now applied where it belongs.
HISTORY_TURNS = 20

# Conversations accumulate forever otherwise. Keeping the most recent N per user
# bounds the table without anyone having to tidy up, and the drawer only ever
# shows a fraction of that.
KEEP_PER_USER = 50


def _keep_per_user() -> int:
    try:
        return max(5, int(os.environ.get("CHAT_KEEP_CONVERSATIONS", "") or KEEP_PER_USER))
    except ValueError:
        return KEEP_PER_USER


def new_id() -> str:
    return "conv-" + uuid.uuid4().hex[:16]


def derive_title(text: str) -> str:
    """A dropdown label from the opening question."""
    flat = re.sub(r"\s+", " ", (text or "").strip())
    if not flat:
        return "New conversation"
    if len(flat) <= MAX_TITLE_CHARS:
        return flat
    # Prefer a word boundary so the label doesn't end mid-word.
    cut = flat[:MAX_TITLE_CHARS]
    space = cut.rfind(" ")
    return (cut[:space] if space > 40 else cut).rstrip() + "…"


def _json_loads(raw: Any, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _conn(env: str):
    from database import get_db_connection

    return get_db_connection(env)


# ------------------------------------------------------------------ read side

def list_conversations(env: str, username: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Recent conversations for one user, newest activity first."""
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT v.id, v.title, v.profile_id, v.created_at, v.updated_at,
                   (SELECT COUNT(*) FROM chat_messages m WHERE m.conversation_id = v.id)
            FROM chat_conversations v
            WHERE v.username = %s
            ORDER BY v.updated_at DESC
            LIMIT %s
            """,
            (username, max(1, min(limit, 200))),
        )
        return [
            {
                "id": row[0],
                "title": row[1] or "New conversation",
                "profile_id": row[2] or "",
                "created_at": row[3].isoformat() if row[3] else None,
                "updated_at": row[4].isoformat() if row[4] else None,
                "message_count": int(row[5] or 0),
            }
            for row in c.fetchall()
        ]
    finally:
        conn.close()


def _fetch_conversation(c, username: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    c.execute(
        "SELECT id, title, profile_id, created_at, updated_at FROM chat_conversations WHERE id = %s AND username = %s",
        (conversation_id, username),
    )
    row = c.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "title": row[1] or "New conversation",
        "profile_id": row[2] or "",
        "created_at": row[3].isoformat() if row[3] else None,
        "updated_at": row[4].isoformat() if row[4] else None,
    }


def get_conversation(env: str, username: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    """Conversation metadata, or None when it doesn't exist or isn't theirs."""
    conn = _conn(env)
    try:
        return _fetch_conversation(conn.cursor(), username, conversation_id)
    finally:
        conn.close()


def read_conversation(env: str, username: str, conversation_id: str):
    """Metadata, transcript and attached files over a single connection.

    Restoring a conversation is on the critical path of every page load, and
    opening a Lakebase connection costs about as much as the queries themselves —
    so the three reads the drawer needs share one. Returns None when the
    conversation doesn't exist or isn't theirs.
    """
    from services import upload_store

    conn = _conn(env)
    try:
        c = conn.cursor()
        meta = _fetch_conversation(c, username, conversation_id)
        if meta is None:
            return None
        return meta, _fetch_messages(c, conversation_id), upload_store.fetch_uploads(c, username, conversation_id)
    finally:
        conn.close()


def get_messages(env: str, conversation_id: str) -> List[Dict[str, Any]]:
    """The full transcript, shaped the way the drawer renders it."""
    conn = _conn(env)
    try:
        return _fetch_messages(conn.cursor(), conversation_id)
    finally:
        conn.close()


def _fetch_messages(c, conversation_id: str) -> List[Dict[str, Any]]:
    c.execute(
        """
        SELECT seq, role, content, reasoning, tool_calls_json, attachments_json, is_error
        FROM chat_messages WHERE conversation_id = %s ORDER BY seq
        """,
        (conversation_id,),
    )
    out: List[Dict[str, Any]] = []
    for seq, role, content, reasoning, tools, attachments, is_error in c.fetchall():
        message: Dict[str, Any] = {
            "seq": int(seq),
            "role": role,
            "content": content or "",
            # A restored turn is always complete, so it renders as a settled
            # answer rather than as live "thinking" scaffolding.
            "finalized": role == "assistant",
        }
        if reasoning:
            message["reasoning"] = reasoning
        tool_calls = _json_loads(tools, [])
        if tool_calls:
            message["tool_calls"] = tool_calls
        files = _json_loads(attachments, [])
        if files:
            message["attachments"] = files
        if is_error:
            message["isError"] = True
        out.append(message)
    return out


def history_for_model(env: str, conversation_id: str, limit: int = HISTORY_TURNS,
                      before_seq: Optional[int] = None) -> List[Dict[str, str]]:
    """Prior turns as `{role, content}` for the LLM, oldest first.

    `before_seq` excludes the turn currently being answered, which has already
    been written by the time the runtime asks for context.

    Assistant turns carry a `[tools used: …]` line when they had tool calls. The
    replay is text, so without it an agent asked "what did you tell me earlier?"
    sees a bare number with no evidence behind it and tells the user it made the
    number up. The names are the evidence; the runtime's prompt explains the line.
    """
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT role, content, tool_calls_json FROM chat_messages
            WHERE conversation_id = %s
              AND role IN ('user', 'assistant')
              AND content <> ''
              AND (%s IS NULL OR seq < %s)
            ORDER BY seq DESC
            LIMIT %s
            """,
            (conversation_id, before_seq, before_seq, max(0, limit)),
        )
        rows = c.fetchall()
    finally:
        conn.close()
    return [
        {"role": role, "content": with_tool_evidence(role, content, tools)}
        for role, content, tools in reversed(rows)
    ]


def with_tool_evidence(role: str, content: str, tools_json: Any) -> str:
    """Append the tools an assistant turn ran, for the replay to carry."""
    if role != "assistant":
        return content
    names = [
        str(t.get("tool_name") or t.get("name") or "").strip()
        for t in _json_loads(tools_json, [])
        if isinstance(t, dict) and (t.get("tool_name") or t.get("name"))
    ]
    if not names:
        return content
    return f"{content}\n\n[tools used: {', '.join(dict.fromkeys(names))}]"


# ----------------------------------------------------------------- write side

def create_conversation(env: str, username: str, profile_id: str = "", title: str = "",
                        conversation_id: Optional[str] = None) -> Dict[str, Any]:
    """Start a conversation, optionally at an id the client already generated."""
    cid = (conversation_id or "").strip() or new_id()
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO chat_conversations (id, username, title, profile_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (cid, username, title, profile_id or ""),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": cid, "title": title or "New conversation", "profile_id": profile_id or ""}


def ensure_conversation(env: str, username: str, conversation_id: str, profile_id: str = "") -> str:
    """Return an id that is safe to write turns to.

    The client generates conversation ids so it can render optimistically before
    the first turn round-trips. An id that doesn't exist yet is created here; one
    that exists but belongs to somebody else is replaced with a fresh one rather
    than written to.
    """
    cid = (conversation_id or "").strip()
    if not cid:
        return create_conversation(env, username, profile_id)["id"]
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute("SELECT username FROM chat_conversations WHERE id = %s", (cid,))
        row = c.fetchone()
        if row is not None:
            if (row[0] or "") == username:
                return cid
            logger.warning("conversation %s belongs to another user; starting a new one", cid)
            return create_conversation(env, username, profile_id)["id"]
    finally:
        conn.close()
    return create_conversation(env, username, profile_id, conversation_id=cid)["id"]


def append_message(env: str, conversation_id: str, role: str, content: str, *,
                   reasoning: str = "", tool_calls: Optional[List[Dict[str, Any]]] = None,
                   attachments: Optional[List[Dict[str, Any]]] = None,
                   is_error: bool = False, profile_id: Optional[str] = None) -> int:
    """Append a turn and return its sequence number.

    Also refreshes `updated_at` (so the conversation list orders by activity) and
    titles the conversation from its first user turn.
    """
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO chat_messages
                (conversation_id, seq, role, content, reasoning, tool_calls_json, attachments_json, is_error)
            SELECT %s, COALESCE(MAX(seq), 0) + 1, %s, %s, %s, %s, %s, %s
            FROM chat_messages WHERE conversation_id = %s
            RETURNING seq
            """,
            (
                conversation_id, role, content or "", reasoning or "",
                json.dumps(tool_calls or []), json.dumps(attachments or []),
                1 if is_error else 0, conversation_id,
            ),
        )
        seq = int(c.fetchone()[0])
        if role == "user":
            # COALESCE keeps a user-renamed conversation from being retitled.
            c.execute(
                """
                UPDATE chat_conversations
                SET title = CASE WHEN COALESCE(title, '') = '' THEN %s ELSE title END,
                    profile_id = COALESCE(%s, profile_id),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (derive_title(content), profile_id, conversation_id),
            )
        else:
            c.execute(
                "UPDATE chat_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (conversation_id,),
            )
        conn.commit()
        return seq
    finally:
        conn.close()


def rename_conversation(env: str, username: str, conversation_id: str, title: str) -> bool:
    clean = re.sub(r"\s+", " ", (title or "").strip())[:MAX_TITLE_CHARS]
    if not clean:
        return False
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE chat_conversations SET title = %s WHERE id = %s AND username = %s",
            (clean, conversation_id, username),
        )
        changed = c.rowcount > 0
        conn.commit()
        return changed
    finally:
        conn.close()


def delete_conversation(env: str, username: str, conversation_id: str) -> bool:
    """Delete a conversation with its turns and uploaded files.

    These tables carry no foreign keys (the schema is created table by table
    across environments), so the children are removed explicitly.
    """
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute(
            "DELETE FROM chat_conversations WHERE id = %s AND username = %s",
            (conversation_id, username),
        )
        removed = c.rowcount > 0
        if removed:
            c.execute("DELETE FROM chat_messages WHERE conversation_id = %s", (conversation_id,))
            c.execute("DELETE FROM chat_uploads WHERE conversation_id = %s", (conversation_id,))
        conn.commit()
        return removed
    finally:
        conn.close()


def prune_conversations(env: str, username: str, keep: Optional[int] = None) -> int:
    """Drop all but this user's most recent conversations. Returns how many went."""
    limit = keep if keep is not None else _keep_per_user()
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT id FROM chat_conversations
            WHERE username = %s ORDER BY updated_at DESC OFFSET %s
            """,
            (username, limit),
        )
        stale = [row[0] for row in c.fetchall()]
        if not stale:
            return 0
        c.execute("DELETE FROM chat_messages WHERE conversation_id = ANY(%s)", (stale,))
        c.execute("DELETE FROM chat_uploads WHERE conversation_id = ANY(%s)", (stale,))
        c.execute("DELETE FROM chat_conversations WHERE id = ANY(%s)", (stale,))
        conn.commit()
        return len(stale)
    finally:
        conn.close()
