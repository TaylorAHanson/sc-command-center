"""Widgets as the library holds them (/api/widgets).

A widget has published versions (rows of `widgets`) and at most one draft
(`object_drafts`, see `services/drafts.py`). Who reaches it is its access list
(`services/access.py`): people who can use it see its published versions,
people who can manage it also see and save its draft, publish, certify and
delete it. Domains are labels for filtering; they decide nothing here.

**A view lends its widgets.** USE on a view grants read of the latest published
version of every widget it places, and of each exact published version it pins
(`props._version`) — never a draft, and never anything the view doesn't place.
So a view shared with someone renders for them without every widget on it being
shared too, as a dashboard's charts do. MANAGE on a view lends the same for what
its draft places. Those rows come back marked `in_library: false`: the registry
needs them to render the view, the library must not offer them.

Routes still accept the `env` older clients and stored widget code send; there
is one content store, so nothing reads it.
"""
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
import json
import logging
import uuid

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_db_connection
from middleware.auth import get_db_client
from routes.roles import _get_current_username
from services import access, drafts
from services import activity
from services.creator_stats import is_person, unowned_sql

router = APIRouter()

WIDGET = access.WIDGET
MANAGE, USE = access.MANAGE, access.USE

# NOTE: `_get_current_username` comes from `routes.roles` (imported above) and goes
# through `services.caller_identity`. This module used to define its own copy right
# here, which shadowed the import and called `w.current_user()` — but `current_user`
# is a property returning a `CurrentUserAPI`, and that object is not callable, so
# every single call raised and fell into the except branch. Widgets were therefore
# stamped `created_by = "dev"` locally and `"unknown"` in the deployment, which is
# how authorship went missing. Don't reintroduce a local resolver.


@router.get("/me")
def get_current_user(w: WorkspaceClient = Depends(get_db_client)):
    """Return the current user's identity."""
    return {"user": _get_current_username(w)}


# --------------------------------------------------------------------- pure rules

#: What a library row carries, published or draft. `snapshot` is not among them:
#: thumbnails come from `/custom/snapshots` (see `get_custom_widgets`).
LIBRARY_FIELDS = (
    "id", "version", "name", "description", "category", "domain",
    "default_w", "default_h", "configuration_mode", "config_schema",
    "data_source_type", "data_source", "help_text", "open_in_new_tab_link",
    "layout_kind", "is_executable", "is_certified", "created_by", "timestamp",
    "published_by", "published_at", "has_snapshot", "is_latest", "tsx_code",
)

#: Body keys a save may name each draft column by. The studio sends camelCase for
#: some, older clients snake_case; both have always been accepted.
_BODY_KEYS: Dict[str, Tuple[str, ...]] = {
    "name": ("name",),
    "description": ("description",),
    "category": ("category",),
    "domain": ("domain",),
    "default_w": ("default_w", "defaultW"),
    "default_h": ("default_h", "defaultH"),
    "tsx_code": ("tsx_code",),
    "configuration_mode": ("configurationMode", "configuration_mode"),
    "config_schema": ("configSchema", "config_schema"),
    "data_source_type": ("data_source_type",),
    "data_source": ("data_source",),
    "help_text": ("help_text",),
    "open_in_new_tab_link": ("open_in_new_tab_link",),
}
_DEFAULTS: Dict[str, Any] = {
    "name": "Untitled Widget", "description": "", "category": "Custom", "domain": "General",
    "default_w": 6, "default_h": 6, "tsx_code": "", "configuration_mode": "none",
    "config_schema": None, "data_source_type": "none", "data_source": None,
    "help_text": None, "open_in_new_tab_link": None,
}


def layout_kind(widget: dict) -> str:
    """What a save body says the widget is: a page, or else a card."""
    return "page" if widget.get("layout_kind") == "page" else "card"


def widget_payload(body: Dict[str, Any], existing: Optional[Dict[str, Any]], created_by: str) -> Dict[str, Any]:
    """The draft a save body describes, over what the widget already holds.

    A key the body leaves out keeps its current value rather than resetting to a
    default, so a client that saves part of a widget can't blank the rest. The
    author is never taken from the body: it is whoever created the widget.
    """
    held = existing or {}
    out: Dict[str, Any] = {}
    for column, keys in _BODY_KEYS.items():
        key = next((k for k in keys if k in body), None)
        if key is not None:
            out[column] = body[key]
        elif column in held:
            out[column] = held[column]
        else:
            out[column] = _DEFAULTS[column]
    if "layout_kind" in body or "layout_kind" not in held:
        out["layout_kind"] = layout_kind(body)
    else:
        out["layout_kind"] = held.get("layout_kind") or "card"
    # The column is TEXT. A draft holds it as JSON and publish copies it verbatim,
    # so a client that sends the parsed list would otherwise fail only at publish.
    if isinstance(out["config_schema"], (list, dict)):
        out["config_schema"] = json.dumps(out["config_schema"])
    executable = next((body[k] for k in ("isExecutable", "is_executable") if k in body), held.get("is_executable", 0))
    out["is_executable"] = 1 if executable else 0
    # A save that couldn't capture a thumbnail sends none; that isn't a request
    # to drop the one the widget has.
    out["snapshot"] = body.get("snapshot") or held.get("snapshot")
    out["created_by"] = held.get("created_by") or created_by
    return out


def summary_of(counts: Optional[Dict[str, Any]]) -> str:
    """'private', 'shared' or 'everyone' from an ACL's counts; `accessSummaryFromCount` in src/sharing.ts."""
    if not counts:
        return "private"
    if counts.get("everyone"):
        return "everyone"
    return "shared" if int(counts.get("entries") or 0) > 1 else "private"


def draft_row(widget_id: str, draft: Dict[str, Any], latest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A draft in the library's row shape: version 0, with its whole source.

    It is the latest row only when nothing has been published, so the registry
    keeps rendering the published version under the widget's plain id.
    """
    payload = draft.get("payload") or {}
    row = {k: (latest or {}).get(k) for k in LIBRARY_FIELDS}
    for k in LIBRARY_FIELDS:
        if k in payload:
            row[k] = payload[k]
    row.update(
        id=widget_id,
        version=0,
        is_latest=latest is None,
        is_certified=0,
        layout_kind=payload.get("layout_kind") or row.get("layout_kind") or "card",
        has_snapshot=bool(payload.get("snapshot")) or bool((latest or {}).get("has_snapshot")),
        timestamp=draft.get("updated_at"),
        published_by=None,
        published_at=None,
        tsx_code=payload.get("tsx_code") or "",
        is_draft=True,
        base_version=draft.get("base_version"),
        draft_updated_by=draft.get("updated_by"),
    )
    return row


def view_grants(specs: Iterable[Dict[str, Any]]) -> Tuple[Set[str], Set[str]]:
    """What views lend: every widget id they place, and every `id@version` they pin.

    An id counts even when it is placed pinned, because a pin whose version is
    gone falls back to the latest one in the browser.
    """
    from services.app_spec import placed_widgets

    latest: Set[str] = set()
    pins: Set[str] = set()
    for spec in specs:
        ids, pinned = placed_widgets(spec)
        latest.update(ids)
        pins.update(pinned)
    return latest, pins


def shape_rows(
    published: Sequence[Dict[str, Any]],
    pending: Dict[str, Dict[str, Any]],
    levels: Optional[Dict[str, str]],
    *,
    lent_latest: Iterable[str] = (),
    lent_pins: Iterable[str] = (),
    sharing: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """The rows a caller gets, from what is stored and what they may reach.

    ``levels`` is the caller's level per widget id, or None for an app admin
    (MANAGE on everything). ``pending`` is the drafts; only a manager's are
    used. A widget the caller has no level on still contributes the rows a view
    lends them (``lent_latest`` / ``lent_pins``), and nothing else — not the
    rest of its version list, not its draft, not its sharing.
    """
    lent_latest, lent_pins = set(lent_latest), set(lent_pins)
    sharing = sharing or {}
    by_id: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    newest: Dict[str, Dict[str, Any]] = {}
    for r in published:
        by_id.setdefault(r["id"], []).append(r)
        if r.get("is_latest"):
            newest[r["id"]] = r

    out: List[Dict[str, Any]] = []
    for widget_id in list(by_id) + [i for i in pending if i not in by_id]:
        level = MANAGE if levels is None else levels.get(widget_id)
        draft = pending.get(widget_id) if level == MANAGE else None
        latest = newest.get(widget_id)
        version = latest["version"] if latest else None
        common = {
            "access": level,
            "state": drafts.state_of(draft is not None, version),
            "has_draft": draft is not None,
            "published_version": version,
            "is_draft": False,
        }
        if level:
            common["sharing"] = sharing.get(widget_id) or "private"
            for r in by_id.get(widget_id, []):
                out.append({**r, **common})
            if draft is not None:
                out.append({**draft_row(widget_id, draft, latest), **common, "is_draft": True})
            continue
        for r in by_id.get(widget_id, []):
            if (r.get("is_latest") and widget_id in lent_latest) or f"{widget_id}@{r['version']}" in lent_pins:
                out.append({**r, **common, "in_library": False})
    return out


# --------------------------------------------------------------------- reads

def library_rows(c, ids: Optional[List[str]] = None, pinned: Sequence[str] = ()) -> List[dict]:
    """Published rows for every widget or only ``ids``, before any access is applied.

    Every version is listed but only the current one carries its source, plus any
    named in ``pinned`` (`id@version`).
    """
    # `is_latest` is computed here rather than by fetching everything and sorting
    # in Python, so the old versions' source never leaves Postgres.
    with_source = "version = MAX(version) OVER (PARTITION BY id)"
    params: list = []
    if pinned:
        with_source += " OR (id || '@' || version::text) = ANY(%s)"
        params.append(list(pinned))
    where = "is_deprecated = 0"
    if ids is not None:
        where += " AND id = ANY(%s)"
        params.append(list(ids))
    c.execute(f'''
        SELECT id, version, name, description, category, domain,
               default_w, default_h, configuration_mode, config_schema,
               data_source_type, data_source, help_text, open_in_new_tab_link,
               COALESCE(layout_kind, 'card') AS layout_kind,
               is_executable, is_certified, created_by, timestamp,
               published_by, published_at,
               (snapshot IS NOT NULL AND snapshot <> '') AS has_snapshot,
               (version = MAX(version) OVER (PARTITION BY id)) AS is_latest,
               CASE WHEN {with_source} THEN tsx_code END AS tsx_code
        FROM widgets
        WHERE {where}
        ORDER BY timestamp DESC
    ''', tuple(params) or None)
    columns = [desc[0] for desc in c.description]
    return [dict(zip(columns, row)) for row in c.fetchall()]


def _sharing() -> Dict[str, str]:
    """Each widget's access summary, for the library's icons. A failure costs the icons only."""
    try:
        return {object_id: summary_of(counts)
                for (_, object_id), counts in access.acl_summaries(WIDGET).items()}
    except Exception as e:  # noqa: BLE001
        logging.info("Could not read widget sharing summaries: %s", e)
        return {}


def lent_by_views(c, who: access.Caller) -> Tuple[Set[str], Set[str]]:
    """What the views this caller can open lend them; see the module docstring.

    USE reads a view's latest published version; MANAGE its draft as well. An
    archived view lends nothing to someone who can only use it, since it is out
    of circulation for them.
    """
    from services.app_spec import read_spec

    grants = access.grants_for(who, access.APP)
    if not grants:
        return set(), set()
    ids = list(grants)
    c.execute("SELECT id FROM archived_views WHERE id = ANY(%s)", (ids,))
    archived = {r[0] for r in c.fetchall()}
    readable = [i for i in ids if grants[i] == MANAGE or i not in archived]
    if not readable:
        return set(), set()
    c.execute(
        """
        SELECT d.id, d.spec_json, d.widgets_json FROM dashboard_views d
        INNER JOIN (SELECT id, MAX(version) AS version FROM dashboard_views
                    WHERE id = ANY(%s) GROUP BY id) m
                ON d.id = m.id AND d.version = m.version
        """,
        (readable,),
    )
    specs = [read_spec(str(i), spec_json, widgets_json) for i, spec_json, widgets_json in c.fetchall()]
    managed = [i for i in readable if grants[i] == MANAGE]
    for app_id, held in (drafts.drafts(c, access.APP, managed) if managed else {}).items():
        payload = held.get("payload") or {}
        specs.append(read_spec(app_id, payload.get("spec_json"), payload.get("widgets_json")))
    return view_grants(specs)


def caller_rows(c, who: access.Caller) -> List[Dict[str, Any]]:
    """`/custom` for this caller: what they can reach, plus what their views lend them."""
    sharing = _sharing()
    if who.is_admin:
        return shape_rows(library_rows(c), drafts.drafts(c, WIDGET), None, sharing=sharing)
    levels = access.grants_for(who, WIDGET)
    lent_latest, lent_pins = lent_by_views(c, who)
    wanted = set(levels) | lent_latest | {p.rpartition("@")[0] for p in lent_pins}
    published = library_rows(c, sorted(wanted), sorted(lent_pins)) if wanted else []
    managed = [i for i, level in levels.items() if level == MANAGE]
    pending = drafts.drafts(c, WIDGET, managed) if managed else {}
    return shape_rows(published, pending, levels, lent_latest=lent_latest, lent_pins=lent_pins, sharing=sharing)


def bundle_rows(c, who: access.Caller, ids: Sequence[str], pinned: Sequence[str] = (), *,
                draft: bool = False) -> List[Dict[str, Any]]:
    """The rows for the widgets one view places, for a caller already allowed to open it.

    The view lends every one of them (see the module docstring), so nothing here
    needs a grant on the widget. ``draft`` is the view's draft mode: the widget
    drafts this caller manages come too, as they do in the library.
    """
    if not ids:
        return []
    levels = None if who.is_admin else access.levels_for(who, WIDGET, ids)
    managed = list(ids) if levels is None else [i for i, level in levels.items() if level == MANAGE]
    pending = drafts.drafts(c, WIDGET, managed) if draft and managed else {}
    return shape_rows(library_rows(c, list(ids), pinned), pending, levels,
                      lent_latest=ids, lent_pins=pinned, sharing=_sharing())


@router.get("/custom")
def get_custom_widgets(w: WorkspaceClient = Depends(get_db_client)):
    """Every widget the caller can reach — with the source of the current version only.

    This answers the first request the app makes, so what it *doesn't* send matters
    more than what it does. It used to be `SELECT *`: every version of every widget,
    each carrying its full source and its base64 thumbnail. That grew without bound
    — 30 widgets with a few dozen versions each is tens of megabytes over the wire,
    and the browser then compiled every row of it, freezing the page for long
    enough that Chrome offered to end it.

    Older versions are still listed, because the version dropdown on a placed widget
    has to know they exist, but only their metadata: the source of one comes from
    `/version` if somebody actually pins it. Thumbnails come from
    `/custom/snapshots` when the library is opened, which is the only place they're
    shown; here they'd be paid for on every page load by everyone.

    Each row says the caller's `access` and the widget's `state`. A widget the
    caller manages that has a draft adds one row with `is_draft: true`, version 0
    and its whole source; a draft-only widget has only that row.
    """
    who = access.caller(w)
    conn = get_db_connection()
    try:
        rows = caller_rows(conn.cursor(), who)
        conn.commit()
    finally:
        conn.close()
    return {"widgets": rows}


@router.get("/custom/snapshots")
def get_widget_snapshots(w: WorkspaceClient = Depends(get_db_client)):
    """Thumbnails for what the library shows of each widget, keyed by widget id.

    Split out of `/custom` because these are the heaviest thing the app stores — a
    base64 PNG per widget — and the only place they are shown is the Widget
    Library, which most sessions never open. The library shows a widget's latest
    published version, or its draft when it has never been published.
    """
    who = access.caller(w)
    levels = None if who.is_admin else access.grants_for(who, WIDGET)
    if levels is not None and not levels:
        return {"snapshots": {}}

    conn = get_db_connection()
    try:
        c = conn.cursor()
        params: list = []
        only = ""
        if levels is not None:
            only = " AND id = ANY(%s)"
            params.append(list(levels))
        c.execute(f'''
            SELECT id, snapshot FROM (
                SELECT id, snapshot, version,
                       MAX(version) OVER (PARTITION BY id) AS latest
                FROM widgets WHERE is_deprecated = 0{only}
            ) w
            WHERE version = latest AND snapshot IS NOT NULL AND snapshot <> ''
        ''', tuple(params) or None)
        snapshots = {r[0]: r[1] for r in c.fetchall()}
        c.execute(f"SELECT DISTINCT id FROM widgets WHERE is_deprecated = 0{only}", tuple(params) or None)
        has_published = {r[0] for r in c.fetchall()}
        managed = None if levels is None else [i for i, level in levels.items() if level == MANAGE]
        for widget_id, held in drafts.drafts(c, WIDGET, managed).items():
            shot = (held.get("payload") or {}).get("snapshot")
            if widget_id not in has_published and shot:
                snapshots[widget_id] = shot
        conn.commit()
    finally:
        conn.close()
    return {"snapshots": snapshots}


def _may_read_version(c, who: access.Caller, widget_id: str, version: int) -> bool:
    """A level on the widget, or a view that lends this version (see the module docstring)."""
    if access.level_for(who, WIDGET, widget_id):
        return True
    lent_latest, lent_pins = lent_by_views(c, who)
    if f"{widget_id}@{version}" in lent_pins:
        return True
    return widget_id in lent_latest and drafts.published_version(c, WIDGET, widget_id) == version


@router.get("/history")
def get_widget_history(widget_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Every published version of a widget, newest first.

    Carries each version's size but not its code: the size is what tells a version
    apart at a glance (a 12-line entry under a 240-line one is the turn that ate
    the widget), while shipping every version's source would make the list heavy
    for no one's benefit. Widget Studio fetches the code for the one version it
    restores from `/version`. `is_certified` is here so the studio can badge the
    versions that have been reviewed.
    """
    who = access.caller(w)
    level = access.require(who, WIDGET, widget_id, USE, not_found="Widget not found")
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT version, name, created_by, timestamp, published_by, published_at, is_certified, domain, tsx_code "
            "FROM widgets WHERE id = %s AND is_deprecated = 0 ORDER BY version DESC",
            (widget_id,)
        )
        columns = [d[0] for d in c.description]
        rows = []
        for row in c.fetchall():
            entry = dict(zip(columns, row))
            code = entry.pop("tsx_code", None) or ""
            entry["lines"] = sum(1 for line in code.split("\n") if line.strip())
            entry["chars"] = len(code)
            rows.append(entry)
        has_draft = level == MANAGE and drafts.read(c, WIDGET, widget_id) is not None
        conn.commit()
    finally:
        conn.close()
    published = rows[0]["version"] if rows else None
    return {"history": rows, "published_version": published,
            "state": drafts.state_of(has_draft, published), "access": level}


@router.get("/version")
def get_widget_version(widget_id: str, version: int, w: WorkspaceClient = Depends(get_db_client)):
    """Return one published version in full, including its code.

    Backs Restore in Widget Studio — the studio loads this into the editor, where
    it becomes an ordinary unsaved change — and an older version someone pinned on
    a view. A view that pins a version lends it to whoever can open the view.
    """
    who = access.caller(w)
    conn = get_db_connection()
    try:
        c = conn.cursor()
        if not _may_read_version(c, who, widget_id, version):
            raise HTTPException(status_code=404, detail=f"Version {version} of this widget was not found.")
        c.execute("SELECT * FROM widgets WHERE id = %s AND version = %s", (widget_id, version))
        row = c.fetchone()
        columns = [d[0] for d in c.description]
        conn.commit()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Version {version} of this widget was not found.")
    return {"widget": dict(zip(columns, row))}


@router.get("/custom/{widget_id}/draft")
def get_widget_draft(widget_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """The widget's draft (for a manager), where it stands, and the caller's access.

    `published` is the latest published version in full, so the studio can open a
    widget with no draft without a second request.
    """
    who = access.caller(w)
    level = access.require(who, WIDGET, widget_id, USE, not_found="Widget not found")
    conn = get_db_connection()
    try:
        c = conn.cursor()
        latest = drafts.latest(c, WIDGET, widget_id)
        held = drafts.read(c, WIDGET, widget_id) if level == MANAGE else None
        conn.commit()
    finally:
        conn.close()
    if latest is None and held is None:
        raise HTTPException(status_code=404, detail="Widget not found")
    version = int(latest["version"]) if latest else None
    return {
        "draft": drafts.merge(latest, held, widget_id) if held is not None else None,
        "published": latest,
        "published_version": version,
        "state": drafts.state_of(held is not None, version),
        "access": level,
    }


# --------------------------------------------------------------------- writes

def _reject_unsafe(tsx_code, data_source, data_source_type, is_executable) -> None:
    """Refuse to store a widget that breaks the runtime's safety rules.

    Applied on every save and again on publish: an author who cannot save unsafe
    code but can publish a draft that arrived some other way (an import, the move
    from the Dev/Test workspaces) has not been stopped by anything.
    """
    from services.widget_safety import review_widget

    problems = review_widget(
        tsx_code or "",
        data_source or "",
        data_source_type or "none",
        bool(is_executable),
    )
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))


def _reject_payload(payload: Dict[str, Any]) -> None:
    _reject_unsafe(payload.get("tsx_code"), payload.get("data_source"), payload.get("data_source_type"),
                   payload.get("is_executable"))


def _save_draft(c, widget_id: str, body: Dict[str, Any], username: str,
                existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = widget_payload(body, existing, username)
    if existing is not None and (not (payload.get("name") or "").strip() or not (payload.get("tsx_code") or "").strip()):
        raise HTTPException(status_code=400, detail="Name and tsx_code are required")
    _reject_payload(payload)
    drafts.save(c, WIDGET, widget_id, payload, username)
    return payload


@router.post("/custom")
def create_custom_widget(widget: dict, w: WorkspaceClient = Depends(get_db_client)):
    """Start a widget as a draft only its creator (and admins) can see until it's published.

    Anyone may build. A body naming a widget that already exists saves its draft
    instead, which needs Can manage like any other save.
    """
    who = access.caller(w)
    created_by = _get_current_username(w)
    widget_id = str(widget.get("id") or uuid.uuid4())

    conn = get_db_connection()
    c = conn.cursor()
    try:
        existing = drafts.current(c, WIDGET, widget_id, MANAGE)
        # A retired widget's id still has versions and an access list; reusing it
        # would hand them to whoever named it.
        c.execute("SELECT 1 FROM widgets WHERE id = %s LIMIT 1", (widget_id,))
        if existing is not None or c.fetchone() is not None:
            access.require(who, WIDGET, widget_id, MANAGE, not_found="Widget not found")
        payload = _save_draft(c, widget_id, widget, created_by, existing)
        state = drafts.state_of(True, (existing or {}).get("version") or None)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if existing is None:
        # After the commit: the access list is another connection, and a failure
        # here leaves a widget only admins can reach rather than one anyone can.
        try:
            access.grant_owner(WIDGET, widget_id, created_by)
        except Exception:  # noqa: BLE001
            logging.exception("Could not give %s Can manage on new widget %s", created_by, widget_id)
        activity.record(who.username, "widget.create", WIDGET, widget_id)
    return {"status": "success", "id": widget_id, "created_by": payload["created_by"], "state": state}


@router.put("/custom/{widget_id}")
def update_custom_widget(widget_id: str, widget: dict, w: WorkspaceClient = Depends(get_db_client)):
    """Save the draft in place. Nothing anyone else sees changes until Publish."""
    who = access.caller(w)
    access.require(who, WIDGET, widget_id, MANAGE, not_found="Widget not found")
    username = _get_current_username(w)

    conn = get_db_connection()
    c = conn.cursor()
    try:
        existing = drafts.current(c, WIDGET, widget_id, MANAGE)
        if existing is None:
            raise HTTPException(status_code=404, detail="Widget not found")
        _save_draft(c, widget_id, widget, username, existing)
        version = drafts.published_version(c, WIDGET, widget_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"status": "success", "id": widget_id, "state": drafts.state_of(True, version)}


class VersionBody(BaseModel):
    version: int


class CertifyBody(BaseModel):
    version: Optional[int] = None
    certified: bool = True


def _managed(w: WorkspaceClient, widget_id: str) -> access.Caller:
    who = access.caller(w)
    access.require(who, WIDGET, widget_id, MANAGE, not_found="Widget not found")
    return who


@router.post("/custom/{widget_id}/publish")
def publish_widget(widget_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Make the draft the next published version, which everyone it's shared with sees."""
    who = _managed(w, widget_id)
    conn = get_db_connection()
    c = conn.cursor()
    try:
        held = drafts.read(c, WIDGET, widget_id)
        if held is not None:
            _reject_payload(held.get("payload") or {})
        version = drafts.publish(c, WIDGET, widget_id, who.username)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    activity.record(who.username, "widget.publish", WIDGET, widget_id, {"version": version})
    return {"status": "success", "id": widget_id, "version": version, "state": drafts.PUBLISHED}


@router.post("/custom/{widget_id}/discard")
def discard_widget_draft(widget_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Throw the draft away and go back to the published version."""
    who = _managed(w, widget_id)
    conn = get_db_connection()
    c = conn.cursor()
    try:
        version = drafts.published_version(c, WIDGET, widget_id)
        if version is None:
            # With nothing published, the draft is the whole widget.
            raise HTTPException(
                status_code=409,
                detail="This widget has never been published, so discarding its draft would delete it. Delete it instead.",
            )
        discarded = drafts.discard(c, WIDGET, widget_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if discarded:
        activity.record(who.username, "widget.discard", WIDGET, widget_id)
    return {"status": "success", "id": widget_id, "discarded": discarded, "state": drafts.PUBLISHED}


@router.post("/custom/{widget_id}/revert")
def revert_widget(widget_id: str, body: VersionBody, w: WorkspaceClient = Depends(get_db_client)):
    """Copy a published version into the draft, to be published again (or not)."""
    who = _managed(w, widget_id)
    conn = get_db_connection()
    c = conn.cursor()
    try:
        drafts.revert(c, WIDGET, widget_id, body.version, who.username)
        version = drafts.published_version(c, WIDGET, widget_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    activity.record(who.username, "widget.revert", WIDGET, widget_id, {"version": body.version})
    return {"status": "success", "id": widget_id, "state": drafts.state_of(True, version)}


@router.post("/custom/{widget_id}/certify")
def certify_widget(widget_id: str, body: CertifyBody, w: WorkspaceClient = Depends(get_db_client)):
    """Mark a published version as reviewed, or take that back. The latest one unless named.

    A manager's call, like publishing. Certification belongs to one version's
    code, which is why publishing never carries it over (`drafts.RESET_ON_PUBLISH`).
    """
    who = _managed(w, widget_id)
    conn = get_db_connection()
    c = conn.cursor()
    try:
        version = body.version if body.version is not None else drafts.published_version(c, WIDGET, widget_id)
        if version is None:
            raise HTTPException(status_code=409, detail="Publish this widget before certifying it.")
        c.execute(
            "UPDATE widgets SET is_certified = %s WHERE id = %s AND version = %s AND is_deprecated = 0",
            (1 if body.certified else 0, widget_id, version),
        )
        if c.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Version {version} of this widget was not found.")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    activity.record(who.username, "widget.certify", WIDGET, widget_id, {"version": version, "certified": body.certified})
    return {"status": "success", "id": widget_id, "version": version, "certified": body.certified}


@router.post("/custom/{widget_id}/snapshot")
def update_widget_snapshot(widget_id: str, payload: dict, w: WorkspaceClient = Depends(get_db_client)):
    """Backfill or refresh a thumbnail for what the library shows of a widget.

    The latest published row is updated in place rather than given a new version,
    since the snapshot is presentation-only and not part of the published code. A
    draft gets it too, or the next publish would bring the old picture back.
    """
    _managed(w, widget_id)
    snapshot = payload.get("snapshot")
    if not snapshot:
        raise HTTPException(status_code=400, detail="snapshot is required")
    conn = get_db_connection()
    c = conn.cursor()
    try:
        version = drafts.published_version(c, WIDGET, widget_id)
        if version is not None:
            c.execute("UPDATE widgets SET snapshot = %s WHERE id = %s AND version = %s", (snapshot, widget_id, version))
        # In place, not `drafts.save`: a new thumbnail isn't an edit, and the draft
        # should still say who last changed the widget.
        c.execute(
            "UPDATE object_drafts SET payload = jsonb_set(payload, '{snapshot}', to_jsonb(%s::text)) "
            "WHERE object_type = %s AND object_id = %s",
            (snapshot, WIDGET, widget_id),
        )
        if version is None and c.rowcount == 0:
            raise HTTPException(status_code=404, detail="Widget not found")
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
    return {"status": "success", "id": widget_id, "version": version}


@router.post("/custom/{widget_id}/claim")
def claim_custom_widget(widget_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Put your name on a widget nobody is recorded as having written.

    Authorship was recorded by a resolver that never worked — it shipped broken in
    the same commit that added the `created_by` column — so the credit for every
    widget built before that was fixed is a placeholder, and nothing we stored can
    recover it. `action_logs` has no username, `widget_runs` says who *used* a
    widget, and a view only says who placed one. So the person who recognises their
    own work says so, and that is the only route back to a real name.

    It can only ever fill a blank. A widget with a real author is not claimable —
    including by that author's colleague — and the check happens inside the UPDATE
    so that two people claiming at once can't overwrite each other. Claiming needs
    Can manage, the right to change the widget at all.
    """
    who = access.caller(w)
    me = _get_current_username(w)
    if not is_person(me):
        raise HTTPException(status_code=403, detail="We can't tell who you are, so we can't credit you.")
    access.require(who, WIDGET, widget_id, MANAGE, not_found="Widget not found")

    conn = get_db_connection()
    try:
        c = conn.cursor()
        current = drafts.current(c, WIDGET, widget_id, MANAGE)
        if current is None:
            raise HTTPException(status_code=404, detail="Widget not found")
        owner = current.get("created_by")
        if is_person(owner):
            raise HTTPException(status_code=409, detail=f"{owner} is already credited with this widget.")

        # Every version, because no version ever held a real name: this is filling
        # in a blank rather than rewriting history. The condition repeats the
        # placeholder test so the row can't have been claimed since we read it.
        unowned, params = unowned_sql()
        c.execute(
            f"UPDATE widgets SET created_by = %s WHERE id = %s AND {unowned}",
            [me, widget_id, *params],
        )
        claimed = c.rowcount
        # The draft is published as it stands, so it has to carry the name too.
        held = drafts.read(c, WIDGET, widget_id)
        if held is not None and not is_person((held.get("payload") or {}).get("created_by")):
            drafts.save(c, WIDGET, widget_id, {**held["payload"], "created_by": me}, held.get("updated_by") or me,
                        base_version=held.get("base_version"))
            claimed += 1
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logging.exception("Failed to claim widget %s", widget_id)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    if not claimed:
        raise HTTPException(status_code=409, detail="Somebody else claimed this widget first.")
    return {"status": "success", "id": widget_id, "created_by": me, "versions": claimed}


@router.delete("/custom/{widget_id}")
def delete_custom_widget(widget_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Retire a widget: its versions are deprecated (not removed) and its draft dropped.

    A widget that was never published is only its draft, so deleting it is
    permanent and its access list goes with it.
    """
    who = _managed(w, widget_id)
    conn = get_db_connection()
    c = conn.cursor()
    try:
        version = drafts.published_version(c, WIDGET, widget_id)
        c.execute("UPDATE widgets SET is_deprecated = 1 WHERE id = %s", (widget_id,))
        retired = c.rowcount
        dropped = drafts.discard(c, WIDGET, widget_id)
        if not retired and not dropped:
            raise HTTPException(status_code=404, detail="Widget not found")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if version is None and not retired:
        try:
            access.delete_acl(WIDGET, widget_id)
        except Exception:  # noqa: BLE001
            logging.exception("Could not remove the access list of deleted widget %s", widget_id)
    activity.record(who.username, "widget.delete", WIDGET, widget_id)
    return {"status": "deleted", "id": widget_id}
