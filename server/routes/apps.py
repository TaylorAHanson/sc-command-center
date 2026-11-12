"""Apps: what a user composes from widgets, agents and data, and shares (/api/apps).

An app is a row in `dashboard_views` under the id the view always had; a view is
an app with one tab. See `services/app_spec.py` for what an app holds and
`services/app_store.py` for how it is written.

Who may do what is the app's access list (`services/access.py`): Can use to open
it, Can manage to change, share, publish, archive or delete it. Managers edit a
draft, saved in place (`services/drafts.py`); Publish makes the draft the next
version, and that is all anyone with Can use ever sees. No access at all reads
as missing, by id or by link name alike, so a link never confirms that a view
exists to someone it isn't shared with.
"""
import logging
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from database import content_env, get_db_connection
from middleware.auth import get_db_client, get_db_client_sp
from routes import custom_widgets as widget_routes
from routes.roles import _get_current_username
from routes.widget_studio import quick_helper_reply
from services import access, app_links, app_spec, app_store, drafts, look_helper
from services import view_catalog

logger = logging.getLogger(__name__)
router = APIRouter()

_NOT_FOUND = "App not found"
APP, WIDGET, AGENT = access.APP, access.WIDGET, access.AGENT
MANAGE, USE = access.MANAGE, access.USE
MODES = ("draft", "published")
_NOT_A_PERSON = {"", "system", "unknown", "dev"}


class AppCreate(BaseModel):
    id: Optional[str] = None
    name: str
    domain: Optional[str] = "General"
    is_locked: bool = False
    pinned_agent_id: Optional[str] = None
    spec: Optional[Dict[str, Any]] = None


class AppUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    is_locked: Optional[bool] = None
    # Absent keeps the pin, "" clears it; see app_spec.pin_value.
    pinned_agent_id: Optional[str] = None
    # Absent keeps the spec; present replaces it whole.
    spec: Optional[Dict[str, Any]] = None


class LookRequest(BaseModel):
    description: str
    current: Optional[Dict[str, Any]] = None


class AppCompose(BaseModel):
    name: str
    source_ids: List[str]
    domain: Optional[str] = "General"
    presentation: Optional[str] = None


class PublishItem(BaseModel):
    object_type: str
    object_id: str


class PublishRequest(BaseModel):
    include: List[PublishItem] = []


class RevertRequest(BaseModel):
    version: int


def _connect():
    return get_db_connection(content_env())


def _timestamp(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _person(name: Any) -> Optional[str]:
    value = str(name or "").strip()
    return None if value.lower() in _NOT_A_PERSON else value


def _same(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a) and bool(b) and a.lower() == b.lower()


def _acl_facts(app_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Owner and sharing per app; when it can't be read, the row's creator stands in for the owner."""
    return access.acl_facts(APP, app_ids)


def _public(row: Dict[str, Any], *, level: str, published_version: Optional[int], has_draft: bool,
            me: str, facts: Optional[Dict[str, Any]] = None, link: Optional[str] = None) -> Dict[str, Any]:
    facts = facts or {}
    owner = facts.get("owner") or _person(row.get("username"))
    return {
        "id": row["id"],
        # Names are claimed on publishing; see services/app_links.py.
        "link": link if published_version else None,
        "version": published_version or 0,
        "name": row.get("name") or "",
        "domain": row.get("domain"),
        "username": row.get("username"),
        "is_locked": bool(row.get("is_locked")),
        # The app-level agent; a tab's own pin, in the spec, overrides it.
        "pinned_agent_id": row.get("pinned_agent_id") or None,
        "timestamp": _timestamp(row.get("draft_updated_at") or row.get("timestamp")),
        "spec": app_store.spec_of(row),
        "access": level,
        "state": drafts.state_of(has_draft, published_version),
        "owner": owner,
        "published_version": published_version,
        "has_draft": has_draft,
        "is_draft": bool(row.get("is_draft")),
        "shared_with_me": not _same(owner, me),
        # 'private' | 'shared' | 'everyone', for the sidebar's access icon.
        "sharing": facts.get("sharing"),
    }


def _links(c, app_ids: List[str]) -> Dict[str, str]:
    """Link names for these apps. Read last on the connection: a failure ends its transaction."""
    try:
        return app_links.current(c, app_ids)
    except Exception as e:  # noqa: BLE001 - without names, links carry ids, which always work
        logger.warning("Couldn't read app link names: %s", e)
        return {}


def _row_for(c, app_id: str, level: str, mode: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[int], bool]:
    """What this caller sees of an app in this mode, its published version, and whether it has a draft.

    Only managers know about drafts: to someone with Can use an app is its newest
    published version, and one never published isn't there at all.
    """
    published = app_store.head(c, app_id)
    version = int(published["version"]) if published else None
    if level != MANAGE:
        return published, version, False
    held = drafts.read(c, APP, app_id)
    row = published if mode == "published" else drafts.merge(published, held, app_id)
    return row, version, held is not None


def _open(c, who: access.Caller, ref: str, mode: Optional[str] = None,
          ) -> Tuple[str, str, Dict[str, Any], Optional[int], bool]:
    """The app a ref names, if the caller may open it: (id, level, row, published version, has draft); else 404.

    Archived apps are out of circulation and read as missing, as they drop out of
    the sidebar; the Archived group is the way back to them.
    """
    if mode is not None and mode not in MODES:
        raise HTTPException(status_code=400, detail="mode must be 'draft' or 'published'.")
    app_id = app_store.resolve_ref(c, ref)
    if app_id is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    level = access.require(who, APP, app_id, USE, not_found=_NOT_FOUND)
    if app_store.is_archived(c, app_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    row, version, has_draft = _row_for(c, app_id, level, mode)
    if row is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return app_id, level, row, version, has_draft


def _grant_owner(app_id: str, username: str) -> None:
    """Make the creator the owner, after the content commit: the access list is in the settings schema."""
    try:
        access.grant_owner(APP, app_id, username)
    except Exception as e:  # noqa: BLE001
        logger.error("App %s was created but %s couldn't be made its owner: %s", app_id, username, e)
        raise HTTPException(
            status_code=500,
            detail="The view was created, but you couldn't be given access to it. An app administrator can share it with you.",
        )


@router.get("/")
def list_apps(w: WorkspaceClient = Depends(get_db_client)):
    """The caller's sidebar: views they own and views shared with them, less those they closed.

    Granted views only, admins included. An admin can manage every view, but
    listing every view in the deployment in each admin's sidebar would bury their
    own; Admin Panel → Content is where they see them all.
    """
    who = access.caller(w)
    try:
        grants = access.grants_for(who, APP)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching apps: {str(e)}")
    ids = list(grants)
    if not ids:
        return {"apps": []}

    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            f"""
            SELECT {', '.join('dv.' + col for col in app_store.HEAD_COLUMNS)}
            FROM dashboard_views dv
            INNER JOIN (
                SELECT id, MAX(version) AS max_version
                FROM dashboard_views
                WHERE id = ANY(%s)
                GROUP BY id
            ) latest ON dv.id = latest.id AND dv.version = latest.max_version
            """,
            (ids,),
        )
        published = {r["id"]: r for r in app_store.fetch_rows(c)}
        held = drafts.drafts(c, APP, ids)
        hidden = app_store.hidden_ids(c, who.username)
        archived = app_store.archived_ids(c)
        links = _links(c, list(published))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching apps: {str(e)}")
    finally:
        conn.close()

    shown = []
    for app_id in ids:
        if app_id in archived or app_id in hidden:
            continue
        level = MANAGE if who.is_admin else grants[app_id]
        pub = published.get(app_id)
        draft = held.get(app_id) if level == MANAGE else None
        row = drafts.merge(pub, draft, app_id) if level == MANAGE else pub
        if row is None:
            continue
        version = int(pub["version"]) if pub else None
        shown.append((row, level, version, draft is not None))

    facts = _acl_facts(row["id"] for row, *_ in shown)
    apps = [
        _public(row, level=level, published_version=version, has_draft=has_draft, me=who.username,
                facts=facts.get(row["id"]), link=links.get(row["id"]))
        for row, level, version, has_draft in shown
    ]
    apps.sort(key=lambda a: (a["name"].lower(), a["id"]))
    return {"apps": apps}


@router.get("/archived")
def list_archived_apps(w: WorkspaceClient = Depends(get_db_client)):
    """Archived apps the caller manages, newest first, for Restore and Delete.

    Only those they manage: the archive is where an app goes to be forgotten, so
    it should not become a way to find views one was never shown.
    """
    who = access.caller(w)
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute("SELECT id, archived_by, timestamp AS archived_at FROM archived_views ORDER BY timestamp DESC")
        rows = app_store.fetch_rows(c)
        levels = access.levels_for(who, APP, [r["id"] for r in rows])
        managed = [r for r in rows if levels.get(r["id"]) == MANAGE]
        out = []
        for r in managed:
            published = app_store.head(c, r["id"])
            held = drafts.read(c, APP, r["id"])
            row = drafts.merge(published, held, r["id"])
            if row is None:
                continue
            out.append({
                "id": r["id"],
                "version": int(published["version"]) if published else 0,
                "name": row.get("name") or "",
                "domain": row.get("domain"),
                "archived_by": r.get("archived_by"),
                "archived_at": _timestamp(r.get("archived_at")),
            })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching archived views: {str(e)}")
    finally:
        conn.close()
    return {"apps": out}


@router.get("/history")
def app_history(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Every published version of an app, newest first. The draft is not a version.

    Managers only, as on a Databricks dashboard: the list exists to revert from,
    and who published what and when is the managers' business.
    """
    who = access.caller(w)
    conn = _connect()
    try:
        c = conn.cursor()
        app_id, level, *_ = _open(c, who, app_id)
        if level != MANAGE:
            raise HTTPException(status_code=403, detail="You need Can manage on this view to see its history.")
        c.execute(
            "SELECT version, name, username, published_by, published_at, timestamp FROM dashboard_views "
            "WHERE id = %s ORDER BY version DESC",
            (app_id,),
        )
        rows = app_store.fetch_rows(c)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching app history: {str(e)}")
    finally:
        conn.close()
    return {"history": [
        {**r, "timestamp": _timestamp(r.get("timestamp")), "published_at": _timestamp(r.get("published_at"))}
        for r in rows
    ]}


@router.post("/look")
def suggest_look(body: LookRequest, w: WorkspaceClient = Depends(get_db_client),
                 sp: WorkspaceClient = Depends(get_db_client_sp)):
    """A look for a view or tab from a description, for View settings to show.

    Saves nothing: the editor fills its fields with the result and the user keeps
    it with Save, which validates it like any other change. Inference is signed by
    the service principal as Widget Studio's is; the description and the current
    look are the whole payload, and no tool runs.
    """
    _get_current_username(w)  # signed in, as every other call here requires
    if not (body.description or "").strip():
        raise HTTPException(status_code=400, detail="Describe the look you want.")
    sent = look_helper.messages(body.description, body.current)
    try:
        reply = quick_helper_reply(sp, [SystemMessage(content=sent[0][1]), HumanMessage(content=sent[1][1])])
    except Exception as exc:  # noqa: BLE001 — the model's failure is the user's answer here
        logger.warning("Describe the look failed: %s", exc)
        raise HTTPException(status_code=502, detail="The model didn't answer. Try again in a moment.")
    theme, dropped = look_helper.theme_from_reply(reply)
    if theme is None:
        raise HTTPException(status_code=422, detail="That didn't come back as a look. Try describing colors, a font or the cards.")
    return {"theme": theme, "dropped": dropped}


@router.post("/compose")
def compose_app(body: AppCompose, w: WorkspaceClient = Depends(get_db_client)):
    """Build a new app, owned by the caller, whose tabs are copies of existing views or apps.

    The way into apps for a deployment that already has many views: pick several,
    get one app with a tab for each. The sources are not changed, moved or
    archived, so their links keep working; the caller can archive them afterwards.
    Every source must be one the caller can open, and is copied as they see it.
    """
    source_ids = list(dict.fromkeys(s for s in body.source_ids if s))
    if len(source_ids) > app_spec.MAX_TABS:
        raise HTTPException(status_code=400, detail=f"An app may have at most {app_spec.MAX_TABS} tabs.")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the app a name.")

    who = access.caller(w)
    app_id = str(uuid.uuid4())
    conn = _connect()
    try:
        c = conn.cursor()
        sources = []
        for source_id in source_ids:
            try:
                _, _, row, _, _ = _open(c, who, source_id)
            except HTTPException as e:
                raise HTTPException(status_code=e.status_code, detail=f"{_NOT_FOUND}: {source_id}")
            sources.append({"name": row["name"], "pinned_agent_id": row.get("pinned_agent_id"),
                            "spec": app_store.spec_of(row)})
        try:
            spec = app_spec.compose_spec(sources, presentation=body.presentation)
        except app_spec.SpecError as e:
            raise HTTPException(status_code=400, detail=str(e))
        app_store.create_draft(
            c, app_id=app_id, name=name, domain=body.domain or "General", username=who.username,
            is_locked=False, pinned_agent_id=None, spec=spec,
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error composing app: {str(e)}")
    finally:
        conn.close()
    _grant_owner(app_id, who.username)
    return {"status": "success", "id": app_id, "state": drafts.DRAFT_ONLY, "tabs": len(spec["tabs"])}


@router.post("/")
def create_app(body: AppCreate, w: WorkspaceClient = Depends(get_db_client)):
    """A new view, owned by the caller: a draft nobody else sees until they share and publish it."""
    who = access.caller(w)
    app_id = body.id or str(uuid.uuid4())
    try:
        spec = app_spec.validate_spec(body.spec, app_id) if body.spec is not None else app_spec.legacy_spec(app_id, [])
    except app_spec.SpecError as e:
        raise HTTPException(status_code=400, detail=str(e))

    conn = _connect()
    try:
        c = conn.cursor()
        app_store.create_draft(
            c, app_id=app_id, name=body.name, domain=body.domain or "General", username=who.username,
            is_locked=body.is_locked, pinned_agent_id=app_spec.pin_value(body.pinned_agent_id, None), spec=spec,
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating app: {str(e)}")
    finally:
        conn.close()
    _grant_owner(app_id, who.username)
    return {"status": "success", "id": app_id, "state": drafts.DRAFT_ONLY}


@router.get("/{app_id}")
def get_app(app_id: str, mode: Optional[str] = None, w: WorkspaceClient = Depends(get_db_client)):
    """One app, by id or by what its link names it, if the caller can use it.

    `mode` picks draft or published for a manager (default draft); someone with
    Can use always gets the published version. Reads only.
    """
    who = access.caller(w)
    conn = _connect()
    try:
        c = conn.cursor()
        app_id, level, row, version, has_draft = _open(c, who, app_id, mode)
        links = _links(c, [app_id] if version else [])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching app: {str(e)}")
    finally:
        conn.close()
    shown = "published" if level != MANAGE or mode == "published" else "draft"
    app = _public(row, level=level, published_version=version, has_draft=has_draft, me=who.username,
                  facts=_acl_facts([app_id]).get(app_id), link=links.get(app_id))
    return {"app": app, "mode": shown}


@router.get("/{app_id}/widgets")
def app_widgets(app_id: str, mode: Optional[str] = None, w: WorkspaceClient = Depends(get_db_client)):
    """The library rows for the widgets this app places, in the shape `/api/widgets/custom` sends.

    Enough to render the app without loading the whole library: each placed
    widget's published versions, with the source of the current one and of any
    version a tab pins. Can use on the app is enough to see them, without Can use
    on each widget: sharing a view shares what it shows. In draft mode a manager
    also gets the drafts of the widgets they manage.
    """
    who = access.caller(w)
    conn = _connect()
    try:
        c = conn.cursor()
        _, level, row, _, _ = _open(c, who, app_id, mode)
        ids, pinned = app_spec.placed_widgets(app_store.spec_of(row))
        rows = widget_routes.bundle_rows(c, who, ids, pinned, draft=level == MANAGE and mode != "published")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching app widgets: {str(e)}")
    finally:
        conn.close()
    return {"widgets": rows}


@router.put("/{app_id}")
def update_app(app_id: str, body: AppUpdate, w: WorkspaceClient = Depends(get_db_client)):
    """Save the draft. Nobody with only Can use sees it until it is published."""
    who = access.caller(w)
    access.require(who, APP, app_id, MANAGE, not_found=_NOT_FOUND)
    conn = _connect()
    try:
        c = conn.cursor()
        state = app_store.save_draft(
            c, app_id, who.username,
            name=body.name,
            domain=body.domain,
            is_locked=body.is_locked,
            pinned_agent_id=body.pinned_agent_id,
            spec=body.spec,
        )
        conn.commit()
        return {"status": "success", "id": app_id, "state": state}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating app: {str(e)}")
    finally:
        conn.close()


def _shared_beyond_owner(app_id: str) -> Tuple[bool, bool]:
    """(shared with anyone besides its owner, shared with everyone), from the access list."""
    summary = access.summary_of(access.get_acl(APP, app_id), access.owner_of(APP, app_id))
    return summary != "private", summary == "everyone"


def _includes(items: List[PublishItem]) -> List[Tuple[str, str]]:
    out = []
    for item in items:
        if item.object_type not in (WIDGET, AGENT):
            raise HTTPException(status_code=400, detail="Only widgets and agents can be published with a view.")
        if item.object_id and (item.object_type, item.object_id) not in out:
            out.append((item.object_type, item.object_id))
    return out


@router.post("/{app_id}/publish/preflight")
def publish_preflight(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """What publishing this view would leave behind, for the Publish dialog.

    Widgets it places and agents it pins that people with Can use couldn't see
    yet (never published, or with unpublished changes), each saying whether the
    caller may publish it along with the view; and, when the certified-widgets
    setting is on and the view is shared beyond its owner, the widgets that would
    have it refused.
    """
    who = access.caller(w)
    access.require(who, APP, app_id, MANAGE, not_found=_NOT_FOUND)
    shared, _ = _shared_beyond_owner(app_id)
    conn = _connect()
    try:
        c = conn.cursor()
        has_draft = drafts.read(c, APP, app_id) is not None
        row = drafts.current(c, APP, app_id, MANAGE)
        if row is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        spec = app_store.spec_of(row)
        widget_ids = app_store.custom_widget_ids(spec)
        agent_ids = app_store.pinned_agent_ids(row, spec)
        published: Dict[str, Dict[str, Any]] = {
            WIDGET: {i: h.get("name") for i, h in app_store.widget_heads(c, widget_ids).items()},
            AGENT: {},
        }
        for agent_id in agent_ids:
            agent = drafts.latest(c, AGENT, agent_id)
            if agent is not None:
                published[AGENT][agent_id] = agent.get("name")
        held = {WIDGET: drafts.drafts(c, WIDGET, widget_ids), AGENT: drafts.drafts(c, AGENT, agent_ids)}
        problem = app_store.certification_problem(c, spec, shared)
        uncertified = app_store.uncertified_widgets(c, spec) if problem else []
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error checking the view: {str(e)}")
    finally:
        conn.close()

    items: List[Dict[str, Any]] = []
    for object_type, ids in ((WIDGET, widget_ids), (AGENT, agent_ids)):
        drafted = [i for i in ids if i in held[object_type]]
        levels = access.levels_for(who, object_type, drafted)
        for object_id in drafted:
            name = (held[object_type][object_id].get("payload") or {}).get("name") or published[object_type].get(object_id)
            items.append({
                "object_type": object_type,
                "object_id": object_id,
                "name": name or object_id,
                "reason": "unpublished_changes" if object_id in published[object_type] else "never_published",
                "can_publish": levels.get(object_id) == MANAGE,
            })
    items.extend({"object_type": WIDGET, "object_id": wid, "name": name, "reason": "uncertified", "can_publish": False}
                 for wid, name in uncertified)
    blocking = [] if has_draft else ["There are no unpublished changes to publish."]
    if problem:
        blocking.append(problem)
    return {"items": items, "blocking": blocking}


@router.post("/{app_id}/publish")
def publish_app(app_id: str, body: PublishRequest, w: WorkspaceClient = Depends(get_db_client)):
    """Publish the draft as the next version, after the widgets and agents named in `include`.

    One transaction: if the view can't be published (no draft, or refused under
    the certified-widgets setting), the widgets and agents published with it roll
    back too, so nobody is left with half of what they confirmed.
    """
    who = access.caller(w)
    access.require(who, APP, app_id, MANAGE, not_found=_NOT_FOUND)
    include = _includes(body.include)
    for object_type in (WIDGET, AGENT):
        wanted = [i for t, i in include if t == object_type]
        levels = access.levels_for(who, object_type, wanted)
        refused = [i for i in wanted if levels.get(i) != MANAGE]
        if refused:
            raise HTTPException(
                status_code=403,
                detail=f"You need Can manage on every {object_type} you publish with the view.",
            )
    shared, everyone = _shared_beyond_owner(app_id)

    conn = _connect()
    try:
        c = conn.cursor()
        held = drafts.read(c, APP, app_id)
        if held is None:
            raise HTTPException(status_code=409, detail="There are no unpublished changes to publish.")
        for object_type, object_id in include:
            # Someone else may have published it since the dialog opened; that's done, not an error.
            if drafts.read(c, object_type, object_id) is not None:
                drafts.publish(c, object_type, object_id, who.username)
        payload = dict(held.get("payload") or {})
        problem = app_store.certification_problem(c, app_store.spec_of({"id": app_id, **payload}), shared)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        if bool(payload.get("is_global")) != everyone:
            payload["is_global"] = int(everyone)
            drafts.save(c, APP, app_id, payload, held.get("updated_by") or who.username,
                        base_version=held.get("base_version"))
        version = drafts.publish(c, APP, app_id, who.username)
        app_store.claim_link(c, app_id, payload.get("name") or "")
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error publishing view: {str(e)}")
    finally:
        conn.close()
    return {"status": "success", "version": version}


@router.post("/{app_id}/discard")
def discard_draft(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Throw the draft away; the view goes back to its newest published version."""
    who = access.caller(w)
    access.require(who, APP, app_id, MANAGE, not_found=_NOT_FOUND)
    conn = _connect()
    try:
        c = conn.cursor()
        if app_store.head(c, app_id) is None:
            # The draft is all there is, so discarding it would delete the view
            # without the confirmation Delete asks for.
            raise HTTPException(status_code=409, detail="This view has never been published, so there is nothing to go back to. Delete it instead.")
        discarded = drafts.discard(c, APP, app_id)
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error discarding the draft: {str(e)}")
    finally:
        conn.close()
    return {"status": "success", "discarded": discarded, "state": drafts.PUBLISHED}


@router.post("/{app_id}/revert")
def revert_app(app_id: str, body: RevertRequest, w: WorkspaceClient = Depends(get_db_client)):
    """Make a published version the draft, replacing any draft; publishing it is a separate step."""
    who = access.caller(w)
    access.require(who, APP, app_id, MANAGE, not_found=_NOT_FOUND)
    conn = _connect()
    try:
        c = conn.cursor()
        drafts.revert(c, APP, app_id, body.version, who.username)
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error reverting view: {str(e)}")
    finally:
        conn.close()
    return {"status": "success", "state": drafts.PUBLISHED_WITH_DRAFT}


def _set_hidden(app_id: str, w: WorkspaceClient, hidden: bool) -> Dict[str, Any]:
    who = access.caller(w)
    conn = _connect()
    try:
        c = conn.cursor()
        if hidden:
            access.require(who, APP, app_id, USE, not_found=_NOT_FOUND)
            c.execute(
                "INSERT INTO sidebar_hidden (username, app_id) VALUES (%s, %s) ON CONFLICT (username, app_id) DO NOTHING",
                (who.username, app_id),
            )
        else:
            c.execute("DELETE FROM sidebar_hidden WHERE username = %s AND app_id = %s", (who.username, app_id))
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating the sidebar: {str(e)}")
    finally:
        conn.close()
    return {"status": "success", "id": app_id, "hidden": hidden}


@router.post("/{app_id}/hide")
def hide_app(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Close a view shared with the caller: out of their sidebar, still shared with them."""
    return _set_hidden(app_id, w, True)


@router.delete("/{app_id}/hide")
def unhide_app(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    return _set_hidden(app_id, w, False)


@router.post("/{app_id}/subscribe")
def subscribe_app(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """What opening a shared link used to do. Sharing now decides who sees a view, so this only checks Can use."""
    who = access.caller(w)
    conn = _connect()
    try:
        c = conn.cursor()
        app_id, *_ = _open(c, who, app_id)
    finally:
        conn.close()
    return {"status": "success", "id": app_id}


@router.delete("/{app_id}/subscribe")
def unsubscribe_app(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    _get_current_username(w)
    return {"status": "success"}


@router.post("/{app_id}/archive")
def archive_app(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Take an app out of every sidebar without deleting anything.

    Every version and the draft stay, so restoring is exact and nothing an author
    built is lost to a misclick. Idempotent: archiving twice is the same as once.
    """
    who = access.caller(w)
    access.require(who, APP, app_id, MANAGE, not_found=_NOT_FOUND)
    conn = _connect()
    try:
        c = conn.cursor()
        if not app_store.exists(c, app_id):
            raise HTTPException(status_code=404, detail="View not found")
        c.execute(
            "INSERT INTO archived_views (id, archived_by) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (app_id, who.username),
        )
        view_catalog.touch(c, APP, app_id)
        conn.commit()
        return {"status": "success", "id": app_id, "archived": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error archiving view: {str(e)}")
    finally:
        conn.close()


@router.post("/{app_id}/restore")
def restore_app(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Put an archived app back exactly as it was."""
    who = access.caller(w)
    access.require(who, APP, app_id, MANAGE, not_found=_NOT_FOUND)
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM archived_views WHERE id = %s", (app_id,))
        view_catalog.touch(c, APP, app_id)
        conn.commit()
        return {"status": "success", "id": app_id, "archived": False}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error restoring view: {str(e)}")
    finally:
        conn.close()


@router.delete("/{app_id}")
def delete_app(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Delete an app: every version, the draft, its names and its access list. Nothing brings it back."""
    who = access.caller(w)
    access.require(who, APP, app_id, MANAGE, not_found=_NOT_FOUND)
    shared, _ = _shared_beyond_owner(app_id)
    conn = _connect()
    try:
        c = conn.cursor()
        if not app_store.exists(c, app_id):
            raise HTTPException(status_code=404, detail="View not found")
        # A view other people can open is archived first, where someone could
        # notice it gone and say so before it is gone for good. One only its
        # owner can see is theirs to delete outright, as closing it always has.
        if shared and not app_store.is_archived(c, app_id):
            raise HTTPException(
                status_code=409,
                detail="This view is shared with other people. Archive it before deleting it permanently.",
            )
        c.execute("DELETE FROM dashboard_views WHERE id = %s", (app_id,))
        drafts.discard(c, APP, app_id)
        c.execute("DELETE FROM archived_views WHERE id = %s", (app_id,))
        c.execute("DELETE FROM sidebar_hidden WHERE app_id = %s", (app_id,))
        app_links.forget(c, app_id)
        view_catalog.touch(c, APP, app_id)
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting view: {str(e)}")
    finally:
        conn.close()
    try:
        access.delete_acl(APP, app_id)
    except Exception as e:  # noqa: BLE001 - grants on an id that no longer exists open nothing
        logger.warning("View %s was deleted but its access list wasn't: %s", app_id, e)
    return {"status": "success", "message": f"View {app_id} deleted"}
