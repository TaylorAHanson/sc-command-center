"""Admin-managed deployment settings, and the model list that drives their picker.

Changing which serving endpoint the agents call used to require editing
`databricks.yml` and redeploying. These routes put that behind the Admin Panel;
`services/settings_store.py` holds the precedence rules and the storage.

Everything here is global-admin only. The values are deployment-wide, so a domain
admin changing the chat model would be reaching well outside their domain.
"""

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from middleware.auth import get_db_client
from routes.roles import _get_current_username, require_global_admin
from services.settings_store import describe_settings, save_settings, settings_env

router = APIRouter()

logger = logging.getLogger(__name__)

# Endpoints change rarely and the list is ~40 rows; a short cache keeps the picker
# instant when an admin reopens the page without going stale for long.
_MODEL_CACHE_TTL = 300.0
_model_lock = threading.Lock()
_model_cache: Dict[str, Any] = {"items": [], "at": 0.0, "loaded": False}


class SettingsUpdate(BaseModel):
    settings: Dict[str, Any]


@router.get("")
@router.get("/")
def get_settings(w: WorkspaceClient = Depends(get_db_client)):
    require_global_admin(w, settings_env())
    return {"settings": describe_settings(), "settings_env": settings_env()}


@router.put("")
@router.put("/")
def update_settings(body: SettingsUpdate, w: WorkspaceClient = Depends(get_db_client)):
    require_global_admin(w, settings_env())
    try:
        result = save_settings(body.settings or {}, _get_current_username(w))
    except Exception as e:  # noqa: BLE001
        logger.exception("Failed to save app settings")
        raise HTTPException(status_code=500, detail=f"Could not save settings: {e}")
    if result["errors"]:
        # Nothing was written — surface every problem at once so the admin fixes
        # the form in one pass.
        raise HTTPException(status_code=400, detail=result["errors"])
    return {**result, "settings": describe_settings()}


def _chat_endpoints(w: WorkspaceClient) -> List[Dict[str, Any]]:
    """Chat-capable models a caller may pick, alphabetical (the picker filters).

    Serving endpoints are the source of truth — there is no listing API for AI
    Gateway model names — but `name` is the AI Gateway alias for the built-in
    foundation models, since that is the route Databricks is steering deployments
    toward and workspace endpoints are on their way out. The alias is the endpoint
    name minus its `databricks-` prefix, which holds for every foundation endpoint
    in the workspace; `endpoint` carries the original so the UI can show both and
    an admin can pin the serving-endpoint name instead by typing it.

    Only `llm/v1/chat` endpoints qualify — the agents all speak the chat API, so an
    embedding endpoint in this list would just be a way to break them. Endpoints
    that report no task are kept, since externally-hosted models often report none.
    """
    items: List[Dict[str, Any]] = []
    for endpoint in w.serving_endpoints.list():
        endpoint_name = getattr(endpoint, "name", None)
        if not endpoint_name:
            continue
        task = str(getattr(endpoint, "task", "") or "")
        if task and "chat" not in task:
            continue
        state = getattr(endpoint, "state", None)
        ready = str(getattr(state, "ready", "") or "")
        foundation = endpoint_name.startswith("databricks-")
        items.append({
            "name": f"system.ai.{endpoint_name[len('databricks-'):]}" if foundation else endpoint_name,
            "endpoint": endpoint_name,
            "route": "gateway" if foundation else "serving",
            "task": task,
            "ready": "READY" in ready.upper() if ready else None,
            "foundation": foundation,
        })
    items.sort(key=lambda item: item["endpoint"])
    return items


@router.get("/models")
def list_models(refresh: bool = False, w: WorkspaceClient = Depends(get_db_client)):
    """Serving endpoints for the model pickers.

    Runs under the caller's own identity (OBO), so the list is what that user can
    actually see. Not restricted to global admins: Agent Studio authors pick a
    model per agent from the same list.
    """
    now = time.monotonic()
    with _model_lock:
        fresh = (now - float(_model_cache["at"])) < _MODEL_CACHE_TTL
        if not refresh and _model_cache["loaded"] and fresh:
            return {"models": list(_model_cache["items"]), "cached": True}

    try:
        items = _chat_endpoints(w)
    except Exception as e:  # noqa: BLE001
        logger.warning("Serving endpoint listing failed: %s", e)
        with _model_lock:
            if _model_cache["loaded"]:
                return {"models": list(_model_cache["items"]), "cached": True, "stale": True}
        # A failed listing must not block editing: the caller falls back to a
        # free-text field, which is what this setting was before.
        raise HTTPException(status_code=503, detail=f"Could not list serving endpoints: {e}")

    with _model_lock:
        _model_cache["items"] = items
        _model_cache["at"] = now
        _model_cache["loaded"] = True
    return {"models": items, "cached": False}
