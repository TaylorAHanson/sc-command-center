"""Storage for files a user attaches to the assistant.

Everything lives in `chat_uploads` rows: the original bytes, the normalized form
(a zip of Parquet, one member per sheet — see `file_extract`), extracted document
text, and a small JSON profile. Postgres is the only durable store the app has,
and unlike a Unity Catalog Volume it needs nothing from the caller's workspace
permissions, which matters because plenty of users have app access and no
workspace access at all.

Two consequences shape this module:

  * The app runs multiple uvicorn workers, so an upload cannot be held in memory
    on the worker that received it — every tool call re-reads from Postgres. The
    per-process cache here is therefore a pure read-through cache of derived
    bytes, safe to be cold, stale-proof because rows are immutable once parsed.
  * Re-reading must be cheap, since one question can turn into several tool
    calls. That is what the Parquet normalization buys: a 20 MB spreadsheet is
    parsed by openpyxl exactly once, at upload time.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from services import file_extract

logger = logging.getLogger(__name__)

STATUS_PARSING = "parsing"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

# Files this size are already awkward as a Postgres row and slow to push through
# the Apps front door; the agent works from a profile and tools rather than raw
# content anyway, so a bigger ceiling would buy very little.
DEFAULT_MAX_MB = 25

# Enough for a conversation to compare a few files without any single turn
# carrying an unbounded number of prompt cards.
MAX_PER_CONVERSATION = 5


def max_upload_bytes() -> int:
    try:
        mb = int(os.environ.get("CHAT_MAX_UPLOAD_MB", "") or DEFAULT_MAX_MB)
    except ValueError:
        mb = DEFAULT_MAX_MB
    return max(1, mb) * 1024 * 1024


def max_per_conversation() -> int:
    try:
        return max(1, int(os.environ.get("CHAT_MAX_ATTACHMENTS", "") or MAX_PER_CONVERSATION))
    except ValueError:
        return MAX_PER_CONVERSATION


class UploadError(Exception):
    """A problem the user can act on (wrong type, too big, not theirs)."""


def _conn(env: str):
    from database import get_db_connection

    return get_db_connection(env)


def _binary(data: bytes):
    import psycopg2

    return psycopg2.Binary(data)


def _as_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    return bytes(value) if isinstance(value, memoryview) else bytes(value)


# ------------------------------------------------------------- derived cache

# Keyed by (env, upload_id, what). Values are immutable derived data — a row's
# parsed bytes never change after extraction — so entries only ever need evicting
# for space, and a cold cache is merely slower.
_CACHE_TTL = 900.0
_CACHE_MAX_ENTRIES = 8
_cache_lock = threading.Lock()
_cache: Dict[Tuple[str, str, str], Tuple[float, Any]] = {}


def _cache_get(key: Tuple[str, str, str]) -> Any:
    with _cache_lock:
        hit = _cache.get(key)
        if not hit:
            return None
        stamp, value = hit
        if time.monotonic() - stamp > _CACHE_TTL:
            _cache.pop(key, None)
            return None
        return value


def _cache_put(key: Tuple[str, str, str], value: Any) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            oldest = min(_cache.items(), key=lambda kv: kv[1][0])[0]
            _cache.pop(oldest, None)
        _cache[key] = (time.monotonic(), value)


def _cache_drop(env: str, upload_id: str) -> None:
    with _cache_lock:
        for key in [k for k in _cache if k[0] == env and k[1] == upload_id]:
            _cache.pop(key, None)


# --------------------------------------------------------------------- write

def create_upload(env: str, username: str, filename: str, data: bytes, *,
                  mime: str = "", conversation_id: str = "") -> Dict[str, Any]:
    """Store the bytes and return the row, still `parsing`.

    Validation happens before the write so a rejected file never occupies a row.
    """
    if not data:
        raise UploadError("That file is empty.")
    ceiling = max_upload_bytes()
    if len(data) > ceiling:
        raise UploadError(
            f"That file is {len(data) / 1_048_576:.1f} MB; the limit is {ceiling // 1_048_576} MB."
        )
    try:
        kind = file_extract.sniff_kind(filename, mime)
    except file_extract.UnsupportedFile as exc:
        raise UploadError(str(exc)) from exc

    if conversation_id:
        existing = list_uploads(env, username, conversation_id)
        if len(existing) >= max_per_conversation():
            raise UploadError(
                f"This conversation already has {len(existing)} files attached "
                f"(limit {max_per_conversation()}). Remove one first."
            )

    upload_id = "up-" + uuid.uuid4().hex[:16]
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO chat_uploads
                (id, conversation_id, username, filename, mime, size_bytes, kind, status, raw)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (upload_id, conversation_id or "", username, filename, mime or "",
             len(data), kind, STATUS_PARSING, _binary(data)),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "id": upload_id, "filename": filename, "kind": kind, "mime": mime or "",
        "size_bytes": len(data), "status": STATUS_PARSING, "conversation_id": conversation_id or "",
    }


def parse_upload(env: str, upload_id: str) -> Dict[str, Any]:
    """Extract an upload's content and profile. Safe to run in a background task.

    Images skip extraction entirely: they are handed to the model natively, so
    there is nothing to pull out of them here.
    """
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute("SELECT filename, mime, kind, raw FROM chat_uploads WHERE id = %s", (upload_id,))
        row = c.fetchone()
    finally:
        conn.close()
    if row is None:
        return {"status": STATUS_FAILED, "error": "Upload not found."}

    filename, mime, kind, raw = row[0], row[1] or "", row[2] or "", _as_bytes(row[3])

    if kind == file_extract.KIND_IMAGE:
        _finish(env, upload_id, kind=kind, profile={}, tables=None, text="", warnings=[])
        return {"status": STATUS_READY, "kind": kind}

    try:
        result = file_extract.extract(filename, raw, mime)
    except file_extract.UnsupportedFile as exc:
        _fail(env, upload_id, str(exc))
        return {"status": STATUS_FAILED, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("extraction failed for upload %s (%s)", upload_id, filename)
        _fail(env, upload_id, f"Could not read that file: {exc}")
        return {"status": STATUS_FAILED, "error": str(exc)}

    _finish(env, upload_id, kind=result.kind, profile=result.profile,
            tables=result.tables, text=result.text, warnings=result.warnings)
    return {"status": STATUS_READY, "kind": result.kind, "warnings": result.warnings}


def _finish(env: str, upload_id: str, *, kind: str, profile: Dict[str, Any],
            tables: Optional[bytes], text: str, warnings: List[str]) -> None:
    import json

    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute(
            """
            UPDATE chat_uploads
            SET status = %s, kind = %s, profile_json = %s, warnings_json = %s,
                parsed = %s, text_content = %s, error = ''
            WHERE id = %s
            """,
            (STATUS_READY, kind, json.dumps(profile or {}), json.dumps(warnings or []),
             _binary(tables) if tables else None, text or "", upload_id),
        )
        conn.commit()
    finally:
        conn.close()
    _cache_drop(env, upload_id)


def _fail(env: str, upload_id: str, error: str) -> None:
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE chat_uploads SET status = %s, error = %s WHERE id = %s",
            (STATUS_FAILED, error[:2000], upload_id),
        )
        conn.commit()
    finally:
        conn.close()


def attach_to_conversation(env: str, username: str, upload_ids: List[str], conversation_id: str) -> None:
    """Bind uploads to a conversation once it has an id to bind them to."""
    ids = [i for i in (upload_ids or []) if i]
    if not ids or not conversation_id:
        return
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute(
            """
            UPDATE chat_uploads SET conversation_id = %s
            WHERE id = ANY(%s) AND username = %s AND COALESCE(conversation_id, '') = ''
            """,
            (conversation_id, ids, username),
        )
        conn.commit()
    finally:
        conn.close()


def delete_upload(env: str, username: str, upload_id: str) -> bool:
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute("DELETE FROM chat_uploads WHERE id = %s AND username = %s", (upload_id, username))
        removed = c.rowcount > 0
        conn.commit()
    finally:
        conn.close()
    if removed:
        _cache_drop(env, upload_id)
    return removed


# ---------------------------------------------------------------------- read

_META_COLUMNS = "id, conversation_id, username, filename, mime, size_bytes, kind, status, error, profile_json, warnings_json, created_at"


def _meta_row(row: Tuple[Any, ...]) -> Dict[str, Any]:
    import json

    try:
        profile = json.loads(row[9] or "{}")
    except (TypeError, ValueError):
        profile = {}
    try:
        warnings = json.loads(row[10] or "[]")
    except (TypeError, ValueError):
        warnings = []
    return {
        "id": row[0], "conversation_id": row[1] or "", "username": row[2] or "",
        "filename": row[3], "mime": row[4] or "", "size_bytes": int(row[5] or 0),
        "kind": row[6] or "", "status": row[7] or "", "error": row[8] or "",
        "profile": profile if isinstance(profile, dict) else {},
        "warnings": warnings if isinstance(warnings, list) else [],
        "created_at": row[11].isoformat() if row[11] else None,
    }


def get_upload(env: str, upload_id: str, username: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Metadata and profile for one upload, without its bytes.

    Passing `username` enforces ownership; the runtime omits it because it has
    already resolved the attachment list through the conversation.
    """
    conn = _conn(env)
    try:
        c = conn.cursor()
        if username is None:
            c.execute(f"SELECT {_META_COLUMNS} FROM chat_uploads WHERE id = %s", (upload_id,))
        else:
            c.execute(
                f"SELECT {_META_COLUMNS} FROM chat_uploads WHERE id = %s AND username = %s",
                (upload_id, username),
            )
        row = c.fetchone()
        return _meta_row(row) if row else None
    finally:
        conn.close()


def ui_summary(meta: Dict[str, Any]) -> str:
    """One line for the file chip in the composer."""
    profile = meta.get("profile") or {}
    kind = meta.get("kind") or ""
    if kind == "table":
        sheets = profile.get("sheets") or []
        primary = next((s for s in sheets if s.get("name") == profile.get("primary_sheet")), None) or (sheets[0] if sheets else {})
        rows = int(primary.get("rows") or 0)
        columns = len(primary.get("columns") or [])
        label = f"{rows:,} rows x {columns} columns"
        return label + (f", {len(sheets)} sheets" if len(sheets) > 1 else "")
    if kind == "document":
        pages = profile.get("pages")
        words = int(profile.get("words") or 0)
        return (f"{pages} pages, " if pages else "") + f"{words:,} words"
    if kind == "data":
        return f"JSON {profile.get('json_kind') or 'document'}"
    if kind == "image":
        return "image"
    return ""


def public_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    """What the drawer is told about a file.

    Lives here rather than in a route because two of them serve it: uploading a
    file, and restoring a conversation that already has files on it. Shaping it in
    only one of those is how a restored chip lost its "5,000 rows x 6 columns".
    """
    return {
        "id": meta["id"],
        "filename": meta["filename"],
        "kind": meta["kind"],
        "status": meta["status"],
        "size_bytes": meta["size_bytes"],
        "error": meta.get("error") or "",
        "warnings": meta.get("warnings") or [],
        "summary": ui_summary(meta),
        "conversation_id": meta.get("conversation_id") or "",
    }


def fetch_uploads(c, username: str, conversation_id: str) -> List[Dict[str, Any]]:
    """Files on a conversation, read through a cursor the caller already has.

    Lets a caller that is already talking to the database (restoring a
    conversation, say) avoid paying for a second connection.
    """
    c.execute(
        f"""
        SELECT {_META_COLUMNS} FROM chat_uploads
        WHERE username = %s AND conversation_id = %s ORDER BY created_at
        """,
        (username, conversation_id),
    )
    return [_meta_row(row) for row in c.fetchall()]


def list_uploads(env: str, username: str, conversation_id: str) -> List[Dict[str, Any]]:
    conn = _conn(env)
    try:
        return fetch_uploads(conn.cursor(), username, conversation_id)
    finally:
        conn.close()


def resolve_attachments(env: str, upload_ids: List[str], username: Optional[str] = None) -> List[Dict[str, Any]]:
    """Ready uploads for the ids given, in the order asked for.

    Anything still parsing, failed, or belonging to someone else is dropped: the
    agent is better off not being told about a file it cannot read.
    """
    ids = [i for i in (upload_ids or []) if i]
    if not ids:
        return []
    found: Dict[str, Dict[str, Any]] = {}
    for upload_id in ids:
        meta = get_upload(env, upload_id, username)
        if meta and meta["status"] == STATUS_READY:
            found[upload_id] = meta
    return [found[i] for i in ids if i in found]


def load_tables_archive(env: str, upload_id: str) -> bytes:
    key = (env, upload_id, "parsed")
    cached = _cache_get(key)
    if cached is not None:
        return cached
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute("SELECT parsed FROM chat_uploads WHERE id = %s", (upload_id,))
        row = c.fetchone()
    finally:
        conn.close()
    data = _as_bytes(row[0]) if row else b""
    _cache_put(key, data)
    return data


def load_table(env: str, upload_id: str, sheet: Optional[str] = None):
    """A DataFrame for one sheet of a tabular upload."""
    archive = load_tables_archive(env, upload_id)
    if not archive:
        raise UploadError("That file has no table data to query.")
    key = (env, upload_id, f"df:{sheet or ''}")
    cached = _cache_get(key)
    if cached is not None:
        return cached
    frame = file_extract.load_table(archive, sheet)
    _cache_put(key, frame)
    return frame


def sheet_names(env: str, upload_id: str) -> List[str]:
    archive = load_tables_archive(env, upload_id)
    return file_extract.sheet_names(archive) if archive else []


def load_text(env: str, upload_id: str) -> str:
    key = (env, upload_id, "text")
    cached = _cache_get(key)
    if cached is not None:
        return cached
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute("SELECT text_content FROM chat_uploads WHERE id = %s", (upload_id,))
        row = c.fetchone()
    finally:
        conn.close()
    text = (row[0] or "") if row else ""
    _cache_put(key, text)
    return text


def load_raw(env: str, upload_id: str) -> bytes:
    """Original bytes, for handing images and PDFs to the model natively.

    Deliberately not cached: this is only read while assembling a request, and
    caching whole originals would crowd out the derived data that is read
    repeatedly.
    """
    conn = _conn(env)
    try:
        c = conn.cursor()
        c.execute("SELECT raw FROM chat_uploads WHERE id = %s", (upload_id,))
        row = c.fetchone()
    finally:
        conn.close()
    return _as_bytes(row[0]) if row else b""
