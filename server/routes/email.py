"""Email from a widget's Send dialog: `POST /api/email/preview` and `/send`.

The sender is always the signed-in caller's identity. A `sender` in the body is
not read at all, because an endpoint that let the browser choose whose name goes
on an email would be a forgery tool. Everything else (recipient policy, caps,
rendering, the log) belongs to `services/email_service.py`, so scheduled reports
get the same rules.

The view link is the browser's to send, so it is kept only when it points at the
origin the request came from (`email_service.own_view_link`).

Two callers open the Send dialog: a widget (`props.app.sendEmail`) and an agent
whose author switched on its email tool, which only drafts (`services/email_tool.py`).
`via` says which, for the log. An agent's draft names the conversation and the
draft it came from, and a send that goes is noted on that chat turn, so the agent
learns on its next turn that the email went and the card doesn't offer it again.
"""

import logging
from typing import Any, Dict, List, Literal, Optional, Union

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from middleware.auth import get_db_client
from services import access, conversation_store, email_service

router = APIRouter()

logger = logging.getLogger(__name__)


class EmailRequest(BaseModel):
    to: Union[List[str], str] = []
    subject: str = ""
    message: str = ""
    table: Optional[Dict[str, Any]] = None
    #: More tables, each `{title?, columns, rows}`.
    tables: Optional[List[Any]] = None
    #: HTML, sanitized by the server; images only embedded.
    html: str = ""
    #: `[{filename, content}]` for text, `[{filename, data}]` (base64 or a data: URL) for images.
    attachments: Optional[List[Any]] = None
    attach_csv: bool = False
    view_name: str = ""
    view_link: str = ""
    #: The action_logs row the dialog wrote before sending, tying the two together.
    request_id: str = ""
    #: Who asked for the dialog: a widget, or an agent's draft. A label for the log only.
    via: Literal["widget", "assistant"] = "widget"
    #: An agent's draft: the conversation it is in (content env) and its id there.
    conversation_id: str = ""
    draft_id: str = ""
    env: str = "dev"


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
        view_link=_view_link(body, request), html_body=body.html, tables=body.tables,
        attachments=body.attachments,
    )


@router.post("/send")
def send_email(body: EmailRequest, request: Request, w: WorkspaceClient = Depends(get_db_client)):
    who = access.caller(w)
    result = email_service.send_email(
        who.username, who.username, body.to, body.subject, body.message,
        table=body.table, attach_csv=body.attach_csv, view_name=body.view_name,
        view_link=_view_link(body, request), source=body.via,
        request_id=body.request_id or body.draft_id, html_body=body.html, tables=body.tables,
        attachments=body.attachments,
    )
    if result["ok"]:
        if body.via == "assistant" and body.conversation_id and body.draft_id:
            # The email went whatever happens here; a chat that can't be marked
            # only means the agent isn't told, so it is a log line, not an error.
            try:
                conversation_store.mark_email_draft(
                    body.env, who.username, body.conversation_id, body.draft_id,
                    result["status"], result["recipients"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Couldn't note the sent email on conversation %s: %s", body.conversation_id, exc)
        return result
    status = 429 if result.get("reason") == "daily_limit" else _HTTP_STATUS.get(result["status"], 400)
    raise HTTPException(status_code=status, detail=result.get("error") or email_service.UNAVAILABLE)
