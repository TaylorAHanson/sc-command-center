from fastapi import APIRouter, HTTPException, Depends
from database import get_db_connection
from middleware.auth import get_db_client, get_user_token
from databricks.sdk import WorkspaceClient
from typing import Optional
import uuid
import os
from routes.roles import require_domain_editor, _get_current_username, _get_user_permissions
from services.creator_stats import is_person, same_person

router = APIRouter()


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


@router.get("/custom")
def get_custom_widgets(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    perms = _get_user_permissions(w, env)
    is_admin = perms.get("is_admin", False)
    domain_permissions = perms.get("domain_permissions", {})
    
    conn = get_db_connection(env)
    c = conn.cursor()
    query = '''
        SELECT * FROM widgets 
        WHERE is_deprecated = 0
        ORDER BY timestamp DESC
    '''
    c.execute(query)

    rows = [dict({k: v for k, v in zip([desc[0] for desc in c.description], row)}) for row in c.fetchall()]
    conn.close()

    # Filter widgets based on user permissions
    filtered_rows = []
    for r in rows:
        if is_admin:
            filtered_rows.append(r)
            continue
            
        domain = r.get("domain", "General")
        if domain in domain_permissions:
            filtered_rows.append(r)

    return {"widgets": filtered_rows}


@router.get("/history")
def get_widget_history(widget_id: str, env: str = "dev"):
    """Return all versions of a widget in a given env, ordered newest first.

    Carries each version's size but not its code: the size is what tells a version
    apart at a glance (a 12-line entry under a 240-line one is the turn that ate
    the widget), while shipping every version's source would make the list heavy
    for no one's benefit. Widget Studio fetches the code for the one version it
    restores from `/version`.
    """
    conn = get_db_connection(env)
    c = conn.cursor()
    c.execute(
        "SELECT version, name, created_by, timestamp, tsx_code FROM widgets "
        "WHERE id = %s AND is_deprecated = 0 ORDER BY version DESC",
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
    conn.close()
    return {"history": rows, "env": env}


@router.get("/version")
def get_widget_version(widget_id: str, version: int, env: str = "dev"):
    """Return one published version in full, including its code.

    Backs Restore in Widget Studio: the studio loads this into the editor, where it
    becomes an ordinary unsaved change the user still has to publish.
    """
    conn = get_db_connection(env)
    c = conn.cursor()
    c.execute(
        "SELECT * FROM widgets WHERE id = %s AND version = %s",
        (widget_id, version)
    )
    row = c.fetchone()
    columns = [d[0] for d in c.description]
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Version {version} of this widget was not found in {env}.")
    return {"widget": dict(zip(columns, row)), "env": env}



@router.post("/custom")
def create_custom_widget(widget: dict, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    domain = widget.get("domain", "General")
    require_domain_editor(w, domain, env)
    
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
    help_text = widget.get("help_text", None)
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
        (id, version, name, description, category, domain, default_w, default_h, tsx_code, configuration_mode, config_schema, data_source_type, data_source, snapshot, help_text, open_in_new_tab_link, is_executable, created_by) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (widget_id, new_version, name, description, category, domain, default_w, default_h, tsx_code, config_mode, config_schema, data_source_type, data_source, snapshot, help_text, open_in_new_tab_link, is_executable, created_by))

    conn.commit()
    conn.close()
    return {"status": "success", "id": widget_id, "created_by": created_by}


@router.put("/custom/{widget_id}")
def update_custom_widget(widget_id: str, widget: dict, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    conn = get_db_connection(env)
    c = conn.cursor()

    current_user = _get_current_username(w)

    # Verify ownership / permissions
    c.execute("SELECT created_by, version, domain FROM widgets WHERE id = %s ORDER BY version DESC LIMIT 1", (widget_id,))

    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Widget not found")

    if hasattr(row, 'keys'):
        owner = row['created_by']
        current_version = row['version']
        existing_domain = row['domain']
    else:
        owner = row[0]
        current_version = row[1]
        existing_domain = row[2]
    
    # Must be an editor of the existing domain
    require_domain_editor(w, existing_domain, env)
    
    new_domain = widget.get("domain", "General")
    if new_domain != existing_domain:
        # Must also be an editor of the new domain if changing
        require_domain_editor(w, new_domain, env)

    name = widget.get("name")
    tsx_code = widget.get("tsx_code")
    description = widget.get("description", "")
    category = widget.get("category", "Custom")
    domain = new_domain
    data_source_type = widget.get("data_source_type", "none")
    data_source = widget.get("data_source", None)
    default_w = widget.get("default_w", 6)
    default_h = widget.get("default_h", 6)
    configuration_mode = widget.get("configurationMode", widget.get("configuration_mode", "none"))
    config_schema = widget.get("configSchema", widget.get("config_schema", None))
    snapshot = widget.get("snapshot", widget.get("snapshot", None))
    help_text = widget.get("help_text", widget.get("help_text", None))
    open_in_new_tab_link = widget.get("open_in_new_tab_link", widget.get("open_in_new_tab_link", None))
    is_executable = 1 if widget.get("isExecutable", widget.get("is_executable", False)) else 0

    if not name or not tsx_code:
        conn.close()
        raise HTTPException(status_code=400, detail="Name and tsx_code are required")

    new_version = current_version + 1

    c.execute('''
        INSERT INTO widgets 
        (id, version, name, description, category, domain, default_w, default_h, tsx_code, configuration_mode, config_schema, data_source_type, data_source, snapshot, help_text, open_in_new_tab_link, is_executable, created_by) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (widget_id, new_version, name, description, category, domain, default_w, default_h, tsx_code, configuration_mode, config_schema, data_source_type, data_source, snapshot, help_text, open_in_new_tab_link, is_executable, owner))

    conn.commit()
    conn.close()
    return {"status": "success"}


@router.post("/custom/{widget_id}/snapshot")
def update_widget_snapshot(widget_id: str, payload: dict, env: str = "dev"):
    """Backfill or refresh a thumbnail snapshot for an existing widget. Updates
    the latest version row in place rather than creating a new version, since
    the snapshot is presentation-only and not part of the published code."""
    snapshot = payload.get("snapshot")
    if not snapshot:
        raise HTTPException(status_code=400, detail="snapshot is required")
    conn = get_db_connection(env)
    c = conn.cursor()
    try:
        c.execute("SELECT MAX(version) FROM widgets WHERE id = %s AND is_deprecated = 0", (widget_id,))
        row = c.fetchone()
        max_version = row[0] if (row and row[0] is not None) else None
        if max_version is None:
            conn.close()
            raise HTTPException(status_code=404, detail="Widget not found")
        c.execute("UPDATE widgets SET snapshot = %s WHERE id = %s AND version = %s", (snapshot, widget_id, max_version))
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))
    conn.close()
    return {"status": "success", "id": widget_id, "version": max_version}


@router.delete("/custom/{widget_id}")
def delete_custom_widget(widget_id: str, user_token: Optional[str] = Depends(get_user_token), env: str = "dev"):
    conn = get_db_connection(env)
    c = conn.cursor()

    # Build a WorkspaceClient if we have a token; without one the caller resolves
    # to "unknown", which the ownership check below refuses to match against.
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
    # An author that was never a person — NULL, or one of the placeholders an
    # unresolved identity used to be written as — means the widget belongs to
    # nobody, so anyone may tidy it up. This used to test for "unknown" alone,
    # which left every widget stamped "dev" by the identity bug owned by a user
    # who cannot sign in, and so undeletable by anyone.
    if is_person(owner) and not same_person(owner, current_user):
        conn.close()
        raise HTTPException(status_code=403, detail="You do not have permission to delete this widget")

    c.execute("UPDATE widgets SET is_deprecated = 1 WHERE id = %s", (widget_id,))

    conn.commit()
    conn.close()
    return {"status": "deleted", "id": widget_id}
