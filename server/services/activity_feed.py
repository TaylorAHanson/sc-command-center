"""What the Admin Panel's Activity tab reads, and how long its log is kept.

Two sources in the content schema, read as one feed, newest first:

- `activity_events`, written by `services/activity.py` wherever something
  happens (the verbs are listed in server/AGENTS.md);
- `action_logs`, the widget actions people approved, shown as `widget.action`
  with the widget's and the action's names. The explanation the person typed
  stays in the Action Logs tab: this feed is metadata only.

Pages are keyset, not offset: events keep arriving at the top while an
administrator reads, and an offset would shift under them and repeat rows. The
cursor is the last row shown, as (time, source, id). Each source is read past it
on its own and the two are merged here, so no UNION has to reconcile a
TIMESTAMPTZ with `action_logs.timestamp`, which has no zone. That column is read
`::timestamptz`, which Postgres converts in the session's zone, the zone
`CURRENT_TIMESTAMP` wrote it in, so both sources sort on one clock.

Who is active comes from `known_principals` in the settings schema.
`access.caller` refreshes a person's row at most every ten minutes per worker,
so "active in the last 15 minutes" is accurate to about that.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from services.activity import clean_detail

logger = logging.getLogger(__name__)

EVENT, ACTION = "event", "action"
# Where an event and an action share an instant, the event sorts first; any
# fixed order would do, as long as the cursor can name a single row.
_RANK = {ACTION: 0, EVENT: 1}
ACTION_VERB = "widget.action"
_TABLES = {"app": "dashboard_views", "widget": "widgets", "agent": "agent_profiles"}

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
ACTIVE_MINUTES = 15
MAX_ACTIVE = 100
TOP_OBJECTS = 8

PURGE_EVERY_SECONDS = 3600
PURGE_BATCH = 5000
# Per run. The backlog left by first turning retention on clears over a few
# hourly runs instead of one long delete on the table every chat turn writes to.
PURGE_MAX_BATCHES = 40

_TERM = re.compile(r"^(\*|[a-z0-9_]+)(\.(\*|[a-z0-9_]+))*$")
_MAX_TERMS = 12
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Filters:
    person: str = ""
    verbs: Tuple[str, ...] = ()
    object_type: str = ""
    object_id: str = ""
    since: Optional[datetime] = None
    until: Optional[datetime] = None


@dataclass(frozen=True)
class Cursor:
    at: datetime
    source: str
    id: int


# ------------------------------------------------------------------ parsing

def parse_verbs(raw: Optional[str]) -> Tuple[str, ...]:
    """Comma-separated verb patterns; `*` stands for any run of characters.

    `view.*` is everything done to views, `*.publish` every publish. Raises
    ValueError for anything else, so a typo is a 400 rather than an empty feed.
    """
    terms = tuple(dict.fromkeys(t.strip().lower() for t in (raw or "").split(",") if t.strip()))
    if len(terms) > _MAX_TERMS:
        raise ValueError(f"Filter on at most {_MAX_TERMS} kinds of event at once.")
    for term in terms:
        if not _TERM.match(term):
            raise ValueError(f"'{term}' isn't an event kind, such as view.publish or *.share.")
    return terms


def parse_time(raw: Optional[str]) -> Optional[datetime]:
    """An ISO time from the filter; one without a zone is taken as UTC."""
    if not raw or not raw.strip():
        return None
    try:
        return _aware(datetime.fromisoformat(raw.strip()))
    except ValueError as e:
        raise ValueError(f"'{raw}' isn't a date and time.") from e


def encode_cursor(cursor: Cursor) -> str:
    raw = f"{cursor.at.isoformat()}|{cursor.source}|{cursor.id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(token: Optional[str]) -> Optional[Cursor]:
    if not token:
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        at, source, row_id = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8").split("|")
        if source not in _RANK:
            raise ValueError(source)
        return Cursor(_aware(datetime.fromisoformat(at)), source, int(row_id))
    except (ValueError, binascii.Error, UnicodeError) as e:
        raise ValueError("That page of activity can't be found; start again from the newest.") from e


def _aware(value: Optional[datetime]) -> datetime:
    if value is None:
        return _EPOCH
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def verb_matches(terms: Sequence[str], verb: str) -> bool:
    """The Python reading of the LIKE patterns `events_query` sends."""
    if not terms:
        return True
    return any(re.fullmatch(re.escape(t).replace(r"\*", ".*"), verb) for t in terms)


def _like(term: str) -> str:
    # `_` is a LIKE wildcard and verbs may contain it, so it is escaped; `*` is ours.
    return term.replace("_", r"\_").replace("*", "%")


# ------------------------------------------------------------------ queries

def _keyset(where: List[str], params: List[Any], cursor: Optional[Cursor], source: str,
            time_col: str, id_col: str) -> None:
    """Rows of `source` that sort after `cursor` in (time, source rank, id) descending."""
    if cursor is None:
        return
    if _RANK[source] < _RANK[cursor.source]:
        where.append(f"{time_col} <= %s")
        params.append(cursor.at)
    elif _RANK[source] > _RANK[cursor.source]:
        where.append(f"{time_col} < %s")
        params.append(cursor.at)
    else:
        where.append(f"({time_col} < %s OR ({time_col} = %s AND {id_col} < %s))")
        params += [cursor.at, cursor.at, cursor.id]


def _where(where: List[str]) -> str:
    return (" WHERE " + " AND ".join(where)) if where else ""


def events_query(f: Filters, cursor: Optional[Cursor], limit: int) -> Tuple[str, List[Any]]:
    where: List[str] = []
    params: List[Any] = []
    if f.person:
        where.append("LOWER(username) = LOWER(%s)")
        params.append(f.person)
    if f.verbs:
        where.append("(" + " OR ".join(["verb LIKE %s"] * len(f.verbs)) + ")")
        params += [_like(t) for t in f.verbs]
    if f.object_type:
        where.append("object_type = %s")
        params.append(f.object_type)
    if f.object_id:
        where.append("object_id = %s")
        params.append(f.object_id)
    if f.since:
        where.append("at >= %s")
        params.append(f.since)
    if f.until:
        where.append("at < %s")
        params.append(f.until)
    _keyset(where, params, cursor, EVENT, "at", "id")
    sql = ("SELECT id, at, username, verb, object_type, object_id, detail FROM activity_events"
           + _where(where) + " ORDER BY at DESC, id DESC LIMIT %s")
    return sql, params + [limit]


def actions_query(f: Filters, cursor: Optional[Cursor], limit: int) -> Optional[Tuple[str, List[Any]]]:
    """The approved widget actions the filters allow, or None when they rule all of them out."""
    if f.object_type not in ("", "widget") or not verb_matches(f.verbs, ACTION_VERB):
        return None
    # A row with no time can't be placed in the feed, and would defeat the cursor.
    where: List[str] = ["a.timestamp IS NOT NULL"]
    params: List[Any] = []
    if f.person:
        where.append("LOWER(a.username) = LOWER(%s)")
        params.append(f.person)
    if f.object_id:
        where.append("a.widget_id = %s")
        params.append(f.object_id)
    if f.since:
        where.append("a.timestamp >= %s")
        params.append(f.since)
    if f.until:
        where.append("a.timestamp < %s")
        params.append(f.until)
    _keyset(where, params, cursor, ACTION, "a.timestamp", "a.id")
    sql = ("SELECT a.id, a.timestamp::timestamptz AS at, a.username, a.widget_id, a.widget_name, a.action_name"
           " FROM action_logs a" + _where(where) + " ORDER BY a.timestamp DESC, a.id DESC LIMIT %s")
    return sql, params + [limit]


# ------------------------------------------------------------------ merging

def _rows(c) -> List[Dict[str, Any]]:
    names = [d[0] for d in c.description or ()]
    return [dict(r) if hasattr(r, "keys") else dict(zip(names, r)) for r in c.fetchall()]


def event_row(r: Dict[str, Any]) -> Dict[str, Any]:
    detail = r.get("detail")
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except ValueError:
            detail = {}
    return {
        "source": EVENT, "id": int(r["id"]), "at": _aware(r.get("at")),
        "username": r.get("username") or "unknown", "verb": r.get("verb") or "",
        "object_type": r.get("object_type"), "object_id": r.get("object_id"),
        "detail": detail if isinstance(detail, dict) else {},
    }


def action_row(r: Dict[str, Any]) -> Dict[str, Any]:
    widget_id = r.get("widget_id") or None
    return {
        "source": ACTION, "id": int(r["id"]), "at": _aware(r.get("at")),
        "username": r.get("username") or "unknown", "verb": ACTION_VERB,
        "object_type": "widget" if widget_id else None, "object_id": widget_id,
        "detail": clean_detail({"widget_name": r.get("widget_name"), "action_name": r.get("action_name")}),
    }


def _sort_key(row: Dict[str, Any]) -> Tuple[datetime, int, int]:
    return row["at"], _RANK[row["source"]], row["id"]


def merge(events: Iterable[Dict[str, Any]], actions: Iterable[Dict[str, Any]],
          limit: int) -> Tuple[List[Dict[str, Any]], Optional[Cursor]]:
    """One page from both sources, each read `limit + 1` past the cursor, and the next cursor.

    Every row of the true page is among the first `limit` of its own source, so
    reading one more than a page from each is enough; anything left over means
    there is another page.
    """
    rows = sorted([*events, *actions], key=_sort_key, reverse=True)
    page = rows[:limit]
    if len(rows) <= limit or not page:
        return page, None
    last = page[-1]
    return page, Cursor(last["at"], last["source"], last["id"])


def describe_objects(c, refs: Iterable[Tuple[Optional[str], Optional[str]]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """The current name and state of each view, widget or agent named in some events.

    State is `published`, `draft` (never published), `archived` (views only) or
    `deleted`, so the tab can link only to what can still be opened.
    """
    wanted: Dict[str, List[str]] = {}
    for object_type, object_id in refs:
        if object_type in _TABLES and object_id:
            ids = wanted.setdefault(object_type, [])
            if object_id not in ids:
                ids.append(object_id)
    if not wanted:
        return {}
    c.execute(
        "SELECT object_type, object_id, payload->>'name' AS name FROM object_drafts"
        " WHERE object_type = ANY(%s) AND object_id = ANY(%s)",
        (sorted(wanted), sorted({i for ids in wanted.values() for i in ids})),
    )
    pending = {(r["object_type"], r["object_id"]): r.get("name") or "" for r in _rows(c)}
    archived: set = set()
    if "app" in wanted:
        c.execute("SELECT id FROM archived_views WHERE id = ANY(%s)", (wanted["app"],))
        archived = {r["id"] for r in _rows(c)}
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for object_type, ids in wanted.items():
        retired = "" if object_type == "app" else ", COALESCE(is_deprecated, 0) AS retired"
        c.execute(
            f"SELECT DISTINCT ON (id) id, name{retired} FROM {_TABLES[object_type]}"
            " WHERE id = ANY(%s) ORDER BY id, version DESC",
            (ids,),
        )
        published = {r["id"]: r for r in _rows(c)}
        for object_id in ids:
            pub = published.get(object_id)
            draft = pending.get((object_type, object_id))
            if pub is not None and pub.get("retired"):
                state = "deleted"
            elif object_type == "app" and object_id in archived:
                state = "archived"
            elif pub is not None:
                state = "published"
            elif draft is not None:
                state = "draft"
            else:
                state = "deleted"
            out[(object_type, object_id)] = {"name": draft or (pub or {}).get("name") or None, "state": state}
    return out


def public_row(row: Dict[str, Any], names: Dict[Tuple[str, str], Dict[str, Any]]) -> Dict[str, Any]:
    info = names.get((row["object_type"], row["object_id"])) or {}
    return {
        "key": f"{row['source']}:{row['id']}",
        "source": row["source"],
        "at": row["at"].isoformat(),
        "username": row["username"],
        "verb": row["verb"],
        "object_type": row["object_type"],
        "object_id": row["object_id"],
        "object_name": info.get("name"),
        "object_state": info.get("state"),
        "detail": row["detail"],
    }


def read_page(c, f: Filters, cursor: Optional[Cursor], limit: int) -> Dict[str, Any]:
    sql, params = events_query(f, cursor, limit + 1)
    c.execute(sql, params)
    events = [event_row(r) for r in _rows(c)]
    actions: List[Dict[str, Any]] = []
    query = actions_query(f, cursor, limit + 1)
    if query is not None:
        c.execute(*query)
        actions = [action_row(r) for r in _rows(c)]
    page, after = merge(events, actions, limit)
    names = describe_objects(c, [(r["object_type"], r["object_id"]) for r in page])
    return {"events": [public_row(r, names) for r in page], "next_cursor": encode_cursor(after) if after else None}


# ------------------------------------------------------------------ people

ACTIVE_SQL = (
    "SELECT principal AS username, last_seen FROM known_principals"
    " WHERE principal_type = 'user' AND last_seen >= LOCALTIMESTAMP - make_interval(mins => %s)"
    " ORDER BY last_seen DESC LIMIT %s"
)


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def active_now(c, minutes: int = ACTIVE_MINUTES, limit: int = MAX_ACTIVE) -> List[Dict[str, Any]]:
    """People seen in the last `minutes`, most recent first. Settings schema."""
    from services.caller_identity import is_application_id

    c.execute(ACTIVE_SQL, (minutes, limit))
    # A local run signs in as the app's service principal, which is not a person.
    return [{"username": r["username"], "last_seen": _iso(r.get("last_seen"))}
            for r in _rows(c) if not is_application_id(r["username"])]


def last_seen(c, username: str) -> Optional[str]:
    c.execute(
        "SELECT last_seen FROM known_principals WHERE principal_type = 'user' AND LOWER(principal) = LOWER(%s)",
        (username,),
    )
    rows = _rows(c)
    return _iso(rows[0].get("last_seen")) if rows else None


def person_summary(c, username: str, days: int) -> Dict[str, Any]:
    """What one person did in the last `days`: counts by kind, and what they worked on most."""
    c.execute(
        "SELECT verb, COUNT(*) AS n, MAX(at) AS last_at FROM activity_events"
        " WHERE LOWER(username) = LOWER(%s) AND at >= now() - make_interval(days => %s)"
        " GROUP BY verb ORDER BY n DESC, verb",
        (username, days),
    )
    verbs = [{"verb": r["verb"], "count": int(r["n"]), "last_at": _iso(r.get("last_at"))} for r in _rows(c)]
    c.execute(
        "SELECT COUNT(*) AS n, MAX(a.timestamp::timestamptz) AS last_at FROM action_logs a"
        " WHERE LOWER(a.username) = LOWER(%s) AND a.timestamp >= now() - make_interval(days => %s)",
        (username, days),
    )
    actions = (_rows(c) or [{}])[0]
    if int(actions.get("n") or 0):
        verbs.append({"verb": ACTION_VERB, "count": int(actions["n"]), "last_at": _iso(actions.get("last_at"))})
        verbs.sort(key=lambda v: (-v["count"], v["verb"]))
    c.execute(
        "SELECT object_type, object_id, COUNT(*) AS n, MAX(at) AS last_at FROM activity_events"
        " WHERE LOWER(username) = LOWER(%s) AND at >= now() - make_interval(days => %s)"
        " AND object_type = ANY(%s) AND object_id IS NOT NULL"
        " GROUP BY object_type, object_id ORDER BY n DESC, last_at DESC LIMIT %s",
        (username, days, sorted(_TABLES), TOP_OBJECTS),
    )
    top = _rows(c)
    names = describe_objects(c, [(r["object_type"], r["object_id"]) for r in top])
    objects = []
    for r in top:
        info = names.get((r["object_type"], r["object_id"])) or {}
        objects.append({
            "object_type": r["object_type"], "object_id": r["object_id"], "count": int(r["n"]),
            "last_at": _iso(r.get("last_at")), "object_name": info.get("name"), "object_state": info.get("state"),
        })
    return {
        "username": username, "days": days, "total": sum(v["count"] for v in verbs),
        "verbs": verbs, "objects": objects,
    }


# ------------------------------------------------------------------ retention

PURGE_SQL = (
    "DELETE FROM activity_events WHERE id IN ("
    "SELECT id FROM activity_events WHERE at < now() - make_interval(days => %s) LIMIT %s)"
)


def purge(conn, days: int, *, batch: int = PURGE_BATCH, max_batches: int = PURGE_MAX_BATCHES) -> int:
    """Delete events older than `days`, one committed batch at a time. Returns how many.

    `activity_events` only: `action_logs` holds what people wrote to justify an
    action, which is a record of its own and not this setting's to expire.
    """
    if days <= 0:
        return 0
    total = 0
    c = conn.cursor()
    for _ in range(max_batches):
        c.execute(PURGE_SQL, (days, batch))
        deleted = max(c.rowcount or 0, 0)
        conn.commit()
        total += deleted
        if deleted < batch:
            break
    return total


def retention_job() -> None:
    """The background job: apply `activity_retention_days`, where 0 keeps everything."""
    from database import get_db_connection
    from services.settings_store import get_int_setting

    days = get_int_setting("activity_retention_days")
    if days <= 0:
        return
    conn = get_db_connection()
    try:
        deleted = purge(conn, days)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if deleted:
        logger.info("Deleted %d activity events older than %d days", deleted, days)
