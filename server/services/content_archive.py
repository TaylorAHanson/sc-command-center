"""Archiving views and widgets: by hand, and automatically once nobody uses them.

Archiving takes an object out of circulation without deleting anything. Every
version, the draft and the access list stay, so restoring is exact. A view's
marker is a row in `archived_views` (which predates this module, see
`routes/apps.py`), a widget's a row in `archived_widgets`; both are keyed by id
rather than being a flag on the versioned table, because a flag would travel
with one version and be lost on a revert. `reason` says `manual` or `unused`.

What archiving changes:

* **A view** leaves Discover, search, the sidebar and the creator board, as it
  always has. Its link answers 410 with who archived it and why
  (`routes/apps.py::_open`), so the page can say "archived" and offer Restore
  to its managers instead of a bare "not found".
* **A widget** leaves the Widget Library, the studio's `search_widgets` and the
  pickers (its rows come back `in_library: false`), and **keeps rendering**
  wherever a view already places it. That is the rule that makes archiving a
  widget safe: nothing anyone is looking at breaks.

Owners and managers (Can manage, `services/access.py`) and Administrators
restore. Restoring resets the clock (`reset_clock`), or the next sweep would
archive the object again on the same old evidence; restoring a view also
restores the widgets the sweep archived only because that view had gone.

**The sweep** (`sweep_job`, every `EVERY_SECONDS`) archives published views and
widgets with no use in `archive_unused_days` (Admin Panel → Settings, default
60, 0 turns it off). What counts as use, and why each is there:

* a view: opened (`view_visits`, folded into `content_last_used` because visits
  are pruned after 35 days), published or saved (its newest version, its draft),
  starred; and it is never archived while featured in Discover or while an
  active schedule reports from it;
* a widget: shown on a view someone opened (the view's open is folded onto every
  widget its catalog row places), added to a view (`widget_runs`), an action run
  (`action_logs`), published or saved; and it is never archived while any live
  view places it — published or draft — or an active schedule runs it;
* for both, **the moment archiving was switched on** (`enabled_since`). Nothing
  recorded use before this module existed, and view opens only since Discover,
  so "no use recorded" must not read as "unused": the first deploy, and turning
  the setting back on after it was off, each start a full grace period.

The decision is `is_stale`, pure and tested (`tests/test_content_archive.py`);
the queries only gather its inputs. Each run archives at most `MAX_PER_RUN`
objects, oldest first, so a mistake shows in the Activity tab before it reaches
everything. A source that can't be read (the catalog not built yet, a table
missing) means that kind is skipped this run rather than judged without it, and
the job never raises out of a failure it can survive: the background loop logs
it and startup is never involved.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

APP, WIDGET = "app", "widget"
SETTING = "archive_unused_days"
MANUAL, UNUSED = "manual", "unused"
#: Who the Activity tab says archived something the sweep archived.
SWEEPER = "system"
EVERY_SECONDS = 3600
MAX_PER_RUN = 200
_TABLES = {APP: "archived_views", WIDGET: "archived_widgets"}
_VERB_NOUN = {APP: "view", WIDGET: "widget"}

# --------------------------------------------------------------- process state

_ready = False


def tables_ready() -> None:
    """Called by `database._create_archive_tables` once the tables exist.

    Until then every read here answers "nothing archived" and every hook does
    nothing, so a worker whose startup couldn't reach the database, and every
    test that fakes one, never issues a statement against a missing table.
    """
    global _ready
    _ready = True


def enabled() -> bool:
    return _ready


# --------------------------------------------------------------- the decision

def aware(value: Any) -> Optional[datetime]:
    """A datetime with a zone, or None. Naive values are read as UTC; ISO strings parse."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def last_used(*moments: Any) -> Optional[datetime]:
    """The latest of these moments, ignoring the ones that are missing."""
    seen = [m for m in (aware(v) for v in moments) if m is not None]
    return max(seen) if seen else None


def next_state(state: Dict[str, Any], days: int, now: datetime) -> Tuple[Optional[datetime], Dict[str, Any]]:
    """When archiving was switched on, and the state to save.

    `enabled_since` is set the first time a run sees archiving on, and cleared
    whenever it sees it off, so switching it on again starts a new grace period
    rather than archiving at once everything that went unused in between.
    """
    state = dict(state or {})
    if days <= 0:
        state.pop("enabled_since", None)
        return None, state
    since = aware(state.get("enabled_since"))
    if since is None:
        since = aware(now)
        state["enabled_since"] = since.isoformat()
    return since, state


def is_stale(now: datetime, days: int, since: Optional[datetime], moments: Iterable[Any], *,
             in_use: bool = False) -> bool:
    """Whether something has gone unused long enough to archive.

    `since` (when archiving was switched on) counts as a use, so nothing is
    archived for lacking a history nobody was recording. Anything `in_use` (a
    live view places the widget, a schedule runs it, the view is featured) is
    never stale, whatever its dates say. Off (`days` 0) nothing is.
    """
    if days <= 0 or since is None or in_use:
        return False
    latest = last_used(since, *moments)
    return latest is not None and latest <= aware(now) - timedelta(days=days)


def plan(now: datetime, days: int, since: Optional[datetime], candidates: Sequence[Dict[str, Any]],
         limit: int = MAX_PER_RUN) -> List[Dict[str, Any]]:
    """The candidates to archive, least recently used first, at most `limit`.

    Each candidate is `{"id", "moments": [...], "in_use": bool}`; the result
    adds `last_used`, the latest of its moments and `since`.
    """
    stale = []
    for cand in candidates:
        if is_stale(now, days, since, cand.get("moments") or (), in_use=bool(cand.get("in_use"))):
            stale.append({**cand, "last_used": last_used(since, *(cand.get("moments") or ()))})
    stale.sort(key=lambda c: (c["last_used"], str(c["id"])))
    return stale[:max(limit, 0)]


def mentions(text: str, ids: Iterable[str]) -> Set[str]:
    """Which of these widget ids appear in a view's stored spec.

    Widget ids are UUIDs, so a substring is a placement or a pinned version of
    one; over-counting only ever keeps a widget, never archives one.
    """
    text = text or ""
    return {i for i in ids if i and i in text}


def describe(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """An archive marker as the API hands it out."""
    if not row:
        return None
    at = row.get("timestamp") if "timestamp" in row else row.get("archived_at")
    return {
        "archived_at": at.isoformat() if hasattr(at, "isoformat") else (str(at) if at else None),
        "archived_by": row.get("archived_by") or None,
        "reason": row.get("reason") or MANUAL,
    }


# --------------------------------------------------------------- reads

def _rows(c) -> List[Dict[str, Any]]:
    names = [d[0] for d in c.description]
    return [dict(row) if hasattr(row, "keys") else dict(zip(names, row)) for row in c.fetchall()]


def _savepoint(c, name: str, fn):
    """Run `fn(c)` in a savepoint: a failure rolls back only it, and raises."""
    c.execute(f"SAVEPOINT {name}")
    try:
        out = fn(c)
    except Exception:
        c.execute(f"ROLLBACK TO SAVEPOINT {name}")
        raise
    c.execute(f"RELEASE SAVEPOINT {name}")
    return out


def archived(c, object_type: str, ids: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, Any]]:
    """The archive marker of each of these objects that has one (all, without `ids`).

    Views have always been readable, from `archived_views`; widgets only once
    the table exists. Read in a savepoint: a deployment whose startup couldn't
    add `reason` reads every marker as manual rather than failing the page.
    """
    if object_type == WIDGET and not enabled():
        return {}
    table = _TABLES[object_type]
    wanted = None if ids is None else [i for i in dict.fromkeys(ids) if i]
    if wanted is not None and not wanted:
        return {}
    where, params = ("", ()) if wanted is None else (" WHERE id = ANY(%s)", (wanted,))

    def read(cur, columns):
        cur.execute(f"SELECT id, {columns} FROM {table}{where}", params or None)
        return {r["id"]: describe(r) for r in _rows(cur)}

    try:
        return _savepoint(c, "archive_read", lambda cur: read(cur, "archived_by, reason, timestamp"))
    except Exception as e:  # noqa: BLE001
        if object_type == WIDGET:
            logger.info("Could not read archived widgets: %s", e)
            return {}
        return read(c, "archived_by, timestamp")


def reset_clock(c, object_type: str, ids: Iterable[str]) -> None:
    """Count now as a use of these objects, so a restore isn't undone by the next sweep."""
    wanted = [i for i in dict.fromkeys(ids) if i]
    if not wanted or not enabled():
        return
    try:
        _savepoint(c, "archive_clock", lambda cur: cur.execute(
            "INSERT INTO content_last_used (object_type, object_id, last_used_at) "
            "SELECT %s, id, now() FROM unnest(%s::text[]) AS id "
            "ON CONFLICT (object_type, object_id) DO UPDATE SET last_used_at = EXCLUDED.last_used_at",
            (object_type, wanted),
        ))
    except Exception as e:  # noqa: BLE001 - the restore stands; the sweep may archive it again sooner
        logger.warning("Could not reset the archive clock of %s %s: %s", object_type, wanted, e)


# --------------------------------------------------------------- writes

def archive(c, object_type: str, object_id: str, who: Optional[str], reason: str = MANUAL) -> bool:
    """Mark one object archived, in the caller's transaction. False if it already was."""
    c.execute(f"INSERT INTO {_TABLES[object_type]} (id, archived_by, reason) VALUES (%s, %s, %s) "
              "ON CONFLICT (id) DO NOTHING", (object_id, who, reason))
    return (c.rowcount or 0) != 0


def restore(c, object_type: str, object_id: str) -> bool:
    """Clear one object's marker and reset its clock, in the caller's transaction."""
    c.execute(f"DELETE FROM {_TABLES[object_type]} WHERE id = %s", (object_id,))
    gone = (c.rowcount or 0) != 0
    reset_clock(c, object_type, [object_id])
    return gone


def restore_placed_widgets(c, app_id: str) -> List[str]:
    """Restore the widgets this view places that the sweep archived, and reset their clocks.

    A widget a live view places is never swept, so one the sweep archived among
    this view's went because the view did; bringing the view back brings them
    too. One archived by hand stays archived: a person decided that.
    """
    if not enabled():
        return []
    from services import app_spec, app_store, drafts

    specs = []
    head = app_store.head(c, app_id)
    if head:
        specs.append(app_store.spec_of(head))
    held = drafts.read(c, APP, app_id)
    if held:
        payload = held.get("payload") or {}
        specs.append(app_spec.read_spec(app_id, payload.get("spec_json"), payload.get("widgets_json")))
    ids = sorted({w for s in specs for w in app_store.custom_widget_ids(s)})
    if not ids:
        return []

    def clear(cur) -> List[str]:
        cur.execute("DELETE FROM archived_widgets WHERE id = ANY(%s) AND reason = %s RETURNING id", (ids, UNUSED))
        return [r[0] for r in cur.fetchall()]

    try:
        restored = _savepoint(c, "archive_placed", clear)
    except Exception as e:  # noqa: BLE001 - the view is back; its widgets still render
        logger.warning("Could not restore the widgets view %s places: %s", app_id, e)
        return []
    reset_clock(c, WIDGET, restored)
    return restored


# --------------------------------------------------------------- the sweep

_STATE_KEY = "sweep"

# Each fold reads only what arrived since the last run, with an hour's overlap
# for transactions that committed after the previous run read the clock. Every
# one keeps the later of what is stored and what it found, so folding twice is
# the same as once.
_UPSERT = (
    "INSERT INTO content_last_used (object_type, object_id, last_used_at) {select} "
    "ON CONFLICT (object_type, object_id) DO UPDATE "
    "SET last_used_at = GREATEST(content_last_used.last_used_at, EXCLUDED.last_used_at)"
)
_OPENED = ("SELECT app_id, MAX(last_opened_at) AS at FROM view_visits "
           "WHERE last_opened_at > %(since)s GROUP BY app_id")
FOLDS: Tuple[Tuple[str, str, str], ...] = (
    (APP, "view opens", _UPSERT.format(select=f"SELECT 'app', o.app_id, o.at FROM ({_OPENED}) o")),
    # A widget is used whenever a view showing it is opened. The catalog holds
    # what each published view places, already parsed, so this costs one join.
    (WIDGET, "views showing it opened", _UPSERT.format(
        select=f"SELECT 'widget', w.id, MAX(o.at) FROM ({_OPENED}) o "
               "JOIN view_catalog vc ON vc.id = o.app_id CROSS JOIN LATERAL unnest(vc.widget_ids) AS w(id) "
               "GROUP BY w.id")),
    (WIDGET, "widgets added to views", _UPSERT.format(
        select="SELECT 'widget', widget_id, MAX(timestamp)::timestamptz FROM widget_runs "
               "WHERE timestamp > %(since)s::timestamptz GROUP BY widget_id")),
    (WIDGET, "widget actions", _UPSERT.format(
        select="SELECT 'widget', widget_id, MAX(timestamp)::timestamptz FROM action_logs "
               "WHERE widget_id IS NOT NULL AND timestamp > %(since)s::timestamptz GROUP BY widget_id")),
)

_LIVE_SCHEDULE = "s.status IN ('active', 'needs_reconnect')"

VIEW_CANDIDATES = f"""
SELECT h.id, h.changed_at, d.updated_at::timestamptz AS draft_at, u.last_used_at, f.at AS favorited_at,
       (cur.featured_position IS NOT NULL) AS featured,
       EXISTS (SELECT 1 FROM schedules s WHERE s.source_app_id = h.id AND {_LIVE_SCHEDULE}) AS scheduled
  FROM (SELECT id, MAX(GREATEST(timestamp::timestamptz, published_at::timestamptz)) AS changed_at
          FROM dashboard_views GROUP BY id) h
  LEFT JOIN object_drafts d ON d.object_type = 'app' AND d.object_id = h.id
  LEFT JOIN content_last_used u ON u.object_type = 'app' AND u.object_id = h.id
  LEFT JOIN (SELECT app_id, MAX(created_at) AS at FROM user_favorites GROUP BY app_id) f ON f.app_id = h.id
  LEFT JOIN view_curation cur ON cur.app_id = h.id
 WHERE h.id NOT IN (SELECT id FROM archived_views)
"""

WIDGET_CANDIDATES = f"""
SELECT h.id, h.changed_at, d.updated_at::timestamptz AS draft_at, u.last_used_at,
       EXISTS (SELECT 1 FROM schedules s WHERE s.source_widget_id = h.id AND {_LIVE_SCHEDULE}) AS scheduled
  FROM (SELECT id, MAX(GREATEST(timestamp::timestamptz, published_at::timestamptz)) AS changed_at
          FROM widgets WHERE COALESCE(is_deprecated, 0) = 0 GROUP BY id) h
  LEFT JOIN object_drafts d ON d.object_type = 'widget' AND d.object_id = h.id
  LEFT JOIN content_last_used u ON u.object_type = 'widget' AND u.object_id = h.id
 WHERE h.id NOT IN (SELECT id FROM archived_widgets)
"""

# Written only where nothing has counted as a use since the run decided: a
# restore (which resets the clock) between the read and this write wins.
_ARCHIVE = """
INSERT INTO {table} (id, archived_by, reason)
SELECT id, NULL, %(reason)s FROM unnest(%(ids)s::text[]) AS id
 WHERE NOT EXISTS (SELECT 1 FROM content_last_used u
                    WHERE u.object_type = %(type)s AND u.object_id = id AND u.last_used_at > %(cutoff)s)
ON CONFLICT (id) DO NOTHING
RETURNING id
"""


def _state(c) -> Dict[str, Any]:
    c.execute("SELECT value FROM content_archive_state WHERE key = %s", (_STATE_KEY,))
    row = c.fetchone()
    value = row[0] if row else None
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value or {})


def _save_state(c, state: Dict[str, Any]) -> None:
    c.execute(
        "INSERT INTO content_archive_state (key, value, updated_at) VALUES (%s, %s::jsonb, now()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (_STATE_KEY, json.dumps(state, default=str)),
    )


def fold_usage(c, since: Any) -> Set[str]:
    """Fold usage since `since` into `content_last_used`; the kinds whose every source was read."""
    failed: Set[str] = set()
    for object_type, label, sql in FOLDS:
        try:
            _savepoint(c, "archive_fold", lambda cur, s=sql: cur.execute(s, {"since": since}))
        except Exception as e:  # noqa: BLE001
            failed.add(object_type)
            logger.warning("Archive sweep couldn't read %s: %s", label, e)
    return {APP, WIDGET} - failed


def view_candidates(c) -> List[Dict[str, Any]]:
    c.execute(VIEW_CANDIDATES)
    return [{"id": r["id"], "moments": [r["changed_at"], r["draft_at"], r["last_used_at"], r["favorited_at"]],
             "in_use": bool(r["featured"] or r["scheduled"])} for r in _rows(c)]


def widget_candidates(c) -> List[Dict[str, Any]]:
    c.execute(WIDGET_CANDIDATES)
    return [{"id": r["id"], "moments": [r["changed_at"], r["draft_at"], r["last_used_at"]],
             "in_use": bool(r["scheduled"])} for r in _rows(c)]


def catalog_built(c) -> bool:
    from services import view_catalog

    if not view_catalog.enabled():
        return False
    return bool((view_catalog._state(c, "build") or {}).get("built_at"))


def placed_on_live_views(c, ids: Sequence[str], leaving: Iterable[str] = ()) -> Set[str]:
    """Which of these widgets a view that is staying live places, published or in its draft.

    Published placements come from the catalog (one row per published,
    unarchived view, its widgets already parsed), plus the heads of views still
    queued for it, so one published a moment ago counts. Drafts are read from
    `object_drafts`. `leaving` is the views this run is archiving.
    """
    wanted = sorted(set(ids))
    if not wanted:
        return set()
    gone = sorted(set(leaving))
    c.execute("SELECT DISTINCT w FROM view_catalog vc, unnest(vc.widget_ids) AS w "
              "WHERE vc.widget_ids && %s::text[] AND vc.id <> ALL(%s::text[]) AND w = ANY(%s::text[])",
              (wanted, gone, wanted))
    placed = {r[0] for r in c.fetchall()}
    rest = [i for i in wanted if i not in placed]
    if not rest:
        return placed
    c.execute(
        """
        SELECT COALESCE(d.spec_json, '') || COALESCE(d.widgets_json, '')
          FROM dashboard_views d
          JOIN (SELECT id, MAX(version) AS version FROM dashboard_views
                 WHERE id IN (SELECT app_id FROM view_catalog_queue) GROUP BY id) m
            ON d.id = m.id AND d.version = m.version
         WHERE d.id NOT IN (SELECT id FROM archived_views) AND d.id <> ALL(%s::text[])
        UNION ALL
        SELECT COALESCE(payload->>'spec_json', '') || COALESCE(payload->>'widgets_json', '')
          FROM object_drafts
         WHERE object_type = 'app' AND object_id NOT IN (SELECT id FROM archived_views)
           AND object_id <> ALL(%s::text[])
           AND EXISTS (SELECT 1 FROM unnest(%s::text[]) AS w
                        WHERE strpos(COALESCE(payload->>'spec_json', '') || COALESCE(payload->>'widgets_json', ''), w) > 0)
        """,
        (gone, gone, rest),
    )
    for (text,) in c.fetchall():
        placed |= mentions(text, rest)
    return placed


def _archive_batch(c, object_type: str, chosen: Sequence[Dict[str, Any]], cutoff: datetime) -> List[str]:
    if not chosen:
        return []
    c.execute(_ARCHIVE.format(table=_TABLES[object_type]),
              {"reason": UNUSED, "ids": [x["id"] for x in chosen], "type": object_type, "cutoff": cutoff})
    done = [r[0] for r in c.fetchall()]
    if object_type == APP:
        from services import view_catalog

        for app_id in done:
            view_catalog.touch(c, APP, app_id)
    return done


def sweep(conn, days: int) -> Dict[str, Any]:
    """One run: fold usage, then archive what has gone unused. Returns what it did."""
    c = conn.cursor()
    c.execute("SELECT now()")
    now = aware(c.fetchone()[0])
    state = _state(c)
    previous = aware(state.get("folded_through"))
    readable = fold_usage(c, previous - timedelta(hours=1) if previous else "-infinity")
    if readable == {APP, WIDGET}:
        state["folded_through"] = now.isoformat()
    since, state = next_state(state, days, now)
    _save_state(c, state)
    conn.commit()
    out: Dict[str, Any] = {"views": [], "widgets": [], "since": since, "last_used": {}}
    if since is None:
        return out
    cutoff = now - timedelta(days=days)
    budget = MAX_PER_RUN

    if APP in readable:
        try:
            chosen = plan(now, days, since, view_candidates(c), budget)
            out["views"] = _archive_batch(c, APP, chosen, cutoff)
            out["last_used"].update({x["id"]: x["last_used"] for x in chosen})
            conn.commit()
            budget -= len(out["views"])
        except Exception as e:  # noqa: BLE001 - views wait for the next run; widgets may still go
            conn.rollback()
            logger.warning("Archive sweep skipped views: %s", e)

    if WIDGET in readable and budget > 0:
        try:
            if not catalog_built(c):
                logger.info("Archive sweep skipped widgets: the view catalog isn't built yet")
            else:
                candidates = widget_candidates(c)
                stale = plan(now, days, since, candidates, limit=len(candidates))
                placed = placed_on_live_views(c, [x["id"] for x in stale], out["views"])
                chosen = [x for x in stale if x["id"] not in placed][:budget]
                out["widgets"] = _archive_batch(c, WIDGET, chosen, cutoff)
                out["last_used"].update({x["id"]: x["last_used"] for x in chosen})
                conn.commit()
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            logger.warning("Archive sweep skipped widgets: %s", e)
    return out


def sweep_job() -> None:
    """The background job (`archive.sweep`): apply `archive_unused_days`, where 0 turns it off."""
    if not enabled():
        return
    from database import content_env, get_db_connection
    from services import activity
    from services.settings_store import get_int_setting

    days = get_int_setting(SETTING)
    conn = get_db_connection(content_env())
    try:
        done = sweep(conn, days)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    for object_type, key in ((APP, "views"), (WIDGET, "widgets")):
        for object_id in done[key]:
            used = done["last_used"].get(object_id)
            activity.record(SWEEPER, f"{_VERB_NOUN[object_type]}.archive", object_type, object_id, {
                "reason": UNUSED, "days": days,
                "last_used": used.isoformat() if hasattr(used, "isoformat") else None,
            })
    if done["views"] or done["widgets"]:
        logger.info("Archived %d view(s) and %d widget(s) unused for %d days",
                    len(done["views"]), len(done["widgets"]), days)
