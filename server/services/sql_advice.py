"""One piece of SQL advice, attached wherever a query fails.

Databricks needs a backtick-quoted identifier for any column, table or schema name
that is not made up only of letters, digits and underscores — and column mapping,
which Unity Catalog tables have on by default, means names with spaces and
punctuation are common. A model that forgets the quotes gets UNRESOLVED_COLUMN back
and tends to respond by guessing a different column name rather than quoting the one
it already had, so the rule travels with the failure as well as sitting in the
prompt.

Used by both surfaces that run model-written SQL: the chat agent's tools
(`services/agent_runtime.py`) and the widget data-source endpoint
(`routes/sql_query.py`), which is what Widget Studio's auto-retry reads.
"""

from __future__ import annotations

# Errors Databricks reports for an identifier that needed quoting. PARSE_SYNTAX_ERROR
# is here because an unquoted name with a space in it usually fails as a syntax error
# rather than an unresolved one: `SELECT Order Number` parses as a bad alias.
_QUOTING_ERRORS = (
    "unresolved_column",
    "parse_syntax_error",
    "cannot be resolved",
    "unresolved column",
)

HINT = (
    "Identifiers containing a space or punctuation must be backtick-quoted in "
    "Databricks — `Order Number`, not Order Number. Check the quoting before "
    "changing the column you asked for."
)


def quoting_hint(statement: str, error: str) -> str:
    """The hint prefixed by a blank line, or "" when it doesn't apply.

    Kept quiet when the statement already uses backticks: the author clearly knows
    about them, so the column really is missing and repeating the rule would send
    them down the wrong path.
    """
    if not statement or "`" in statement:
        return ""
    lowered = (error or "").lower()
    if not any(clue in lowered for clue in _QUOTING_ERRORS):
        return ""
    return "\n\nHint: " + HINT
