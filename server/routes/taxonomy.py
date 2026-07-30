"""CRUD routes for managing widget categories and domains.

These are surfaced to admins so they can keep the dropdowns in Widget Studio
and the Widget Library in sync with their organization's terminology without
having to ship a frontend release.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor
from databricks.sdk import WorkspaceClient

from database import get_db_connection
from middleware.auth import get_db_client
from routes.roles import require_global_admin

router = APIRouter()

logger = logging.getLogger(__name__)


class TaxonomyItem(BaseModel):
    name: str


def _list(table: str, env: str):
    """Read a taxonomy table.

    Fails loudly (503) instead of returning an empty list. The dropdowns that
    consume this cannot tell "no categories exist" from "the read failed", so a
    transient Lakebase error — an idle autoscaling instance waking up, an
    expired credential — used to render as silently empty pickers.
    """
    conn = None
    try:
        conn = get_db_connection(env)
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute(f"SELECT id, name, timestamp FROM {table} ORDER BY name ASC")
        return [dict(r) for r in c.fetchall()]
    except Exception as e:
        logger.exception("Failed to list %s (env=%s)", table, env)
        raise HTTPException(status_code=503, detail=f"Could not load {table}: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _create(table: str, name: str, env: str):
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    conn = get_db_connection(env)
    c = conn.cursor()
    try:
        c.execute(f"INSERT INTO {table} (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id", (name,))
        row = c.fetchone()
        conn.commit()
        # If already exists, return the existing record id so the caller can succeed idempotently.
        if not row:
            c.execute(f"SELECT id FROM {table} WHERE name = %s", (name,))
            row = c.fetchone()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))
    conn.close()
    return {"id": row[0], "name": name}


def _update(table: str, item_id: int, name: str, env: str):
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    conn = get_db_connection(env)
    c = conn.cursor()
    try:
        c.execute(f"UPDATE {table} SET name = %s WHERE id = %s", (name, item_id))
        if c.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="Not found")
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))
    conn.close()
    return {"id": item_id, "name": name}


def _delete(table: str, item_id: int, env: str):
    conn = get_db_connection(env)
    c = conn.cursor()
    try:
        c.execute(f"DELETE FROM {table} WHERE id = %s", (item_id,))
        if c.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="Not found")
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))
    conn.close()
    return {"status": "deleted", "id": item_id}


@router.get("/categories")
def list_categories(env: str = "dev"):
    return {"categories": _list("widget_categories", env)}


@router.post("/categories")
def create_category(item: TaxonomyItem, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    require_global_admin(w, env)
    return _create("widget_categories", item.name, env)


@router.put("/categories/{item_id}")
def update_category(item_id: int, item: TaxonomyItem, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    require_global_admin(w, env)
    return _update("widget_categories", item_id, item.name, env)


@router.delete("/categories/{item_id}")
def delete_category(item_id: int, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    require_global_admin(w, env)
    return _delete("widget_categories", item_id, env)


@router.get("/domains")
def list_domains(env: str = "dev"):
    return {"domains": _list("widget_domains", env)}


@router.post("/domains")
def create_domain(item: TaxonomyItem, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    require_global_admin(w, env)
    return _create("widget_domains", item.name, env)


@router.put("/domains/{item_id}")
def update_domain(item_id: int, item: TaxonomyItem, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    require_global_admin(w, env)
    return _update("widget_domains", item_id, item.name, env)


@router.delete("/domains/{item_id}")
def delete_domain(item_id: int, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    require_global_admin(w, env)
    return _delete("widget_domains", item_id, env)
