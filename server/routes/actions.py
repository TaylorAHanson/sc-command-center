from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Any, List, Dict
import json
from databricks.sdk import WorkspaceClient
from database import log_user_action, get_action_logs, query_action_logs, action_log_facets
from middleware.auth import get_db_client
from routes.roles import _get_current_username
from services import access
from services import action_log_query as alq

router = APIRouter(
    prefix="/api/actions",
    tags=["actions"]
)

class ActionLogRequest(BaseModel):
    widget_id: str
    widget_name: str
    action_name: str = ""
    explanation: str
    context: Any  # Receives JSON object, will be stringified
    # Optional handle tying this approval to the statement it ran, so an auditor
    # can join the intent recorded here to the effect Databricks recorded in
    # `system.query.history` and the table's Delta history.
    request_id: str = ""

@router.post("/log")
def log_action(
    request: ActionLogRequest,
    env: str = "dev",
    w: WorkspaceClient = Depends(get_db_client),
):
    try:
        # Ensure context is stored as a string
        context_str = json.dumps(request.context) if not isinstance(request.context, str) else request.context

        # Resolved server-side from the caller's own token rather than taken from
        # the request body: an audit trail the client can name itself in is not one.
        return log_user_action(
            widget_id=request.widget_id,
            widget_name=request.widget_name,
            action_name=request.action_name,
            explanation=request.explanation,
            context=context_str,
            username=_get_current_username(w),
            request_id=request.request_id,
            env=env,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/")
def get_actions(
    limit: int = 100,
    offset: int = 0,
    env: str = "dev",
    w: WorkspaceClient = Depends(get_db_client),
):
    # Every user's actions, each with the dashboard it was taken on, so only
    # Administrators may read them; writing your own row (`/log`) stays open to
    # everyone. Checked outside the try, which would turn the 403 into a 500.
    access.require_app_admin(w)
    try:
        return get_action_logs(limit, offset, env)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# `GET /` above stays exactly as it was, a bare list of the newest rows, for
# anything written against it before (stored widget code can call any /api
# route). The Action Logs tab reads these two instead. Neither takes `env`.

@router.get("/search")
def search_actions(
    q: str = "",
    widget_id: str = "",
    action_name: str = "",
    username: str = "",
    domain: str = "",
    since: Optional[str] = None,
    until: Optional[str] = None,
    sort: str = alq.DEFAULT_SORT,
    direction: str = Query(alq.DEFAULT_DIRECTION, alias="dir"),
    limit: int = Query(alq.DEFAULT_LIMIT, ge=1, le=alq.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    w: WorkspaceClient = Depends(get_db_client),
):
    """One page of the action log, searched, filtered and sorted on the server.

    `q` is a substring of the widget, its id, the action, the user, the
    explanation, the request id or the domain (or an action id, `42` / `#42`).
    The filters match exactly, the user case-insensitively; `since` is
    inclusive and `until` exclusive, ISO times (UTC when no zone is given).
    `total` is how many rows match in all, so the browser can number pages.
    """
    access.require_app_admin(w)
    try:
        filters = alq.make_filters(q, widget_id, action_name, username, domain, since, until)
        key, way = alq.parse_sort(sort, direction)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        page = query_action_logs(filters, key, way, limit, offset, with_total=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"rows": page["rows"], "total": page["total"], "limit": limit, "offset": offset,
            "sort": key, "dir": way}


@router.get("/facets")
def action_facets(w: WorkspaceClient = Depends(get_db_client)):
    """The choices each filter offers, from the whole log: `widgets`, `actions`,
    `users` and `domains`, each a list of `{value, label, count}`."""
    access.require_app_admin(w)
    try:
        return action_log_facets()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
