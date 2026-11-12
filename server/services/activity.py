"""Who did what, for the Admin Panel's Activity tab. Metadata only.

`action_logs` records approved widget actions with the user's explanation. This
records the rest of what an administrator wants to see happening — publishes,
shares, archives, studio generations, chat turns, emails sent, schedule runs —
as one row per event: who, a verb, which object, and a little metadata.

What it never holds: prompts, chat text, generated code, email bodies, query
results. Those are the user's work, readable through the object itself under its
own access list; an audit trail that copied them would be a second, ungoverned
copy every administrator could read. `clean_detail` enforces that on the way in.

`record` never raises. An event lost to a database hiccup is better than a
publish that fails because the log was unreachable.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

_VERB = re.compile(r"^[a-z][a-z0-9_.]{1,63}$")
_MAX_KEYS = 20
_MAX_TEXT = 200
_MAX_ID = 256

# Keys whose values are the user's own content rather than facts about an event.
_CONTENT_KEYS = frozenset({
    "prompt", "message", "messages", "text", "body", "content", "code", "source",
    "html", "markdown", "sql", "query", "result", "results", "rows", "answer",
})


def clean_detail(detail: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The metadata worth keeping: short scalars under keys that aren't content.

    Nested structures are dropped rather than flattened: anything big enough to
    need nesting is more than an audit row should carry.
    """
    out: Dict[str, Any] = {}
    for key, value in (detail or {}).items():
        if len(out) >= _MAX_KEYS:
            break
        name = str(key).strip()[:64]
        if not name or name.lower() in _CONTENT_KEYS:
            continue
        if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
            out[name] = value
        elif isinstance(value, str):
            out[name] = value[:_MAX_TEXT]
    return out


def record(who: str, verb: str, object_type: Optional[str] = None, object_id: Optional[str] = None,
           detail: Optional[Mapping[str, Any]] = None) -> None:
    """Append one event. `verb` is dotted lowercase, object first: `view.publish`,
    `widget.share`, `email.send`, `schedule.run`. Never raises."""
    try:
        if not _VERB.match(verb or ""):
            logger.warning("Activity verb %r is not dotted lowercase; not recorded", verb)
            return
        from database import get_db_connection

        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO activity_events (username, verb, object_type, object_id, detail)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (
                    (who or "unknown")[:_MAX_ID],
                    verb,
                    (object_type or None) and object_type[:64],
                    (object_id or None) and str(object_id)[:_MAX_ID],
                    json.dumps(clean_detail(detail)),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.info("Could not record activity %s by %s: %s", verb, who, e)
