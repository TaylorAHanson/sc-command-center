from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Tuple
from database import get_db_connection
from middleware.auth import get_db_client
from databricks.sdk import WorkspaceClient
from routes.roles import require_domain_editor
from services import app_spec, app_store

router = APIRouter()

#: Per-row bookkeeping that differs between copies of the same widget or view.
_BOOKKEEPING = {"version", "timestamp", "is_deprecated", "is_certified", "created_by"}

#: The pin that means "the built-in assistant"; it names no agent row.
_DEFAULT_AGENT = "default"


def same_content(a: dict, b: dict) -> bool:
    """Whether two widget or view rows (possibly from different envs) hold the same thing."""
    keys = (set(a) | set(b)) - _BOOKKEEPING
    return all((a.get(k) or None) == (b.get(k) or None) for k in keys)


def same_view_content(a: dict, b: dict) -> bool:
    """`same_content` for view/app rows, comparing what the rows mean rather than how they're stored.

    A row saved before apps has only `widgets_json`; the same layout saved since
    also carries `spec_json`. Compared column by column, every view promoted from
    an env where someone had touched it to one where nobody had would look
    changed, and get a new version, with nothing different about it.
    """
    from services.app_spec import read_spec

    def meaning(row: dict) -> dict:
        out = {k: v for k, v in row.items() if k not in ("widgets_json", "spec_json")}
        out["spec"] = read_spec(str(row.get("id") or ""), row.get("spec_json"), row.get("widgets_json"))
        return out

    return same_content(meaning(a), meaning(b))


def _one(c) -> Optional[Dict[str, Any]]:
    row = c.fetchone()
    return dict(zip([d[0] for d in c.description], row)) if row else None


def _copy_widget(c, widget: Dict[str, Any]) -> Tuple[int, bool]:
    """Write a widget row from another env as this env's next version, unless its head already holds it.

    Returns the version that holds it here and whether a row was written.
    """
    # Version numbers are per environment (every copy gets the target's next
    # number), so Dev v5 and Test v5 are unrelated rows. "Up to date" therefore
    # has to mean the target's current head carries the same widget.
    c.execute(
        "SELECT * FROM widgets WHERE id = %s AND is_deprecated = 0 ORDER BY version DESC LIMIT 1",
        (widget["id"],),
    )
    head = _one(c)
    if head is not None and same_content(widget, head):
        return head["version"], False

    # Deprecated rows count: a rollback leaves them in place, and reusing one of
    # their numbers would collide on the (id, version) primary key.
    c.execute("SELECT MAX(version) FROM widgets WHERE id = %s", (widget["id"],))
    target_row = c.fetchone()
    new_version = (target_row[0] if (target_row and target_row[0] is not None) else 0) + 1

    row = {k: v for k, v in widget.items() if k != "timestamp"}
    row["version"] = new_version
    keys = list(row)
    c.execute(
        f"INSERT INTO widgets ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})",
        tuple(row[k] for k in keys),
    )
    return new_version, True


class TransferRequest(BaseModel):
    widget_id: str
    source_env: str
    target_env: str
    version: Optional[int] = None # If None, defaults to the latest version
    is_rollback: bool = False

@router.post("/transfer")
def transfer_widget(request: TransferRequest, w: WorkspaceClient = Depends(get_db_client)):
    # Connect to the source environment to fetch the widget
    source_conn = get_db_connection(request.source_env)
    c_source = source_conn.cursor()
    
    if request.version is not None:
        c_source.execute("SELECT * FROM widgets WHERE id = %s AND version = %s AND is_deprecated = 0", (request.widget_id, request.version))
    else:
        c_source.execute("SELECT * FROM widgets WHERE id = %s AND is_deprecated = 0 ORDER BY version DESC LIMIT 1", (request.widget_id,))

    widget = _one(c_source)
    source_conn.close()
    if not widget:
        raise HTTPException(status_code=404, detail=f"Widget not found in source environment ({request.source_env})")

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

    new_version, copied = _copy_widget(c_target, widget)
    target_conn.commit()
    target_conn.close()

    if not copied:
        return {"status": "success", "message": f"Already up to date: {request.target_env} v{new_version} is the same widget"}
    return {"status": "success", "message": f"Transferred widget {request.widget_id} to {request.target_env} as version {new_version}", "new_version": new_version}

class CertifyRequest(BaseModel):
    widget_id: str
    version: int

@router.post("/certify")
def certify_widget(request: CertifyRequest, w: WorkspaceClient = Depends(get_db_client)):
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


class AppTransferRequest(BaseModel):
    app_id: str
    source_env: str
    target_env: str
    version: Optional[int] = None
    is_rollback: bool = False
    # Widgets the app places that go with it, each at its current version in the
    # source env. Promoted under the same rule as promoting each one alone.
    include_widgets: List[str] = []


def _source_app(c, request: AppTransferRequest) -> Dict[str, Any]:
    if request.version is not None:
        c.execute("SELECT * FROM dashboard_views WHERE id = %s AND version = %s", (request.app_id, request.version))
    else:
        c.execute("SELECT * FROM dashboard_views WHERE id = %s ORDER BY version DESC LIMIT 1", (request.app_id,))
    app = _one(c)
    if not app:
        raise HTTPException(status_code=404, detail=f"View not found in source environment ({request.source_env})")
    return app


def _agent_names(c, ids: List[str]) -> Dict[str, str]:
    """Live agents among `ids`, by id, with their newest name."""
    if not ids:
        return {}
    c.execute(
        "SELECT id, name FROM agent_profiles WHERE id = ANY(%s) AND is_deprecated = 0 ORDER BY version DESC",
        (list(ids),),
    )
    names: Dict[str, str] = {}
    for row in app_store.fetch_rows(c):
        names.setdefault(str(row["id"]), row.get("name") or "")
    return names


def _pinned_agents(app: Dict[str, Any], spec: Dict[str, Any]) -> List[str]:
    pins = [app.get("pinned_agent_id")] + [tab.get("pinned_agent_id") for tab in spec.get("tabs") or []]
    return list(dict.fromkeys(p for p in pins if p and p != _DEFAULT_AGENT))


def _version_pins(spec: Dict[str, Any]) -> List[Tuple[str, int]]:
    _, pinned = app_spec.placed_widgets(spec)
    out = []
    for key in pinned:
        widget_id, _, version = key.rpartition("@")
        if app_store.is_custom_widget(widget_id):
            out.append((widget_id, int(version)))
    return out


def app_preflight(c_source, c_target, app: Dict[str, Any], *, require_certified: bool) -> Dict[str, List[Dict[str, Any]]]:
    """What an app would be missing, or show differently, once copied into the target env.

    The app row travels on its own, and widgets and agents are rows of their own in
    each env, so nothing guarantees the target has what the app places. Four things
    can go wrong there:

    - `missing_widgets`: placed widgets the target has no live version of. They
      don't render there.
    - `version_pins`: a widget pinned to a version (`props._version`), where the
      target's row of that number is absent (the widget shows its current
      version instead) or holds something else (it shows that). Version numbers
      are per env, so a pin means nothing across envs unless the rows agree.
    - `missing_agents`: pinned agents the target has no live row for. The
      assistant there opens with whatever the user last picked.
    - `uncertified`: when global apps may only hold certified widgets, the ones
      that aren't certified in the target (or, if absent, in the source, as they
      would arrive). Saving the app there is refused until they are.
    """
    spec = app_store.spec_of(app)
    ids = app_store.custom_widget_ids(spec)
    source_heads = app_store.widget_heads(c_source, ids)
    target_heads = app_store.widget_heads(c_target, ids)

    def described(widget_id: str) -> Dict[str, Any]:
        known = target_heads.get(widget_id) or source_heads.get(widget_id) or {}
        return {"id": widget_id, "name": known.get("name") or None, "domain": known.get("domain") or None}

    missing_widgets = [described(i) for i in ids if i not in target_heads]

    version_pins = []
    for widget_id, version in _version_pins(spec):
        c_source.execute("SELECT * FROM widgets WHERE id = %s AND version = %s", (widget_id, version))
        source_row = _one(c_source)
        if source_row is None:
            continue  # Already shows the current version in the source; nothing changes.
        c_target.execute(
            "SELECT * FROM widgets WHERE id = %s AND version = %s AND is_deprecated = 0", (widget_id, version),
        )
        target_row = _one(c_target)
        if target_row is None or not same_content(source_row, target_row):
            version_pins.append({
                **described(widget_id),
                "version": version,
                "problem": "missing" if target_row is None else "different",
            })

    agent_ids = _pinned_agents(app, spec)
    target_agents = _agent_names(c_target, agent_ids)
    source_agents = _agent_names(c_source, [a for a in agent_ids if a not in target_agents])
    missing_agents = [{"id": a, "name": source_agents.get(a) or None} for a in agent_ids if a not in target_agents]

    uncertified = []
    if require_certified and app.get("is_global"):
        for widget_id in ids:
            head = target_heads.get(widget_id) or source_heads.get(widget_id)
            if not (head and head["is_certified"]):
                uncertified.append(described(widget_id))

    return {
        "missing_widgets": missing_widgets,
        "version_pins": version_pins,
        "missing_agents": missing_agents,
        "uncertified": uncertified,
    }


def _require_promoter(w, app: Dict[str, Any], target_env: str) -> None:
    # RBAC Enforcement: must be editor/admin in the target environment for this domain
    require_domain_editor(w, app.get("domain") or "General", target_env)


@router.post("/transfer_app/preflight")
def transfer_app_preflight(request: AppTransferRequest, w: WorkspaceClient = Depends(get_db_client)):
    """What promoting this app would leave missing in the target; writes nothing.

    Asks the same right as the promotion itself, so it tells nobody anything about
    the target they couldn't find out by promoting.
    """
    from services.settings_store import get_bool_setting

    source_conn = get_db_connection(request.source_env)
    target_conn = None
    try:
        c_source = source_conn.cursor()
        app = _source_app(c_source, request)
        _require_promoter(w, app, request.target_env)
        target_conn = get_db_connection(request.target_env)
        found = app_preflight(
            c_source, target_conn.cursor(), app,
            require_certified=get_bool_setting("require_certified_for_global_views"),
        )
    finally:
        source_conn.close()
        if target_conn is not None:
            target_conn.close()
    return {"preflight": found, "source_env": request.source_env, "target_env": request.target_env}


@router.post("/transfer_app")
def transfer_app(request: AppTransferRequest, w: WorkspaceClient = Depends(get_db_client)):
    """Copy a version of an app (every tab) into another env, optionally with widgets it places.

    The app and any widgets go in one transaction, so a refusal for one of the
    widgets leaves the target exactly as it was.
    """
    source_conn = get_db_connection(request.source_env)
    try:
        c_source = source_conn.cursor()
        app = _source_app(c_source, request)
        placed = set(app_store.custom_widget_ids(app_store.spec_of(app)))
        widgets = []
        if not request.is_rollback:
            for widget_id in dict.fromkeys(request.include_widgets):
                if widget_id not in placed:
                    raise HTTPException(status_code=400, detail=f"Widget {widget_id} isn't on this view.")
                c_source.execute(
                    "SELECT * FROM widgets WHERE id = %s AND is_deprecated = 0 ORDER BY version DESC LIMIT 1",
                    (widget_id,),
                )
                widget = _one(c_source)
                if widget is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Widget {widget_id} not found in source environment ({request.source_env})",
                    )
                widgets.append(widget)
    finally:
        source_conn.close()

    _require_promoter(w, app, request.target_env)
    for widget in widgets:
        require_domain_editor(w, widget.get("domain") or "General", request.target_env)

    target_conn = get_db_connection(request.target_env)
    try:
        c_target = target_conn.cursor()

        if request.is_rollback and request.version is not None:
            # dashboard_views does not have is_deprecated; delete newer versions to restore
            c_target.execute(
                "DELETE FROM dashboard_views WHERE id = %s AND version > %s",
                (request.app_id, request.version),
            )
            target_conn.commit()
            return {"status": "success", "message": f"Rolled back view {request.app_id} to v{request.version} in {request.target_env}"}

        promoted = []
        for widget in widgets:
            version, copied = _copy_widget(c_target, widget)
            promoted.append({"id": widget["id"], "name": widget.get("name"), "version": version, "copied": copied})

        # As with widgets, version numbers are per environment, so the target having
        # a row with the source's number says nothing; compare against its head.
        c_target.execute(
            "SELECT * FROM dashboard_views WHERE id = %s ORDER BY version DESC LIMIT 1",
            (request.app_id,),
        )
        head = _one(c_target)
        if head is not None and same_view_content(app, head):
            target_conn.commit()
            return {
                "status": "success",
                "message": f"Already up to date: {request.target_env} v{head['version']} is the same view",
                "widgets": promoted,
            }

        c_target.execute("SELECT MAX(version) FROM dashboard_views WHERE id = %s", (request.app_id,))
        target_row = c_target.fetchone()
        new_version = (target_row[0] if (target_row and target_row[0] is not None) else 0) + 1

        row = {k: v for k, v in app.items() if k != "timestamp"}
        row["version"] = new_version
        keys = list(row)
        c_target.execute(
            f"INSERT INTO dashboard_views ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})",
            tuple(row[k] for k in keys),
        )
        target_conn.commit()
    except Exception:
        target_conn.rollback()
        raise
    finally:
        target_conn.close()

    return {
        "status": "success",
        "message": f"Transferred view {request.app_id} to {request.target_env} as version {new_version}",
        "new_version": new_version,
        "widgets": promoted,
    }

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d
