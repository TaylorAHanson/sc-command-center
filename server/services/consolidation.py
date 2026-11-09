"""Folds the retired Dev and Test workspaces into drafts in the one content store.

Each deployment used to hold three copies of its content — the dev, test and prod
schemas (or, on the legacy `command-center` instance, three databases) — with
promotion copying versions between them. Drafts replaced that, and
`database.content_env()` (Prod by default) is now the only store. This runs once
per deployment, at startup, and brings over what only Dev or Test knew:

  * **Prod's versions stay the published history**, untouched.
  * **Each object's newest Dev version** (else its newest Test one) becomes its
    draft, but only when it says something Prod's latest doesn't — compared by
    meaning, the way promotion decided "already up to date". `base_version` is
    Prod's latest.
  * **Objects only in Dev or Test** become drafts that were never published. Only
    editors and admins could open those workspaces, and the access migration
    gives them Can manage, so the same people see the same work.
  * **Widget pins** (`props._version`) in an imported view are Dev or Test version
    numbers, which mean nothing in Prod. Each is moved to the Prod version with
    identical source, or dropped (the view then shows the latest published
    version) and listed in the report.
  * **Everything else** — taxonomy, archive markers, link names, subscriptions,
    activity, chats — goes through `data_migration`'s natural-key merge, which
    never carries serial ids and adds nothing on a second run.

Only rows are added. Dev and Test are read and never written, and no Prod row is
changed, so redeploying the previous version finds every workspace as it was;
what it can't see is the drafts, which is the point of keeping them in a table of
their own.

It also keeps the one-time bookkeeping both cutover steps share: the
`cutover_log` table in the settings schema, and the advisory lock that stops two
uvicorn workers running a step at once.
"""
from __future__ import annotations

import contextlib
import json
import logging
from typing import Any, Callable, Dict, Iterable, Iterator, List, NamedTuple, Optional, Sequence, Set, Tuple

from services import data_migration as dm
from services import drafts

logger = logging.getLogger(__name__)

STEP = "consolidation"
DONE, SKIPPED, FAILED = "done", "skipped", "failed"

APP, WIDGET, AGENT = drafts.APP, drafts.WIDGET, drafts.AGENT
#: In this order so a report reads views, then what they place, then agents.
VERSIONED: Tuple[Tuple[str, str], ...] = ((APP, "dashboard_views"), (WIDGET, "widgets"), (AGENT, "agent_profiles"))
NOUNS = {APP: ("view", "views"), WIDGET: ("widget", "widgets"), AGENT: ("agent", "agents")}
#: Tables that retire rows by flag. A retired row is not anyone's work in progress.
_DEPRECATES = {WIDGET, AGENT}

#: Columns that differ between two copies of the same object without meaning
#: anything: identity, per-version stamps, review state, and who last touched
#: it. Owners are an access-list fact now, so a different `username` or
#: `created_by` is not a change worth a draft.
BOOKKEEPING = frozenset({
    "id", "version", "timestamp", "is_deprecated", "is_certified", "created_by", "username",
    "updated_at", "published_by", "published_at",
})

#: Merged with `data_migration`'s natural-key merge. Not the versioned tables
#: (handled above), and not settings or role mappings, which were only ever kept
#: in the settings schema.
MERGED = (
    "widget_categories", "widget_domains", "shared_views", "archived_views", "app_links",
    "widget_runs", "action_logs", "chat_conversations", "chat_messages", "chat_uploads",
)

UNCHANGED, DRAFT, DRAFT_ONLY = "unchanged", "draft", "draft_only"
UPDATED_BY = "migration"
#: Pins listed one by one in the notes; the rest are counted.
_NOTE_LIMIT = 20
#: Objects listed in the stored report. The counts are always complete.
_OBJECTS_KEPT = 2000


# ------------------------------------------------------------------ cutover log

LOG_DDL = '''
    CREATE TABLE IF NOT EXISTS cutover_log (
        step TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        report JSONB NOT NULL DEFAULT '{}'::jsonb,
        error TEXT
    )
'''

#: Near init_db's keys (918273645 + 0..9) but clear of them: the same session
#: may take both.
_LOCK_KEYS = {"consolidation": 918274645, "access": 918274646}


def _rows(c) -> List[Dict[str, Any]]:
    names = [d[0] for d in c.description]
    return [dict(r) if hasattr(r, "keys") else dict(zip(names, r)) for r in c.fetchall()]


def _first(row: Any) -> Any:
    if row is None:
        return None
    return list(row.values())[0] if hasattr(row, "keys") else row[0]


def _settings_connection():
    from database import get_db_connection
    from services.settings_store import settings_env

    # Unpooled: the advisory lock belongs to the session, and a pooled connection
    # that went back still holding it would block the next worker forever.
    return get_db_connection(settings_env(), pooled=False, physical=True)


@contextlib.contextmanager
def step_lock(step: str) -> Iterator[Any]:
    """A settings connection holding `step`'s advisory lock, with `cutover_log` in place.

    Every worker runs startup, so without the lock two would fold the same rows
    in at once; the second waits here and then finds the step already logged.
    """
    conn = _settings_connection()
    c = conn.cursor()
    locked = False
    try:
        try:
            c.execute("SELECT pg_advisory_lock(%s)", (_LOCK_KEYS[step],))
            conn.commit()
            locked = True
        except Exception as e:  # noqa: BLE001 - unserialized is still correct, only riskier
            conn.rollback()
            logger.warning("Cutover step %s could not take its lock: %s", step, e)
        c.execute(LOG_DDL)
        conn.commit()
        yield conn
    finally:
        if locked:
            try:
                c.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEYS[step],))
                conn.commit()
            except Exception:  # noqa: BLE001 - closing the session releases it anyway
                conn.rollback()
        conn.close()


def _log_row(row: Dict[str, Any]) -> Dict[str, Any]:
    report = row.get("report")
    if isinstance(report, str):
        try:
            report = json.loads(report)
        except ValueError:
            report = {}
    ran_at = row.get("ran_at")
    return {
        "step": row.get("step"),
        "status": row.get("status"),
        "ran_at": ran_at.isoformat() if hasattr(ran_at, "isoformat") else ran_at,
        "report": report or {},
        "error": row.get("error"),
    }


def read_step(c, step: str) -> Optional[Dict[str, Any]]:
    c.execute("SELECT step, status, ran_at, report, error FROM cutover_log WHERE step = %s", (step,))
    rows = _rows(c)
    return _log_row(rows[0]) if rows else None


def record(c, step: str, status: str, report: Dict[str, Any], error: Optional[str] = None) -> None:
    from psycopg2.extras import Json

    c.execute(
        """
        INSERT INTO cutover_log (step, status, ran_at, report, error)
        VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)
        ON CONFLICT (step) DO UPDATE
           SET status = EXCLUDED.status, ran_at = EXCLUDED.ran_at,
               report = EXCLUDED.report, error = EXCLUDED.error
        """,
        (step, status, Json(report, dumps=lambda v: json.dumps(v, default=str)), error),
    )


def read_logs() -> Dict[str, Dict[str, Any]]:
    """Every step's log row, by step. Empty before the first run (or if it can't be read)."""
    conn = _settings_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT to_regclass('cutover_log')")
        if _first(c.fetchone()) is None:
            conn.rollback()
            return {}
        c.execute("SELECT step, status, ran_at, report, error FROM cutover_log")
        rows = {r["step"]: _log_row(r) for r in _rows(c)}
        conn.rollback()
        return rows
    finally:
        conn.close()


def clear_failures(steps: Sequence[str]) -> int:
    """Forget the failed steps among `steps`, so the next run tries them again. Finished ones stay."""
    conn = _settings_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT to_regclass('cutover_log')")
        if _first(c.fetchone()) is None:
            conn.rollback()
            return 0
        c.execute("DELETE FROM cutover_log WHERE status = %s AND step = ANY(%s)", (FAILED, list(steps)))
        gone = max(c.rowcount, 0)
        conn.commit()
        return gone
    finally:
        conn.close()


def run_step(step: str, work: Callable[[Any], Tuple[str, Dict[str, Any]]],
             on_failure: Optional[Callable[[Any], None]] = None) -> Optional[Dict[str, Any]]:
    """Run `work(settings_conn)` once per deployment and log what it did. Never raises.

    A logged step, failed or not, is not run again by a restart: a failure that
    repeats would cost every startup the same work and change the report under
    the admin reading it. Retry in the Admin Panel clears a failure. A step that
    couldn't reach the settings store at all logs nothing, so the next start
    tries again — that is the transient case.
    """
    try:
        with step_lock(step) as conn:
            c = conn.cursor()
            held = read_step(c, step)
            conn.commit()
            if held is not None:
                return held
            error = None
            try:
                status, report = work(conn)
            except Exception as e:  # noqa: BLE001 - recorded for the Admin Panel instead
                conn.rollback()
                logger.error("Cutover step %s failed: %s", step, e, exc_info=True)
                status, report, error = FAILED, {"notes": []}, f"{type(e).__name__}: {e}"
                if on_failure is not None:
                    try:
                        on_failure(conn)
                    except Exception as e2:  # noqa: BLE001
                        conn.rollback()
                        logger.error("Cutover step %s's fallback failed too: %s", step, e2, exc_info=True)
            record(c, step, status, report, error)
            conn.commit()
            return read_step(c, step)
    except Exception as e:  # noqa: BLE001 - startup must survive this
        logger.error("Cutover step %s could not run: %s", step, e, exc_info=True)
        return None


# ------------------------------------------------------------------ which stores

class Store(NamedTuple):
    env: str
    conn: Any
    tables: frozenset


def store_identity(conn) -> Optional[Tuple[str, str, str, str]]:
    """Which physical schema a connection lands in: (host, port, database, schema).

    Comparing env names can't answer "is this the same store": `APP_DB_SCHEMA`
    points every env at one schema, and the legacy instance tells envs apart by
    database rather than schema. What the server reports for the session can.
    None when no schema on the search path exists.
    """
    c = conn.cursor()
    c.execute("SELECT current_database(), current_schema()")
    row = c.fetchone()
    conn.rollback()
    if row is None:
        return None
    database, schema = (list(row.values()) if hasattr(row, "keys") else list(row))[:2]
    if not schema:
        return None
    params = conn.get_dsn_parameters() if hasattr(conn, "get_dsn_parameters") else {}
    return (str(params.get("host") or ""), str(params.get("port") or ""), str(database or ""), str(schema))


def describe_identity(identity: Optional[Sequence[str]]) -> str:
    if not identity:
        return "no schema"
    return f"{identity[2]}.{identity[3]}"


def same_store_note(env: str, identity: Sequence[str]) -> str:
    return (f"{env.capitalize()} is the same database and schema as the content store "
            f"({describe_identity(identity)}), so there was nothing of its own to bring over.")


def distinct_sources(content: Optional[Sequence[str]],
                     candidates: Sequence[Tuple[str, Optional[Sequence[str]]]]) -> Tuple[List[str], List[str]]:
    """(envs to read, notes on the ones skipped). The first env to claim a store keeps it."""
    seen = {tuple(content)} if content else set()
    keep: List[str] = []
    notes: List[str] = []
    for env, identity in candidates:
        if identity is None:
            notes.append(f"{env.capitalize()} has no schema of its own here, so there was nothing to bring over.")
            continue
        if tuple(identity) in seen:
            notes.append(same_store_note(env, identity))
            continue
        seen.add(tuple(identity))
        keep.append(env)
    return keep, notes


_KNOWN_TABLES = tuple(t for _, t in VERSIONED) + MERGED


def present_tables(c, names: Iterable[str] = _KNOWN_TABLES) -> frozenset:
    names = list(names)
    c.execute("SELECT " + ", ".join(f"to_regclass('{n}') IS NOT NULL" for n in names))
    row = c.fetchone()
    flags = list(row.values()) if hasattr(row, "keys") else list(row)
    return frozenset(n for n, there in zip(names, flags) if there)


def legacy_envs() -> List[str]:
    """The envs that used to be workspaces beside the content store, Dev first."""
    from database import CONTENT_ENVS, content_env

    return [e for e in CONTENT_ENVS if e != content_env()]


def open_legacy_stores(content_identity: Optional[Sequence[str]]) -> Tuple[List[Store], List[str]]:
    """Read-only connections to the old workspaces that really are separate stores, Dev first."""
    from database import get_db_connection

    opened: List[Tuple[str, Any, Optional[Tuple[str, ...]]]] = []
    notes: List[str] = []
    for env in legacy_envs():
        try:
            conn = get_db_connection(env, pooled=False, physical=True)
        except Exception as e:  # noqa: BLE001 - a workspace that was never created has nothing in it
            notes.append(f"{env.capitalize()} could not be opened ({e}), so nothing was brought over from it.")
            continue
        try:
            opened.append((env, conn, store_identity(conn)))
        except Exception as e:  # noqa: BLE001
            conn.close()
            notes.append(f"{env.capitalize()} could not be identified ({e}), so nothing was brought over from it.")
    keep, skipped = distinct_sources(content_identity, [(env, ident) for env, _, ident in opened])
    notes.extend(skipped)
    stores: List[Store] = []
    for env, conn, _ in opened:
        if env not in keep:
            conn.close()
            continue
        try:
            tables = present_tables(conn.cursor())
            conn.rollback()
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            tables = frozenset()
            notes.append(f"Could not list {env.capitalize()}'s tables: {e}")
        if not any(t in tables for _, t in VERSIONED):
            conn.close()
            notes.append(f"{env.capitalize()} has no widgets, views or agents, so there was nothing to bring over.")
            continue
        stores.append(Store(env, conn, tables))
    return stores, notes


def close_stores(stores: Iterable[Store]) -> None:
    for s in stores:
        try:
            s.conn.rollback()
            s.conn.close()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ comparing

def _norm(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", "replace")
    return value or None


def same_content(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Whether two rows of a versioned table (from different stores) hold the same thing.

    Only columns both rows have are compared. Startup stopped initialising the
    old Test schema, so it can lack a column added since; that column can't hold
    a difference, and counting it would give every untouched object a draft.
    """
    keys = (set(a) & set(b)) - BOOKKEEPING
    return all(_norm(a.get(k)) == _norm(b.get(k)) for k in keys)


def same_view_content(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """`same_content` for view rows, by what they mean rather than how they're stored.

    A row saved before apps has only `widgets_json`; the same layout saved since
    also carries `spec_json`. Compared column by column, an untouched Prod copy
    of a view someone opened in Dev would look changed and get a draft for
    nothing.
    """
    try:
        from services.app_spec import read_spec
    except Exception:  # noqa: BLE001 - compare as stored rather than not at all
        return same_content(a, b)

    def meaning(row: Dict[str, Any]) -> Dict[str, Any]:
        out = {k: v for k, v in row.items() if k not in ("widgets_json", "spec_json")}
        out["spec"] = json.dumps(read_spec(str(row.get("id") or ""), row.get("spec_json"), row.get("widgets_json")),
                                 sort_keys=True, default=str)
        return out

    return same_content(meaning(a), meaning(b))


def decide(object_type: str, published: Optional[Dict[str, Any]], candidate: Dict[str, Any]) -> str:
    """What a Dev/Test row becomes: nothing, the draft of a published object, or a never-published draft."""
    if published is None:
        return DRAFT_ONLY
    same = same_view_content if object_type == APP else same_content
    return UNCHANGED if same(published, candidate) else DRAFT


def pick_sources(per_env: Sequence[Tuple[str, Dict[str, Dict[str, Any]]]]) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    """Per object id, the row its draft comes from: the first env (Dev before Test) that has one."""
    out: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for env, rows in per_env:
        for object_id, row in rows.items():
            out.setdefault(object_id, (env, row))
    return out


# ------------------------------------------------------------------ widget pins

def pin_of(props: Any) -> Optional[int]:
    """The version `props._version` pins, read as `app_spec.placed_widgets` reads it."""
    if not isinstance(props, dict):
        return None
    version = props.get("_version")
    if isinstance(version, str) and version.strip().isdigit():
        version = int(version.strip())
    if isinstance(version, int) and not isinstance(version, bool) and version > 0:
        return version
    return None


def _loads(text: Any) -> Any:
    if text is None or text == "":
        return None
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except ValueError:
        return None


def _widget_lists(row: Dict[str, Any]) -> Iterator[List[Any]]:
    spec = _loads(row.get("spec_json"))
    if isinstance(spec, dict):
        for tab in spec.get("tabs") or []:
            if isinstance(tab, dict) and isinstance(tab.get("widgets"), list):
                yield tab["widgets"]
    widgets = _loads(row.get("widgets_json"))
    if isinstance(widgets, list):
        yield widgets


def view_pins(row: Dict[str, Any]) -> List[Tuple[str, int]]:
    """Every (widget id, version) a view row pins, in both its spec and `widgets_json`, once each."""
    out: Dict[Tuple[str, int], None] = {}
    for widgets in _widget_lists(row):
        for w in widgets:
            if isinstance(w, dict) and isinstance(w.get("type"), str):
                v = pin_of(w.get("props"))
                if v is not None:
                    out[(w["type"], v)] = None
    return list(out)


def _repin(widgets: List[Any], mapping: Dict[Tuple[str, int], Optional[int]]) -> Tuple[List[Any], bool]:
    changed = False
    out = []
    for w in widgets:
        if isinstance(w, dict):
            v = pin_of(w.get("props"))
            key = (w.get("type"), v)
            if v is not None and key in mapping and mapping[key] != v:
                props = dict(w["props"])
                if mapping[key] is None:
                    props.pop("_version", None)
                else:
                    props["_version"] = mapping[key]
                w = {**w, "props": props}
                changed = True
        out.append(w)
    return out, changed


def remap_pins(row: Dict[str, Any], mapping: Dict[Tuple[str, int], Optional[int]]) -> Dict[str, Any]:
    """The view row with each pin in `mapping` moved to its new version (None drops the pin).

    Both `spec_json` and `widgets_json` are rewritten, since a rollback reads the
    second. A column with nothing to change keeps its exact text, so an untouched
    view still compares equal to its Prod copy.
    """
    out = dict(row)
    spec = _loads(row.get("spec_json"))
    if isinstance(spec, dict) and isinstance(spec.get("tabs"), list):
        tabs = []
        any_changed = False
        for tab in spec["tabs"]:
            if isinstance(tab, dict) and isinstance(tab.get("widgets"), list):
                widgets, changed = _repin(tab["widgets"], mapping)
                if changed:
                    tab = {**tab, "widgets": widgets}
                    any_changed = True
            tabs.append(tab)
        if any_changed:
            out["spec_json"] = json.dumps({**spec, "tabs": tabs})
    widgets = _loads(row.get("widgets_json"))
    if isinstance(widgets, list):
        widgets, changed = _repin(widgets, mapping)
        if changed:
            out["widgets_json"] = json.dumps(widgets)
    return out


def choose_version(source_code: Optional[str], candidates: Iterable[Tuple[int, Optional[str], Any]]) -> Optional[int]:
    """The content store's version with the same source as a pinned Dev/Test one, or None.

    `candidates` are (version, tsx_code, is_deprecated). The newest live match
    wins; a retired one only if nothing live matches, since a pin is a request
    for that code and the code is what renders.
    """
    if not source_code:
        return None
    live = [v for v, code, dep in candidates if code == source_code and not dep]
    if live:
        return max(live)
    retired = [v for v, code, _ in candidates if code == source_code]
    return max(retired) if retired else None


class PinResolver:
    """Works out, for one source store, where each of its widget versions lives in the content store."""

    KEEP = "keep"

    def __init__(self, source_cursor, content_cursor):
        self.src = source_cursor
        self.dst = content_cursor
        self._src: Dict[str, Dict[int, Optional[str]]] = {}
        self._dst: Dict[str, List[Tuple[int, Optional[str], Any]]] = {}

    def _source_versions(self, widget_id: str) -> Dict[int, Optional[str]]:
        if widget_id not in self._src:
            self.src.execute("SELECT version, tsx_code FROM widgets WHERE id = %s", (widget_id,))
            self._src[widget_id] = {int(r["version"]): r.get("tsx_code") for r in _rows(self.src)}
        return self._src[widget_id]

    def _content_versions(self, widget_id: str) -> List[Tuple[int, Optional[str], Any]]:
        if widget_id not in self._dst:
            self.dst.execute(
                "SELECT version, tsx_code, COALESCE(is_deprecated, 0) AS dep FROM widgets WHERE id = %s",
                (widget_id,),
            )
            self._dst[widget_id] = [(int(r["version"]), r.get("tsx_code"), bool(r.get("dep"))) for r in _rows(self.dst)]
        return self._dst[widget_id]

    def resolve(self, widget_id: str, version: int) -> Any:
        """The content store's version for this pin, None to drop it, or KEEP for a pin that isn't ours."""
        versions = self._source_versions(widget_id)
        if not versions:
            # Not a stored widget there (a built-in, say): its number never meant a row.
            return self.KEEP
        if version not in versions:
            # Already showed the latest in Dev/Test; here the same number is some other row.
            return None
        return choose_version(versions[version], self._content_versions(widget_id))


def pin_mapping(row: Dict[str, Any], resolve: Callable[[str, int], Any]) -> Tuple[Dict[Tuple[str, int], Optional[int]], List[Tuple[str, int]]]:
    """(mapping for `remap_pins`, pins dropped) for one view row."""
    mapping: Dict[Tuple[str, int], Optional[int]] = {}
    dropped: List[Tuple[str, int]] = []
    for widget_id, version in view_pins(row):
        target = resolve(widget_id, version)
        if target == PinResolver.KEEP:
            continue
        mapping[(widget_id, version)] = target
        if target is None:
            dropped.append((widget_id, version))
    return mapping, dropped


# ------------------------------------------------------------------ merging

def held_back(table: str, body: Dict[str, Any], *, published_apps: Set[str],
              named_apps: Set[str]) -> Tuple[Dict[str, Any], int]:
    """(rows to merge, how many were held back) — where the content store's own answer must win.

    An archive marker from Dev would retire a view that is live in Prod, and a
    link name from Dev, being claimed later, would become a published view's
    name. Both are kept only for views Prod has no answer for.
    """
    columns = body.get("columns") or []
    rows = body.get("rows") or []
    if table == "archived_views" and "id" in columns:
        i = columns.index("id")
        keep = [r for r in rows if r[i] not in published_apps]
    elif table == "app_links" and "app_id" in columns:
        i = columns.index("app_id")
        keep = [r for r in rows if r[i] not in named_apps]
    else:
        return body, 0
    return {**body, "rows": keep}, len(rows) - len(keep)


def _ids(c, sql: str) -> Set[str]:
    c.execute(sql)
    return {str(_first(r)) for r in c.fetchall()}


def merge_store(cc, store: Store) -> List[Dict[str, Any]]:
    """Merge one old workspace's non-versioned tables into the content store. Rows only added."""
    sc = store.conn.cursor()
    published_apps = _ids(cc, "SELECT DISTINCT id FROM dashboard_views")
    out = []
    for name in MERGED:
        if name not in store.tables:
            continue
        spec = dm.SPECS[name]
        # One table at a time: chats carry their attached files, and holding a
        # whole workspace's in memory at once is how a startup runs out of it.
        body = dm.export_tables(sc, [spec]).get(name)
        if body is None:
            continue
        named_apps = _ids(cc, "SELECT DISTINCT app_id FROM app_links") if name == "app_links" else set()
        body, kept_back = held_back(name, body, published_apps=published_apps, named_apps=named_apps)
        entry = dm.import_tables(cc, {name: body}, [spec], "merge")[0]
        entry["env"] = store.env
        entry["held_back"] = kept_back
        out.append(entry)
    return out


# ------------------------------------------------------------------ folding in

def latest_rows(c, table: str, object_type: str) -> Dict[str, Dict[str, Any]]:
    """The newest live row of every id in `table`."""
    live = " WHERE COALESCE(is_deprecated, 0) = 0" if object_type in _DEPRECATES else ""
    c.execute(f"SELECT DISTINCT ON (id) * FROM {table}{live} ORDER BY id, version DESC")
    return {str(r["id"]): r for r in _rows(c)}


def author_of(object_type: str, row: Dict[str, Any]) -> str:
    try:
        from services.creator_stats import is_person
    except Exception:  # noqa: BLE001
        def is_person(name):
            return bool(name)
    name = row.get("created_by") if object_type == WIDGET else row.get("username")
    return name if is_person(name) else UPDATED_BY


def plural(n: int, object_type: str) -> str:
    one, many = NOUNS[object_type]
    return f"{n} {one if n == 1 else many}"


def counts_phrase(counts: Dict[str, int]) -> str:
    parts = [plural(counts[t], t) for t, _ in VERSIONED if counts.get(t)]
    if not parts:
        return "nothing"
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def fold(cc, stores: Sequence[Store]) -> Dict[str, Any]:
    """Write the drafts and merges into the content store's open transaction. Doesn't commit."""
    report: Dict[str, Any] = {
        "sources": [s.env for s in stores],
        "drafts": {t: 0 for t, _ in VERSIONED},
        "draft_only": {t: 0 for t, _ in VERSIONED},
        "unchanged": {t: 0 for t, _ in VERSIONED},
        "kept_existing_drafts": 0,
        "pins_remapped": 0,
        "pins_dropped": [],
        "objects": [],
        "merged": [],
        "notes": [],
    }
    resolvers = {s.env: PinResolver(s.conn.cursor(), cc) for s in stores}

    for object_type, table in VERSIONED:
        published = latest_rows(cc, table, object_type)
        existing = set(drafts.drafts(cc, object_type))
        per_env = [(s.env, latest_rows(s.conn.cursor(), table, object_type)) for s in stores if table in s.tables]
        for object_id, (env, row) in sorted(pick_sources(per_env).items()):
            if object_id in existing:
                # A draft is someone's work (or this step's, on a retry); never overwrite it.
                report["kept_existing_drafts"] += 1
                continue
            if object_type == APP:
                mapping, dropped = pin_mapping(row, resolvers[env].resolve)
                if mapping:
                    row = remap_pins(row, mapping)
                    report["pins_remapped"] += sum(1 for k, v in mapping.items() if v is not None)
                for widget_id, version in dropped:
                    report["pins_dropped"].append({"app_id": object_id, "name": row.get("name") or "",
                                                   "env": env, "widget_id": widget_id, "version": version})
            base = published.get(object_id)
            kind = decide(object_type, base, row)
            if kind == UNCHANGED:
                report["unchanged"][object_type] += 1
                continue
            drafts.save(cc, object_type, object_id, drafts.payload_of(row), author_of(object_type, row),
                        base_version=int(base["version"]) if base else None)
            report["drafts" if kind == DRAFT else "draft_only"][object_type] += 1
            if len(report["objects"]) < _OBJECTS_KEPT:
                report["objects"].append({"object_type": object_type, "object_id": object_id,
                                          "name": row.get("name") or "", "env": env, "kind": kind})

    for store in stores:
        report["merged"].extend(merge_store(cc, store))

    report["notes"] = notes_for(report)
    report["summary"] = {
        "drafts_created": sum(report["drafts"].values()) + sum(report["draft_only"].values()),
        "pins_dropped": len(report["pins_dropped"]),
    }
    return report


def notes_for(report: Dict[str, Any]) -> List[str]:
    notes: List[str] = []
    where = " and ".join(e.capitalize() for e in report.get("sources") or []) or "Dev and Test"
    if any(report["drafts"].values()):
        notes.append(f"{counts_phrase(report['drafts'])} had newer work in {where} than here; that work is now "
                     "the draft (Unpublished changes), and what people use is unchanged until someone publishes it.")
    if any(report["draft_only"].values()):
        notes.append(f"{counts_phrase(report['draft_only'])} existed only in {where}; each is now a draft that "
                     "has never been published, which only the people who can manage it see.")
    if report.get("kept_existing_drafts"):
        notes.append(f"{report['kept_existing_drafts']} object(s) already had a draft, which was left as it was.")
    if report.get("pins_remapped"):
        notes.append(f"{report['pins_remapped']} widget version pin(s) in imported views were moved to the "
                     "version here with the same code.")
    dropped = report.get("pins_dropped") or []
    for pin in dropped[:_NOTE_LIMIT]:
        notes.append(f"View '{pin['name'] or pin['app_id']}' pinned widget {pin['widget_id']} to "
                     f"{pin['env'].capitalize()} version {pin['version']}, which has no copy with the same code "
                     "here; its draft now shows the widget's latest published version.")
    if len(dropped) > _NOTE_LIMIT:
        notes.append(f"…and {len(dropped) - _NOTE_LIMIT} more pins like that.")
    held = {}
    for entry in report.get("merged") or []:
        if entry.get("held_back"):
            held[entry["table"]] = held.get(entry["table"], 0) + entry["held_back"]
    if held.get("archived_views"):
        notes.append(f"{held['archived_views']} view(s) archived in {where} are live here, and stay live.")
    if held.get("app_links"):
        notes.append(f"{held['app_links']} link name(s) from {where} belong to views that already have a name "
                     "here and were not added, so published views keep the names people know.")
    return notes


def _consolidate(_settings_conn) -> Tuple[str, Dict[str, Any]]:
    from database import content_env, get_db_connection

    content = get_db_connection(content_env(), pooled=False, physical=True)
    try:
        stores, notes = open_legacy_stores(store_identity(content))
        if not stores:
            return SKIPPED, {"sources": [], "notes": notes or ["There were no Dev or Test workspaces to bring over."],
                             "summary": {"drafts_created": 0, "pins_dropped": 0}}
        try:
            cc = content.cursor()
            report = fold(cc, stores)
            content.commit()
        except Exception:
            content.rollback()
            raise
        finally:
            close_stores(stores)
        report["notes"] = notes + report["notes"]
        logger.warning("Folded %s into the %s content store: %s drafts, %s pins dropped",
                       ", ".join(report["sources"]), content_env(),
                       report["summary"]["drafts_created"], report["summary"]["pins_dropped"])
        return DONE, report
    finally:
        content.close()


def run_once() -> Optional[Dict[str, Any]]:
    """Fold Dev and Test into drafts, once per deployment. Never raises; see `run_step`."""
    return run_step(STEP, _consolidate)
