"""Telling a query that reads from a statement that changes something.

Two callers need this and they need it to agree, because disagreeing is what
would produce the bad outcome: `routes/sql_query.py` refuses a write on the
read-only endpoint, and `routes/custom_widgets.py` refuses to publish a widget
whose data source writes unless the widget is marked executable. If publishing
classified a statement as a read and the endpoint then ran it as a write, a
widget would be shipped without the confirmation prompt that is supposed to
govern it.

The design is deliberately lopsided:

  * **Reads are an allowlist, not a denylist.** A statement is a read only if it
    *starts* with a verb we recognise as read-only and contains no write verb
    anywhere. Enumerating the ways to mutate data and hoping the list is complete
    is the wrong shape for a security check; enumerating the five ways to ask a
    question is tractable.
  * **Ambiguity resolves to "write".** A statement we cannot classify is treated
    as a write, so the failure mode is a widget author being told to mark their
    widget executable — annoying, visible, fixable — rather than a mutation
    slipping through a path that never asks for confirmation.

None of this is a SQL parser and it is not trying to be. It is a gate in front
of Unity Catalog, which remains the thing that actually decides whether the
caller may write; this exists so that *the app* knows what kind of statement it
is handling and can apply its own confirmation and review rules.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

#: Statements that only ever read. A statement must begin with one of these.
READ_VERBS = frozenset({
    "select", "with", "show", "describe", "desc", "explain", "values", "table",
})

#: Verbs that change data, schema, or permissions. Presence anywhere disqualifies
#: a statement from the read path, which is what stops a write hiding behind a
#: leading CTE or a second statement after a semicolon.
WRITE_VERBS = frozenset({
    "insert", "update", "delete", "merge", "upsert", "copy", "create", "drop",
    "alter", "truncate", "replace", "grant", "revoke", "optimize", "vacuum",
    "restore", "refresh", "call", "rename", "comment", "analyze", "msck",
    "cache", "uncache", "reset", "put", "remove",
})

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_SINGLE_QUOTED = re.compile(r"'(?:''|\\.|[^'])*'", re.DOTALL)
_DOUBLE_QUOTED = re.compile(r'"(?:""|\\.|[^"])*"', re.DOTALL)
_BACKTICKED = re.compile(r"`(?:``|[^`])*`")
_WORD = re.compile(r"[a-z_][a-z0-9_]*")


def strip_noise(sql: str) -> str:
    """Remove comments, string literals and quoted identifiers.

    All three can contain anything at all, including the word `delete` and the
    action-correlation comment widgets prepend to their statements, so leaving
    them in makes the word test meaningless in both directions.
    """
    text = sql or ""
    text = _BLOCK_COMMENT.sub(" ", text)
    text = _LINE_COMMENT.sub(" ", text)
    text = _SINGLE_QUOTED.sub(" '' ", text)
    text = _DOUBLE_QUOTED.sub(' "" ', text)
    text = _BACKTICKED.sub(" `` ", text)
    return text


def classify_statement(sql: str) -> Tuple[str, Optional[str]]:
    """`("read" | "write" | "empty", offending_verb)`.

    The verb is returned so callers can name it: "this looks like a write
    (`merge`)" is actionable where "invalid statement" is not.
    """
    cleaned = strip_noise(sql).strip()
    if not cleaned:
        return "empty", None

    words = _WORD.findall(cleaned.lower())
    if not words:
        return "empty", None

    offending = next((w for w in words if w in WRITE_VERBS), None)
    if offending:
        return "write", offending

    # Leading-verb check last, so an unrecognised opener reports itself rather
    # than being mistaken for a known write.
    if words[0] not in READ_VERBS:
        return "write", words[0]

    return "read", None


def is_write_statement(sql: str) -> bool:
    """True when `sql` is anything other than a recognised read.

    An empty statement is not a write — callers reject it separately, with a
    better message than this function could give.
    """
    kind, _ = classify_statement(sql)
    return kind == "write"


def describe_refusal(sql: str) -> Optional[str]:
    """The message to show when a read-only path is handed a write, or None."""
    kind, verb = classify_statement(sql)
    if kind != "write":
        return None
    if verb:
        return (
            f"This endpoint runs read-only queries, and this statement starts with or contains "
            f"'{verb.upper()}'. A widget that changes data must be marked executable, which routes it "
            f"through the confirmation prompt that records who approved it and why."
        )
    return "This endpoint runs read-only queries only."
