"""Schedules as rows: what `/api/schedules` reads and writes, and the shape it returns.

The tables are `schedules`, `schedule_runs` and `schedule_reminders`, in the content
schema (`database._create_schedule_tables`). Running them is `services/scheduler.py`;
this module is the fields, their limits, and CRUD.

`owner` is stored the way the token vault keys a person
(`token_vault.normalize_username`), because every run asks the vault for that
person's token. `owner_email` is the address their reports come from (replies go
there), and `owner_groups` the groups they had when they last created, edited,
resumed or ran the schedule: a run has no request to ask SCIM with, and a
run_statement checks the widget it comes from as them.

`clean_fields` is pure and does everything that needs no database or settings, so
the routes' 400s are testable without either.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from services import email_service, recurrence, sql_safety

KINDS = ("email_report", "run_statement")
SEND_WHEN = ("always", "has_rows", "no_rows")
STATUSES = ("active", "paused", "needs_reconnect")
RUN_STATUSES = ("ok", "skipped", "failed", "needs_reconnect")
TRIGGERS = ("schedule", "manual", "recovery")

MAX_NAME_CHARS = 120
# Generous for a hand-written report, and far below what a statement can carry;
# the point is that a schedule isn't a place to park a script.
MAX_SQL_CHARS = 50_000
MAX_REF_CHARS = 200
MAX_RUNS = 100
DEFAULT_RUNS = 20

#: What PATCH may change. `owner`, `kind` and `id` are fixed for a schedule's life.
EDITABLE = ("name", "sql", "source_app_id", "source_widget_instance", "source_widget_id", "view_name",
            "view_link", "recipients", "subject", "message", "send_when", "attach_csv", "recurrence")
FIXED = ("id", "owner", "kind")
#: Fields an admin may change on someone else's schedule. Anything else would let
#: an admin choose what runs under another person's identity, or who receives it.
ADMIN_EDITABLE = ("name", "recurrence")

_COLUMNS = ("id", "owner", "owner_email", "owner_groups", "kind", "name", "sql", "source_app_id",
            "source_widget_instance", "source_widget_id", "view_name", "view_link", "recipients", "subject",
            "message", "send_when", "attach_csv", "recurrence", "next_run_at", "status", "paused_reason",
            "failure_count", "run_requested", "claimed_by", "claimed_until", "created_at", "updated_at")
_RUN_COLUMNS = ("id", "schedule_id", "trigger", "started_at", "finished_at", "status", "row_count", "emailed",
                "error")
COLUMNS_SQL = ", ".join(f"s.{c}" for c in _COLUMNS)
RUN_COLUMNS_SQL = ", ".join(_RUN_COLUMNS)


# --------------------------------------------------------------------- fields

def _text(value: Any, limit: int) -> str:
    return email_service.clean_line(value, limit)


def _ref(value: Any) -> Optional[str]:
    text = _text(value, MAX_REF_CHARS)
    return text or None


def read_only_problem(sql: str) -> Optional[str]:
    """Why `sql` can't be a report's query, or None. Checked at create and every run."""
    kind, verb = sql_safety.classify_statement(sql)
    if kind == "empty":
        return "Add the query the report runs."
    if kind == "write":
        named = f" ('{verb.upper()}')" if verb else ""
        return (f"A scheduled report only runs read-only queries, and this one changes data{named}. "
                "Schedule it as an action from an executable widget instead.")
    return None


def _recipients(value: Any) -> Tuple[Optional[List[str]], Optional[str]]:
    if value is None:
        return [], None
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
        return None, "Recipients must be a list of email addresses."
    good, bad = email_service.parse_recipients(list(value))
    if bad:
        return None, f"Not an email address: {', '.join(bad[:3])}{' and more' if len(bad) > 3 else ''}."
    return good, None


def clean_fields(body: Any, kind: str, *, partial: bool) -> Tuple[Dict[str, Any], Optional[str]]:
    """(fields, None) or ({}, a sentence). `partial` is PATCH: only what `body` names.

    Checks shapes, limits, the recurrence, and that a report's query reads only.
    What needs settings or a database (the recipient policy, the per-person cap,
    whether a widget is executable) is the caller's.
    """
    if not isinstance(body, dict):
        return {}, "Send the schedule as a JSON object."
    if kind not in KINDS:
        return {}, "The kind must be email_report or run_statement."
    out: Dict[str, Any] = {}

    def wanted(key: str) -> bool:
        return not partial or key in body

    if wanted("name"):
        name = _text(body.get("name"), MAX_NAME_CHARS)
        if not name:
            return {}, "Give the schedule a name."
        out["name"] = name

    if wanted("sql"):
        raw = body.get("sql")
        sql = raw.strip() if isinstance(raw, str) else ""
        if not sql:
            return {}, ("Add the query the report runs." if kind == "email_report"
                        else "Add the statement the action runs.")
        if len(sql) > MAX_SQL_CHARS:
            return {}, f"The statement is too long: at most {MAX_SQL_CHARS:,} characters."
        if kind == "email_report":
            problem = read_only_problem(sql)
            if problem:
                return {}, problem
        out["sql"] = sql

    for key in ("source_app_id", "source_widget_instance", "source_widget_id"):
        if wanted(key):
            out[key] = _ref(body.get(key))
    if kind == "run_statement" and wanted("source_widget_id") and not out.get("source_widget_id"):
        return {}, "A scheduled action needs the executable widget it comes from."

    if wanted("view_name"):
        out["view_name"] = _text(body.get("view_name"), email_service.MAX_VIEW_NAME_CHARS) or None
    if wanted("view_link"):
        link = body.get("view_link")
        out["view_link"] = link.strip() if isinstance(link, str) and link.strip() else None

    if wanted("recipients"):
        recipients, problem = _recipients(body.get("recipients"))
        if problem:
            return {}, problem
        if kind == "email_report" and not recipients:
            return {}, "Add at least one recipient."
        out["recipients"] = recipients

    if wanted("subject"):
        out["subject"] = _text(body.get("subject"), email_service.MAX_SUBJECT_CHARS) or None
    if wanted("message"):
        raw = body.get("message")
        if raw is not None and not isinstance(raw, str):
            return {}, "The message must be text."
        message = (raw or "").strip()
        if len(message) > email_service.MAX_MESSAGE_CHARS:
            return {}, f"The message is too long: at most {email_service.MAX_MESSAGE_CHARS:,} characters."
        out["message"] = message or None

    if wanted("send_when"):
        send_when = str(body.get("send_when") or "always").strip().lower()
        if send_when not in SEND_WHEN:
            return {}, "Send when must be always, has_rows or no_rows."
        out["send_when"] = send_when
    if wanted("attach_csv"):
        value = body.get("attach_csv", False)
        if not isinstance(value, bool):
            return {}, "Attach CSV must be true or false."
        out["attach_csv"] = value

    if wanted("recurrence"):
        normalized, problem = recurrence.validate(body.get("recurrence"))
        if problem:
            return {}, problem
        out["recurrence"] = normalized
    return out, None


def patch_problem(body: Dict[str, Any], current: Dict[str, Any], is_owner: bool) -> Optional[Tuple[int, str]]:
    """(status, sentence) when a PATCH asks for something it may not, else None.

    `current` is the schedule as the API returns it. Fields that repeat their
    current value aren't changes, so a client may send the whole schedule back.
    """
    for key in FIXED:
        if key in body and body[key] != current.get(key):
            return 400, f"A schedule's {key} can't be changed; create a new schedule instead."
    if not is_owner:
        changing = [k for k in EDITABLE if k in body and k not in ADMIN_EDITABLE and body[k] != current.get(k)]
        if changing:
            return 403, "Only the schedule's owner can change what it runs or who it goes to."
    return None


# --------------------------------------------------------------------- shapes

def _iso(value: Any) -> Optional[str]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def from_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def run_to_api(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row or not row.get("id"):
        return None
    return {
        "id": row["id"],
        "schedule_id": row.get("schedule_id"),
        "trigger": row.get("trigger"),
        "started_at": _iso(row.get("started_at")),
        "finished_at": _iso(row.get("finished_at")),
        "status": row.get("status"),
        "rows": row.get("row_count"),
        "emailed": bool(row.get("emailed")),
        "error": row.get("error"),
    }


def to_api(row: Dict[str, Any], last_run: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The contract's Schedule. Claim columns and `owner_groups` stay server-side."""
    stored = from_json(row.get("recurrence")) or {}
    normalized, _problem = recurrence.validate(stored)
    return {
        "id": row["id"],
        "owner": row.get("owner"),
        "kind": row.get("kind"),
        "name": row.get("name"),
        "sql": row.get("sql"),
        "source_app_id": row.get("source_app_id"),
        "source_widget_instance": row.get("source_widget_instance"),
        "source_widget_id": row.get("source_widget_id"),
        "view_name": row.get("view_name"),
        "view_link": row.get("view_link"),
        "recipients": list(row.get("recipients") or []),
        "subject": row.get("subject"),
        "message": row.get("message"),
        "send_when": row.get("send_when") or "always",
        "attach_csv": bool(row.get("attach_csv")),
        "recurrence": normalized or stored,
        "next_run_at": _iso(row.get("next_run_at")),
        "last_run": run_to_api(last_run),
        "status": row.get("status"),
        "paused_reason": row.get("paused_reason"),
        "failure_count": int(row.get("failure_count") or 0),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


# --------------------------------------------------------------------- storage

def _conn():
    from database import get_db_connection

    return get_db_connection()


def dict_rows(c) -> List[Dict[str, Any]]:
    names = [d[0] for d in c.description]
    return [dict(zip(names, r)) for r in c.fetchall()]


def _split(row: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    schedule = {k: row[k] for k in _COLUMNS if k in row}
    run = {k: row.get(f"r_{k}") for k in _RUN_COLUMNS}
    return schedule, run if run.get("id") else None


_WITH_LAST_RUN = f"""
    SELECT {COLUMNS_SQL}, {", ".join(f"r.{c} AS r_{c}" for c in _RUN_COLUMNS)}
    FROM schedules s
    LEFT JOIN LATERAL (
        SELECT {RUN_COLUMNS_SQL} FROM schedule_runs
        WHERE schedule_id = s.id ORDER BY started_at DESC LIMIT 1
    ) r ON TRUE
"""


def new_id() -> str:
    return str(uuid.uuid4())


def list_schedules(owner: Optional[str]) -> List[Dict[str, Any]]:
    """Every schedule `owner` has, newest first, or everyone's for `owner=None`."""
    conn = _conn()
    try:
        c = conn.cursor()
        if owner is None:
            c.execute(_WITH_LAST_RUN + " ORDER BY s.created_at DESC")
        else:
            c.execute(_WITH_LAST_RUN + " WHERE s.owner = %s ORDER BY s.created_at DESC", (owner,))
        rows = dict_rows(c)
        conn.commit()
    finally:
        conn.close()
    return [to_api(*_split(r)) for r in rows]


def get_row(schedule_id: str) -> Optional[Dict[str, Any]]:
    """The stored row, claim columns and all, or None."""
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(f"SELECT {COLUMNS_SQL} FROM schedules s WHERE s.id = %s", (schedule_id,))
        rows = dict_rows(c)
        conn.commit()
    finally:
        conn.close()
    return rows[0] if rows else None


def get_api(schedule_id: str) -> Optional[Dict[str, Any]]:
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(_WITH_LAST_RUN + " WHERE s.id = %s", (schedule_id,))
        rows = dict_rows(c)
        conn.commit()
    finally:
        conn.close()
    return to_api(*_split(rows[0])) if rows else None


def _store(value: Any) -> Any:
    return json.dumps(value) if isinstance(value, dict) else value


def create(fields: Dict[str, Any], owner: str, max_per_person: int) -> Optional[Dict[str, Any]]:
    """Insert one schedule, or None when `owner` already has `max_per_person`.

    The count and the insert share a transaction holding a lock on the owner, so
    two requests at once can't both squeeze under the cap.
    """
    columns = list(fields)
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"cc-schedules:{owner}",))
        c.execute("SELECT COUNT(*) FROM schedules WHERE owner = %s", (owner,))
        if int(c.fetchone()[0]) >= max_per_person:
            conn.rollback()
            return None
        c.execute(
            f"INSERT INTO schedules ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id",
            [_store(fields[k]) for k in columns],
        )
        new = c.fetchone()[0]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_api(new)


def count_for(owner: str) -> int:
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM schedules WHERE owner = %s", (owner,))
        n = int(c.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    return n


def update(schedule_id: str, fields: Dict[str, Any], touch: bool = True) -> Optional[Dict[str, Any]]:
    """Set `fields`, and `updated_at` unless `touch` is off (asking for a run isn't an
    edit). The schedule afterwards, or None if it's gone."""
    if fields:
        sets = ", ".join(f"{k} = %s" for k in fields) + (", updated_at = now()" if touch else "")
        conn = _conn()
        try:
            c = conn.cursor()
            c.execute(f"UPDATE schedules SET {sets} WHERE id = %s",
                      [_store(v) for v in fields.values()] + [schedule_id])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return get_api(schedule_id)


def delete(schedule_id: str) -> bool:
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM schedules WHERE id = %s", (schedule_id,))
        gone = c.rowcount > 0
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return gone


def runs(schedule_id: str, limit: int = DEFAULT_RUNS) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or DEFAULT_RUNS), MAX_RUNS))
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(f"SELECT {RUN_COLUMNS_SQL} FROM schedule_runs WHERE schedule_id = %s "
                  "ORDER BY started_at DESC LIMIT %s", (schedule_id, limit))
        rows = dict_rows(c)
        conn.commit()
    finally:
        conn.close()
    return [run_to_api(r) for r in rows]


def owners_needing_reconnect(limit: int = 500) -> List[str]:
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT DISTINCT owner FROM schedules WHERE status = 'needs_reconnect' LIMIT %s", (limit,))
        out = [r[0] for r in c.fetchall()]
        conn.commit()
    finally:
        conn.close()
    return out


def recurrences(owner: str, status: str) -> List[Tuple[str, Any]]:
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT id, recurrence FROM schedules WHERE owner = %s AND status = %s", (owner, status))
        out = [(r[0], from_json(r[1])) for r in c.fetchall()]
        conn.commit()
    finally:
        conn.close()
    return out


def set_status_where(owner: str, from_status: str, updates: Iterable[Tuple[str, Dict[str, Any]]]) -> List[str]:
    """Apply per-schedule `updates` to `owner`'s schedules still in `from_status`.
    The ids that changed; one whose status moved meanwhile is left alone."""
    changed: List[str] = []
    conn = _conn()
    try:
        c = conn.cursor()
        for schedule_id, fields in updates:
            sets = ", ".join(f"{k} = %s" for k in fields)
            c.execute(f"UPDATE schedules SET {sets}, updated_at = now() "
                      "WHERE id = %s AND owner = %s AND status = %s",
                      [_store(v) for v in fields.values()] + [schedule_id, owner, from_status])
            if c.rowcount:
                changed.append(schedule_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return changed


def active_owners(usernames: Sequence[str]) -> Dict[str, Tuple[str, int]]:
    """{owner: (owner_email, active schedule count)} for those of `usernames` with any."""
    if not usernames:
        return {}
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT owner, MAX(owner_email), COUNT(*) FROM schedules "
                  "WHERE status = 'active' AND owner = ANY(%s) GROUP BY owner", (list(usernames),))
        out = {r[0]: (r[1] or "", int(r[2])) for r in c.fetchall()}
        conn.commit()
    finally:
        conn.close()
    return out
