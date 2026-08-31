from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json
import re
import uuid
from database import get_db_connection
from middleware.auth import get_db_client
from databricks.sdk import WorkspaceClient
from routes.roles import _get_current_username, require_domain_editor, _get_user_permissions

router = APIRouter()

# Custom widgets are stored under UUID ids; built-in types (iframe, etc.) have no row.
_CUSTOM_WIDGET_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _require_certified_widgets(widgets: List[Dict[str, Any]], env: str) -> None:
    """Block a global view holding widgets nobody has certified, when configured to.

    A global view is the one place in this app where one person's work lands on
    everyone else's screen without them choosing it, so it is the place worth
    gating on review. Off by default — see the setting's own note: certification
    happens during promotion to production, so requiring it everywhere would make
    global views impossible to create in dev and test.

    Only widgets present in the `widgets` table are considered. Built-in widget
    types ship with the app and are reviewed by the act of being in the repo;
    they have no row here and are not something an author can introduce.
    """
    from services.settings_store import get_bool_setting

    if not get_bool_setting("require_certified_for_global_views"):
        return

    types = {str(w.get("type")) for w in (widgets or []) if w.get("type")}
    custom_ids = sorted(t for t in types if _CUSTOM_WIDGET_ID.match(t))
    if not custom_ids:
        return

    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT w.id, w.name, COALESCE(w.is_certified, 0) AS is_certified
              FROM widgets w
              INNER JOIN (
                    SELECT id, MAX(version) AS version
                      FROM widgets
                     WHERE is_deprecated = 0
                       AND id = ANY(%s)
                     GROUP BY id
                   ) latest ON w.id = latest.id AND w.version = latest.version
            """,
            (custom_ids,),
        )
        uncertified: List[str] = []
        found_ids: set[str] = set()
        for row in c.fetchall():
            wid, name, certified = row[0], row[1], row[2]
            found_ids.add(str(wid))
            if not certified:
                uncertified.append(name)
        for missing_id in custom_ids:
            if missing_id not in found_ids:
                uncertified.append(f"unknown widget ({missing_id})")
        uncertified = sorted(uncertified)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    if uncertified:
        raise HTTPException(
            status_code=400,
            detail=(
                "A view shared with everyone may only contain certified widgets. "
                f"Not yet certified: {', '.join(uncertified)}."
            ),
        )


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


def pin_value(incoming: Optional[str], previous: Optional[str]) -> Optional[str]:
    """The agent id to store for a view, given what the client sent.

    A save that says nothing about the pin keeps it: every widget move is a full
    PUT, and those must not quietly unpin a view. An empty string is how a client
    says "no agent" — JSON null can't carry that meaning here, since an absent
    field arrives as null too.
    """
    if incoming is None:
        return (previous or "").strip() or None
    return incoming.strip() or None

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
            SELECT dv.id, dv.version, dv.name, dv.domain, dv.username, dv.is_global, dv.widgets_json, dv.is_locked,
                   dv.pinned_agent_id, dv.timestamp,
                   CASE WHEN dv.username != %s AND dv.is_global = 0 AND sv.username IS NOT NULL THEN 1 ELSE 0 END as is_shared
            FROM dashboard_views dv
            INNER JOIN (
                SELECT id, MAX(version) as max_version
                FROM dashboard_views
                GROUP BY id
            ) latest ON dv.id = latest.id AND dv.version = latest.max_version
            LEFT JOIN shared_views sv ON dv.id = sv.view_id AND sv.username = %s
            WHERE (dv.username = %s) 
               OR (dv.is_global = 1)
               OR (sv.username IS NOT NULL)
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
                    
            try:
                widgets = json.loads(v.get('widgets_json', '[]'))
            except:
                widgets = []
                
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
        _require_certified_widgets(view.widgets, env)

    actual_username = 'system' if view.is_global else username
    view_id = view.id if view.id else str(uuid.uuid4())
    widgets_json = json.dumps(view.widgets)
    
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        c.execute("""
            INSERT INTO dashboard_views (id, version, name, domain, username, is_global, widgets_json, is_locked, pinned_agent_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (view_id, 1, view.name, view.domain, actual_username, int(view.is_global), widgets_json,
              int(view.is_locked), pin_value(view.pinned_agent_id, None)))
            
        conn.commit()
        conn.close()
        
        return {"status": "success", "id": view_id, "version": 1}
    except Exception as e:
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=f"Error creating view: {str(e)}")

@router.put("/{view_id}")
def update_view(view_id: str, view: ViewUpdate, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    username = _get_current_username(w)
    
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        # Check ownership and current version
        c.execute("SELECT username, is_global, version FROM dashboard_views WHERE id = %s ORDER BY version DESC LIMIT 1", (view_id,))
        row = c.fetchone()
        if row:
            existing = dict(zip([column[0] for column in c.description], row))
        else:
            existing = None
            
        if not existing:
            conn.close()
            raise HTTPException(status_code=404, detail="View not found")
        
        if existing['is_global']:
            require_domain_editor(w, existing.get('domain', 'General'), env)
            
        if not existing['is_global'] and existing['username'] != username:
            conn.close()
            raise HTTPException(status_code=403, detail="You can only edit your own views")
            
        # Instead of updating the row directly, we insert a new version for history/promotion
        new_version = existing['version'] + 1
        
        # We need the full existing row to copy fields not being updated
        c.execute("SELECT * FROM dashboard_views WHERE id = %s AND version = %s", (view_id, existing['version']))
        row = c.fetchone()
        full_existing = dict(zip([column[0] for column in c.description], row))
        
        name = view.name if view.name is not None else full_existing['name']
        domain = view.domain if view.domain is not None else full_existing['domain']
        is_global = view.is_global if view.is_global is not None else bool(full_existing['is_global'])
        is_locked = view.is_locked if view.is_locked is not None else bool(full_existing['is_locked'])
        pinned_agent_id = pin_value(view.pinned_agent_id, full_existing.get('pinned_agent_id'))
        
        if view.widgets is not None:
            widgets_json = json.dumps(view.widgets)
        else:
            widgets_json = full_existing['widgets_json']
            
        actual_username = 'system' if is_global else username

        # Checked on update too, and against the resulting widget list rather than
        # the submitted one: a view that passed at creation must not become a way
        # to put an uncertified widget in front of everyone by editing it later.
        if is_global:
            try:
                _require_certified_widgets(json.loads(widgets_json or "[]"), env)
            except HTTPException:
                # This connection is still open and the outer handler re-raises
                # HTTPException untouched, so release it here rather than leaving
                # it to garbage collection.
                conn.close()
                raise

        c.execute("""
            INSERT INTO dashboard_views (id, version, name, domain, username, is_global, widgets_json, is_locked, pinned_agent_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (view_id, new_version, name, domain, actual_username, int(is_global), widgets_json,
              int(is_locked), pinned_agent_id))
            
        conn.commit()
        conn.close()
        
        return {"status": "success", "id": view_id, "version": new_version}
    except HTTPException:
        raise
    except Exception as e:
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=f"Error updating view: {str(e)}")

@router.delete("/{view_id}")
def delete_view(view_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    username = _get_current_username(w)
    
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        c.execute("SELECT username, is_global, domain FROM dashboard_views WHERE id = %s LIMIT 1", (view_id,))
        row = c.fetchone()
        if row:
            existing = dict(zip([column[0] for column in c.description], row))
        else:
            existing = None
            
        if not existing:
            conn.close()
            raise HTTPException(status_code=404, detail="View not found")
        
        if existing['is_global']:
            require_domain_editor(w, existing.get('domain', 'General'), env)
            
        if not existing['is_global'] and existing['username'] != username:
            conn.close()
            raise HTTPException(status_code=403, detail="You can only delete your own views")
            
        c.execute("DELETE FROM dashboard_views WHERE id = %s", (view_id,))
            
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
