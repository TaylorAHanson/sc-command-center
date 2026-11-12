"""Email from a widget's Send dialog: `POST /api/email/preview` and `/send`.

The sender is always the signed-in caller's identity. A `sender` in the body is
not read at all, because an endpoint that let the browser choose whose name goes
on an email would be a forgery tool. Everything else (recipient policy, caps,
rendering, the log) belongs to `services/email_service.py`, so scheduled reports
get the same rules.

The view link is the browser's to send, so it is kept only when it points at the
origin the request came from (`email_service.own_view_link`).
"""

from typing import Any, Dict, List, Optional, Union

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from middleware.auth import get_db_client
from services import access, email_service

router = APIRouter()


class EmailRequest(BaseModel):
    to: Union[List[str], str] = []
    subject: str = ""
    message: str = ""
    table: Optional[Dict[str, Any]] = None
    attach_csv: bool = False
    view_name: str = ""
    view_link: str = ""
    #: The action_logs row the dialog wrote before sending, tying the two together.
    request_id: str = ""


# A refusal is the request's fault; not set up and SES failing are not.
_HTTP_STATUS = {"refused": 400, "unavailable": 503, "failed": 502}


def _view_link(body: EmailRequest, request: Request) -> str:
    headers = request.headers
    return email_service.own_view_link(
        body.view_link,
        origin=headers.get("origin", ""),
        host=headers.get("x-forwarded-host") or headers.get("host", ""),
    )


@router.post("/preview")
def preview_email(body: EmailRequest, request: Request, w: WorkspaceClient = Depends(get_db_client)):
    """What Send would send, and anything that would stop it. Writes nothing."""
    who = access.caller(w)
    return email_service.preview_email(
        who.username, who.username, body.to, body.subject, body.message,
        table=body.table, attach_csv=body.attach_csv, view_name=body.view_name,
        view_link=_view_link(body, request),
    )


@router.post("/send")
def send_email(body: EmailRequest, request: Request, w: WorkspaceClient = Depends(get_db_client)):
    who = access.caller(w)
    result = email_service.send_email(
        who.username, who.username, body.to, body.subject, body.message,
        table=body.table, attach_csv=body.attach_csv, view_name=body.view_name,
        view_link=_view_link(body, request), source="widget", request_id=body.request_id,
    )
    if result["ok"]:
        return result
    status = 429 if result.get("reason") == "daily_limit" else _HTTP_STATUS.get(result["status"], 400)
    raise HTTPException(status_code=status, detail=result.get("error") or email_service.UNAVAILABLE)
