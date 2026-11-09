"""Sharing views, widgets and agents, and the app's administrators (/api/sharing).

The share dialog reads and writes an object's access list here, whatever kind of
object it is; see `services/access.py` for the rules. Kept apart from each
object's own routes so there is one place that changes who can reach anything.
"""
from typing import Any, Dict, List, Literal, Optional

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from database import get_db_connection
from middleware.auth import get_db_client
from services import access, drafts

router = APIRouter()

ObjectType = Literal["app", "widget", "agent"]


class Entry(BaseModel):
    principal: str
    principal_type: Optional[str] = None
    level: str


class AclUpdate(BaseModel):
    entries: List[Entry]


class AdminAdd(BaseModel):
    principal: str
    principal_type: Optional[str] = None


#: Where each kind of object records who made it.
_OWNER_COLUMN = {"app": "username", "widget": "created_by", "agent": "username"}
_NOT_AN_OWNER = {"", "system", "unknown", "dev"}


def owner_from(object_type: str, row: Optional[Dict[str, Any]]) -> Optional[str]:
    value = ((row or {}).get(_OWNER_COLUMN[object_type]) or "").strip()
    return None if value.lower() in _NOT_AN_OWNER else value


def _acl_response(object_type: str, object_id: str, level: str) -> Dict[str, Any]:
    return {
        "object_type": object_type,
        "object_id": object_id,
        "my_level": level,
        "owner": access.owner_of(object_type, object_id),
        "entries": access.get_acl(object_type, object_id),
    }


@router.get("/principals")
def principals(q: str = "", w: WorkspaceClient = Depends(get_db_client)):
    """Suggestions for the share dialog: your groups first, then people and groups seen in this app."""
    return {"principals": access.search_principals(access.caller(w), q)}


@router.get("/admins")
def list_admins(w: WorkspaceClient = Depends(get_db_client)):
    access.require_app_admin(w)
    return {"admins": access.list_admins()}


@router.post("/admins")
def add_admin(body: AdminAdd, w: WorkspaceClient = Depends(get_db_client)):
    who = access.require_app_admin(w)
    return {"admins": access.add_admin(who, body.principal, body.principal_type)}


@router.delete("/admins")
def remove_admin(principal: str, w: WorkspaceClient = Depends(get_db_client)):
    access.require_app_admin(w)
    return {"admins": access.remove_admin(principal)}


def _timestamp(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _latest_rows(c, object_type: str) -> Dict[str, Dict[str, Any]]:
    table = drafts.TABLES[object_type]
    live = "WHERE COALESCE(is_deprecated, 0) = 0" if object_type != "app" else ""
    owner = _OWNER_COLUMN[object_type]
    c.execute(f"""
        SELECT t.id, t.version, t.name, t.{owner} AS owner, t.timestamp FROM {table} t
        INNER JOIN (SELECT id, MAX(version) AS v FROM {table} {live} GROUP BY id) m
                ON t.id = m.id AND t.version = m.v
    """)
    names = [d[0] for d in c.description]
    return {r["id"]: r for r in (dict(zip(names, row)) if not hasattr(row, "keys") else dict(row) for row in c.fetchall())}


@router.get("/content")
def content(w: WorkspaceClient = Depends(get_db_client)):
    """Every view, widget and agent with its state and how widely it is shared. Admins only."""
    access.require_app_admin(w)
    summaries = access.acl_summaries()
    conn = get_db_connection()
    items: List[Dict[str, Any]] = []
    try:
        c = conn.cursor()
        c.execute("SELECT id FROM archived_views")
        archived = {r[0] if not hasattr(r, "keys") else r["id"] for r in c.fetchall()}
        for object_type in access.TYPES:
            published = _latest_rows(c, object_type)
            pending = drafts.drafts(c, object_type)
            for object_id in set(published) | set(pending):
                pub = published.get(object_id)
                draft = pending.get(object_id)
                payload = (draft or {}).get("payload") or {}
                name = payload.get("name") or (pub or {}).get("name") or "Untitled"
                owner = owner_from(object_type, payload) or owner_from(object_type, {
                    _OWNER_COLUMN[object_type]: (pub or {}).get("owner")})
                summary = summaries.get((object_type, object_id), {"entries": 0, "everyone": False})
                items.append({
                    "object_type": object_type,
                    "object_id": object_id,
                    "name": name,
                    "owner": owner,
                    "state": drafts.state_of(draft is not None, (pub or {}).get("version")),
                    "published_version": (pub or {}).get("version"),
                    "archived": object_type == "app" and object_id in archived,
                    "entries": summary["entries"],
                    "everyone": summary["everyone"],
                    "updated_at": _timestamp((draft or {}).get("updated_at") or (pub or {}).get("timestamp")),
                })
        conn.commit()
    finally:
        conn.close()
    items.sort(key=lambda i: (i["object_type"], (i["name"] or "").lower()))
    return {"items": items}


@router.get("/{object_type}/{object_id}")
def get_acl(object_type: ObjectType, object_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Who has access. Anyone who can use the object may see the list, as on a dashboard."""
    who = access.caller(w)
    level = access.require(who, object_type, object_id, access.USE)
    return _acl_response(object_type, object_id, level)


@router.put("/{object_type}/{object_id}")
def put_acl(object_type: ObjectType, object_id: str, body: AclUpdate, w: WorkspaceClient = Depends(get_db_client)):
    who = access.caller(w)
    access.replace_acl(who, object_type, object_id, [e.model_dump() for e in body.entries])
    return _acl_response(object_type, object_id, access.MANAGE)
