from fastapi import APIRouter, HTTPException, Depends
from database import get_db_connection
from middleware.auth import get_db_client, get_user_token
from databricks.sdk import WorkspaceClient
from typing import Optional
import logging
import uuid
import os
from routes.roles import require_domain_editor, _get_current_username, _get_user_permissions
from services.creator_stats import is_person, same_person, unowned_sql

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


def _visible(rows: list, perms: dict) -> list:
    """The rows this caller may see. A global admin sees every domain."""
    if perms.get("is_admin", False):
        return rows
    allowed = perms.get("domain_permissions", {})
    return [r for r in rows if (r.get("domain") or "General") in allowed]


@router.get("/custom")
def get_custom_widgets(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Every widget the caller can see — with the source of the current version only.

    This answers the first request the app makes, so what it *doesn't* send matters
    more than what it does. It used to be `SELECT *`: every version of every widget,
    each carrying its full source and its base64 thumbnail. Widget Studio publishes
    a version per save, so that grows without bound — 30 widgets with a few dozen
    saves each is tens of megabytes over the wire, and the browser then compiled
    every row of it, freezing the page for long enough that Chrome offered to end it.

    Older versions are still listed, because the version dropdown on a placed widget
    has to know they exist, but only their metadata: the source of one comes from
    `/version` if somebody actually pins it. Thumbnails come from
    `/custom/snapshots` when the library is opened, which is the only place they're
    shown; here they'd be paid for on every page load by everyone.
    """
    perms = _get_user_permissions(w, env)

    conn = get_db_connection(env)
    c = conn.cursor()
    # `is_latest` is computed here rather than by fetching everything and sorting
    # in Python, so the old versions' source never leaves Postgres.
    c.execute('''
        SELECT id, version, name, description, category, domain,
               default_w, default_h, configuration_mode, config_schema,
               data_source_type, data_source, help_text, open_in_new_tab_link,
               is_executable, is_certified, created_by, timestamp,
               (snapshot IS NOT NULL AND snapshot <> '') AS has_snapshot,
               (version = MAX(version) OVER (PARTITION BY id)) AS is_latest,
               CASE WHEN version = MAX(version) OVER (PARTITION BY id)
                    THEN tsx_code END AS tsx_code
        FROM widgets
        WHERE is_deprecated = 0
        ORDER BY timestamp DESC
    ''')
    columns = [desc[0] for desc in c.description]
    rows = [dict(zip(columns, row)) for row in c.fetchall()]
    conn.close()

    return {"widgets": _visible(rows, perms)}


@router.get("/custom/snapshots")
def get_widget_snapshots(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Thumbnails for the current version of each widget, keyed by widget id.

    Split out of `/custom` because these are the heaviest thing the app stores — a
    base64 PNG per widget — and the only place they are shown is the Widget
    Library, which most sessions never open.
    """
    perms = _get_user_permissions(w, env)

    conn = get_db_connection(env)
    c = conn.cursor()
    c.execute('''
        SELECT id, domain, snapshot FROM (
            SELECT id, domain, snapshot, version,
                   MAX(version) OVER (PARTITION BY id) AS latest
            FROM widgets WHERE is_deprecated = 0
        ) w
        WHERE version = latest AND snapshot IS NOT NULL AND snapshot <> ''
    ''')
    columns = [desc[0] for desc in c.description]
    rows = [dict(zip(columns, row)) for row in c.fetchall()]
    conn.close()

    return {"snapshots": {r["id"]: r["snapshot"] for r in _visible(rows, perms)}}


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


@router.post("/custom/{widget_id}/claim")
def claim_custom_widget(widget_id: str, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """Put your name on a widget nobody is recorded as having written.

    Authorship was recorded by a resolver that never worked — it shipped broken in
    the same commit that added the `created_by` column — so the credit for every
    widget built before that was fixed is a placeholder, and nothing we stored can
    recover it. `action_logs` has no username, `widget_runs` says who *used* a
    widget, and a view only says who placed one. So the person who recognises their
    own work says so, and that is the only route back to a real name.

    It can only ever fill a blank. A widget with a real author is not claimable —
    including by that author's colleague — and the check happens inside the UPDATE
    so that two people claiming at once can't overwrite each other.
    """
    me = _get_current_username(w)
    if not is_person(me):
        raise HTTPException(status_code=403, detail="We can't tell who you are, so we can't credit you.")

    conn = get_db_connection(env)
    try:
        c = conn.cursor()
        c.execute(
            "SELECT created_by, domain FROM widgets WHERE id = %s ORDER BY version DESC LIMIT 1",
            (widget_id,),
        )
        row = c.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Widget not found")
        if hasattr(row, 'keys'):
            owner, domain = row['created_by'], row['domain']
        else:
            owner, domain = row[0], row[1]

        if is_person(owner):
            raise HTTPException(status_code=409, detail=f"{owner} is already credited with this widget.")

        # Claiming credit in a domain you couldn't publish to isn't yours to do.
        require_domain_editor(w, domain or "General", env)

        # Every version, because no version ever held a real name: this is filling
        # in a blank rather than rewriting history. The condition repeats the
        # placeholder test so the row can't have been claimed since we read it.
        unowned, params = unowned_sql()
        c.execute(
            f"UPDATE widgets SET created_by = %s WHERE id = %s AND {unowned}",
            [me, widget_id, *params],
        )
        claimed = c.rowcount
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
