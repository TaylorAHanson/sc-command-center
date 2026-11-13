"""The chat agent's email tool: it drafts, and the person sends.

An author switches it on per agent in Agent Studio (`EMAIL_TOOL_ID` among the
agent's tools; see `agent_studio_store`). The tool never sends. It checks the
draft the way a send would (content limits, sanitized HTML, the recipient
policy) and hands it to the chat as an `email_draft` on the turn's tool entry;
the drawer shows it as a card whose button opens the same Send dialog a
widget's `props.app.sendEmail` opens. The person edits the recipients, sees the
email exactly as it will arrive, and presses Send, which goes through
`POST /api/email/send` as them (OBO), `via: "assistant"`. So everything that
holds for a widget's email holds here: the sender is the signed-in person, the
recipient policy and caps apply, and it is logged.

Why not let the tool send: the model writes the recipients, subject and body
from a conversation the person may only half be reading, and a sentence in an
uploaded file or a Genie answer could ask for a send. An email under the app's
From address can't be called back, so the person's own Send is the gate.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from services import email_content, email_service

logger = logging.getLogger(__name__)

NAME = "send_email"
FRIENDLY = "Drafting an email"
#: Content-side refusals the model can fix and retry; anything else (no sender,
#: email off) it can't.
_FIXABLE = {"message_too_long", "bad_table", "bad_attachment", "html_too_long", "files_too_large",
            "empty", "no_subject"}
#: A draft rides on the chat turn and is saved with it, so it stays small.
MAX_DRAFT_BYTES = 1024 * 1024


def tool_spec() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": NAME,
            "description": (
                "Draft an email for the person to send. This opens the app's Send dialog with your "
                "draft: the person checks the recipients and the email as it will arrive, then presses "
                "Send or cancels. Nothing is sent by this call, and you can't send it yourself. Use it "
                "only when the person asks to email something. The sender is always the person; email "
                "may only go to addresses in their organization. Write the body as Markdown in "
                "`message`, or as HTML in `html` for a richer layout (inline styles only; no scripts, "
                "and no images from other sites). Put rows in `tables` rather than in the text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "array", "items": {"type": "string"},
                           "description": "Email addresses to start with. The person can change them."},
                    "subject": {"type": "string", "description": "The subject line."},
                    "message": {"type": "string", "description": (
                        "The body as Markdown: paragraphs, headings, lists, **bold**, *italic*, `code`, "
                        "[links](https://…).")},
                    "html": {"type": "string", "description": (
                        "Optional body as HTML, shown after `message`. Tags such as p, h1-h6, table, "
                        "ul/ol, a, b, i, span and div, with inline `style` attributes.")},
                    "tables": {
                        "type": "array",
                        "description": "Tables drawn under the body, first 50 rows each.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "columns": {"type": "array", "items": {"type": "string"}},
                                "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                            },
                            "required": ["columns", "rows"],
                        },
                    },
                    "attach_csv": {"type": "boolean", "description": "Also attach each table as a CSV file."},
                    "attachments": {
                        "type": "array",
                        "description": "Text files to attach: .txt, .csv, .tsv, .json or .md.",
                        "items": {
                            "type": "object",
                            "properties": {"filename": {"type": "string"}, "content": {"type": "string"}},
                            "required": ["filename", "content"],
                        },
                    },
                },
                "required": ["subject"],
            },
        },
    }


def _strings(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if isinstance(v, (str, int, float))]
    return []


def _text_files(value: Any) -> List[Dict[str, str]]:
    # The model writes text; binary data from it would be a guess at base64.
    if not isinstance(value, (list, tuple)):
        return []
    return [{"filename": str(f.get("filename") or ""), "content": str(f.get("content") or "")}
            for f in value if isinstance(f, dict)]


def draft(sender: str, args: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """(what the model is told, the draft for the chat or None). Never raises."""
    try:
        return _draft(sender, args or {})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Drafting an email failed: %s", exc)
        return "The email couldn't be drafted because of an error in the app. Tell the person.", None


def _draft(sender: str, args: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    if email_service.current_transport() == "off":
        return (f"{email_service.UNAVAILABLE} An administrator can set it up under Admin Panel → Settings "
                "→ Email. Tell the person; don't offer to send it some other way.", None)
    if not sender or sender == "unknown":
        return "Email needs a signed-in person with an email address, so this can't be drafted.", None

    to = _strings(args.get("to"))
    subject = str(args.get("subject") or "")
    message = str(args.get("message") or "")
    body_html = str(args.get("html") or "")
    tables = args.get("tables") if isinstance(args.get("tables"), list) else None
    attach_csv = args.get("attach_csv") is True
    attachments = _text_files(args.get("attachments"))
    not_text = [f["filename"] for f in attachments
                if email_content.type_for(email_content.clean_filename(f["filename"])) in email_content.IMAGE_TYPES]
    if not_text:
        return (f"The email wasn't drafted: from chat only text files can be attached (.txt, .csv, .tsv, "
                f".json, .md), not {', '.join(not_text)}. Leave it out, or put a table in `tables`, and call "
                f"{NAME} again.", None)

    rendered, problem, reason = email_service.check_content(
        subject, message, sender, html_body=body_html, tables=tables, attachments=attachments,
        attach_csv=attach_csv)
    if problem:
        if reason in _FIXABLE:
            return f"The email wasn't drafted: {problem} Fix that and call {NAME} again.", None
        return f"The email wasn't drafted: {problem}", None

    the_draft = {
        "id": uuid.uuid4().hex,
        "to": to,
        "subject": subject,
        "message": message,
        "html": body_html,
        "tables": tables or [],
        "attach_csv": attach_csv,
        "attachments": attachments,
    }
    if len(json.dumps(the_draft, default=str)) > MAX_DRAFT_BYTES:
        return (f"The email wasn't drafted: it is too large to hand over. Send fewer rows (the email shows "
                f"50 a table) and call {NAME} again.", None)

    cfg = email_service.current_settings()
    check = email_service.check_recipients(to, sender, cfg.allowed_domains, cfg.max_recipients)
    lines = [
        f"The draft \"{rendered.subject if rendered else subject}\" is ready for the person: a card in the chat "
        "opens the Send dialog, where they check it and press Send. It has NOT been sent, and only they "
        "can send it. Tell them it's ready to review, and never say it was sent.",
    ]
    if check.problem and to:
        lines.append(f"The dialog will ask them to fix the To line: {check.problem}")
    elif not to:
        lines.append("It has no recipients yet; they will add them in the dialog.")
    if rendered and rendered.notes:
        lines.append(" ".join(rendered.notes))
    return "\n".join(lines), the_draft
