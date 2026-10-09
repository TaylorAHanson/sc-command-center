"""Apps: what a user composes from widgets, agents and data, and shares (/api/apps).

An app is a row in `dashboard_views` under the id the view always had; a view is
an app with one tab. See `services/app_spec.py` for what an app holds and
`services/app_store.py` for how it is written. This replaced `/api/views`, which
read and wrote the same rows; the handlers below that came from it (subscribe,
archive, restore, delete, the archive list) do exactly what they did there.

Who may read and change an app is exactly who could read and change the view:
`app_spec.can_read` for reading, `app_store.require_may_edit` for writing. Apps
add two reads views never had, `GET /{id}` and `GET /{id}/widgets`; they write
nothing and do not add or remove anyone's access.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from database import get_db_connection
from middleware.auth import get_db_client, get_db_client_sp
from routes import custom_widgets as widget_routes
from routes.widget_studio import quick_helper_reply
from routes.roles import _get_current_username, _get_user_permissions, require_domain_editor
from services import app_links, app_spec, app_store, look_helper

logger = logging.getLogger(__name__)
router = APIRouter()

_NOT_FOUND = "App not found"


class AppCreate(BaseModel):
    id: Optional[str] = None
    name: str
    domain: Optional[str] = "General"
    is_global: bool = False
    is_locked: bool = False
    pinned_agent_id: Optional[str] = None
    spec: Optional[Dict[str, Any]] = None


class AppUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    is_global: Optional[bool] = None
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


def _timestamp(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _public(row: Dict[str, Any], spec: Dict[str, Any], *, username: str, subscribed: bool,
            link: Optional[str] = None) -> Dict[str, Any]:
    is_global = bool(row.get("is_global"))
    return {
        "id": row["id"],
        # What links to a global app name it by; see services/app_links.py.
        "link": link if is_global else None,
        "version": row["version"],
        "name": row["name"],
        "domain": row.get("domain"),
        "username": row.get("username"),
        "is_global": is_global,
        "is_locked": bool(row.get("is_locked")),
        # Someone else's personal app that the caller has in their sidebar.
        "is_shared": bool(subscribed and not is_global and row.get("username") != username),
        # The app-level agent; a tab's own pin, in the spec, overrides it.
        "pinned_agent_id": row.get("pinned_agent_id") or None,
        # When this version was saved; View Promotion's "Last Modified".
        "timestamp": _timestamp(row.get("timestamp")),
        "spec": spec,
    }


def _caller(w: WorkspaceClient, env: str) -> Tuple[str, Dict[str, Any]]:
    return _get_current_username(w), _get_user_permissions(w)


def _require_readable(c, ref: str, username: str, perms: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
    """The app's head row, spec and whether the caller subscribes to it; else 404.

    `ref` is whatever a link names the app by (`app_store.resolve_ref`); the row
    says which app it turned out to be. Archived apps are out of circulation and
    read as missing, as they drop out of the sidebar list; the archive list in the
    admin screen is the way back to them.
    """
    app_id = app_store.resolve_ref(c, ref) or ref
    row = app_store.head(c, app_id)
    if row is None or app_store.is_archived(c, app_id) or not app_spec.can_read(row, perms=perms):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return row, app_store.spec_of(row), app_store.is_subscribed(c, username, app_id)


@router.get("/")
def list_apps(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """The caller's sidebar: their own apps, global apps in their domains, and subscriptions."""
    username, perms = _caller(w, env)
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        c.execute(
            f"""
            SELECT {', '.join('dv.' + col for col in app_store.HEAD_COLUMNS)},
                   CASE WHEN sv.username IS NOT NULL THEN 1 ELSE 0 END AS subscribed
            FROM dashboard_views dv
            INNER JOIN (
                SELECT id, MAX(version) AS max_version
                FROM dashboard_views
                GROUP BY id
            ) latest ON dv.id = latest.id AND dv.version = latest.max_version
            LEFT JOIN shared_views sv ON dv.id = sv.view_id AND sv.username = %s
            LEFT JOIN archived_views av ON dv.id = av.id
            WHERE av.id IS NULL
              AND ((dv.username = %s)
                   OR (dv.is_global = 1)
                   OR (sv.username IS NOT NULL))
            """,
            (username, username),
        )
        rows = app_store.fetch_rows(c)
        links = _links(c, [r["id"] for r in rows if r.get("is_global")])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching apps: {str(e)}")
    finally:
        conn.close()

    apps = []
    for row in rows:
        if not app_spec.can_read(row, perms=perms):
            continue
        apps.append(_public(row, app_store.spec_of(row), username=username,
                            subscribed=bool(row.get("subscribed")), link=links.get(row["id"])))
    return {"apps": apps}


def _links(c, global_ids: List[str]) -> Dict[str, str]:
    """Link names for these apps. Read last on the connection: a failure ends its transaction."""
    try:
        return app_links.current(c, global_ids)
    except Exception as e:  # noqa: BLE001 - without names, links carry ids, which always work
        logger.warning("Couldn't read app link names: %s", e)
        return {}


@router.get("/archived")
def list_archived_apps(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Archived global apps the caller could restore or delete, newest first.

    Limited to domains the caller edits: the archive is where an app goes to be
    forgotten, so it should not become a way to browse domains one can't see.
    """
    perms = _get_user_permissions(w)
    is_admin = perms.get("is_admin", False)
    domain_permissions = perms.get("domain_permissions", {})

    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        c.execute("""
            SELECT dv.id, dv.version, dv.name, dv.domain, av.archived_by, av.timestamp AS archived_at
            FROM archived_views av
            INNER JOIN dashboard_views dv ON dv.id = av.id
            INNER JOIN (
                SELECT id, MAX(version) AS max_version
                FROM dashboard_views
                GROUP BY id
            ) latest ON dv.id = latest.id AND dv.version = latest.max_version
            ORDER BY av.timestamp DESC
        """)
        rows = app_store.fetch_rows(c)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching archived views: {str(e)}")
    finally:
        conn.close()

    return {"apps": [
        {**r, "archived_at": _timestamp(r.get("archived_at"))}
        for r in rows
        if is_admin or domain_permissions.get(r.get("domain") or "General") in ("editor", "admin")
    ]}


@router.get("/history")
def app_history(app_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Every version of an app in this env, newest first. Version numbers mean nothing across envs."""
    username, perms = _caller(w, env)
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        _require_readable(c, app_id, username, perms)
        c.execute(
            "SELECT version, name, username, timestamp FROM dashboard_views WHERE id = %s ORDER BY version DESC",
            (app_id,),
        )
        rows = app_store.fetch_rows(c)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching app history: {str(e)}")
    finally:
        conn.close()
    return {"history": [{**r, "timestamp": _timestamp(r.get("timestamp"))} for r in rows], "env": env}


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
def compose_app(body: AppCompose, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Build a new personal app whose tabs are copies of existing views or apps.

    The way into apps for a deployment that already has many views: pick several,
    get one app with a tab for each. The sources are not changed, moved or
    archived, so their links and subscriptions keep working; the caller can archive
    them afterwards. Every source must be one the caller could open.
    """
    source_ids = list(dict.fromkeys(s for s in body.source_ids if s))
    if len(source_ids) > app_spec.MAX_TABS:
        raise HTTPException(status_code=400, detail=f"An app may have at most {app_spec.MAX_TABS} tabs.")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the app a name.")

    username, perms = _caller(w, env)
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        sources = []
        for source_id in source_ids:
            try:
                row, spec, _ = _require_readable(c, source_id, username, perms)
            except HTTPException as e:
                raise HTTPException(status_code=e.status_code, detail=f"{_NOT_FOUND}: {source_id}")
            sources.append({"name": row["name"], "pinned_agent_id": row.get("pinned_agent_id"), "spec": spec})
        try:
            spec = app_spec.compose_spec(sources, presentation=body.presentation)
        except app_spec.SpecError as e:
            raise HTTPException(status_code=400, detail=str(e))

        app_id = str(uuid.uuid4())
        app_store.insert_version(
            c,
            app_id=app_id,
            version=1,
            name=name,
            domain=body.domain or "General",
            username=username,
            is_global=False,
            is_locked=False,
            pinned_agent_id=None,
            spec=spec,
        )
        conn.commit()
        return {"status": "success", "id": app_id, "version": 1, "tabs": len(spec["tabs"])}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error composing app: {str(e)}")
    finally:
        conn.close()


@router.post("/")
def create_app(body: AppCreate, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    username = _get_current_username(w)
    domain = body.domain or "General"
    if body.is_global:
        require_domain_editor(w, domain)

    app_id = body.id or str(uuid.uuid4())
    try:
        spec = app_spec.validate_spec(body.spec, app_id) if body.spec is not None else app_spec.legacy_spec(app_id, [])
    except app_spec.SpecError as e:
        raise HTTPException(status_code=400, detail=str(e))

    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        if app_store.head(c, app_id) is not None:
            raise HTTPException(status_code=409, detail="An app with this id already exists.")
        if body.is_global:
            app_store.require_certified_widgets(c, spec, env)
        app_store.insert_version(
            c,
            app_id=app_id,
            version=1,
            name=body.name,
            domain=domain,
            username="system" if body.is_global else username,
            is_global=body.is_global,
            is_locked=body.is_locked,
            pinned_agent_id=app_spec.pin_value(body.pinned_agent_id, None),
            spec=spec,
        )
        conn.commit()
        return {"status": "success", "id": app_id, "version": 1}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating app: {str(e)}")
    finally:
        conn.close()


@router.get("/{app_id}")
def get_app(app_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """One app, if the caller may open it, by id or by what its link names it.

    Reads only — opening a link subscribes nobody.
    """
    username, perms = _caller(w, env)
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        row, spec, subscribed = _require_readable(c, app_id, username, perms)
        links = _links(c, [row["id"]] if row.get("is_global") else [])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching app: {str(e)}")
    finally:
        conn.close()
    return {"app": _public(row, spec, username=username, subscribed=subscribed, link=links.get(row["id"]))}


@router.get("/{app_id}/widgets")
def app_widgets(app_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """The library rows for the widgets this app places, in the shape `/api/widgets/custom` sends.

    Enough to render the app without loading the whole library: each placed
    widget's versions, with the source of the current one and of any version a
    tab pins. Filtered by domain exactly as the library is, so an app shows a
    viewer the widgets they could already see and no others.
    """
    username, perms = _caller(w, env)
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        _, spec, _ = _require_readable(c, app_id, username, perms)
        ids, pinned = app_spec.placed_widgets(spec)
        rows = widget_routes.library_rows(c, ids, pinned) if ids else []
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching app widgets: {str(e)}")
    finally:
        conn.close()
    return {"widgets": widget_routes._visible(rows, perms)}


@router.put("/{app_id}")
def update_app(app_id: str, body: AppUpdate, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    username = _get_current_username(w)
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        new_version = app_store.save_version(
            c, w, env, app_id, username,
            name=body.name,
            domain=body.domain,
            is_global=body.is_global,
            is_locked=body.is_locked,
            pinned_agent_id=body.pinned_agent_id,
            spec=body.spec,
        )
        conn.commit()
        return {"status": "success", "id": app_id, "version": new_version}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating app: {str(e)}")
    finally:
        conn.close()


@router.post("/{app_id}/subscribe")
def subscribe_app(app_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Put an app into the caller's sidebar, which is what opening a shared link has always done.

    Any app that exists, for anyone holding its id: that is what a share link
    means here. It reveals nothing; reading the app still goes through `can_read`.
    A link name reaches only a global app (`app_store.resolve_ref`), so it can't be
    used to subscribe to someone's personal one.
    """
    username = _get_current_username(w)
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        app_id = app_store.resolve_ref(c, app_id) or app_id
        c.execute("SELECT id FROM dashboard_views WHERE id = %s", (app_id,))
        if not c.fetchone():
            raise HTTPException(status_code=404, detail="View not found")
        c.execute("""
            INSERT INTO shared_views (username, view_id)
            VALUES (%s, %s)
            ON CONFLICT (username, view_id) DO NOTHING
        """, (username, app_id))
        conn.commit()
        return {"status": "success", "message": f"Subscribed to shared view {app_id}"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error subscribing to shared view: {str(e)}")
    finally:
        conn.close()


@router.delete("/{app_id}/subscribe")
def unsubscribe_app(app_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    username = _get_current_username(w)
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        c.execute("DELETE FROM shared_views WHERE username = %s AND view_id = %s", (username, app_id))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error unsubscribing from shared view: {str(e)}")
    finally:
        conn.close()


def _owner_and_domain(c, app_id: str) -> Optional[Dict[str, Any]]:
    """Who owns an app and which domain it is filed under, from its newest version.

    Newest, not any: the domain can change between versions, and the permission
    check has to be made against the one people can currently see.
    """
    c.execute(
        "SELECT username, is_global, domain FROM dashboard_views "
        "WHERE id = %s ORDER BY version DESC LIMIT 1",
        (app_id,),
    )
    row = c.fetchone()
    return dict(zip([column[0] for column in c.description], row)) if row else None


def _global_app_for_editor(c, w, app_id: str, env: str) -> Dict[str, Any]:
    """The app, if it is global and the caller may edit its domain; otherwise raise.

    Archiving and restoring act on global apps only. A personal app is already
    private to its owner, so "removing it from circulation" has no meaning there —
    closing it in the sidebar deletes it, as it always has.
    """
    app = _owner_and_domain(c, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="View not found")
    if not app["is_global"]:
        raise HTTPException(
            status_code=400,
            detail="Only global views are archived. Close a personal view to delete it.",
        )
    require_domain_editor(w, app.get("domain") or "General")
    return app


@router.post("/{app_id}/archive")
def archive_app(app_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Take a global app out of everyone's sidebar without deleting anything.

    Every version stays, so restoring is exact and nothing an author built is
    lost to a misclick. Idempotent: archiving twice is the same as once.
    """
    username = _get_current_username(w)
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        _global_app_for_editor(c, w, app_id, env)
        c.execute(
            "INSERT INTO archived_views (id, archived_by) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (app_id, username),
        )
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
def restore_app(app_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Put an archived global app back exactly as it was."""
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        _global_app_for_editor(c, w, app_id, env)
        c.execute("DELETE FROM archived_views WHERE id = %s", (app_id,))
        conn.commit()
        return {"status": "success", "id": app_id, "archived": False}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error restoring view: {str(e)}")
    finally:
        conn.close()


@router.delete("/{app_id}")
def delete_app(app_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    username = _get_current_username(w)
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        existing = _owner_and_domain(c, app_id)
        if not existing:
            raise HTTPException(status_code=404, detail="View not found")

        if existing["is_global"]:
            require_domain_editor(w, existing.get("domain") or "General")
            # Deleting is the second step, after archiving: every version goes and
            # nothing brings them back, so a global app must first have been taken
            # out of circulation where someone could have noticed and said so.
            if not app_store.is_archived(c, app_id):
                raise HTTPException(
                    status_code=409,
                    detail="Archive this global view before deleting it permanently.",
                )
        elif existing["username"] != username:
            raise HTTPException(status_code=403, detail="You can only delete your own views")

        c.execute("DELETE FROM dashboard_views WHERE id = %s", (app_id,))
        c.execute("DELETE FROM archived_views WHERE id = %s", (app_id,))
        app_links.forget(c, app_id)
        conn.commit()
        return {"status": "success", "message": f"View {app_id} deleted"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting view: {str(e)}")
    finally:
        conn.close()
