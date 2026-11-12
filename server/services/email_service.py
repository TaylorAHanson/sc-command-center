"""Email through Amazon SES, sent on behalf of the person who asked.

A widget's Send dialog and scheduled reports both send through `send_email`, so
every caller gets the same safeguards, and they live here rather than in a route:

  * **One From address.** Every email comes from `email_from_address`, a sender
    identity the customer verified in SES. Reply-To is the person who sent it and
    a footer names them and the view, so a recipient knows who to answer, and the
    app never puts someone's own address in From.
  * **Recipients are limited.** Until an admin lists `email_allowed_domains` a
    person may only email their own domain; at most `email_max_recipients` per
    email and `email_daily_limit` per person in any 24 hours. A malformed address
    is refused, never guessed at.
  * **Callers never send HTML.** The message is Markdown, rendered and escaped
    here by a deliberately small renderer (no raw HTML, no images, links only to
    http, https and mailto). A table travels as data and is drawn and capped here
    too, optionally with a CSV copy attached.
  * **Every send is recorded**, in `email_log` (who, recipients, subject, outcome;
    never the body) and in the activity log. The log row is written *before* SES
    is called, under a per-person advisory lock: that is what makes the daily cap
    hold across uvicorn workers, and a send that can't be recorded isn't sent.

Off until set up. SES needs AWS keys, which reach the app only as secret
resources (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, plus AWS_REGION) and never
through `app_settings`, the database, the browser or a log line. The capability
check reads only those env vars: boto3's own chain would also try instance
metadata, and a platform role answering there must not count as "set up". A
deployed app without them refuses to send. A local run (`APP_ENVIRONMENT=local`)
writes the rendered email to the server log instead, with status `logged`, so the
whole flow can be tried under dev.sh; a deployed app never pretends to send.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import logging
import os
import re
import threading
import uuid
from email.utils import formataddr
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

PRODUCT = "Command Center"

#: SES takes at most 50 destinations per message; the admin's cap only goes lower.
SES_MAX_RECIPIENTS = 50
MAX_SUBJECT_CHARS = 200
MAX_MESSAGE_CHARS = 20_000
MAX_VIEW_NAME_CHARS = 120
MAX_LINK_CHARS = 2_000
MAX_COLUMNS = 50
#: Rows drawn in the email itself; the CSV carries more.
TABLE_MAX_ROWS = 50
TABLE_CELL_CHARS = 200
CSV_MAX_ROWS = 10_000
CSV_CELL_CHARS = 2_000
#: Well under SES's 40 MB message limit once base64 has grown it by a third.
CSV_MAX_BYTES = 5 * 1024 * 1024

UNAVAILABLE = "Email isn't set up in this app yet."

# What an admin is told is missing, in the order worth fixing it.
MISSING_ENABLED = "Email is switched off (Admin Panel → Settings → Email → Allow email)"
MISSING_KEYS = ("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, added to the app as "
                "secret resources")
MISSING_REGION = "AWS_REGION in the app's environment (the SES region of the sender identity)"
MISSING_FROM = "A From address verified in SES (Admin Panel → Settings → Email)"

_NEXT_STEPS = {
    MISSING_ENABLED: "Turn on Allow email under Admin Panel → Settings → Email.",
    MISSING_KEYS: ("Create an IAM user allowed only ses:SendEmail on your verified "
                   "sender identity, put its access keys in a Databricks secret scope, "
                   "and add them to the app as secret resources exposed as "
                   "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY. The user guide's "
                   "Set up email section has the bundle snippet."),
    MISSING_REGION: ("Set AWS_REGION in the app's bundle target to the SES region where "
                     "the sender identity is verified (for example us-east-1), then "
                     "redeploy."),
    MISSING_FROM: ("Enter the address you verified in SES under Admin Panel → Settings "
                   "→ Email → From address."),
}

LOG_MODE_STEP = ("This is a local run, so emails are written to the server log "
                 "(backend.log) and the email log instead of being sent. Add what's "
                 "listed as missing to send through SES.")


# ---------------------------------------------------------------------------
# Addresses and the recipient policy
# ---------------------------------------------------------------------------

_LOCAL_PART = re.compile(r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
_BRACKETED = re.compile(r'^(?:"[^"]*"\s*|[^"<>]*)<([^<>]*)>$')


def _valid_domain(domain: str) -> bool:
    labels = domain.split(".")
    return (len(domain) <= 253 and len(labels) >= 2
            and all(_LABEL.match(label) for label in labels)
            and bool(_TLD.match(labels[-1])))


def normalize_address(raw: Any) -> Optional[str]:
    """A lowercased address, or None when it isn't one.

    Deliberately narrower than RFC 5322: no quoted local parts, comments or IP
    literals. The addresses people use pass; anything that would need quoting in
    a header is refused rather than passed through to one.
    """
    text = str(raw or "").strip().lower()
    if not text or len(text) > 254 or text.count("@") != 1:
        return None
    local, domain = text.split("@")
    if len(local) > 64 or not _LOCAL_PART.match(local) or not _valid_domain(domain):
        return None
    return text


def domain_of(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower()


def _split_addresses(text: str) -> List[str]:
    """Pieces of a pasted list: commas, semicolons and new lines separate, but
    not inside quotes or angle brackets ("Doe, Jane" <jane@example.com>)."""
    parts: List[str] = []
    buf: List[str] = []
    quoted = angle = False
    for ch in text:
        if ch == '"' and not angle:
            quoted = not quoted
        elif ch == "<" and not quoted:
            angle = True
        elif ch == ">" and not quoted:
            angle = False
        if ch in ",;\r\n" and not quoted and not angle:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    pieces: List[str] = []
    for part in (p.strip() for p in parts):
        if not part:
            continue
        if "<" in part or '"' in part:
            pieces.append(part)
        else:
            pieces.extend(part.split())
    return pieces


def parse_recipients(value: Any) -> Tuple[List[str], List[str]]:
    """(addresses, rejected) from a list or a pasted string.

    Takes what people paste from a mail client (commas, semicolons, new lines,
    `Name <address>`) and returns each address once, lowercased, in the order
    given. What isn't an address comes back in `rejected` as typed, so the
    person can see what to fix.
    """
    if value is None:
        items: List[str] = []
    elif isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = [str(v) for v in value if v is not None]
    else:
        items = [str(value)]
    good: List[str] = []
    bad: List[str] = []
    for piece in _split_addresses("\n".join(items)):
        match = _BRACKETED.match(piece)
        address = normalize_address(match.group(1) if match else piece)
        if address is None:
            if piece not in bad:
                bad.append(piece[:100])
        elif address not in good:
            good.append(address)
    return good, bad


def parse_domain_entry(entry: str) -> Tuple[str, Optional[str]]:
    """(normalized entry, problem). `example.com` allows exactly that domain;
    `*.example.com` allows its subdomains but not example.com itself."""
    raw = (entry or "").strip()
    text = raw.lower().lstrip("@")
    wildcard = text.startswith("*.")
    host = text[2:] if wildcard else text
    if not host or "*" in host or not _valid_domain(host):
        return "", f"{raw}: expected a domain such as example.com, or *.example.com for its subdomains"
    return ("*." if wildcard else "") + host, None


def allowed_domain_list(raw: Any) -> List[str]:
    """The valid entries of `email_allowed_domains` (one per line or comma)."""
    out: List[str] = []
    for piece in re.split(r"[\s,;]+", str(raw or "")):
        if not piece:
            continue
        entry, problem = parse_domain_entry(piece)
        if not problem and entry not in out:
            out.append(entry)
    return out


def domain_allowed(domain: str, allowed: Sequence[str]) -> bool:
    domain = domain.lower()
    for entry in allowed:
        if entry.startswith("*."):
            if domain.endswith(entry[1:]):
                return True
        elif domain == entry:
            return True
    return False


def _names(addresses: Sequence[str], shown: int = 3) -> str:
    head = ", ".join(addresses[:shown])
    rest = len(addresses) - shown
    return f"{head} and {rest} more" if rest > 0 else head


class RecipientCheck(NamedTuple):
    recipients: List[str]
    problem: Optional[str]
    reason: Optional[str]


def check_recipients(to: Any, sender_email: Any, allowed_domains: Sequence[str],
                     max_recipients: int) -> RecipientCheck:
    """Who an email may go to. `problem` is a sentence for the sender; `reason`
    a stable code for logs and tests."""
    recipients, rejected = parse_recipients(to)
    if rejected:
        return RecipientCheck(recipients, f"Not an email address: {_names(rejected)}.", "bad_address")
    if not recipients:
        return RecipientCheck([], "Add at least one recipient.", "no_recipients")
    cap = max(1, min(int(max_recipients or 1), SES_MAX_RECIPIENTS))
    if len(recipients) > cap:
        return RecipientCheck(recipients, f"At most {cap} recipients per email; this has {len(recipients)}.",
                              "too_many_recipients")
    allowed = list(allowed_domains or [])
    if allowed:
        scope = "the domains this app allows"
    else:
        sender = normalize_address(sender_email)
        if not sender:
            return RecipientCheck(recipients, "Your account has no email address, so the app can't "
                                  "tell which recipients are in your organization.", "no_sender")
        allowed = [domain_of(sender)]
        scope = f"your own domain ({allowed[0]})"
    outside = [r for r in recipients if not domain_allowed(domain_of(r), allowed)]
    if outside:
        return RecipientCheck(recipients, f"Email can only go to {scope}. Not allowed: {_names(outside)}.",
                              "domain_not_allowed")
    return RecipientCheck(recipients, None, None)


# ---------------------------------------------------------------------------
# Markdown, deliberately small
# ---------------------------------------------------------------------------

# Email clients ignore stylesheets unevenly, so every element carries its style.
_STYLE = {
    "p": "margin:0 0 12px",
    "ul": "margin:0 0 12px;padding-left:22px",
    "ol": "margin:0 0 12px;padding-left:22px",
    "li": "margin:0 0 4px",
    "blockquote": "margin:0 0 12px;padding:2px 0 2px 12px;border-left:3px solid #d1d5db;color:#4b5563",
    "pre": "margin:0 0 12px;padding:10px 12px;background:#f3f4f6;border-radius:6px;"
           "font:12px/1.5 Menlo,Consolas,monospace;white-space:pre-wrap",
    "code": "padding:1px 4px;background:#f3f4f6;border-radius:4px;font:12px Menlo,Consolas,monospace",
    "a": "color:#0b5cad",
    "hr": "border:0;border-top:1px solid #e5e7eb;margin:16px 0",
}
_HEADING_SIZES = {1: 22, 2: 19, 3: 16, 4: 15, 5: 14, 6: 14}

_SAFE_URL = re.compile(r"^(?:https?://[^\s<>\"'`]+|mailto:[^\s<>\"'`]+)$", re.I)
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
# A target may hold one level of balanced parentheses, as Wikipedia URLs do.
_TARGET = r"((?:[^()\s]|\([^()\s]*\))*)"
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(" + _TARGET + r"\)")
_LINK = re.compile(r"\[([^\]\n]+)\]\(" + _TARGET + r"\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__")
_ITALIC = re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])|(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)")
_HELD = re.compile(r"\x00(\d+)\x00")

_FENCE = re.compile(r"^(```|~~~)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_RULE = re.compile(r"^(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$")
_BULLET = re.compile(r"^[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\d{1,9}[.)]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")


def _emphasis(escaped: str) -> str:
    escaped = _BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", escaped)
    return _ITALIC.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", escaped)


def _inline(text: str) -> str:
    """Escape a line, then add back the few inline forms this renderer knows.

    Code spans and links are swapped for placeholders before escaping, so their
    contents are escaped once and emphasis can't reach inside them. An image
    becomes a plain link: an <img> would load when the email is opened, which
    tells whoever chose the URL who read it and when.
    """
    held: List[str] = []

    def hold(fragment: str) -> str:
        held.append(fragment)
        return f"\x00{len(held) - 1}\x00"

    def link(m: "re.Match[str]") -> str:
        label, url = m.group(1), m.group(2)
        shown = _emphasis(html.escape(label)) if label.strip() else html.escape(url)
        if _SAFE_URL.match(url):
            return hold(f'<a href="{html.escape(url, quote=True)}" style="{_STYLE["a"]}">{shown}</a>')
        return hold(shown)

    text = text.replace("\x00", "")
    text = _CODE_SPAN.sub(lambda m: hold(f'<code style="{_STYLE["code"]}">{html.escape(m.group(1))}</code>'), text)
    text = _IMAGE.sub(link, text)
    text = _LINK.sub(link, text)
    out = _emphasis(html.escape(text))
    for _ in range(4):
        if "\x00" not in out:
            break
        out = _HELD.sub(lambda m: held[int(m.group(1))], out)
    return out


def render_markdown(md: str) -> str:
    """HTML for a Markdown message, every character of input escaped.

    Paragraphs (single line breaks kept), headings, bullet and numbered lists,
    block quotes, fenced code, rules, **bold**, *italic*, `code` and links.
    Anything else, raw HTML included, comes out as the text it was.
    """
    lines = (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: List[str] = []
    para: List[str] = []
    quote: List[str] = []
    items: List[str] = []
    list_tag = ""

    def flush() -> None:
        nonlocal list_tag
        if para:
            out.append(f'<p style="{_STYLE["p"]}">' + "<br>".join(_inline(line) for line in para) + "</p>")
            para.clear()
        if quote:
            out.append(f'<blockquote style="{_STYLE["blockquote"]}">'
                       + "<br>".join(_inline(line) for line in quote) + "</blockquote>")
            quote.clear()
        if items:
            body = "".join(f'<li style="{_STYLE["li"]}">{_inline(item)}</li>' for item in items)
            out.append(f'<{list_tag} style="{_STYLE[list_tag]}">{body}</{list_tag}>')
            items.clear()
            list_tag = ""

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        fence = _FENCE.match(stripped)
        if fence:
            flush()
            body: List[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence.group(1)):
                body.append(lines[i])
                i += 1
            out.append(f'<pre style="{_STYLE["pre"]}">{html.escape(chr(10).join(body))}</pre>')
            i += 1
            continue
        i += 1
        if not stripped:
            flush()
            continue
        if _RULE.match(stripped):
            flush()
            out.append(f'<hr style="{_STYLE["hr"]}">')
            continue
        heading = _HEADING.match(stripped)
        if heading:
            flush()
            level = len(heading.group(1))
            out.append(f'<h{level} style="margin:16px 0 8px;font-size:{_HEADING_SIZES[level]}px">'
                       f'{_inline(heading.group(2))}</h{level}>')
            continue
        bullet, numbered = _BULLET.match(stripped), _NUMBERED.match(stripped)
        if bullet or numbered:
            tag = "ul" if bullet else "ol"
            if para or quote or (items and list_tag != tag):
                flush()
            list_tag = tag
            items.append((bullet or numbered).group(1))
            continue
        blockquote = _QUOTE.match(stripped)
        if blockquote:
            if para or items:
                flush()
            quote.append(blockquote.group(1))
            continue
        if quote or items:
            flush()
        para.append(stripped)
    flush()
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Tables and the CSV attachment
# ---------------------------------------------------------------------------

class Table(NamedTuple):
    columns: List[str]
    rows: List[List[str]]
    #: Rows the caller supplied, before CSV_MAX_ROWS.
    total_rows: int
    #: Columns dropped past MAX_COLUMNS.
    dropped_columns: int


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, default=str, separators=(",", ":"))
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def normalize_table(table: Any) -> Optional[Table]:
    """A table as `{columns: [names], rows: [[values], ...]}`; a row may also be
    an object keyed by column name, and without `columns` the first rows' keys
    are used. None for no table; ValueError, with a sentence for the sender, for
    a shape that can't be read."""
    if table is None or table == {} or table == []:
        return None
    if not isinstance(table, Mapping):
        raise ValueError("The table must be an object with columns and rows.")
    rows_in = table.get("rows") or []
    columns_in = table.get("columns")
    if not isinstance(rows_in, (list, tuple)):
        raise ValueError("The table's rows must be a list.")
    if columns_in is None:
        columns_in = []
        for row in rows_in[:100]:
            if isinstance(row, Mapping):
                columns_in.extend(k for k in row if k not in columns_in)
    if not isinstance(columns_in, (list, tuple)):
        raise ValueError("The table's columns must be a list of names.")
    keys = list(columns_in)
    if not keys:
        if rows_in:
            raise ValueError("The table needs column names.")
        return None
    dropped = max(0, len(keys) - MAX_COLUMNS)
    keys = keys[:MAX_COLUMNS]
    columns = [_cell(k)[:TABLE_CELL_CHARS] for k in keys]
    rows: List[List[str]] = []
    for row in rows_in[:CSV_MAX_ROWS]:
        if isinstance(row, Mapping):
            values = [row.get(k) if isinstance(k, str) else None for k in keys]
        elif isinstance(row, (list, tuple)):
            values = list(row[:len(columns)]) + [None] * max(0, len(columns) - len(row))
        else:
            raise ValueError("Each table row must be a list of values or an object.")
        rows.append([_cell(v)[:CSV_CELL_CHARS] for v in values])
    return Table(columns, rows, len(rows_in), dropped)


def _short(text: str) -> str:
    return text if len(text) <= TABLE_CELL_CHARS else text[:TABLE_CELL_CHARS - 1] + "…"


def table_html(table: Table, csv_rows: Optional[int] = None) -> str:
    """The first TABLE_MAX_ROWS rows, then a line saying what was left out."""
    th = "padding:6px 10px;border-bottom:2px solid #d1d5db;text-align:left;background:#f9fafb"
    td = "padding:6px 10px;border-bottom:1px solid #e5e7eb;vertical-align:top"
    head = "".join(f'<th style="{th}">{html.escape(_short(c))}</th>' for c in table.columns)
    body = "".join(
        "<tr>" + "".join(f'<td style="{td}">{html.escape(_short(v))}</td>' for v in row) + "</tr>"
        for row in table.rows[:TABLE_MAX_ROWS])
    shown = min(len(table.rows), TABLE_MAX_ROWS)
    notes: List[str] = []
    if shown < table.total_rows:
        note = f"Showing {shown:,} of {table.total_rows:,} rows."
        if csv_rows is not None:
            note += (" The attached CSV has them all." if csv_rows >= table.total_rows
                     else f" The attached CSV has the first {csv_rows:,}.")
        notes.append(note)
    if table.dropped_columns:
        notes.append(f"{table.dropped_columns:,} more columns left out.")
    note_html = (f'<p style="margin:0 0 12px;color:#6b7280;font-size:12px">{html.escape(" ".join(notes))}</p>'
                 if notes else "")
    return (f'<table style="border-collapse:collapse;font-size:13px;margin:0 0 8px">'
            f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{note_html}")


def table_text(table: Table) -> str:
    lines = [" | ".join(_short(c) for c in table.columns)]
    lines += [" | ".join(_short(v) for v in row) for row in table.rows[:TABLE_MAX_ROWS]]
    if len(lines) - 1 < table.total_rows:
        lines.append(f"(Showing {len(lines) - 1:,} of {table.total_rows:,} rows.)")
    return "\n".join(lines)


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def _csv_safe(value: str) -> str:
    # A spreadsheet runs a cell starting with = + - @ as a formula (CSV injection);
    # the quote makes it text. Plain negative numbers are left alone.
    if value.startswith(_FORMULA_START) and not _NUMBER.match(value):
        return "'" + value
    return value


def _csv_line(values: Sequence[str]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerow([_csv_safe(v) for v in values])
    return buf.getvalue()


def table_csv(table: Table) -> Tuple[bytes, int]:
    """(UTF-8 CSV with a BOM so Excel reads it as UTF-8, rows written). Rows
    stop at CSV_MAX_BYTES."""
    chunks = ["\ufeff" + _csv_line(table.columns)]
    size = len(chunks[0].encode("utf-8"))
    for row in table.rows:
        line = _csv_line(row)
        size += len(line.encode("utf-8"))
        if size > CSV_MAX_BYTES:
            break
        chunks.append(line)
    return "".join(chunks).encode("utf-8"), len(chunks) - 1


def csv_filename(subject: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (subject or "").lower()).strip("-")[:60].strip("-")
    return f"{slug or 'table'}.csv"


# ---------------------------------------------------------------------------
# The whole email
# ---------------------------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]+")


def clean_line(value: Any, limit: int) -> str:
    """One line of text for a header or a label: control characters (CR and LF
    included, so nothing can add a header) become spaces, then it is capped."""
    text = re.sub(r"\s+", " ", _CONTROL.sub(" ", str(value or ""))).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def own_view_link(link: Any, origin: str = "", host: str = "") -> str:
    """The view link if it points at this app, else "".

    The link is the client's to send, so it is only trusted when it is on the
    origin the request came from; anything else could put a stranger's URL
    under "Open the view" in an email that carries a colleague's name.
    """
    text = str(link or "").strip()
    if not text or len(text) > MAX_LINK_CHARS or _CONTROL.search(text):
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        return ""
    if origin:
        expected = urlparse(origin)
        return text if (expected.scheme, expected.netloc.lower()) == (parsed.scheme, parsed.netloc.lower()) else ""
    return text if host and parsed.netloc.lower() == host.strip().lower() else ""


class Rendered(NamedTuple):
    subject: str
    html: str
    text: str
    #: (filename, bytes, rows) or None.
    attachment: Optional[Tuple[str, bytes, int]]


def build_email(subject: str, message_md: str, table: Optional[Table], attach_csv: bool,
                sender_email: str, view_name: str = "", view_link: str = "") -> Rendered:
    attachment = None
    if table is not None and attach_csv:
        data, rows = table_csv(table)
        attachment = (csv_filename(subject), data, rows)
    parts = [render_markdown(message_md)] if (message_md or "").strip() else []
    text_parts = [(message_md or "").strip()] if (message_md or "").strip() else []
    if table is not None:
        parts.append(table_html(table, attachment[2] if attachment else None))
        text_parts.append(table_text(table))
    if attachment:
        text_parts.append(f"Attached: {attachment[0]}")

    sender_html = html.escape(sender_email)
    where = f" from {html.escape(view_name)}" if view_name else ""
    footer = (f'Sent by <a href="mailto:{html.escape(sender_email, quote=True)}" style="{_STYLE["a"]}">'
              f"{sender_html}</a>{where} using {PRODUCT}. Reply to this email to reach them.")
    footer_text = f"Sent by {sender_email}{' from ' + view_name if view_name else ''} using {PRODUCT}. " \
                  "Reply to this email to reach them."
    if view_link:
        footer += (f'<br><a href="{html.escape(view_link, quote=True)}" style="{_STYLE["a"]}">'
                   f"Open {html.escape(view_name) if view_name else 'the view'}</a>")
        footer_text += f"\nOpen {view_name or 'the view'}: {view_link}"

    body = "\n".join(parts)
    page = ('<!doctype html><html><body style="margin:0;padding:0;background:#ffffff">'
            '<div style="max-width:720px;padding:20px;font:14px/1.55 -apple-system,Segoe UI,Helvetica,'
            f'Arial,sans-serif;color:#111827">{body}'
            '<div style="margin-top:24px;padding-top:12px;border-top:1px solid #e5e7eb;'
            f'color:#6b7280;font-size:12px">{footer}</div></div></body></html>')
    text = "\n\n".join(text_parts + ["--", footer_text])
    return Rendered(subject, page, text, attachment)


# ---------------------------------------------------------------------------
# Settings, transport and the capability
# ---------------------------------------------------------------------------

class Settings(NamedTuple):
    enabled: bool
    from_address: str
    allowed_domains: List[str]
    max_recipients: int
    daily_limit: int


def current_settings() -> Settings:
    from services import settings_store
    return Settings(
        enabled=settings_store.get_bool_setting("email_enabled"),
        from_address=normalize_address(settings_store.get_setting("email_from_address")) or "",
        allowed_domains=allowed_domain_list(settings_store.get_setting("email_allowed_domains")),
        max_recipients=settings_store.get_int_setting("email_max_recipients"),
        daily_limit=settings_store.get_int_setting("email_daily_limit"),
    )


def aws_keys_present(environ: Mapping[str, str] = os.environ) -> bool:
    return bool((environ.get("AWS_ACCESS_KEY_ID") or "").strip()
                and (environ.get("AWS_SECRET_ACCESS_KEY") or "").strip())


def aws_region(environ: Mapping[str, str] = os.environ) -> str:
    return (environ.get("AWS_REGION") or environ.get("AWS_DEFAULT_REGION") or "").strip()


def choose_transport(enabled: bool, from_address: str, has_keys: bool, region: str,
                     app_environment: str) -> Tuple[str, List[str]]:
    """("ses" | "log" | "off", what SES still needs, in the order to fix it)."""
    missing: List[str] = []
    if not has_keys:
        missing.append(MISSING_KEYS)
    if not region:
        missing.append(MISSING_REGION)
    if not from_address:
        missing.append(MISSING_FROM)
    if not enabled:
        return "off", [MISSING_ENABLED] + missing
    if not missing:
        return "ses", []
    if (app_environment or "").strip().lower() == "local":
        return "log", missing
    return "off", missing


def _transport(cfg: Settings) -> Tuple[str, List[str]]:
    from config.settings import get_app_environment
    return choose_transport(cfg.enabled, cfg.from_address, aws_keys_present(), aws_region(),
                            get_app_environment())


def capability() -> Dict[str, Any]:
    """The `email` check for the Setup card and the Send buttons."""
    from services import capabilities
    transport, missing = _transport(current_settings())
    if transport == "ses":
        return capabilities.result(True, mode="ses")
    if transport == "log":
        return capabilities.result(True, mode="log", missing=missing, next_step=LOG_MODE_STEP)
    return capabilities.result(False, missing=missing, next_step=_NEXT_STEPS[missing[0]])


# ---------------------------------------------------------------------------
# Checking a request
# ---------------------------------------------------------------------------

class Prepared(NamedTuple):
    recipients: List[str]
    rendered: Optional[Rendered]
    problem: Optional[str]
    reason: Optional[str]
    has_table: bool


def _content(subject: Any, message_md: Any, table: Any, attach_csv: bool, reply_to: str,
             view_name: str, view_link: str) -> Tuple[Optional[Rendered], Optional[str], Optional[str], bool]:
    """(rendered, problem, reason, has table) for the content alone."""
    clean_subject = clean_line(subject, MAX_SUBJECT_CHARS)
    message = str(message_md or "")
    if len(message) > MAX_MESSAGE_CHARS:
        return None, f"The message is too long: at most {MAX_MESSAGE_CHARS:,} characters.", "message_too_long", False
    try:
        parsed = normalize_table(table)
    except ValueError as exc:
        return None, str(exc), "bad_table", False
    rendered = build_email(clean_subject, message, parsed, bool(attach_csv), reply_to, view_name, view_link)
    if not clean_subject:
        return rendered, "Add a subject.", "no_subject", parsed is not None
    if not message.strip() and parsed is None:
        return rendered, "The email is empty: add a message or a table.", "empty", False
    return rendered, None, None, parsed is not None


def prepare(cfg: Settings, sender_username: str, sender_email: str, to: Any, subject: Any,
            message_md: Any, table: Any = None, attach_csv: bool = False, view_name: Any = "",
            view_link: str = "") -> Prepared:
    """Everything about a request that needs no database: the sender, the
    recipient policy, the content limits and the rendered email.

    The email is rendered whenever its content allows, even if the sender or
    the recipients are the problem, so the Send dialog can preview it while
    someone fixes the To line. `problem` is the first thing in the way.
    """
    reply_to = normalize_address(sender_email) or ""
    rendered, content_problem, content_reason, has_table = _content(
        subject, message_md, table, attach_csv, reply_to,
        clean_line(view_name, MAX_VIEW_NAME_CHARS), view_link)
    username = (sender_username or "").strip()
    if not username or username == "unknown" or not reply_to:
        return Prepared([], rendered, "Sending email needs a signed-in person with an email address.",
                        "no_sender", has_table)
    check = check_recipients(to, reply_to, cfg.allowed_domains, cfg.max_recipients)
    if check.problem:
        return Prepared(check.recipients, rendered, check.problem, check.reason, has_table)
    return Prepared(check.recipients, rendered, content_problem, content_reason, has_table)


# ---------------------------------------------------------------------------
# email_log
# ---------------------------------------------------------------------------

_COUNT_SQL = """
SELECT COUNT(*) FROM email_log
 WHERE lower(sender) = lower(%s)
   AND status IN ('sending', 'sent', 'logged')
   AND at > now() - interval '24 hours'
"""

_INSERT_SQL = """
INSERT INTO email_log
    (sender, sender_email, recipients, subject, status, transport, source,
     view_name, request_id, has_table, has_attachment, error)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""

_FINISH_SQL = "UPDATE email_log SET status = %s, message_id = %s, error = %s WHERE id = %s"


def _lock_key(sender: str) -> int:
    digest = hashlib.sha256(f"email_log:{sender.strip().lower()}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class Entry(NamedTuple):
    sender: str
    sender_email: str
    recipients: List[str]
    subject: str
    transport: Optional[str]
    source: str
    view_name: str
    request_id: str
    has_table: bool
    has_attachment: bool


def _row(entry: Entry, status: str, error: Optional[str] = None) -> tuple:
    return (entry.sender, entry.sender_email, list(entry.recipients), entry.subject, status,
            entry.transport, entry.source, entry.view_name or None, entry.request_id or None,
            entry.has_table, entry.has_attachment, error)


def reserve(entry: Entry, daily_limit: int) -> Tuple[Optional[int], int]:
    """(log id, sends in the last 24 hours including this one). The id is None
    when the sender has reached the cap. Raises when the log can't be written,
    and the caller then doesn't send."""
    from database import get_db_connection
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Transaction-scoped, so a pooled connection can't carry it to the next borrower.
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_lock_key(entry.sender),))
        cur.execute(_COUNT_SQL, (entry.sender,))
        used = int((cur.fetchone() or [0])[0] or 0)
        if used >= daily_limit:
            conn.rollback()
            return None, used
        cur.execute(_INSERT_SQL, _row(entry, "sending"))
        log_id = cur.fetchone()[0]
        conn.commit()
        return log_id, used + 1
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def finish(log_id: int, status: str, message_id: Optional[str], error: Optional[str]) -> None:
    from database import get_db_connection
    try:
        conn = get_db_connection()
        try:
            conn.cursor().execute(_FINISH_SQL, (status, message_id, error, log_id))
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Couldn't record the outcome of email %s (%s): %s", log_id, status, exc)


def log_refusal(entry: Entry, reason: str) -> Optional[int]:
    from database import get_db_connection
    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(_INSERT_SQL, _row(entry, "refused", reason))
            log_id = cur.fetchone()[0]
            conn.commit()
            return log_id
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Couldn't record a refused email from %s: %s", entry.sender, exc)
        return None


def sends_today(sender: str) -> Optional[int]:
    """Emails this person sent in the last 24 hours, or None if unknown."""
    from database import get_db_connection
    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(_COUNT_SQL, (sender,))
            return int((cur.fetchone() or [0])[0] or 0)
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Couldn't count emails sent by %s: %s", sender, exc)
        return None


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

_client_lock = threading.Lock()
_client: Dict[str, Any] = {}


def _ses_client():
    region = aws_region()
    with _client_lock:
        if _client.get("region") != region:
            import boto3
            from botocore.config import Config
            # A worker thread waits on this call; SES answers in well under a
            # second, so a hung connection should fail fast rather than pin it.
            config = Config(connect_timeout=5, read_timeout=15,
                            retries={"max_attempts": 2, "mode": "standard"})
            _client["client"] = boto3.session.Session().client("sesv2", region_name=region, config=config)
            _client["region"] = region
        return _client["client"]


def _send_ses(rendered: Rendered, from_address: str, reply_to: str, recipients: List[str]) -> str:
    simple: Dict[str, Any] = {
        "Subject": {"Data": rendered.subject, "Charset": "UTF-8"},
        "Body": {"Text": {"Data": rendered.text, "Charset": "UTF-8"},
                 "Html": {"Data": rendered.html, "Charset": "UTF-8"}},
    }
    if rendered.attachment:
        name, data, _rows = rendered.attachment
        simple["Attachments"] = [{"FileName": name, "RawContent": data, "ContentType": "text/csv",
                                  "ContentDisposition": "ATTACHMENT", "ContentTransferEncoding": "BASE64"}]
    response = _ses_client().send_email(
        FromEmailAddress=formataddr((PRODUCT, from_address)),
        Destination={"ToAddresses": list(recipients)},
        ReplyToAddresses=[reply_to],
        Content={"Simple": simple},
    )
    return str(response.get("MessageId") or "")


def _send_log(rendered: Rendered, from_address: str, reply_to: str, recipients: List[str]) -> str:
    message_id = f"log-{uuid.uuid4()}"
    attached = (f"\nAttachment: {rendered.attachment[0]} ({rendered.attachment[2]:,} rows, "
                f"{len(rendered.attachment[1]):,} bytes)" if rendered.attachment else "")
    logger.info(
        "Email written to the log instead of sent (local run, SES not set up) %s\n"
        "From: %s\nReply-To: %s\nTo: %s\nSubject: %s%s\n\n%s",
        message_id, formataddr((PRODUCT, from_address or "(From address not set)")), reply_to,
        ", ".join(recipients), rendered.subject, attached, rendered.text)
    return message_id


def ses_error_message(exc: Exception) -> str:
    """A sentence for the sender. SES's own message is kept: it names the
    unverified identity or the missing permission, which is the fix."""
    response = getattr(exc, "response", None)
    if isinstance(response, Mapping):
        error = response.get("Error") or {}
        code = str(error.get("Code") or "")
        detail = clean_line(error.get("Message") or "", 300)
        if code in ("AccessDenied", "AccessDeniedException"):
            return ("Amazon SES refused the app's AWS keys: the IAM policy must allow "
                    f"ses:SendEmail on the From address's identity. {detail}").strip()
        if code == "MessageRejected":
            return f"Amazon SES rejected the email: {detail}"
        if code in ("SendingPausedException", "AccountSuspendedException"):
            return f"Sending is paused for this AWS account: {detail}"
        if code in ("TooManyRequestsException", "LimitExceededException", "Throttling"):
            return "Amazon SES is limiting how fast this app sends. Try again in a minute."
        return f"Amazon SES couldn't send the email ({code or 'error'}): {detail}"
    return f"Couldn't reach Amazon SES: {clean_line(exc, 300)}"


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def _outcome(status: str, *, transport: Optional[str] = None, recipients: Sequence[str] = (),
             message_id: Optional[str] = None, error: Optional[str] = None,
             reason: Optional[str] = None, log_id: Optional[int] = None) -> Dict[str, Any]:
    return {"ok": status in ("sent", "logged"), "status": status, "reason": reason,
            "transport": transport, "message_id": message_id, "recipients": list(recipients),
            "error": error, "log_id": log_id}


def _record_activity(sender: str, status: str, log_id: Optional[int], detail: Dict[str, Any]) -> None:
    from services import activity
    # `source` is one of activity's content keys and would be dropped, hence `via`.
    activity.record(sender, "email.send", "email", str(log_id) if log_id else None,
                    {"status": status, **detail})


def send_email(sender_username: str, sender_email: str, to: Any, subject: Any, message_md: Any,
               table: Any = None, attach_csv: bool = False, view_name: Any = None,
               view_link: Optional[str] = None, source: str = "widget",
               request_id: Optional[str] = None) -> Dict[str, Any]:
    """Send one email as `sender_username`. Never raises.

    Callers have already established who the sender is (the route from the OBO
    identity, the scheduler from the schedule's owner); everything else is
    checked here. `table` is `{columns, rows}`; `view_link` must already be
    trusted (see `own_view_link`). Returns
    `{ok, status, reason, transport, message_id, recipients, error, log_id}`
    where status is `sent` / `logged` (ok) or `refused` / `unavailable` /
    `failed`, and `error` is a sentence for the sender.
    """
    sender = (sender_username or "").strip()
    try:
        cfg = current_settings()
        transport, _missing = _transport(cfg)
    except Exception as exc:
        logger.warning("Email settings unreadable: %s", exc)
        return _outcome("unavailable", error=UNAVAILABLE, reason="settings_unreadable")
    if transport == "off":
        return _outcome("unavailable", error=UNAVAILABLE, reason="disabled" if not cfg.enabled else "not_set_up")

    clean_view = clean_line(view_name, MAX_VIEW_NAME_CHARS)
    prepared = prepare(cfg, sender, sender_email, to, subject, message_md, table, attach_csv,
                       clean_view, view_link or "")
    rendered = prepared.rendered
    entry = Entry(
        sender=sender or "unknown",
        sender_email=normalize_address(sender_email) or "",
        recipients=prepared.recipients,
        subject=rendered.subject if rendered else clean_line(subject, MAX_SUBJECT_CHARS),
        transport=transport,
        source=clean_line(source, 40) or "widget",
        view_name=clean_view,
        request_id=clean_line(request_id, 100),
        has_table=prepared.has_table,
        has_attachment=bool(rendered and rendered.attachment),
    )
    detail = {"via": entry.source, "transport": transport, "recipient_count": len(entry.recipients),
              "view_name": clean_view or None, "request_id": entry.request_id or None}

    if prepared.problem:
        log_id = log_refusal(entry, prepared.reason or "refused")
        _record_activity(entry.sender, "refused", log_id, {**detail, "reason": prepared.reason})
        return _outcome("refused", transport=transport, recipients=entry.recipients,
                        error=prepared.problem, reason=prepared.reason, log_id=log_id)

    try:
        log_id, used = reserve(entry, cfg.daily_limit)
    except Exception as exc:
        logger.warning("Email from %s not sent: couldn't write email_log: %s", sender, exc)
        return _outcome("failed", transport=transport, recipients=entry.recipients,
                        error="The email couldn't be recorded, so it wasn't sent. Try again shortly.",
                        reason="log_unavailable")
    if log_id is None:
        refusal = log_refusal(entry, "daily_limit")
        _record_activity(entry.sender, "refused", refusal, {**detail, "reason": "daily_limit"})
        return _outcome("refused", transport=transport, recipients=entry.recipients,
                        error=(f"You've sent {cfg.daily_limit} emails in the last 24 hours, the most "
                               "this app allows. Try again later."),
                        reason="daily_limit", log_id=refusal)

    status, message_id, error = "failed", None, None
    try:
        if transport == "ses":
            message_id = _send_ses(rendered, cfg.from_address, entry.sender_email, entry.recipients)
            status = "sent"
        else:
            message_id = _send_log(rendered, cfg.from_address, entry.sender_email, entry.recipients)
            status = "logged"
    except Exception as exc:
        error = ses_error_message(exc)
        logger.warning("Email %s from %s failed: %s", log_id, sender, error)
    finish(log_id, status, message_id, error)
    _record_activity(entry.sender, status, log_id, detail)
    return _outcome(status, transport=transport, recipients=entry.recipients, message_id=message_id,
                    error=error, reason="send_failed" if error else None, log_id=log_id)


def preview_email(sender_username: str, sender_email: str, to: Any, subject: Any, message_md: Any,
                  table: Any = None, attach_csv: bool = False, view_name: Any = None,
                  view_link: Optional[str] = None) -> Dict[str, Any]:
    """What `send_email` would send, without sending or recording anything."""
    try:
        cfg = current_settings()
        transport, _missing = _transport(cfg)
    except Exception as exc:
        logger.warning("Email settings unreadable: %s", exc)
        return {"available": False, "problem": UNAVAILABLE, "reason": "settings_unreadable"}
    prepared = prepare(cfg, (sender_username or "").strip(), sender_email, to, subject, message_md,
                       table, attach_csv, view_name, view_link or "")
    rendered = prepared.rendered
    sent = sends_today((sender_username or "").strip()) if transport != "off" else None
    return {
        "available": transport != "off",
        "mode": transport if transport != "off" else None,
        "problem": UNAVAILABLE if transport == "off" else prepared.problem,
        "reason": ("disabled" if not cfg.enabled else "not_set_up") if transport == "off" else prepared.reason,
        "recipients": prepared.recipients,
        "from_address": cfg.from_address or None,
        "reply_to": normalize_address(sender_email),
        "subject": rendered.subject if rendered else clean_line(subject, MAX_SUBJECT_CHARS),
        "html": rendered.html if rendered else "",
        "attachment": ({"filename": rendered.attachment[0], "rows": rendered.attachment[2],
                        "bytes": len(rendered.attachment[1])} if rendered and rendered.attachment else None),
        "max_recipients": max(1, min(cfg.max_recipients, SES_MAX_RECIPIENTS)),
        "allowed_domains": cfg.allowed_domains,
        "daily_limit": cfg.daily_limit,
        "sent_today": sent,
    }
