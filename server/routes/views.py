"""Views: the single-canvas API from before apps, kept until the frontend moves.

A view is an app with one tab (see `routes/apps.py` and `services/app_spec.py`),
and everything here reads and writes the same rows `/api/apps` does. What this
API cannot see is every tab after the first, so its saves go through
`app_store.save_version(first_tab_widgets=...)`, which changes only the first tab
— a browser still running the old bundle must not erase the rest of an app by
dragging a widget.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import uuid
from database import get_db_connection
from middleware.auth import get_db_client
from databricks.sdk import WorkspaceClient
from routes.roles import _get_current_username, require_domain_editor, _get_user_permissions
from services import app_spec, app_store
from services.app_spec import pin_value  # noqa: F401 - re-exported; tests/test_view_pins.py imports it here

router = APIRouter()


class ViewCreate(BaseModel):
    id: Optional[str] = None
    name: str
    domain: Optional[str] = "General"
    is_global: bool = False
    is_locked: bool = False
    pinned_agent_id: Optional[str] = None
    widgets: List[Dict[str, Any]] = []

class ViewUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    is_global: Optional[bool] = None
    is_locked: Optional[bool] = None
    pinned_agent_id: Optional[str] = None
    widgets: Optional[List[Dict[str, Any]]] = None


@router.get("/")
def get_views(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Fetch all views accessible to the user (their own + matching global views)."""
    username = _get_current_username(w)
    perms = _get_user_permissions(w, env)
    is_admin = perms.get("is_admin", False)
    domain_permissions = perms.get("domain_permissions", {})
    
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        c.execute("""
            SELECT dv.id, dv.version, dv.name, dv.domain, dv.username, dv.is_global, dv.widgets_json, dv.spec_json,
                   dv.is_locked, dv.pinned_agent_id, dv.timestamp,
                   CASE WHEN dv.username != %s AND dv.is_global = 0 AND sv.username IS NOT NULL THEN 1 ELSE 0 END as is_shared
            FROM dashboard_views dv
            INNER JOIN (
                SELECT id, MAX(version) as max_version
                FROM dashboard_views
                GROUP BY id
            ) latest ON dv.id = latest.id AND dv.version = latest.max_version
            LEFT JOIN shared_views sv ON dv.id = sv.view_id AND sv.username = %s
            LEFT JOIN archived_views av ON dv.id = av.id
            WHERE av.id IS NULL
              AND ((dv.username = %s)
                   OR (dv.is_global = 1)
                   OR (sv.username IS NOT NULL))
        """, (username, username, username))
        rows = c.fetchall()
        views = [dict(zip([column[0] for column in c.description], row)) for row in rows]
            
        conn.close()
        
        # Parse JSON and filter global views
        result = []
        for v in views:
            # If it's a global view and the user is NOT a global admin,
            # they must have some explicit domain access to see it
            if v['is_global'] and not is_admin:
                domain = v.get('domain', 'General')
                if domain not in domain_permissions:
                    continue
                    
            widgets = app_spec.first_tab_widgets(app_store.spec_of(v))

            result.append({
                "id": v['id'],
                "version": v['version'],
                "name": v['name'],
                "domain": v['domain'],
                "username": v['username'],
                "is_global": bool(v['is_global']),
                "is_locked": bool(v['is_locked']),
                "is_shared": bool(v['is_shared']),
                "pinned_agent_id": v.get('pinned_agent_id') or None,
                "widgets": widgets
            })
            
        return {"views": result}
    except Exception as e:
        if 'conn' in locals() and conn:
            conn.close()
        raise HTTPException(status_code=500, detail=f"Error fetching views: {str(e)}")

@router.get("/history")
def get_view_history(view_id: str, env: str = "dev"):
    """Return all versions of a view in a given env, ordered newest first."""
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        c.execute(
            "SELECT version, name, username, timestamp FROM dashboard_views WHERE id = %s ORDER BY version DESC",
            (view_id,)
        )
        rows = [dict(zip([d[0] for d in c.description], row)) for row in c.fetchall()]
        conn.close()
        return {"history": rows, "env": env}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching view history: {str(e)}")


@router.post("/shared/{view_id}")
def add_shared_view(view_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Subscribe to a shared view."""
    username = _get_current_username(w)
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        # Check if the view exists
        c.execute("SELECT id FROM dashboard_views WHERE id = %s", (view_id,))
        if not c.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="View not found")
            
        c.execute("""
            INSERT INTO shared_views (username, view_id)
            VALUES (%s, %s)
            ON CONFLICT (username, view_id) DO NOTHING
        """, (username, view_id))
        
        conn.commit()
        conn.close()
        
        return {"status": "success", "message": f"Subscribed to shared view {view_id}"}
    except Exception as e:
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=f"Error subscribing to shared view: {str(e)}")

@router.delete("/shared/{view_id}")
def remove_shared_view(view_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Unsubscribe from a shared view."""
    username = _get_current_username(w)
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
            
        c.execute("""
            DELETE FROM shared_views
            WHERE username = %s AND view_id = %s
        """, (username, view_id))
        
        conn.commit()
        conn.close()
        
        return {"status": "success"}
    except Exception as e:
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=f"Error unsubscribing from shared view: {str(e)}")


@router.post("/")
def create_view(view: ViewCreate, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    username = _get_current_username(w)
    
    if view.is_global:
        require_domain_editor(w, view.domain, env)

    view_id = view.id if view.id else str(uuid.uuid4())
    spec = app_spec.legacy_spec(view_id, view.widgets)

    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        if view.is_global:
            app_store.require_certified_widgets(c, spec, env)
        app_store.insert_version(
            c,
            app_id=view_id,
            version=1,
            name=view.name,
            domain=view.domain,
            username='system' if view.is_global else username,
            is_global=view.is_global,
            is_locked=view.is_locked,
            pinned_agent_id=pin_value(view.pinned_agent_id, None),
            spec=spec,
        )
        conn.commit()
        return {"status": "success", "id": view_id, "version": 1}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating view: {str(e)}")
    finally:
        conn.close()

@router.put("/{view_id}")
def update_view(view_id: str, view: ViewUpdate, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    username = _get_current_username(w)

    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        new_version = app_store.save_version(
            c, w, env, view_id, username,
            name=view.name,
            domain=view.domain,
            is_global=view.is_global,
            is_locked=view.is_locked,
            pinned_agent_id=view.pinned_agent_id,
            first_tab_widgets=view.widgets,
        )
        conn.commit()
        return {"status": "success", "id": view_id, "version": new_version}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating view: {str(e)}")
    finally:
        conn.close()

def _latest_view(c, view_id: str) -> Optional[Dict[str, Any]]:
    """Who owns a view and which domain it is filed under, from its newest version.

    Newest, not any: the domain can change between versions, and the permission
    check has to be made against the one people can currently see.
    """
    c.execute(
        "SELECT username, is_global, domain FROM dashboard_views "
        "WHERE id = %s ORDER BY version DESC LIMIT 1",
        (view_id,),
    )
    row = c.fetchone()
    return dict(zip([column[0] for column in c.description], row)) if row else None


def _global_view_for_editor(c, w, view_id: str, env: str) -> Dict[str, Any]:
    """The view, if it is global and the caller may edit its domain; otherwise raise.

    Archiving and restoring act on global views only. A personal view is already
    private to its owner, so "removing it from circulation" has no meaning there —
    closing it in the sidebar deletes it, as it always has.
    """
    view = _latest_view(c, view_id)
    if not view:
        raise HTTPException(status_code=404, detail="View not found")
    if not view["is_global"]:
        raise HTTPException(
            status_code=400,
            detail="Only global views are archived. Close a personal view to delete it.",
        )
    require_domain_editor(w, view.get("domain") or "General", env)
    return view


def _timestamp(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


@router.get("/archived")
def get_archived_views(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Archived global views the caller could restore or delete, newest first.

    Limited to domains the caller edits: the archive is where a view goes to be
    forgotten, so it should not become a way to browse domains one can't see.
    """
    perms = _get_user_permissions(w, env)
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
        rows = [dict(zip([column[0] for column in c.description], row)) for row in c.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching archived views: {str(e)}")
    finally:
        conn.close()

    return {"views": [
        {**r, "archived_at": _timestamp(r.get("archived_at"))}
        for r in rows
        if is_admin or domain_permissions.get(r.get("domain") or "General") in ("editor", "admin")
    ]}


@router.post("/{view_id}/archive")
def archive_view(view_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Take a global view out of everyone's sidebar without deleting anything.

    Every version stays, so restoring is exact and nothing a view's author built is
    lost to a misclick. Idempotent: archiving twice is the same as once.
    """
    username = _get_current_username(w)
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        _global_view_for_editor(c, w, view_id, env)
        c.execute(
            "INSERT INTO archived_views (id, archived_by) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (view_id, username),
        )
        conn.commit()
        return {"status": "success", "id": view_id, "archived": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error archiving view: {str(e)}")
    finally:
        conn.close()


@router.post("/{view_id}/restore")
def restore_view(view_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Put an archived global view back exactly as it was."""
    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        _global_view_for_editor(c, w, view_id, env)
        c.execute("DELETE FROM archived_views WHERE id = %s", (view_id,))
        conn.commit()
        return {"status": "success", "id": view_id, "archived": False}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error restoring view: {str(e)}")
    finally:
        conn.close()


@router.delete("/{view_id}")
def delete_view(view_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    username = _get_current_username(w)
    
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        existing = _latest_view(c, view_id)
            
        if not existing:
            conn.close()
            raise HTTPException(status_code=404, detail="View not found")
        
        if existing['is_global']:
            require_domain_editor(w, existing.get('domain', 'General'), env)
            # Deleting is the second step, after archiving: every version goes and
            # nothing brings them back, so a global view must first have been taken
            # out of circulation where someone could have noticed and said so.
            c.execute("SELECT 1 FROM archived_views WHERE id = %s", (view_id,))
            if not c.fetchone():
                conn.close()
                raise HTTPException(
                    status_code=409,
                    detail="Archive this global view before deleting it permanently.",
                )
            
        if not existing['is_global'] and existing['username'] != username:
            conn.close()
            raise HTTPException(status_code=403, detail="You can only delete your own views")
            
        c.execute("DELETE FROM dashboard_views WHERE id = %s", (view_id,))
        c.execute("DELETE FROM archived_views WHERE id = %s", (view_id,))
            
        conn.commit()
        conn.close()
        
        return {"status": "success", "message": f"View {view_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=f"Error deleting view: {str(e)}")
