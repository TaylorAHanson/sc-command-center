"""The Admin Panel's Activity tab (/api/activity). App administrators only.

Reads what `services/activity.py` recorded, merged with approved widget actions;
`services/activity_feed.py` holds the queries. Everything here is metadata: who,
which kind of event, which object, when. Nothing a person wrote is returned.
"""
from typing import Optional

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db_connection
from middleware.auth import get_db_client
from services import access, activity_feed
from services.settings_store import settings_env

router = APIRouter()


def _bad(e: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


@router.get("")
@router.get("/")
def list_activity(
    person: str = "",
    verb: str = "",
    object_type: str = "",
    object_id: str = "",
    since: Optional[str] = None,
    until: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = Query(activity_feed.DEFAULT_LIMIT, ge=1, le=activity_feed.MAX_LIMIT),
    w: WorkspaceClient = Depends(get_db_client),
):
    """Newest first. `verb` takes comma-separated patterns (`view.*`, `*.share`);
    pass back `next_cursor` as `cursor` for the next page."""
    access.require_app_admin(w)
    try:
        filters = activity_feed.Filters(
            person=person.strip(),
            verbs=activity_feed.parse_verbs(verb),
            object_type=object_type.strip(),
            object_id=object_id.strip(),
            since=activity_feed.parse_time(since),
            until=activity_feed.parse_time(until),
        )
        after = activity_feed.decode_cursor(cursor)
    except ValueError as e:
        raise _bad(e)
    conn = get_db_connection()
    try:
        page = activity_feed.read_page(conn.cursor(), filters, after, limit)
        conn.commit()
    finally:
        conn.close()
    return page


@router.get("/active")
def active_now(
    minutes: int = Query(activity_feed.ACTIVE_MINUTES, ge=1, le=24 * 60),
    w: WorkspaceClient = Depends(get_db_client),
):
    """People seen recently, from the settings schema's `known_principals`."""
    access.require_app_admin(w)
    conn = get_db_connection(settings_env(), physical=True)
    try:
        people = activity_feed.active_now(conn.cursor(), minutes)
        conn.commit()
    finally:
        conn.close()
    return {"minutes": minutes, "people": people}


@router.get("/person")
def person(
    username: str,
    days: int = Query(30, ge=1, le=3650),
    w: WorkspaceClient = Depends(get_db_client),
):
    """One person's drill-down: what they did by kind, what they worked on, when last seen."""
    access.require_app_admin(w)
    username = username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Name a person.")
    conn = get_db_connection()
    try:
        summary = activity_feed.person_summary(conn.cursor(), username, days)
        conn.commit()
    finally:
        conn.close()
    settings = get_db_connection(settings_env(), physical=True)
    try:
        summary["last_seen"] = activity_feed.last_seen(settings.cursor(), username)
        settings.commit()
    finally:
        settings.close()
    return summary
