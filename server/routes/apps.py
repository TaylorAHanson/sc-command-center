"""Apps: what a user composes from widgets, agents and data, and shares (/api/apps).

An app is a row in `dashboard_views` under the id the view always had; a view is
an app with one tab. See `services/app_spec.py` for what an app holds and
`services/app_store.py` for how it is written. `/api/views` reads and writes the
same rows and stays until the frontend has moved here.

Who may read and change an app is exactly who could read and change the view:
`app_spec.can_read` for reading, `app_store.require_may_edit` for writing. Apps
add a read-by-id (`GET /{id}`) that views never had, and it writes nothing; it
does not add or remove anyone's access.
"""
import uuid
from typing import Any, Dict, List, Optional, Tuple

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_db_connection
from middleware.auth import get_db_client
from routes import views as view_routes
from routes.roles import _get_current_username, _get_user_permissions, require_domain_editor
from services import app_spec, app_store

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


class AppCompose(BaseModel):
    name: str
    source_ids: List[str]
    domain: Optional[str] = "General"
    presentation: Optional[str] = None


def _public(row: Dict[str, Any], spec: Dict[str, Any], *, username: str, subscribed: bool) -> Dict[str, Any]:
    is_global = bool(row.get("is_global"))
    return {
        "id": row["id"],
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
        "spec": spec,
    }


def _caller(w: WorkspaceClient, env: str) -> Tuple[str, Dict[str, Any]]:
    return _get_current_username(w), _get_user_permissions(w, env)


def _require_readable(c, app_id: str, username: str, perms: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
    """The app's head row, spec and whether the caller subscribes to it; else 404.

    Archived apps are out of circulation and read as missing, as they drop out of
    `GET /api/views`; the archive list in the admin screen is the way back to them.
    """
    row = app_store.head(c, app_id)
    if row is None or app_store.is_archived(c, app_id) or not app_spec.can_read(row, perms=perms):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return row, app_store.spec_of(row), app_store.is_subscribed(c, username, app_id)


@router.get("/")
def list_apps(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """The caller's sidebar: their own apps, global apps in their domains, and subscriptions.

    The same rows `GET /api/views` returns, with each app's whole spec.
    """
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching apps: {str(e)}")
    finally:
        conn.close()

    apps = []
    for row in rows:
        if not app_spec.can_read(row, perms=perms):
            continue
        apps.append(_public(row, app_store.spec_of(row), username=username, subscribed=bool(row.get("subscribed"))))
    return {"apps": apps}


@router.get("/archived")
def list_archived_apps(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Archived global apps the caller could restore or delete; see `/api/views/archived`."""
    return {"apps": view_routes.get_archived_views(w=w, env=env)["views"]}


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
    return {"history": [{**r, "timestamp": view_routes._timestamp(r.get("timestamp"))} for r in rows], "env": env}


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
        require_domain_editor(w, domain, env)

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
    """One app, if the caller may open it. Reads only — opening a link subscribes nobody."""
    username, perms = _caller(w, env)
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        row, spec, subscribed = _require_readable(c, app_id, username, perms)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching app: {str(e)}")
    finally:
        conn.close()
    return {"app": _public(row, spec, username=username, subscribed=subscribed)}


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
    """Put an app into the caller's sidebar; the same act as `POST /api/views/shared/{id}`."""
    return view_routes.add_shared_view(app_id, w=w, env=env)


@router.delete("/{app_id}/subscribe")
def unsubscribe_app(app_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    return view_routes.remove_shared_view(app_id, w=w, env=env)


@router.post("/{app_id}/archive")
def archive_app(app_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    return view_routes.archive_view(app_id, w=w, env=env)


@router.post("/{app_id}/restore")
def restore_app(app_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    return view_routes.restore_view(app_id, w=w, env=env)


@router.delete("/{app_id}")
def delete_app(app_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    return view_routes.delete_view(app_id, w=w, env=env)
