from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from database import get_db_connection
from middleware.auth import get_db_client
from databricks.sdk import WorkspaceClient
from routes.roles import require_domain_editor

router = APIRouter()

class TransferRequest(BaseModel):
    widget_id: str
    source_env: str
    target_env: str
    version: Optional[int] = None # If None, defaults to the latest version
    is_rollback: bool = False

@router.post("/transfer")
async def transfer_widget(request: TransferRequest, w: WorkspaceClient = Depends(get_db_client)):
    # Connect to the source environment to fetch the widget
    source_conn = get_db_connection(request.source_env)
    c_source = source_conn.cursor()
    
    if request.version is not None:
        c_source.execute("SELECT * FROM widgets WHERE id = %s AND version = %s AND is_deprecated = 0", (request.widget_id, request.version))
    else:
        c_source.execute("SELECT * FROM widgets WHERE id = %s AND is_deprecated = 0 ORDER BY version DESC LIMIT 1", (request.widget_id,))
            
    row = c_source.fetchone()
    if not row:
        source_conn.close()
        raise HTTPException(status_code=404, detail=f"Widget not found in source environment ({request.source_env})")
        
    columns = [desc[0] for desc in c_source.description]
    widget = dict(zip(columns, row))
    # The dictionary keys should match the widget columns
    keys = list(widget.keys())
    # remove timestamp
    if "timestamp" in keys: keys.remove("timestamp")
    
    source_conn.close()

    # RBAC Enforcement: must be editor/admin in the target environment for this domain
    require_domain_editor(w, widget.get('domain', 'General'), request.target_env)

    # Connect to the target environment to fetch the latest version there
    target_conn = get_db_connection(request.target_env)
    c_target = target_conn.cursor()

    if request.is_rollback and request.version is not None:
        # True rollback: mark all newer versions as deprecated so target_version becomes head
        c_target.execute(
            "UPDATE widgets SET is_deprecated = 1 WHERE id = %s AND version > %s",
            (request.widget_id, request.version)
        )
        target_conn.commit()
        target_conn.close()
        return {"status": "success", "message": f"Rolled back widget {request.widget_id} to v{request.version} in {request.target_env}"}

    c_target.execute("SELECT version, is_deprecated FROM widgets WHERE id = %s AND version = %s", (request.widget_id, widget['version']))
    existing = c_target.fetchone()
    if existing:
        if existing[1]:  # is_deprecated=1 — just restore it
            c_target.execute("UPDATE widgets SET is_deprecated = 0 WHERE id = %s AND version = %s", (request.widget_id, existing[0]))
            target_conn.commit()
            target_conn.close()
            return {"status": "success", "message": f"Restored widget {request.widget_id} v{existing[0]} in {request.target_env}"}
        else:
            target_conn.commit()
            target_conn.close()
            return {"status": "success", "message": "Already up to date"}

    c_target.execute("SELECT MAX(version) FROM widgets WHERE id = %s AND is_deprecated = 0", (request.widget_id,))
        
    target_row = c_target.fetchone()
    max_version = target_row[0] if (target_row and target_row[0] is not None) else 0
    new_version = max_version + 1
    
    # Update version for the insert
    widget['version'] = new_version
    
    columns = ", ".join(keys)
    
    placeholders = ", ".join(["%s"] * len(keys))
    values = tuple([widget[k] for k in keys])
    query = f"INSERT INTO widgets ({columns}) VALUES ({placeholders})"
    c_target.execute(query, values)

    target_conn.commit()
    target_conn.close()

    return {"status": "success", "message": f"Transferred widget {request.widget_id} to {request.target_env} as version {new_version}", "new_version": new_version}

class CertifyRequest(BaseModel):
    widget_id: str
    version: int

@router.post("/certify")
async def certify_widget(request: CertifyRequest, w: WorkspaceClient = Depends(get_db_client)):
    # Connect to the production environment
    conn = get_db_connection('prod')
    c = conn.cursor()
    
    c.execute("SELECT domain FROM widgets WHERE id = %s LIMIT 1", (request.widget_id,))
    row = c.fetchone()
    if row:
        domain = row['domain'] if hasattr(row, 'keys') else row[0]
        require_domain_editor(w, domain, 'prod')
    
    c.execute("UPDATE widgets SET is_certified = 1 WHERE id = %s AND version = %s AND is_deprecated = 0", (request.widget_id, request.version))
        
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Widget not found in production or already deprecated.")
        
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": f"Certified widget {request.widget_id} v{request.version}."}

class ViewTransferRequest(BaseModel):
    view_id: str
    source_env: str
    target_env: str
    version: Optional[int] = None
    is_rollback: bool = False

@router.post("/transfer_view")
async def transfer_view(request: ViewTransferRequest, w: WorkspaceClient = Depends(get_db_client)):
    source_conn = get_db_connection(request.source_env)
    c_source = source_conn.cursor()
    
    if request.version is not None:
        c_source.execute("SELECT * FROM dashboard_views WHERE id = %s AND version = %s", (request.view_id, request.version))
    else:
        c_source.execute("SELECT * FROM dashboard_views WHERE id = %s ORDER BY version DESC LIMIT 1", (request.view_id,))
            
    row = c_source.fetchone()
    if not row:
        source_conn.close()
        raise HTTPException(status_code=404, detail=f"View not found in source environment ({request.source_env})")
        
    columns = [desc[0] for desc in c_source.description]
    view = dict(zip(columns, row))
    keys = list(view.keys())
    if "timestamp" in keys: keys.remove("timestamp")
    
    source_conn.close()

    # RBAC Enforcement: must be editor/admin in the target environment for this domain
    require_domain_editor(w, view.get('domain', 'General'), request.target_env)

    target_conn = get_db_connection(request.target_env)
    c_target = target_conn.cursor()

    if request.is_rollback and request.version is not None:
        # dashboard_views does not have is_deprecated; delete newer versions to restore
        c_target.execute(
            "DELETE FROM dashboard_views WHERE id = %s AND version > %s",
            (request.view_id, request.version)
        )
        target_conn.commit()
        target_conn.close()
        return {"status": "success", "message": f"Rolled back view {request.view_id} to v{request.version} in {request.target_env}"}

    # Check if the exact version already exists in target (possibly deprecated)
    c_target.execute("SELECT version, is_locked FROM dashboard_views WHERE id = %s AND version = %s", (request.view_id, view['version']))
    existing = c_target.fetchone()
    if existing:
        # Row exists — nothing to do (views are never deprecated, just versioned)
        target_conn.commit()
        target_conn.close()
        return {"status": "success", "message": "Already up to date"}

    c_target.execute("SELECT MAX(version) FROM dashboard_views WHERE id = %s", (request.view_id,))
        
    target_row = c_target.fetchone()
    max_version = target_row[0] if (target_row and target_row[0] is not None) else 0
    new_version = max_version + 1
    
    view['version'] = new_version
    columns = ", ".join(keys)
    
    placeholders = ", ".join(["%s"] * len(keys))
    values = tuple([view[k] for k in keys])
    query = f"INSERT INTO dashboard_views ({columns}) VALUES ({placeholders})"
    c_target.execute(query, values)

    target_conn.commit()
    target_conn.close()

    return {"status": "success", "message": f"Transferred view {request.view_id} to {request.target_env} as version {new_version}", "new_version": new_version}

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d
