"""/api/discover: search, rails, the sidebar's working set, favorites and opens.

Reads come from the view catalog (services/view_catalog.py) and per-person
signals from services/view_signals.py. Every list is light rows, never a spec,
and each page is re-checked against the access list before it is sent.
Handlers are plain `def`: they block on Postgres and run on the threadpool.
"""
from typing import List, Optional

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from middleware.auth import get_db_client
from services import access, activity, caller_identity, view_catalog, view_signals

router = APIRouter()


def _split(values: List[str]) -> List[str]:
    """`?domain=a&domain=b` and `?domain=a,b` alike."""
    return [part.strip() for v in values or [] for part in v.split(",") if part.strip()]


@router.get("/search")
def search(
    q: str = "",
    scope: str = "all",
    sort: str = "relevance",
    domain: List[str] = Query(default=[]),
    owner: List[str] = Query(default=[]),
    certified: Optional[bool] = None,
    standalone: Optional[bool] = None,
    status: Optional[str] = None,
    opened: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = view_catalog.DEFAULT_LIMIT,
    facets: bool = False,
    w: WorkspaceClient = Depends(get_db_client),
):
    who = access.caller(w)
    params = view_catalog.SearchParams(
        q=q[:200], scope=scope, sort=sort, domain=_split(domain), owner=_split(owner), certified=certified,
        standalone=standalone, status=status or None, opened=opened or None, cursor=cursor or None,
        limit=limit, facets=facets,
    )
    try:
        return view_catalog.search(who, params)
    except view_catalog.Refused as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/suggest")
def suggest(q: str = "", w: WorkspaceClient = Depends(get_db_client)):
    return view_catalog.suggest(access.caller(w), q[:200])


@router.get("/rails")
def rails(w: WorkspaceClient = Depends(get_db_client)):
    return view_catalog.rails(access.caller(w))


@router.get("/home")
def home(w: WorkspaceClient = Depends(get_db_client)):
    return view_signals.home(access.caller(w))


@router.get("/status")
def status(w: WorkspaceClient = Depends(get_db_client)):
    return view_catalog.status()


@router.get("/favorites")
def list_favorites(w: WorkspaceClient = Depends(get_db_client)):
    return {"favorites": view_signals.favorites(access.caller(w))}


class FavoriteOrder(BaseModel):
    ids: List[str]


# Declared before /favorites/{app_id}, which would otherwise take "order" for an id.
@router.put("/favorites/order")
def order_favorites(body: FavoriteOrder, w: WorkspaceClient = Depends(get_db_client)):
    return {"ids": view_signals.order_favorites(access.caller(w), body.ids)}


@router.put("/favorites/{app_id}")
def add_favorite(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    view_signals.add_favorite(access.caller(w), app_id)
    return {"id": app_id, "favorite": True}


@router.delete("/favorites/{app_id}")
def remove_favorite(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    view_signals.remove_favorite(access.caller(w), app_id)
    return {"id": app_id, "favorite": False}


@router.post("/visit/{app_id}", status_code=204)
def visit(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    # Fire-and-forget from the browser: whatever goes wrong, the page carries on.
    try:
        view_signals.record_visit(caller_identity.username(w), app_id)
    except Exception:  # noqa: BLE001
        pass
    return Response(status_code=204)


@router.put("/hidden/{app_id}")
def hide(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    view_signals.hide(access.caller(w), app_id)
    return {"id": app_id, "hidden": True}


@router.delete("/hidden/{app_id}")
def unhide(app_id: str, w: WorkspaceClient = Depends(get_db_client)):
    view_signals.unhide(access.caller(w), app_id)
    return {"id": app_id, "hidden": False}


class Curation(BaseModel):
    featured_position: Optional[int] = None
    certified: Optional[bool] = None


@router.put("/curation/{app_id}")
def curate(app_id: str, body: Curation, w: WorkspaceClient = Depends(get_db_client)):
    who = access.require_app_admin(w)
    # Absent leaves a field alone; an explicit null featured_position unfeatures.
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    if changes.get("certified", False) is None:
        changes.pop("certified")
    if not changes:
        raise HTTPException(status_code=400, detail="Send featured_position, certified, or both.")
    result = view_signals.curate(who, app_id, changes)
    activity.record(who.username, "view.curate", access.APP, app_id, changes)
    return result
