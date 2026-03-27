from fastapi import APIRouter, HTTPException, Depends
from database import get_db_connection
from middleware.auth import get_db_client, get_user_token
from databricks.sdk import WorkspaceClient
from typing import Optional
import uuid
import logging
import os

router = APIRouter()


def _get_current_username(w: Optional[WorkspaceClient]) -> str:
    """Resolve the current logged-in user's username from the WorkspaceClient."""
    if w is None:
        return "dev" if os.environ.get('DEV_MODE', '').lower() == 'true' else "unknown"
    try:
        return w.current_user().user_name or "unknown"
    except Exception as e:
        if os.environ.get('DEV_MODE', '').lower() == 'true':
            return "dev"
        logging.warning(f"Could not resolve current user: {e}")
        return "unknown"


@router.get("/me")
async def get_current_user(w: WorkspaceClient = Depends(get_db_client)):
    """Return the current user's identity."""
    return {"user": _get_current_username(w)}


@router.get("/custom")
async def get_custom_widgets(env: str = "dev"):
    conn = get_db_connection(env)
    c = conn.cursor()
    query = '''
        SELECT w.* FROM widgets w
        INNER JOIN (
            SELECT id, MAX(version) as max_version 
            FROM widgets 
            WHERE is_deprecated = 0
            GROUP BY id
        ) latest ON w.id = latest.id AND w.version = latest.max_version
        WHERE w.is_deprecated = 0
        ORDER BY w.timestamp DESC
    '''
    c.execute(query)

    rows = [dict({k: v for k, v in zip([desc[0] for desc in c.description], row)}) for row in c.fetchall()]

    conn.close()
    return {"widgets": rows}


@router.get("/history")
async def get_widget_history(widget_id: str, env: str = "dev"):
    """Return all versions of a widget in a given env, ordered newest first."""
    conn = get_db_connection(env)
    c = conn.cursor()
    c.execute(
        "SELECT version, name, created_by, timestamp FROM widgets WHERE id = %s AND is_deprecated = 0 ORDER BY version DESC",
        (widget_id,)
    )
    rows = [dict(zip([d[0] for d in c.description], row)) for row in c.fetchall()]
    conn.close()
    return {"history": rows, "env": env}



@router.post("/custom")
async def create_custom_widget(widget: dict, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    conn = get_db_connection(env)
    c = conn.cursor()

    widget_id = widget.get("id", str(uuid.uuid4()))
    name = widget.get("name", "Untitled Widget")
    description = widget.get("description", "")
    category = widget.get("category", "Custom")
    domain = widget.get("domain", "General")
    default_w = widget.get("defaultW", widget.get("default_w", 6))
    default_h = widget.get("defaultH", widget.get("default_h", 6))
    tsx_code = widget.get("tsx_code", "")
    config_mode = widget.get("configurationMode", "none")
    config_schema = widget.get("configSchema", None)
    data_source_type = widget.get("data_source_type", "none")
    data_source = widget.get("data_source", None)
    snapshot = widget.get("snapshot", None)
    open_in_new_tab_link = widget.get("open_in_new_tab_link", None)
    is_executable = 1 if widget.get("isExecutable", False) else 0
    created_by = _get_current_username(w)

    c.execute("SELECT MAX(version) FROM widgets WHERE id = %s", (widget_id,))
    
    row = c.fetchone()
    # Handle both tuple and sqlite3.Row structures
    max_version = row[0] if (row and row[0] is not None) else 0
        
    if max_version is None:
        max_version = 0
        
    new_version = max_version + 1

    c.execute('''
        INSERT INTO widgets 
        (id, version, name, description, category, domain, default_w, default_h, tsx_code, configuration_mode, config_schema, data_source_type, data_source, snapshot, open_in_new_tab_link, is_executable, created_by) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (widget_id, new_version, name, description, category, domain, default_w, default_h, tsx_code, config_mode, config_schema, data_source_type, data_source, snapshot, open_in_new_tab_link, is_executable, created_by))

    conn.commit()
    conn.close()
    return {"status": "success", "id": widget_id, "created_by": created_by}


@router.put("/custom/{widget_id}")
async def update_custom_widget(widget_id: str, widget: dict, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    conn = get_db_connection(env)
    c = conn.cursor()

    current_user = _get_current_username(w)

    # Verify ownership
    c.execute("SELECT created_by, version FROM widgets WHERE id = %s ORDER BY version DESC LIMIT 1", (widget_id,))

    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Widget not found")

    owner = row["created_by"] if not isinstance(row, tuple) else row[0]
    current_version = row["version"] if not isinstance(row, tuple) else row[1]
    
    if owner and owner != "unknown" and owner != current_user:
        conn.close()
        raise HTTPException(status_code=403, detail="You do not have permission to edit this widget")

    name = widget.get("name")
    tsx_code = widget.get("tsx_code")
    description = widget.get("description", "")
    category = widget.get("category", "Custom")
    domain = widget.get("domain", "General")
    data_source_type = widget.get("data_source_type", "none")
    data_source = widget.get("data_source", None)
    default_w = widget.get("default_w", 6)
    default_h = widget.get("default_h", 6)
    configuration_mode = widget.get("configurationMode", widget.get("configuration_mode", "none"))
    config_schema = widget.get("configSchema", widget.get("config_schema", None))
    snapshot = widget.get("snapshot", widget.get("snapshot", None))
    open_in_new_tab_link = widget.get("open_in_new_tab_link", widget.get("open_in_new_tab_link", None))
    is_executable = 1 if widget.get("isExecutable", widget.get("is_executable", False)) else 0

    if not name or not tsx_code:
        conn.close()
        raise HTTPException(status_code=400, detail="Name and tsx_code are required")

    new_version = current_version + 1

    c.execute('''
        INSERT INTO widgets 
        (id, version, name, description, category, domain, default_w, default_h, tsx_code, configuration_mode, config_schema, data_source_type, data_source, snapshot, open_in_new_tab_link, is_executable, created_by) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (widget_id, new_version, name, description, category, domain, default_w, default_h, tsx_code, configuration_mode, config_schema, data_source_type, data_source, snapshot, open_in_new_tab_link, is_executable, owner))

    conn.commit()
    conn.close()
    return {"status": "success"}


@router.delete("/custom/{widget_id}")
async def delete_custom_widget(widget_id: str, user_token: Optional[str] = Depends(get_user_token), env: str = "dev"):
    conn = get_db_connection(env)
    c = conn.cursor()

    # Build a WorkspaceClient if we have a token, otherwise pass None (DEV_MODE will fall back to "dev")
    w: Optional[WorkspaceClient] = None
    if user_token:
        try:
            w = WorkspaceClient(host=os.environ.get('DATABRICKS_HOST'), token=user_token)
        except Exception:
            pass

    current_user = _get_current_username(w)

    c.execute("SELECT created_by FROM widgets WHERE id = %s ORDER BY version DESC LIMIT 1", (widget_id,))

    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Widget not found")

    owner = row["created_by"] if not isinstance(row, tuple) else row[0]
    # Allow delete if owner is null/unknown (legacy) or matches current user
    if owner and owner != "unknown" and owner != current_user:
        conn.close()
        raise HTTPException(status_code=403, detail="You do not have permission to delete this widget")

    c.execute("UPDATE widgets SET is_deprecated = 1 WHERE id = %s", (widget_id,))

    conn.commit()
    conn.close()
    return {"status": "deleted", "id": widget_id}
