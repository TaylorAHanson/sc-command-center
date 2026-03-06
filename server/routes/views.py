from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json
import uuid
from database import get_db_connection
from middleware.auth import get_db_client
from databricks.sdk import WorkspaceClient
from routes.roles import _get_current_username

router = APIRouter()

class ViewCreate(BaseModel):
    id: Optional[str] = None
    name: str
    domain: Optional[str] = "General"
    is_global: bool = False
    is_locked: bool = False
    widgets: List[Dict[str, Any]] = []

class ViewUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    is_global: Optional[bool] = None
    is_locked: Optional[bool] = None
    widgets: Optional[List[Dict[str, Any]]] = None

def _is_admin(username: str) -> bool:
    # Basic mockup for Admin check
    # In a real app, you would check a specific user group or role mapping
    return True

@router.get("/")
async def get_views(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Fetch all views accessible to the user (their own + matching global views)."""
    username = _get_current_username(w)
    
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        # Get user's active domains (mocked logic or fetch from role_mappings if needed)
        # For now, we return all global views + user's own views
        
        c.execute("""
            SELECT dv.id, dv.version, dv.name, dv.domain, dv.username, dv.is_global, dv.widgets_json, dv.is_locked, dv.timestamp
            FROM dashboard_views dv
            INNER JOIN (
                SELECT id, MAX(version) as max_version
                FROM dashboard_views
                GROUP BY id
            ) latest ON dv.id = latest.id AND dv.version = latest.max_version
            WHERE (dv.username = %s) 
               OR (dv.is_global = 1)
        """, (username,))
        rows = c.fetchall()
        views = [dict(zip([column[0] for column in c.description], row)) for row in rows]
            
        conn.close()
        
        # Parse JSON
        result = []
        for v in views:
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
                "widgets": widgets
            })
            
        return {"views": result}
    except Exception as e:
        if 'conn' in locals() and conn:
            conn.close()
        raise HTTPException(status_code=500, detail=f"Error fetching views: {str(e)}")

@router.get("/history")
async def get_view_history(view_id: str, env: str = "dev"):
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


@router.post("/")
async def create_view(view: ViewCreate, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    username = _get_current_username(w)
    
    if view.is_global and not _is_admin(username):
        raise HTTPException(status_code=403, detail="Only admins can create global views")
        
    actual_username = 'system' if view.is_global else username
    view_id = view.id if view.id else str(uuid.uuid4())
    widgets_json = json.dumps(view.widgets)
    
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        c.execute("""
            INSERT INTO dashboard_views (id, version, name, domain, username, is_global, widgets_json, is_locked)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (view_id, 1, view.name, view.domain, actual_username, int(view.is_global), widgets_json, int(view.is_locked)))
            
        conn.commit()
        conn.close()
        
        return {"status": "success", "id": view_id, "version": 1}
    except Exception as e:
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=f"Error creating view: {str(e)}")

@router.put("/{view_id}")
async def update_view(view_id: str, view: ViewUpdate, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
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
        
        if existing['is_global'] and not _is_admin(username):
            conn.close()
            raise HTTPException(status_code=403, detail="Only admins can edit global views")
            
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
        
        if view.widgets is not None:
            widgets_json = json.dumps(view.widgets)
        else:
            widgets_json = full_existing['widgets_json']
            
        actual_username = 'system' if is_global else username
        
        c.execute("""
            INSERT INTO dashboard_views (id, version, name, domain, username, is_global, widgets_json, is_locked)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (view_id, new_version, name, domain, actual_username, int(is_global), widgets_json, int(is_locked)))
            
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
async def delete_view(view_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    username = _get_current_username(w)
    
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        c.execute("SELECT username, is_global FROM dashboard_views WHERE id = %s LIMIT 1", (view_id,))
        row = c.fetchone()
        if row:
            existing = dict(zip([column[0] for column in c.description], row))
        else:
            existing = None
            
        if not existing:
            conn.close()
            raise HTTPException(status_code=404, detail="View not found")
        
        if existing['is_global'] and not _is_admin(username):
            conn.close()
            raise HTTPException(status_code=403, detail="Only admins can delete global views")
            
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
