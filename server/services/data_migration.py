"""Moving a whole deployment's data from one Command Center app to another.

Promotion (`routes/promotion.py`) copies one widget or view between the dev,
test and prod schemas of *one* Lakebase instance. That stopped being enough when
each bundle target got an instance of its own (`command-center-<env>-v1`): the
test app cannot see the dev app's database at all, so moving people from the dev
app to the test app meant rebuilding every widget and agent by hand.

This moves data as a **snapshot file** rather than over a connection between the
two apps, on purpose:

  * Each app holds credentials for its own instance only — injected by the
    platform, minted for its own service principal — and giving one app a
    standing route into another's database is a much bigger grant than moving the
    data once needs.
  * An app calling another app goes through a second Databricks Apps front door
    with the user's token, which is exactly the hop that produced per-user
    401/403s for the agent proxy.
  * A file is also a backup, can be inspected before it is imported, and works
    between workspaces.

So: an admin downloads a snapshot from the source app (`export_tables`), uploads
it to the target app, previews what it would do, and imports (`import_tables`).
The preview is the import itself run inside a transaction that is rolled back,
so its numbers are not an estimate.

Two modes, because "migrate" means two different things:

  * **merge** (default) — add what the target is missing and leave everything it
    already has. Versioned rows are matched on `(id, version)`, taxonomy on name,
    role mappings on their three fields, and activity rows on their content, so a
    merge can be repeated without duplicating anything. Serial ids are *not*
    carried: the two databases numbered their rows independently, and reusing the
    source's ids would collide with the target's.
  * **replace** — make the target's tables match the file: delete, then insert
    with ids preserved and sequences moved past them. What you want for "dev is
    the source of truth, make test a copy".

Everything for one schema is one transaction. A failure part-way leaves the
target exactly as it was, which matters more here than speed: half a migration
is a deployment in a state nobody designed.

Nothing in this module imports the database or FastAPI, so the planning — which
rows a merge would skip, how values survive JSON — is tested without either.
"""

from __future__ import annotations

import base64
import datetime as _dt
import decimal
import re
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

FORMAT = "command-center-snapshot"
FORMAT_VERSION = 1


class TableSpec:
    """How one table is moved: which group it belongs to and what identifies a row."""

    def __init__(self, name: str, group: str, key: Sequence[str], serial: bool = False):
        self.name = name
        self.group = group
        #: The natural key a merge matches on. For serial tables this is never
        #: `id` — ids are local to the database that assigned them.
        self.key = tuple(key)
        self.serial = serial


# Order is the order of import. There are no foreign keys between these tables,
# so it is chosen for the reader of a preview, not for the database.
TABLES: List[TableSpec] = [
    TableSpec("widgets", "content", ("id", "version")),
    TableSpec("dashboard_views", "content", ("id", "version")),
    TableSpec("shared_views", "content", ("username", "view_id")),
    TableSpec("agent_profiles", "content", ("id", "version")),
    TableSpec("widget_categories", "access", ("name",), serial=True),
    TableSpec("widget_domains", "access", ("name",), serial=True),
    TableSpec("role_mappings", "access", ("external_role", "domain", "permission_level"), serial=True),
    TableSpec("app_settings", "settings", ("key",)),
    TableSpec("widget_runs", "activity", ("widget_id", "username", "timestamp"), serial=True),
    TableSpec("action_logs", "activity",
              ("widget_id", "action_name", "username", "request_id", "user_explanation", "timestamp"),
              serial=True),
    TableSpec("chat_conversations", "conversations", ("id",)),
    TableSpec("chat_messages", "conversations", ("conversation_id", "seq")),
    TableSpec("chat_uploads", "conversations", ("id",)),
]
SPECS: Dict[str, TableSpec] = {t.name: t for t in TABLES}

GROUPS: List[Dict[str, Any]] = [
    {"key": "content", "label": "Widgets, views and agents",
     "help": "Every version of every widget, view and Agent Studio agent, plus who is subscribed to which shared view.",
     "default": True},
    {"key": "access", "label": "Categories, domains and role mappings",
     "help": "The taxonomy and who may edit which domain. Replacing these replaces the target's access control.",
     "default": True},
    {"key": "settings", "label": "Deployment settings",
     "help": "Admin Panel → Settings: models, limits and switches. Merge keeps any the target has already set.",
     "default": True},
    {"key": "activity", "label": "Activity history",
     "help": "Action logs (the audit trail of approved actions) and widget usage behind the creator leaderboard.",
     "default": True},
    # Off by default: everyone's chats and the files they attached, readable by
    # whoever holds the file. Worth moving sometimes; never by accident.
    {"key": "conversations", "label": "Saved conversations and attached files",
     "help": "Everyone's assistant chat history, including uploaded files. The largest and most sensitive part of a snapshot.",
     "default": False},
]
GROUP_KEYS = [g["key"] for g in GROUPS]

MODES = ("merge", "replace")

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def tables_for(groups: Iterable[str]) -> List[TableSpec]:
    wanted = set(groups)
    return [t for t in TABLES if t.group in wanted]


# ------------------------------------------------------------------ values

def encode_value(value: Any) -> Any:
    """A database value as something JSON can hold and `decode_value` can undo.

    Timestamps become ISO strings, which Postgres reads straight back into a
    TIMESTAMP column. Bytes (`chat_uploads.raw` / `.parsed`) are tagged, since a
    base64 string would otherwise be written back as text.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$b64": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    return value


def decode_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"$b64"}:
        return base64.b64decode(value["$b64"])
    return value


def _hashable(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_hashable(v) for v in value)
    return value


def row_key(row: Sequence[Any], columns: Sequence[str], key: Sequence[str]) -> Tuple[Any, ...]:
    """The natural key of an encoded row, comparable across the two databases."""
    index = {c: i for i, c in enumerate(columns)}
    return tuple(_hashable(row[index[k]]) if k in index else None for k in key)


# ---------------------------------------------------------------- planning

def validate_snapshot(snapshot: Any) -> List[str]:
    """What is wrong with an uploaded snapshot, as messages. Empty means usable."""
    if not isinstance(snapshot, dict):
        return ["This file is not a Command Center snapshot."]
    if snapshot.get("format") != FORMAT:
        return ["This file is not a Command Center snapshot (no 'format' marker)."]
    version = snapshot.get("format_version")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        return [f"This snapshot was written by a newer version of the app (format {version}). "
                "Update this app before importing it."]
    tables = snapshot.get("tables")
    if not isinstance(tables, dict):
        return ["The snapshot has no tables."]
    problems = []
    for name, body in tables.items():
        if name not in SPECS:
            continue  # reported as ignored, not an error: a newer app may add tables
        if not isinstance(body, dict) or not isinstance(body.get("columns"), list) \
                or not isinstance(body.get("rows"), list):
            problems.append(f"Table '{name}' is malformed.")
            continue
        columns = body["columns"]
        if not all(isinstance(c, str) and _IDENT.match(c) for c in columns):
            problems.append(f"Table '{name}' has an invalid column name.")
        if any(not isinstance(r, list) or len(r) != len(columns) for r in body["rows"]):
            problems.append(f"Table '{name}' has rows that don't match its columns.")
    return problems


def choose_columns(source: Sequence[str], target: Sequence[str], spec: TableSpec,
                   mode: str) -> Tuple[List[str], List[str]]:
    """(columns to write, source columns the target lacks).

    A snapshot from an older or newer app can differ by a column or two. Writing
    only the shared ones is right in both directions: a column the target lacks
    has nowhere to go, and one the source lacks takes its default, exactly as it
    would for a row written before the column existed.

    A merge leaves a serial table's `id` to the target's sequence.
    """
    target_set = set(target)
    shared = [c for c in source if c in target_set]
    dropped = [c for c in source if c not in target_set]
    if mode == "merge" and spec.serial:
        shared = [c for c in shared if c != "id"]
    return shared, dropped


def plan_merge(rows: Sequence[Sequence[Any]], columns: Sequence[str], spec: TableSpec,
               existing: Iterable[Tuple[Any, ...]]) -> Tuple[List[Sequence[Any]], int]:
    """(rows to insert, rows skipped because the target already has them).

    Counted as a multiset rather than a set. Two identical activity rows are two
    events — the same widget added twice in one second is rare, not impossible —
    so a key present once in the target skips one source row, not every row
    sharing it. That is also what makes a repeated merge a no-op.
    """
    have = Counter(existing)
    keep: List[Sequence[Any]] = []
    skipped = 0
    for row in rows:
        k = row_key(row, columns, spec.key)
        if have[k] > 0:
            have[k] -= 1
            skipped += 1
        else:
            keep.append(row)
    return keep, skipped


# --------------------------------------------------------------- database

def _target_columns(cur, table: str) -> List[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position",
        (table,),
    )
    return [r[0] if not hasattr(r, "keys") else r["column_name"] for r in cur.fetchall()]


def _quoted(columns: Sequence[str]) -> str:
    return ", ".join(f'"{c}"' for c in columns)


def summarize(cur, groups: Iterable[str] = GROUP_KEYS) -> List[Dict[str, Any]]:
    """Row counts and on-disk size per table, for the export form."""
    out = []
    for spec in tables_for(groups):
        try:
            cur.execute(
                f'SELECT COUNT(*), pg_total_relation_size(to_regclass(%s)) FROM "{spec.name}"',
                (spec.name,),
            )
            count, size = cur.fetchone()
            out.append({"table": spec.name, "group": spec.group, "rows": int(count), "bytes": int(size or 0)})
        except Exception as exc:  # noqa: BLE001 — a missing table is reported, not fatal
            cur.connection.rollback()
            out.append({"table": spec.name, "group": spec.group, "rows": 0, "bytes": 0, "error": str(exc)})
    return out


def export_tables(cur, specs: Iterable[TableSpec]) -> Dict[str, Any]:
    """`{table: {"columns": [...], "rows": [[...]]}}` for each table that exists."""
    tables: Dict[str, Any] = {}
    for spec in specs:
        columns = _target_columns(cur, spec.name)
        if not columns:
            continue
        # A stable order makes two snapshots of the same data the same file.
        if spec.serial and "id" in columns:
            order = ' ORDER BY "id"'
        elif all(k in columns for k in spec.key):
            order = " ORDER BY " + _quoted(spec.key)
        else:
            order = ""
        cur.execute(f'SELECT {_quoted(columns)} FROM "{spec.name}"{order}')
        tables[spec.name] = {
            "columns": columns,
            "rows": [[encode_value(v) for v in row] for row in cur.fetchall()],
        }
    return tables


def _insert(cur, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]],
            batch: int = 500) -> int:
    """Insert `rows`, skipping any that collide with a unique key. Returns rows written."""
    from psycopg2.extras import execute_values

    written = 0
    sql = f'INSERT INTO "{table}" ({_quoted(columns)}) VALUES %s ON CONFLICT DO NOTHING'
    for start in range(0, len(rows), batch):
        chunk = rows[start:start + batch]
        # One statement per chunk, so rowcount counts the whole chunk (with
        # several pages in one call it only reports the last).
        execute_values(cur, sql, chunk, page_size=len(chunk))
        written += max(cur.rowcount, 0)
    return written


def import_tables(cur, tables: Dict[str, Any], specs: Iterable[TableSpec], mode: str) -> List[Dict[str, Any]]:
    """Write the snapshot's tables into the schema `cur` is on. Does not commit.

    The caller owns the transaction: it commits, or — for a preview — rolls back,
    and either way the whole schema moves together.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    report: List[Dict[str, Any]] = []
    for spec in specs:
        body = tables.get(spec.name)
        entry: Dict[str, Any] = {"table": spec.name, "group": spec.group, "in_file": 0,
                                 "inserted": 0, "skipped": 0, "deleted": 0, "dropped_columns": []}
        report.append(entry)
        if body is None:
            entry["note"] = "Not in this snapshot."
            continue
        source_columns = body["columns"]
        rows = body["rows"]
        entry["in_file"] = len(rows)

        target_columns = _target_columns(cur, spec.name)
        if not target_columns:
            entry["note"] = "This app has no such table; skipped."
            continue
        columns, dropped = choose_columns(source_columns, target_columns, spec, mode)
        entry["dropped_columns"] = dropped
        index = [source_columns.index(c) for c in columns]

        if mode == "replace":
            cur.execute(f'DELETE FROM "{spec.name}"')
            entry["deleted"] = max(cur.rowcount, 0)
            todo = rows
        else:
            key_cols = [k for k in spec.key if k in target_columns]
            cur.execute(f'SELECT {_quoted(key_cols)} FROM "{spec.name}"')
            existing = [tuple(_hashable(encode_value(v)) for v in r) for r in cur.fetchall()]
            # Keys missing from the target's schema compare as None, as they do in
            # `row_key` for the source.
            if len(key_cols) != len(spec.key):
                existing = [tuple(dict(zip(key_cols, e)).get(k) for k in spec.key) for e in existing]
            todo, entry["skipped"] = plan_merge(rows, source_columns, spec, existing)

        values = [tuple(decode_value(r[i]) for i in index) for r in todo]
        written = _insert(cur, spec.name, columns, values) if values else 0
        entry["inserted"] = written
        # A unique key other than the one planned on (a PK in merge, say) can still
        # refuse a row; say so rather than let the counts quietly disagree.
        entry["skipped"] += len(values) - written

        if spec.serial and mode == "replace" and "id" in columns:
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('\"{spec.name}\"', 'id'), "
                f'COALESCE((SELECT MAX(id) FROM "{spec.name}"), 1), '
                f'(SELECT MAX(id) IS NOT NULL FROM "{spec.name}"))'
            )
    return report


def snapshot_document(tables: Dict[str, Any], *, groups: Sequence[str], source: Dict[str, Any],
                      exported_by: str, now: Optional[Callable[[], _dt.datetime]] = None) -> Dict[str, Any]:
    stamp = (now or (lambda: _dt.datetime.now(_dt.timezone.utc)))()
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "exported_at": stamp.isoformat(),
        "exported_by": exported_by,
        "source": source,
        "groups": list(groups),
        "tables": tables,
    }
