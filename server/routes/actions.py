from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Any, List, Dict
import json
from databricks.sdk import WorkspaceClient
from database import log_user_action, get_action_logs
from middleware.auth import get_db_client
from routes.roles import _get_current_username

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
def get_actions(limit: int = 100, offset: int = 0, env: str = "dev"):
    try:
        return get_action_logs(limit, offset, env)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
