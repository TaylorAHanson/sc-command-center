"""Drafts and published versions for views, widgets and agents, as dashboards have.

Each object has at most one **draft** — the working copy its managers edit,
saved in place — and any number of **published versions**, the rows of its
versioned table (`dashboard_views`, `widgets`, `agent_profiles`). Publishing
inserts the next version from the draft and drops the draft; people who can only
use an object always read its newest published version, so nothing a manager is
halfway through reaches them.

The draft is a row in `object_drafts` holding the versioned row's columns as
JSON, not an unpublished version in the versioned table. Code from before drafts
reads the newest version as live, so a draft stored as a version would be shown
to everyone on a rollback; kept apart, a rollback simply doesn't see it. It also
stopped every save from becoming a version, which is what grew the widget
library without bound and what personal views' save-coalescing worked around.

Functions take a cursor on the content store and leave committing to the caller,
so a route can check, write and commit in one transaction.
"""
from __future__ import annotations

import datetime
import decimal
import json
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException
from psycopg2.extras import Json

APP, WIDGET, AGENT = "app", "widget", "agent"
TABLES = {APP: "dashboard_views", WIDGET: "widgets", AGENT: "agent_profiles"}
#: Tables that retire rows by flag rather than deleting them.
_DEPRECATES = {WIDGET, AGENT}

DRAFT_ONLY, PUBLISHED, PUBLISHED_WITH_DRAFT = "draft_only", "published", "published_with_draft"

#: Never part of a draft: identity, and what publishing itself stamps.
NOT_PAYLOAD = frozenset({"id", "version", "timestamp", "published_by", "published_at"})
#: Reset on every new version, because they describe a version rather than the work.
#: Certification is a review of particular code; a new version hasn't had one.
RESET_ON_PUBLISH = {WIDGET: {"is_certified": 0, "is_deprecated": 0}, AGENT: {"is_deprecated": 0}}

_KEEP = object()


def _table(object_type: str) -> str:
    try:
        return TABLES[object_type]
    except KeyError:
        raise HTTPException(status_code=400, detail="Unknown kind of object.")


def _rows(c) -> List[Dict[str, Any]]:
    names = [d[0] for d in c.description]
    return [dict(r) if hasattr(r, "keys") else dict(zip(names, r)) for r in c.fetchall()]


def _one(c) -> Optional[Dict[str, Any]]:
    rows = _rows(c)
    return rows[0] if rows else None


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", "replace")
    return value


def payload_of(row: Dict[str, Any]) -> Dict[str, Any]:
    """A versioned row as a draft payload."""
    return {k: _jsonable(v) for k, v in (row or {}).items() if k not in NOT_PAYLOAD and not k.startswith("_")}


def state_of(has_draft: bool, published_version: Optional[int]) -> str:
    if not published_version:
        return DRAFT_ONLY
    return PUBLISHED_WITH_DRAFT if has_draft else PUBLISHED


def merge(latest: Optional[Dict[str, Any]], draft: Optional[Dict[str, Any]], object_id: str) -> Optional[Dict[str, Any]]:
    """What a manager sees: the draft over the newest published row, flagged as a draft."""
    if draft is None:
        return dict(latest) if latest else None
    merged = dict(latest or {})
    merged.update(draft.get("payload") or {})
    merged["id"] = object_id
    merged["version"] = (latest or {}).get("version") or 0
    merged["is_draft"] = True
    merged["base_version"] = draft.get("base_version")
    merged["draft_updated_by"] = draft.get("updated_by")
    merged["draft_updated_at"] = _jsonable(draft.get("updated_at"))
    return merged


def insert_columns(object_type: str, payload: Dict[str, Any], table_columns: Iterable[str]) -> Dict[str, Any]:
    """The columns a publish writes: the payload, limited to what the table has, with per-version fields reset."""
    allowed = set(table_columns) - NOT_PAYLOAD
    values = {k: v for k, v in (payload or {}).items() if k in allowed}
    for k, v in RESET_ON_PUBLISH.get(object_type, {}).items():
        if k in allowed:
            values[k] = v
    return values


_columns_cache: Dict[str, List[str]] = {}


def table_columns(c, object_type: str) -> List[str]:
    table = _table(object_type)
    if table not in _columns_cache:
        c.execute(f"SELECT * FROM {table} LIMIT 0")
        _columns_cache[table] = [d[0] for d in c.description]
    return _columns_cache[table]


# --------------------------------------------------------------------- reads

def read(c, object_type: str, object_id: str) -> Optional[Dict[str, Any]]:
    _table(object_type)
    c.execute(
        "SELECT payload, base_version, updated_by, updated_at FROM object_drafts "
        "WHERE object_type = %s AND object_id = %s",
        (object_type, object_id),
    )
    row = _one(c)
    if row is not None and isinstance(row.get("payload"), str):
        row["payload"] = json.loads(row["payload"])
    return row


def drafts(c, object_type: str, ids: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, Any]]:
    _table(object_type)
    sql = ("SELECT object_id, payload, base_version, updated_by, updated_at FROM object_drafts "
           "WHERE object_type = %s")
    params: list = [object_type]
    if ids is not None:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        sql += " AND object_id = ANY(%s)"
        params.append(ids)
    c.execute(sql, params)
    out = {}
    for row in _rows(c):
        if isinstance(row.get("payload"), str):
            row["payload"] = json.loads(row["payload"])
        out[row.pop("object_id")] = row
    return out


def latest(c, object_type: str, object_id: str) -> Optional[Dict[str, Any]]:
    """The newest published version, or None if it has never been published (or was retired)."""
    table = _table(object_type)
    live = " AND COALESCE(is_deprecated, 0) = 0" if object_type in _DEPRECATES else ""
    c.execute(f"SELECT * FROM {table} WHERE id = %s{live} ORDER BY version DESC LIMIT 1", (object_id,))
    return _one(c)


def published_version(c, object_type: str, object_id: str) -> Optional[int]:
    row = latest(c, object_type, object_id)
    return int(row["version"]) if row else None


def current(c, object_type: str, object_id: str, level: Optional[str]) -> Optional[Dict[str, Any]]:
    """What this caller should see: the draft (merged) for MANAGE, the published row for USE."""
    pub = latest(c, object_type, object_id)
    if level == "MANAGE":
        return merge(pub, read(c, object_type, object_id), object_id)
    return dict(pub) if pub else None


def exists(c, object_type: str, object_id: str) -> bool:
    return latest(c, object_type, object_id) is not None or read(c, object_type, object_id) is not None


# --------------------------------------------------------------------- writes

def save(c, object_type: str, object_id: str, payload: Dict[str, Any], username: str,
         base_version: Any = _KEEP) -> None:
    """Write the draft in place. A new draft starts from the newest published version."""
    _table(object_type)
    clean = {k: _jsonable(v) for k, v in (payload or {}).items() if k not in NOT_PAYLOAD}
    if base_version is _KEEP:
        held = read(c, object_type, object_id)
        base_version = held["base_version"] if held else published_version(c, object_type, object_id)
    c.execute(
        """
        INSERT INTO object_drafts (object_type, object_id, payload, base_version, updated_by, updated_at)
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (object_type, object_id) DO UPDATE
           SET payload = EXCLUDED.payload, base_version = EXCLUDED.base_version,
               updated_by = EXCLUDED.updated_by, updated_at = CURRENT_TIMESTAMP
        """,
        (object_type, object_id, Json(clean, dumps=lambda v: json.dumps(v, default=str)), base_version, username),
    )


def discard(c, object_type: str, object_id: str) -> bool:
    _table(object_type)
    c.execute("DELETE FROM object_drafts WHERE object_type = %s AND object_id = %s", (object_type, object_id))
    return c.rowcount > 0


def publish(c, object_type: str, object_id: str, username: str) -> int:
    """Insert the next published version from the draft and drop the draft. 409 if there is none."""
    table = _table(object_type)
    draft = read(c, object_type, object_id)
    if draft is None:
        raise HTTPException(status_code=409, detail="There are no unpublished changes to publish.")
    c.execute(f"SELECT COALESCE(MAX(version), 0) AS v FROM {table} WHERE id = %s", (object_id,))
    row = _one(c)
    version = int((row or {}).get("v") or 0) + 1
    values = insert_columns(object_type, draft["payload"], table_columns(c, object_type))
    columns = ["id", "version", *values.keys(), "published_by", "published_at"]
    placeholders = ", ".join(["%s"] * (len(columns) - 1) + ["CURRENT_TIMESTAMP"])
    c.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [object_id, version, *values.values(), username],
    )
    discard(c, object_type, object_id)
    return version


def revert(c, object_type: str, object_id: str, version: int, username: str) -> None:
    """Make a published version the draft, to be published again (or not)."""
    table = _table(object_type)
    c.execute(f"SELECT * FROM {table} WHERE id = %s AND version = %s", (object_id, version))
    row = _one(c)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Version {version} was not found.")
    save(c, object_type, object_id, payload_of(row), username,
         base_version=published_version(c, object_type, object_id))
