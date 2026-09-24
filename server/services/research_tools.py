"""Letting the studio agents look at the data before they write about it.

Widget Studio writes widgets that query a table, and Agent Studio writes agents
that answer questions about one, and until now neither could see the data it was
writing for. Widget Studio had nothing but `search_widgets`, so a request naming
`main.supply.shipments` was answered with column names the model guessed; Agent
Studio could confirm a schema but not ask the question the agent will be asked
("which statuses exist?", "what does a normal week look like?"), so its prompts
described data it had seen five rows of.

Two tools, shared by both studios because they are LangGraph ReAct agents alike:

  * `run_sql` — a read-only query on the app's warehouse (`SQL_WAREHOUSE_ID`), the
    one widgets use, so what the agent learns is what the widget will see.
    `sql_safety` classifies the statement before anything is sent: a studio is a
    place for reading, and a write here would bypass the confirmation prompt that
    governs every write the app makes.
  * `ask_genie` — the AI Gateway Genie MCP server, driven to completion with the
    chat runtime's own poll loop (`agent_runtime._exec_genie`), so "how are late
    shipments defined here?" gets an answer rather than a handle.

Both run under the caller's OBO client. The studios sign their *inference* with the
service principal (see `routes/widget_studio._llm_credentials`), and that exception
must not spread to data: a studio user sees exactly the rows Unity Catalog lets
them see, the same as in chat.

The admin switches in Admin Panel → Settings (`enable_sql_tool`,
`enable_genie_tool`) apply here as they do to chat, and for the same reason: a
deployment that has kept the assistant away from Genie has not done so only for
the drawer. A switched-off tool is not offered at all, as in `agent_runtime`.

Results are text and bounded. A studio's context window also holds the widget
file, the instructions and the history, and a model handed a clipped table
without being told summarises it as if it were whole — so the cut is said aloud.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

from services import sql_safety
from services.sql_advice import quoting_hint

logger = logging.getLogger(__name__)

#: Rows a research query returns unless the model asks for fewer. Enough to see
#: the distinct values of a status column or a week of daily totals; not enough to
#: tempt a model into pasting the table into the widget as literal data.
DEFAULT_ROWS = 50
MAX_ROWS = 200

#: Ceiling on one tool result, in characters. The chat runtime uses 8000 for a
#: whole context of its own; a studio's is shared with the code it is editing.
MAX_RESULT_CHARS = 6000

#: A result cell longer than this is cut. JSON blobs and free-text columns are
#: what make a 50-row sample unreadable, and the model rarely needs all of one.
MAX_CELL_CHARS = 80

#: How long a research query may run on the warehouse. Statement Execution's own
#: inline wait tops out at 50s; past this the statement is cancelled so it isn't
#: left burning warehouse time for a studio turn that has moved on.
SQL_WAIT_SECONDS = 30

#: Research is skipped outright with less than this left on the caller's clock.
#: A query started with seconds to spare only makes the widget later.
MIN_SECONDS = 20

_LIMIT_RE = re.compile(r"\blimit\s+\d+", re.IGNORECASE)

#: How `ask_genie` and `agent_runtime._exec_genie` begin a reply that isn't an
#: answer, so the narration can tell the two apart.
_GENIE_FAILURES = (
    "ask_genie needs", "Genie is unavailable", "Genie could not", "Genie did not",
    "Genie poll error", "Genie query failed",
)

TOOL_LABELS = {
    "run_sql": "Running SQL",
    "ask_genie": "Asking Genie",
}


# ------------------------------------------------------------------ switches

def enabled_tools() -> Dict[str, bool]:
    """Which research tools this deployment allows, from the admin switches.

    Never raises. A settings outage leaves the tools on, matching
    `agent_runtime._tool_is_disabled`: silently stripping every tool from an agent
    is a worse failure than the one it would be protecting against, and Unity
    Catalog still governs what the query can reach.
    """
    try:
        from services.settings_store import get_bool_setting

        return {
            "run_sql": get_bool_setting("enable_sql_tool"),
            "ask_genie": get_bool_setting("enable_genie_tool"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("research tool switch lookup failed, leaving tools enabled: %s", exc)
        return {"run_sql": True, "ask_genie": True}


# ------------------------------------------------------------ pure helpers

def bounded_query(sql: str, max_rows: int) -> str:
    """The statement to send: the model's query, wrapped in a LIMIT if it has none.

    Only SELECT-shaped reads are wrapped. `SHOW TABLES` and `DESCRIBE` cannot sit in
    a subquery, and they are small anyway; `format_result` still caps what comes
    back from them.
    """
    query = (sql or "").strip().rstrip(";").strip()
    if _LIMIT_RE.search(query):
        return query
    first = sql_safety.strip_noise(query).strip().split(None, 1)
    verb = first[0].lower() if first else ""
    if verb in ("select", "with", "values", "table"):
        return f"SELECT * FROM ({query}) AS _research LIMIT {max_rows}"
    return query


def clamp_rows(max_rows: Any) -> int:
    try:
        n = int(max_rows)
    except (TypeError, ValueError):
        return DEFAULT_ROWS
    return max(1, min(n, MAX_ROWS))


def _cell(value: Any) -> str:
    if value is None:
        return "NULL"
    text = str(value).replace("\n", " ").replace("|", "\\|")
    return text if len(text) <= MAX_CELL_CHARS else text[: MAX_CELL_CHARS - 1] + "…"


def format_result(columns: List[str], rows: List[List[Any]], limit: int,
                  max_chars: int = MAX_RESULT_CHARS) -> str:
    """A markdown table of what came back, and an honest line about what didn't."""
    if not columns:
        return "The statement ran and returned no result set."
    if not rows:
        return "No rows. Columns: " + ", ".join(columns)

    lines = [
        "| " + " | ".join(_cell(c) for c in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    shown = 0
    size = sum(len(line) + 1 for line in lines)
    for row in rows:
        line = "| " + " | ".join(_cell(v) for v in row) + " |"
        if size + len(line) + 1 > max_chars:
            break
        lines.append(line)
        size += len(line) + 1
        shown += 1

    head = f"{len(rows)} row(s)"
    if len(rows) >= limit:
        head += f" — stopped at the {limit}-row limit, so there may be more"
    note = ""
    if shown < len(rows):
        note = (f"\n\n[showing {shown} of {len(rows)} rows to fit; aggregate or select fewer "
                "columns to see the rest]")
    return f"{head}:\n\n" + "\n".join(lines) + note


def refusal(sql: str) -> Optional[str]:
    """Why `run_sql` won't send this statement, or None if it will."""
    kind, verb = sql_safety.classify_statement(sql)
    if kind == "empty":
        return "run_sql needs a query."
    if kind == "write":
        named = f" ('{verb.upper()}')" if verb else ""
        return (
            f"run_sql only reads, and this statement would change something{named}. "
            "Research with SELECT, SHOW or DESCRIBE; a widget that writes is built as an "
            "executable widget, which asks the user to confirm each write."
        )
    return None


# ------------------------------------------------------------------- runners

def run_sql(ws, sql: str, max_rows: Any = DEFAULT_ROWS) -> str:
    """Run a read-only research query as the caller and describe the result."""
    from databricks.sdk.service.sql import Disposition, StatementState

    refused = refusal(sql)
    if refused:
        return refused
    warehouse_id = os.environ.get("SQL_WAREHOUSE_ID", "")
    if not warehouse_id:
        return "run_sql is unavailable: no SQL warehouse is configured for this app (SQL_WAREHOUSE_ID)."

    limit = clamp_rows(max_rows)
    statement = bounded_query(sql, limit)
    try:
        result = ws.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=statement,
            wait_timeout=f"{SQL_WAIT_SECONDS}s",
            disposition=Disposition.INLINE,
        )
    except Exception as exc:  # noqa: BLE001 — the model reads the reason and adjusts
        message = str(exc).strip() or type(exc).__name__
        return f"Query failed: {message}{quoting_hint(sql, message)}"

    state = getattr(getattr(result, "status", None), "state", None)
    if state in (StatementState.PENDING, StatementState.RUNNING):
        try:
            ws.statement_execution.cancel_execution(result.statement_id)
        except Exception:  # noqa: BLE001 — best effort; the warehouse times it out anyway
            pass
        return (f"Query was still running after {SQL_WAIT_SECONDS}s and was cancelled. "
                "Narrow it — filter by date, aggregate, or query fewer columns.")
    if state is not None and state != StatementState.SUCCEEDED:
        error = getattr(getattr(result, "status", None), "error", None)
        message = (getattr(error, "message", None) or str(state)).strip()
        return f"Query failed: {message}{quoting_hint(sql, message)}"

    columns: List[str] = []
    manifest = getattr(result, "manifest", None)
    if manifest and manifest.schema and manifest.schema.columns:
        columns = [c.name for c in manifest.schema.columns]
    rows = (result.result.data_array if getattr(result, "result", None) else None) or []
    return format_result(columns, rows[:limit], limit)


def _genie_client(ws):
    """The Genie MCP client for this caller. Separate so tests can replace it."""
    from databricks_mcp import DatabricksMCPClient

    host = (ws.config.host or os.environ.get("DATABRICKS_HOST", "")).rstrip("/")
    return DatabricksMCPClient(server_url=f"{host}/api/2.0/mcp/genie", workspace_client=ws)


def ask_genie(ws, question: str, conversation_id: str = "",
              timeout: Optional[float] = None, response_id: str = "") -> str:
    """Ask Genie a question as the caller and wait for its answer.

    With `response_id` (and its `conversation_id`) it asks nothing: it goes back to
    waiting on an answer an earlier call ran out of time for. A broad question can
    take Genie longer than one research turn allows, and asking it again starts the
    whole search over.
    """
    from services import agent_runtime as rt

    question = (question or "").strip()
    conversation_id = (conversation_id or "").strip()
    response_id = (response_id or "").strip()
    if not question and not response_id:
        return "ask_genie needs a question."
    if response_id and not conversation_id:
        return "ask_genie needs the conversation_id that came with that response_id."
    try:
        client = _genie_client(ws)
        if response_id and conversation_id:
            handle = (conversation_id, response_id)
        else:
            args: Dict[str, Any] = {"question": question}
            if conversation_id:
                args["conversation_id"] = conversation_id
            handle, problem = rt._genie_start(client, "genie_ask", args)
            if handle is None:
                return problem
        answer, still_running = rt._genie_wait(client, *handle, rt._genie_budget(timeout))
    except Exception as exc:  # noqa: BLE001
        return f"Genie is unavailable: {str(exc).strip() or type(exc).__name__}"
    if len(answer) > MAX_RESULT_CHARS:
        answer = answer[:MAX_RESULT_CHARS] + "\n\n[... truncated]"
    if still_running:
        answer += (f'\n\nTo keep waiting for this answer without asking again, call ask_genie '
                   f'with conversation_id="{handle[0]}" and response_id="{handle[1]}".')
    return answer


# --------------------------------------------------------------- LangChain

def langchain_tools(ws, note: Optional[Callable[[str], None]] = None,
                    seconds_left: Optional[Callable[[], float]] = None) -> List[Any]:
    """The research tools this deployment allows, bound to one caller.

    `note` hears one line per call, for a studio that narrates its work (Widget
    Studio's Thinking panel). `seconds_left` is the caller's clock: a tool asked to
    run without the time to finish says so instead of starting, and Genie's wait is
    capped to what remains — so research can make a widget late but never cost the
    turn it was meant to help.
    """
    from langchain_core.tools import tool

    if ws is None:
        return []
    allowed = enabled_tools()

    def say(line: str) -> None:
        if note:
            try:
                note(line)
            except Exception:  # noqa: BLE001 — narration must never break a tool
                pass

    def remaining() -> Optional[float]:
        return seconds_left() if seconds_left else None

    def out_of_time() -> Optional[str]:
        left = remaining()
        if left is not None and left < MIN_SECONDS:
            return ("No time left for research in this turn. Carry on with what you know, "
                    "and say which details you could not confirm.")
        return None

    tools: List[Any] = []

    if allowed.get("run_sql"):
        @tool("run_sql")
        def run_sql_tool(query: str, max_rows: int = DEFAULT_ROWS) -> str:
            """Run a read-only SQL query against Unity Catalog, as the current user.

            Use it to research the data before relying on it: confirm that a table
            exists and what its columns are called (DESCRIBE TABLE, SHOW TABLES IN
            catalog.schema), see the distinct values of a status or category column,
            check date ranges and row counts, or sample a few rows. Use fully
            qualified names (catalog.schema.table) and backtick-quote any name that
            is not plain letters, digits and underscores.

            SELECT, WITH, SHOW, DESCRIBE and EXPLAIN only — anything that changes
            data is refused. Returns up to `max_rows` rows (default 50, at most 200)
            as a table.
            """
            late = out_of_time()
            if late:
                return late
            say(f"querying: {' '.join((query or '').split())[:160]}")
            answer = run_sql(ws, query, max_rows)
            say("query returned " + answer.split("\n", 1)[0][:120])
            return answer

        tools.append(run_sql_tool)

    if allowed.get("ask_genie"):
        @tool("ask_genie")
        def ask_genie_tool(question: str = "", conversation_id: str = "", response_id: str = "") -> str:
            """Ask Databricks Genie a natural-language question about the data.

            Genie searches the Genie spaces the current user can reach and answers
            with the business definitions curated there — use it to learn what a
            term means in this organization, which table holds a metric, or to get a
            quick figure before deciding how to build something. Slower than
            run_sql (tens of seconds); prefer run_sql once you know the table.
            Pass `conversation_id` from an earlier answer to ask a follow-up. If a
            call says Genie is still working, pass the `conversation_id` and
            `response_id` it gives (no question) to keep waiting for that answer.
            """
            late = out_of_time()
            if late:
                return late
            if (response_id or "").strip():
                say("still waiting on Genie's answer")
            else:
                say(f"asking Genie: {' '.join((question or '').split())[:160]}")
            left = remaining()
            answer = ask_genie(ws, question, conversation_id,
                               timeout=(left - MIN_SECONDS) if left is not None else None,
                               response_id=response_id)
            say(answer.split("\n", 1)[0][:160] if answer.startswith(_GENIE_FAILURES) else "Genie answered")
            return answer

        tools.append(ask_genie_tool)

    return tools


def prompt_section(tools: List[Any]) -> str:
    """What to tell a studio agent about the research tools it has, or "".

    Generated from the tools actually bound, so an admin switch that removes one
    removes it from the instructions too — an agent told about a tool it doesn't
    have spends a step discovering that.
    """
    names = [getattr(t, "name", "") for t in tools]
    if not names:
        return ""
    lines = ["## Researching the user's data",
             "You can look at the user's data before you rely on it. Everything runs "
             "as the signed-in user, so you see only what they are allowed to see."]
    if "run_sql" in names:
        lines.append("- `run_sql` runs a read-only query on the warehouse this app uses. "
                     "Use it to confirm table and column names (DESCRIBE TABLE), see the "
                     "real values of a column, and check how much data there is.")
    if "ask_genie" in names:
        lines.append("- `ask_genie` asks Databricks Genie, which knows the business "
                     "definitions curated in the user's Genie spaces. It is slow; use it "
                     "for meaning (what counts as 'late'?), not for rows.")
    lines.append("Research when the request names data you have not been shown, or when "
                 "a wrong guess about a column or value would break the result. Skip it "
                 "when the schema you were given already answers the question. Findings "
                 "inform what you write; they are never pasted in as hardcoded data.")
    return "\n".join(lines)
