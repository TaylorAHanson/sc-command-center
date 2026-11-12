"""`/api/schedules`: reports and actions that run on a timetable, as whoever set them up.

A schedule belongs to the person who created it, and every run is them
(`services/scheduler.py` explains how). Item routes are for that owner or an app
Administrator; anyone else gets 404, so an id never confirms that a schedule
exists. An Administrator may rename someone else's schedule, change when it runs,
pause, resume, run or delete it, but not change what it runs or who it goes to:
that would put words in the owner's mouth, under the owner's identity.

Creating always succeeds once the request is valid: without a connection the
schedule is made as `needs_reconnect`, and the response's `connection` (the
`/api/oauth/status` body) tells the browser to offer Connect. It goes active by
itself once they do.

Errors are 400, 403 or 404 with `detail` as one sentence. Creating, resuming and
running need the `scheduling` capability (503 without it), and a report also
needs `email`.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Body, Depends, HTTPException, Request

from middleware.auth import get_db_client
from services import access, activity, capabilities, email_service, recurrence, schedule_store, scheduler, token_vault

router = APIRouter()

SCHEDULING_OFF = "Scheduling isn't set up in this app yet."
NOT_FOUND = "That schedule wasn't found."
STATUS_UNREADABLE = "Couldn't read your connection status. Try again shortly."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require(kind: str) -> None:
    if not capabilities.available("scheduling"):
        raise HTTPException(status_code=503, detail=SCHEDULING_OFF)
    if kind == "email_report" and not capabilities.available("email"):
        raise HTTPException(status_code=503, detail=email_service.UNAVAILABLE)


def _owner_name(who: access.Caller) -> str:
    return token_vault.normalize_username(who.username)


def _signed_in(who: access.Caller) -> str:
    owner = _owner_name(who)
    if not owner or owner == "unknown":
        raise HTTPException(status_code=403, detail="The app couldn't tell who you are, so it can't schedule "
                                                    "anything for you.")
    return owner


def _load(schedule_id: str, who: access.Caller) -> Tuple[Dict[str, Any], bool]:
    """(the stored row, whether the caller owns it). 404 for anyone else who isn't an admin."""
    row = schedule_store.get_row(schedule_id)
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    is_owner = row.get("owner") == _owner_name(who)
    if not is_owner and not who.is_admin:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return row, is_owner


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else value


def _connection_body(status: Dict[str, Any]) -> Dict[str, Any]:
    return {**status, "connected_at": _iso(status.get("connected_at")), "expires_at": _iso(status.get("expires_at"))}


def _connection(owner: str) -> Tuple[Dict[str, Any], bool]:
    try:
        return scheduler.connection(owner)
    except Exception:  # noqa: BLE001 - the vault's database didn't answer
        raise HTTPException(status_code=503, detail=STATUS_UNREADABLE) from None


def _check_recipients(recipients: Any, sender: str, required: bool) -> None:
    """The same recipient policy a Send button applies, now rather than at the first run."""
    if not recipients and not required:
        return
    cfg = email_service.current_settings()
    check = email_service.check_recipients(recipients, sender, cfg.allowed_domains, cfg.max_recipients)
    if check.problem:
        raise HTTPException(status_code=400, detail=check.problem)


def _view_link(link: Any, request: Request) -> Optional[str]:
    headers = request.headers
    return email_service.own_view_link(
        link, origin=headers.get("origin", ""), host=headers.get("x-forwarded-host") or headers.get("host", ""),
    ) or None


def _check_widget(owner: str, who: access.Caller, widget_id: str) -> None:
    problem, _name = scheduler.widget_check(owner, who.groups, widget_id)
    if problem:
        raise HTTPException(status_code=problem[0], detail=problem[1])


def _as_owner(who: access.Caller) -> Dict[str, Any]:
    """What a schedule remembers about its owner, refreshed whenever they act on it."""
    return {"owner_email": who.username, "owner_groups": list(who.groups)}


def _record(who: access.Caller, verb: str, row: Dict[str, Any], **detail: Any) -> None:
    activity.record(who.username, verb, "schedule", row["id"], {"kind": row.get("kind"), **detail})


@router.get("")
@router.get("/")
def list_schedules(all: bool = False, w: WorkspaceClient = Depends(get_db_client)):
    """The caller's schedules, newest first; `?all=true` is everyone's, for admins."""
    who = access.caller(w)
    if all and not who.is_admin:
        raise HTTPException(status_code=403, detail="Only app administrators can see everyone's schedules.")
    owner = None if all else _owner_name(who)
    schedules = schedule_store.list_schedules(owner)
    # Someone back from connecting sees their schedules running, not waiting on the next pass.
    if owner and any(s["status"] == "needs_reconnect" for s in schedules) and capabilities.available("scheduling"):
        if scheduler.resume_owner(owner):
            schedules = schedule_store.list_schedules(owner)
    return {"schedules": schedules, "can_see_all": who.is_admin}


@router.post("")
@router.post("/")
def create_schedule(request: Request, body: Dict[str, Any] = Body(...), w: WorkspaceClient = Depends(get_db_client)):
    who = access.caller(w)
    owner = _signed_in(who)
    kind = str(body.get("kind") or "").strip()
    if kind not in schedule_store.KINDS:
        raise HTTPException(status_code=400, detail="The kind must be email_report or run_statement.")
    _require(kind)
    fields, problem = schedule_store.clean_fields(body, kind, partial=False)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    _check_recipients(fields["recipients"], who.username, required=kind == "email_report")
    fields["view_link"] = _view_link(fields.get("view_link"), request)
    if kind == "run_statement":
        _check_widget(owner, who, fields["source_widget_id"])
    status, usable = _connection(owner)

    from services.settings_store import get_int_setting

    cap = get_int_setting("schedule_max_per_person")
    fields.update(
        id=schedule_store.new_id(), owner=owner, kind=kind, **_as_owner(who),
        status="active" if usable else "needs_reconnect",
        next_run_at=recurrence.next_run(fields["recurrence"], _now()),
    )
    created = schedule_store.create(fields, owner, cap)
    if created is None:
        raise HTTPException(status_code=400, detail=f"You already have {cap} schedule{'' if cap == 1 else 's'}, "
                                                    "the most this app allows each person. Delete one to add another.")
    _record(who, "schedule.create", created, status=created["status"], freq=fields["recurrence"]["freq"],
            recipient_count=len(fields["recipients"]))
    return {"schedule": created, "connection": _connection_body(status)}


@router.patch("/{schedule_id}")
def update_schedule(schedule_id: str, request: Request, body: Dict[str, Any] = Body(...),
                    w: WorkspaceClient = Depends(get_db_client)):
    who = access.caller(w)
    row, is_owner = _load(schedule_id, who)
    current = schedule_store.to_api(row)
    refused = schedule_store.patch_problem(body, current, is_owner)
    if refused:
        raise HTTPException(status_code=refused[0], detail=refused[1])
    kind = row["kind"]
    allowed = schedule_store.EDITABLE if is_owner else schedule_store.ADMIN_EDITABLE
    fields, problem = schedule_store.clean_fields({k: v for k, v in body.items() if k in allowed}, kind,
                                                  partial=True)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    if "recipients" in fields:
        _check_recipients(fields["recipients"], who.username, required=kind == "email_report")
    if "view_link" in fields:
        fields["view_link"] = _view_link(fields["view_link"], request)
    if kind == "run_statement" and ("source_widget_id" in fields or "sql" in fields):
        _check_widget(row["owner"], who, fields.get("source_widget_id") or row.get("source_widget_id") or "")
    changed = sorted(fields)
    if "recurrence" in fields:
        fields["next_run_at"] = recurrence.next_run(fields["recurrence"], _now())
    if is_owner:
        fields.update(_as_owner(who))
    updated = schedule_store.update(schedule_id, fields)
    if updated is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    _record(who, "schedule.update", row, fields=",".join(changed), count=len(changed))
    return updated


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: str, w: WorkspaceClient = Depends(get_db_client)):
    who = access.caller(w)
    row, _is_owner = _load(schedule_id, who)
    if schedule_store.delete(schedule_id):
        _record(who, "schedule.delete", row)
    return {"deleted": True}


@router.post("/{schedule_id}/pause")
def pause_schedule(schedule_id: str, w: WorkspaceClient = Depends(get_db_client)):
    who = access.caller(w)
    row, _is_owner = _load(schedule_id, who)
    if row["status"] == "paused" and row.get("paused_reason") == "owner":
        return schedule_store.get_api(schedule_id)
    updated = schedule_store.update(schedule_id, {"status": "paused", "paused_reason": "owner",
                                                  "run_requested": False})
    if updated is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    _record(who, "schedule.pause", row)
    return updated


@router.post("/{schedule_id}/resume")
def resume_schedule(schedule_id: str, w: WorkspaceClient = Depends(get_db_client)):
    who = access.caller(w)
    row, is_owner = _load(schedule_id, who)
    if row["status"] == "active":
        return schedule_store.get_api(schedule_id)
    _require(row["kind"])
    _status, usable = _connection(row["owner"])
    fields: Dict[str, Any] = {
        "status": "active" if usable else "needs_reconnect",
        "paused_reason": None,
        "failure_count": 0,
        "next_run_at": recurrence.next_run(schedule_store.from_json(row["recurrence"]), _now()),
    }
    if is_owner:
        fields.update(_as_owner(who))
    updated = schedule_store.update(schedule_id, fields)
    if updated is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    _record(who, "schedule.resume", row, status=updated["status"])
    return updated


@router.post("/{schedule_id}/run")
def run_schedule(schedule_id: str, w: WorkspaceClient = Depends(get_db_client)):
    """Queue one run for the next tick, within about 30 seconds."""
    who = access.caller(w)
    row, is_owner = _load(schedule_id, who)
    _require(row["kind"])
    if row["status"] == "paused":
        raise HTTPException(status_code=400, detail="This schedule is paused. Resume it to run it.")
    if row["status"] == "needs_reconnect":
        raise HTTPException(status_code=400, detail="This schedule is waiting for its owner to connect their "
                                                    "account again.")
    fields: Dict[str, Any] = {"run_requested": True}
    if is_owner:
        fields.update(_as_owner(who))
    updated = schedule_store.update(schedule_id, fields, touch=False)
    if updated is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    _record(who, "schedule.run", row, via="manual")
    return updated


@router.get("/{schedule_id}/runs")
def list_runs(schedule_id: str, limit: int = schedule_store.DEFAULT_RUNS, w: WorkspaceClient = Depends(get_db_client)):
    who = access.caller(w)
    _load(schedule_id, who)
    return {"runs": schedule_store.runs(schedule_id, limit)}
