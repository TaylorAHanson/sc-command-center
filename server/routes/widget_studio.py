"""The agent behind Widget Studio: it writes and edits widget TSX.

Mounted at ``/api/agent/widget``. This is not the Agent Studio, which authors
the chat agents kept as database rows — that is ``routes/agent_studio_profiles``
at ``/api/agent/studio``, backed by ``agent_studio_store``. This module was
called ``agent_studio`` for long enough to fool people editing their own
codebase, so if you are here to change how an *authored agent* behaves, you are
in the wrong file.

Generation is a polled background job rather than a stream: ``/generate`` returns
a job id and the browser polls it. The contract the code it writes must satisfy
is ``routes/agent_instructions.md``, which is loaded into the system prompt.
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from openai import OpenAI
import json
import os
import re
import time
import uuid
from typing import List, Optional, Dict, Any
from middleware.auth import get_db_client, get_db_client_sp
from databricks.sdk import WorkspaceClient
from database import get_db_connection
from services.code_patch import (
    apply_edits,
    assess_rewrite,
    continuation_anchor,
    extract_code_block,
    has_conflict_markers,
    looks_truncated,
    parse_edits,
    sloc,
    strip_edit_blocks,
)
from services import llm_params, native_files, research_tools, sql_safety
from services.generation_jobs import JobStore
from services.settings_store import base_path_for_model, get_int_setting, get_setting
from services.llm_client import DatabricksChatOpenAI, chat_client, reply_text
from services.upload_tools import attachments_prompt

# LangChain imports
from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

@tool
def search_widgets(query: str) -> str:
    """Search for existing widgets by name or description to suggest before creating a new one."""
    try:
        conn = get_db_connection("dev")
        c = conn.cursor()
        search_term = f"%{query}%"
        # We query the widgets table.
        c.execute("SELECT id, name, description FROM widgets WHERE (name ILIKE %s OR description ILIKE %s) AND is_deprecated = 0 LIMIT 5", (search_term, search_term))
        results = c.fetchall()
        conn.close()
        
        if not results:
            return f"No matching widgets found for '{query}'."
            
        output = f"Found the following widgets matching '{query}':\n"
        for r in results:
            # handle both RealDictCursor or tuple
            if hasattr(r, 'keys'):
                output += f"- Name: {r['name']}, Description: {r['description']}\n"
            else:
                output += f"- Name: {r[1]}, Description: {r[2]}\n"
        return output
    except Exception as e:
        return f"Error searching widgets: {str(e)}"

router = APIRouter()

# Held in memory by the worker running the job and mirrored to Lakebase, because
# the studio's polls and its Stop can reach either worker. See services/generation_jobs.
generation_jobs = JobStore()

class Message(BaseModel):
    role: str
    content: str

class GenerateRequest(BaseModel):
    prompt: str
    history: List[Message] = []
    error_log: Optional[str] = None
    current_code: Optional[str] = None
    data_source_schema: Optional[Dict[str, Any]] = None
    data_source: Optional[str] = None
    data_source_type: Optional[str] = None
    configuration_mode: Optional[str] = "none"
    config_schema: Optional[List[Dict[str, Any]]] = None
    # Constrains the settings the model may propose, so it can't suggest a
    # category or domain that isn't selectable in the UI.
    available_categories: List[str] = []
    available_domains: List[str] = []
    # Metadata fields the user has already filled in themselves. The model is
    # told not to bother proposing values for these.
    locked_settings: List[str] = []
    # How many rows the configured data source actually returns, when the studio
    # has tested it. The agent cannot judge whether to page, filter and sort in
    # the database or in the browser without knowing this, and left guessing it
    # writes widgets that pull whole tables down a page at a time.
    data_source_row_estimate: Optional[int] = None
    # Files the user attached to this turn (ids from POST /api/agent/uploads).
    attachment_ids: List[str] = []
    # False on the turn that answers a clarifying question, so answering one can
    # never be met with another. See `_clarify`.
    allow_clarify: bool = True
    # A few rows the data source returned when it was tested. A schema says a
    # column is a DATE; only a row says it looks like "2026-09-30" and that the
    # status column holds "Late" rather than "LATE".
    data_source_sample: Optional[List[Dict[str, Any]]] = None
    # What the widget did when it last ran in the preview: failed requests, what
    # its data calls returned, errors it logged or threw. The browser is the only
    # place the widget runs, so this is the agent's only view of its behaviour.
    runtime_log: List[str] = []
    # The studio's deterministic checks on the current code (src/widgetLint.ts).
    lint_findings: List[str] = []
    # A PNG data URL of the rendered widget, sent with review and runtime-fix turns.
    preview_screenshot: Optional[str] = None
    # "page" fills a whole tab rather than a card; `page_instructions.md` applies.
    layout_kind: str = "card"
    env: str = "dev"

class DataSourceTestRequest(BaseModel):
    data_source_type: str
    data_source: str

# A response that gets cut off mid-file is the classic failure for large widgets.
# When we detect one we ask the model to carry on from where it stopped rather
# than starting over, which would just hit the same ceiling.
MAX_CONTINUATIONS = int(os.environ.get("WIDGET_AGENT_MAX_CONTINUATIONS", "3"))

_META_BLOCK_RE = re.compile(r"```widget-meta[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)

_NEXT_BLOCK_RE = re.compile(r"```widget-next[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)

# A suggestion is a prompt the user is one click from sending, so it is bounded
# on both ends: a label short enough for a chip, and a prompt short enough to
# read before sending something that costs a minute of generation.
_SUGGESTION_LIMITS = {"label": 70, "prompt": 400}
MAX_SUGGESTIONS = 4


def _extract_next(content: str) -> tuple[List[Dict[str, str]], str]:
    """Pull the review's follow-up actions out of a reply, and remove the block.

    The review already writes what it would change and what it would add. Left as
    prose that is where it stops: the user reads three good ideas and then retypes
    one of them. This turns each into a prompt the studio can offer as a button —
    the same "see it, act on it" the rest of the app is built around, applied to
    the agent's own findings.

    Unparseable or malformed entries are dropped rather than raised: suggestions
    are a nicety on top of a review that has already done its job.
    """
    match = _NEXT_BLOCK_RE.search(content or "")
    if not match:
        return [], content or ""

    remainder = re.sub(r"\n{3,}", "\n\n", content[:match.start()] + content[match.end():]).strip()
    try:
        raw = json.loads(match.group(1).strip())
    except Exception as e:  # noqa: BLE001 — malformed JSON costs the buttons, not the review
        print(f"Ignoring malformed widget-next block: {e}")
        return [], remainder
    if not isinstance(raw, list):
        return [], remainder

    out: List[Dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not label or not prompt:
            continue
        out.append({
            "kind": "fix" if str(item.get("kind") or "").strip().lower() == "fix" else "idea",
            "label": label[:_SUGGESTION_LIMITS["label"]],
            "prompt": prompt[:_SUGGESTION_LIMITS["prompt"]],
        })
    return out[:MAX_SUGGESTIONS], remainder

# Bounds on what the model may propose for the Configuration tab. Anything not
# listed here is dropped rather than trusted.
_META_TEXT_LIMITS = {"name": 120, "description": 600, "helpText": 2000}

# A configuration field's key becomes a `props.data` key and a settings field id.
_LINK_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
MAX_PROPOSED_LINKS = 12
MAX_PROPOSED_CONFIG_FIELDS = 12
_CONFIG_TYPES = {"text", "number", "select", "textarea"}
_CONFIG_RESERVED_KEYS = {
    "dataSource", "dataSourceType", "username", "variables", "setVariable",
}


def _short_text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:limit]


def _proposed_config(value: Any) -> List[Dict[str, Any]]:
    """Validated dynamic inputs the model wants added to the widget's gear."""
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        field_type = str(item.get("type") or "").strip().lower()
        label = _short_text(item.get("label"), 60)
        if (
            not isinstance(key, str)
            or not _LINK_KEY_RE.match(key)
            or key in seen
            or key in _CONFIG_RESERVED_KEYS
            or field_type not in _CONFIG_TYPES
            or not label
        ):
            continue

        field: Dict[str, Any] = {"key": key, "label": label, "type": field_type}
        if isinstance(item.get("required"), bool):
            field["required"] = item["required"]
        placeholder = _short_text(item.get("placeholder"), 120)
        if placeholder:
            field["placeholder"] = placeholder
        help_text = _short_text(item.get("helpText"), 300)
        if help_text:
            field["helpText"] = help_text

        if field_type == "select":
            options: List[Dict[str, str]] = []
            option_values: set = set()
            raw_options = item.get("options")
            if not isinstance(raw_options, list):
                continue
            for option in raw_options:
                if not isinstance(option, dict):
                    continue
                option_value = _short_text(option.get("value"), 100)
                option_label = _short_text(option.get("label"), 100)
                if not option_value or not option_label or option_value in option_values:
                    continue
                option_values.add(option_value)
                options.append({"value": option_value, "label": option_label})
                if len(options) == 30:
                    break
            if not options:
                continue
            field["options"] = options
            default = item.get("defaultValue")
            if isinstance(default, str) and default in option_values:
                field["defaultValue"] = default
        elif field_type == "number":
            default = item.get("defaultValue")
            if isinstance(default, (int, float)) and not isinstance(default, bool):
                field["defaultValue"] = default
        else:
            default = item.get("defaultValue")
            if isinstance(default, str):
                field["defaultValue"] = default[:500]

        seen.add(key)
        out.append(field)
        if len(out) == MAX_PROPOSED_CONFIG_FIELDS:
            break
    return out


def _proposed_links(value: Any) -> List[Dict[str, str]]:
    """The widget's named links the model declared, as `link` settings fields."""
    if not isinstance(value, list):
        return []
    out: List[Dict[str, str]] = []
    seen: set = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        key, label = item.get("key"), item.get("label")
        if not isinstance(key, str) or not _LINK_KEY_RE.match(key) or key in seen:
            continue
        if not isinstance(label, str) or not label.strip():
            continue
        seen.add(key)
        out.append({"key": key, "label": label.strip()[:60]})
        if len(out) == MAX_PROPOSED_LINKS:
            break
    return out


def _extract_meta(content: str, req: GenerateRequest) -> tuple[Dict[str, Any], str]:
    """Pull the proposed widget settings out of a response.

    Returns the sanitized settings and the content with the block removed, so the
    block never reaches the code extractor or the user-visible explanation.
    """
    import json

    match = _META_BLOCK_RE.search(content or "")
    if not match:
        return {}, content or ""

    # Collapse the gap the removed block leaves behind, so the explanation the
    # user sees doesn't have a hole in it.
    remainder = re.sub(r"\n{3,}", "\n\n", content[:match.start()] + content[match.end():]).strip()
    try:
        raw = json.loads(match.group(1).strip())
    except Exception as e:
        print(f"Ignoring malformed widget-meta block: {e}")
        return {}, remainder
    if not isinstance(raw, dict):
        return {}, remainder

    def pick(options: List[str], value: Any) -> Optional[str]:
        """Resolve a proposed category/domain to one the UI actually offers."""
        if not isinstance(value, str):
            return None
        wanted = value.strip().lower()
        for option in options:
            if option.strip().lower() == wanted:
                return option
        return None

    meta: Dict[str, Any] = {}
    for key, limit in _META_TEXT_LIMITS.items():
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            meta[key] = value.strip()[:limit]

    category = pick(req.available_categories, raw.get("category"))
    if category:
        meta["category"] = category
    domain = pick(req.available_domains, raw.get("domain"))
    if domain:
        meta["domain"] = domain

    for key, hi in (("defaultW", 12), ("defaultH", 40)):
        try:
            value = int(raw.get(key))
        except (TypeError, ValueError):
            continue
        if 1 <= value <= hi:
            meta[key] = value

    if isinstance(raw.get("isExecutable"), bool):
        meta["isExecutable"] = raw["isExecutable"]

    config_schema = _proposed_config(raw.get("configSchema"))
    if config_schema:
        meta["configSchema"] = config_schema

    links = _proposed_links(raw.get("links"))
    if links:
        meta["links"] = links

    proposed_mode = raw.get("configurationMode")
    has_fields = bool(config_schema or links or req.config_schema)
    if proposed_mode in ("config_allowed", "config_required") and has_fields:
        meta["configurationMode"] = proposed_mode
    elif config_schema:
        # A schema hidden behind "none" cannot be configured. Make a missing or
        # contradictory mode useful while keeping "required" an explicit choice.
        meta["configurationMode"] = "config_allowed"

    # The user's own choices win; don't even return a competing suggestion.
    for key in req.locked_settings:
        meta.pop(key, None)
    if "configSchema" in req.locked_settings:
        # `links` is shorthand for link-typed configSchema entries.
        meta.pop("links", None)

    return meta, remainder


# Which side should search, sort, filter and page is the old server-side versus
# client-side choice, and the deciding number is how much the browser has to
# download and hold, not how many rows there are. Fetched once and worked on
# locally, a table is as fast as it can be and costs no round trip per keystroke;
# the price is the payload, and past roughly 10 MB (desktop only) the transfer gets
# slow and then the tab does. Beyond that the work moves into the query and the
# widget only ever holds the slice being looked at. Neither is a limit: both work at
# any row count, which is why this is advice to the model and not a cap.
CLIENT_SIDE_MAX_MB = 10

# What one cell of a fetched row costs once it is JSON: `"order_id":"10482",` is
# about this, with the key repeated on every row. A judgement, not a measurement;
# it is deliberately on the high side because the estimate that matters is the one
# that errs toward the database.
BYTES_PER_CELL = 32

# A source tested before its columns were known, or one that returned none.
ASSUMED_COLUMNS = 20


def _column_count(req: GenerateRequest) -> int:
    schema = req.data_source_schema
    return len(schema) if isinstance(schema, dict) and schema else ASSUMED_COLUMNS


def estimated_payload_mb(rows: int, columns: int) -> float:
    return rows * max(columns, 1) * BYTES_PER_CELL / 1_000_000


def _size_guidance(req: GenerateRequest) -> str:
    """Where filtering, sorting and paging should happen, given what we know.

    This is conditional and not part of `agent_instructions.md` on purpose. The
    instructions are paid for on every call including every step of a plan, and
    only a request with a tested data source can be told anything specific — with
    no row count the honest advice is to find out, which is a different paragraph
    from the one a 40,000-row table needs.
    """
    if req.data_source_type != "sql":
        return ""

    rows = req.data_source_row_estimate
    if rows is None:
        return (
            "\n\nThe size of this result set is unknown — the data source hasn't been "
            "tested, so treat it as potentially large. Add a `LIMIT` to what you display "
            "and do the filtering, sorting and aggregating in SQL rather than in the "
            "component. Never fetch a whole table in order to reduce it in JavaScript. "
            "Any query whose rows the component does filter, sort, total or chart must "
            "send `all_rows: true`, never a guessed `max_rows`, so the work is done over "
            "every row rather than the first few hundred."
        )

    columns = _column_count(req)
    megabytes = estimated_payload_mb(rows, columns)
    size = f"about {rows:,} rows x {columns} columns, roughly {megabytes:.1f} MB as JSON"

    if megabytes <= CLIENT_SIDE_MAX_MB:
        # A count from when the source was tested goes stale as the table grows, so
        # it must not become the widget's `max_rows`: that is how a widget that
        # worked when it was built starts dropping rows months later.
        return (
            f"\n\nThis query returns {size}, which is comfortable to fetch once. Sort, "
            "filter and page in the component over the rows you already have — a round "
            "trip per keystroke would be slower, not faster. Keep the query's own `WHERE` "
            "doing the coarse work, and cap how many rows you render at once.\n"
            "`/api/sql/execute-raw` returns at most 500 rows unless you ask for more, so "
            "send `all_rows: true` in the request body — not a `max_rows` sized to this "
            "count, which drops rows once the table grows. If the response has "
            "`truncated: true`, tell the user the table is showing part of the data; "
            "never present it as the whole."
        )

    return (
        f"\n\nThis query returns {size} — more than a browser tab should download and "
        f"hold (about {CLIENT_SIDE_MAX_MB} MB is the practical ceiling). **Do the work in "
        "the database, not the browser.** Compose the SQL for `props.data.dataSource` per "
        "interaction and re-query:\n"
        "- Page with `LIMIT`/`OFFSET` — one page of rows per request, never the whole "
        "table in batches. Fetching sequential pages in a loop to assemble the full "
        "result is the thing this rule exists to prevent: it is slower than one large "
        "query and it holds every row in the tab.\n"
        "- Sort by putting the column and direction in `ORDER BY`, not by sorting an "
        "array you fetched. Whitelist the column names against the schema you were given "
        "before interpolating them, and backtick them.\n"
        "- Filter and search with `WHERE` (`ILIKE '%' || :term || '%'` shaped predicates), "
        "debounced by ~300ms so typing doesn't fire a query per character.\n"
        "- Aggregate with `GROUP BY` and read the totals back; never sum a page of rows "
        "and present it as a total for the table.\n"
        "- Get the row count for the pager from a separate `SELECT COUNT(*)` over the same "
        "`WHERE`, not from the length of the page you fetched.\n"
        "- A page of up to 500 rows needs nothing extra; for a larger page, send "
        "`max_rows` with the request, because that is all `/api/sql/execute-raw` returns "
        "by default.\n"
        "Wrap the configured query rather than editing it — "
        "`SELECT * FROM (<props.data.dataSource>) AS t WHERE … ORDER BY … LIMIT … OFFSET …` "
        "— so the user's own SQL keeps working. Show a loading state on each re-query and "
        "keep the previous page visible while the next one arrives."
    )


def _page_instructions() -> str:
    """The rules that replace the card rules for a page widget.

    Separate from `agent_instructions.md` for the reason `_size_guidance` is: that
    file is paid for on every call, and most widgets are cards.
    """
    path = os.path.join(os.path.dirname(__file__), "page_instructions.md")
    with open(path, "r") as f:
        return f.read()


def _build_system_prompt(req: GenerateRequest) -> str:
    import json

    try:
        instructions_path = os.path.join(os.path.dirname(__file__), "agent_instructions.md")
        with open(instructions_path, "r") as f:
            system_prompt = f.read()
    except Exception as e:
        print(f"Failed to load agent instructions: {e}")
        system_prompt = "You are an expert React developer."

    if req.layout_kind == "page":
        system_prompt += "\n\n" + _page_instructions()

    system_prompt += "\n\nIf the user is asking to build a widget that sounds like it might already exist, use the search_widgets tool to find similar widgets and suggest them before proceeding. If they explicitly want to build it anyway, then generate the code."

    if req.error_log:
        system_prompt += f"\n\nPrevious attempt failed with error:\n{req.error_log}\nPlease fix the issue."

    if req.current_code:
        system_prompt += f"\n\nHere is the CURRENT state of the widget code:\n```tsx\n{req.current_code}\n```\n"
        if has_conflict_markers(req.current_code):
            # Edits can't clean this: a SEARCH body ends at the first ======= line,
            # so no block can quote the damage. Left to try anyway, the model spends
            # every round on edits that are refused and the widget stays broken.
            system_prompt += (
                "That code was damaged by a bad edit — it contains leftover <<<<<<< / ======= / "
                ">>>>>>> markers, which is why it does not compile. Edits cannot remove them. "
                "Reply with the complete corrected widget in a single tsx block: keep everything "
                "the widget was doing, delete the marker lines, and resolve each spot where they "
                "left duplicated or half-written code."
            )
        else:
            system_prompt += (
                "Modify this code according to the user's instructions using SEARCH/REPLACE blocks "
                "as described in Output Format. Do not re-send the parts you aren't changing."
            )

    if req.data_source:
        # Always tell the LLM what data source is configured so it can wire it up correctly
        if req.data_source_type == "sql":
            ds_label = "SQL query"
        elif req.data_source_type == "databricks_api":
            ds_label = "Databricks API path"
        else:
            ds_label = "API endpoint URL"
        system_prompt += f"\n\nThe widget has a configured data source ({ds_label}):\n```\n{req.data_source}\n```\nYou MUST use `props.data.dataSource` directly in your fetch/query call — do NOT hardcode the SQL or URL."
        system_prompt += _size_guidance(req)

    if req.data_source_schema:
        schema_str = json.dumps(req.data_source_schema, indent=2)
        system_prompt += f"\n\nThe data source returns the following schema (use these exact field names in your component):\n```json\n{schema_str}\n```"
    system_prompt += _sample_section(req)

    config_schema_str = json.dumps(req.config_schema or [], indent=2)
    system_prompt += (
        "\n\nThe widget's current runtime-configuration state is:\n"
        f"- `configurationMode`: `{req.configuration_mode or 'none'}`\n"
        f"- `configSchema`:\n```json\n{config_schema_str}\n```\n"
        "Every listed key arrives on `props.data` (for example, "
        "`props.data.myKey`). Preserve and use existing keys exactly. If the "
        "request adds a runtime parameter, add it to `configSchema` in the "
        "`widget-meta` block and read that same key from `props.data` in the "
        "component. Provide a sensible code fallback, but do not hardcode a "
        "value when a configuration key already exists for it."
    )

    system_prompt += "\n\nThe widget receives the current user's username via `props.data.username`. You can use this to personalize the widget or make user-specific API calls."

    if req.available_categories:
        system_prompt += f"\n\nAllowed `category` values for the widget-meta block: {json.dumps(req.available_categories)}."
    if req.available_domains:
        system_prompt += f"\nAllowed `domain` values for the widget-meta block: {json.dumps(req.available_domains)}."
    if req.locked_settings:
        system_prompt += (
            f"\nThe user has already set these settings themselves: {', '.join(req.locked_settings)}. "
            "Leave those keys out of the widget-meta block entirely."
        )

    if (req.current_code or "").strip():
        system_prompt += _runtime_section(req) + _lint_section(req)

    return system_prompt


# What rides along about the running widget. All of it is paid for on every call of
# a turn — each step of a plan included — so it is bounded here as well as in the
# browser, which is a client and can send anything.
MAX_SAMPLE_ROWS = 5
MAX_SAMPLE_CELL_CHARS = 120
MAX_RUNTIME_LINES = 20
MAX_RUNTIME_LINE_CHARS = 600
MAX_LINT_LINES = 25


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _sample_section(req: GenerateRequest) -> str:
    """A few real rows from the tested data source, or ""."""
    rows = [r for r in (req.data_source_sample or []) if isinstance(r, dict)][:MAX_SAMPLE_ROWS]
    if not rows:
        return ""

    def cell(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return _clip(json.dumps(value, default=str), MAX_SAMPLE_CELL_CHARS)
        if isinstance(value, str):
            return _clip(value, MAX_SAMPLE_CELL_CHARS)
        return value

    trimmed = [{str(k)[:80]: cell(v) for k, v in list(row.items())[:40]} for row in rows]
    return (
        "\n\nThese rows came back when the data source was tested (long values are cut). "
        "Use them to judge formats and real values — date shapes, casing of categories, "
        "which columns are empty — never as data to hardcode:\n"
        f"```json\n{json.dumps(trimmed, indent=1, default=str)}\n```"
    )


def _runtime_section(req: GenerateRequest) -> str:
    """What the widget did when it last ran in the preview, or ""."""
    lines = [_clip(line, MAX_RUNTIME_LINE_CHARS) for line in req.runtime_log if str(line).strip()]
    lines = lines[-MAX_RUNTIME_LINES:]
    if not lines:
        return ""
    return (
        "\n\nWhat the current code did the last time it ran in the studio's preview, oldest "
        "first. These are observations of the running widget, not guesses: when the request "
        "is about something not working or not showing, start from these.\n"
        + "\n".join(f"- {line}" for line in lines)
    )


def _sql_check_hint(tools: List[Any]) -> str:
    """Tell an agent holding `run_sql` to run the SQL it writes, or "".

    A statement composed from a schema is a guess about names, quoting and types
    until a warehouse has seen it, and the preview is a slow and indirect way to
    find out: the widget renders, the query 400s, and the fix costs a whole turn.
    """
    if "run_sql" not in [getattr(t, "name", "") for t in tools]:
        return ""
    # "Code containing a SQL statement" alone was read as "any reply to a widget
    # that queries", and a styling fix came back having run `SELECT 1` to satisfy
    # the rule: the condition has to be the change, and the default has to be no.
    return (
        "\n\nIf — and only if — this change adds a SQL statement or edits the text of "
        "one, run that statement once with `run_sql` (with a small LIMIT) before you hand "
        "the code back, and fix it until it succeeds and returns the columns your code "
        "reads. A change that leaves every statement as it was (layout, styling, wording, "
        "behaviour) needs no query at all, not even a connectivity check. Check read "
        "statements only — never run an INSERT, UPDATE, MERGE or DELETE to test it. The "
        "configured data source was already run when it was tested, so it needs no check "
        "of its own."
    )


def _lint_section(req: GenerateRequest) -> str:
    """The studio's mechanical checks on the current code, or ""."""
    lines = [_clip(line, 300) for line in req.lint_findings if str(line).strip()][:MAX_LINT_LINES]
    if not lines:
        return ""
    return (
        "\n\nThe studio's automated checks flag these in the current code:\n"
        + "\n".join(f"- {line}" for line in lines)
        + "\nDo not introduce more of these, and fix any on lines you are already changing. "
        "They are pattern checks, so an occasional one is a false positive — if so, leave "
        "it and say why in one sentence."
    )


def _finish_reason(message: Any) -> str:
    metadata = getattr(message, "response_metadata", None) or {}
    return metadata.get("finish_reason") or ""


def _continue_truncated(next_llm, system_prompt: str, user_prompt: str, content: str,
                        *, job_id: Optional[str] = None) -> str:
    """Extend a response that ran out of room, one continuation at a time.

    `next_llm()` hands back a client for another round, or None once the
    generation's time allowance is spent — in which case what has arrived so far is
    returned rather than nothing.
    """
    for round_no in range(MAX_CONTINUATIONS):
        if not looks_truncated(content):
            break
        llm = next_llm()
        if llm is None:
            break
        code_so_far, _ = extract_code_block(content)
        anchor = continuation_anchor(code_so_far or content)
        _trace(job_id, f"the reply was cut off mid-file; asking it to carry on (continuation {round_no + 1})")
        follow_up = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
            AIMessage(content=content),
            HumanMessage(content=(
                "Your response was cut off before the file was finished. These were "
                f"its last lines:\n\n{anchor}\n\n"
                "Continue the file from exactly that point. Output the remaining code "
                "only — do not repeat any line you already sent, do not re-open a code "
                "fence, and do not explain anything. Close the ``` fence when the "
                "component is complete."
            )),
        ])
        addition = reply_text(follow_up)
        # A continuation that opens with a fence is restating, not continuing.
        addition = re.sub(r"^\s*```[a-zA-Z]*\n", "", addition)
        if not addition.strip():
            break
        content = content.rstrip("\n") + "\n" + addition
    return content


def _repair_edits(next_llm, system_prompt: str, user_prompt: str, content: str,
                  code: str, failures: List[str]) -> str:
    """Ask for corrected SEARCH text when a block didn't match the file."""
    llm = next_llm()
    if llm is None:
        return ""
    return reply_text(llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
        AIMessage(content=content),
        HumanMessage(content=(
            "Some of your edits could not be applied:\n" + "\n".join(f"- {f}" for f in failures) +
            "\n\nThis is the code as it stands now, after the edits that did apply:\n"
            f"```tsx\n{code}\n```\n"
            "Re-send only the blocks that failed, copying their SEARCH text exactly "
            "from the code above. No explanation."
        )),
    ]))


def _demand_edits(next_llm, system_prompt: str, user_prompt: str, content: str,
                  code: str, reason: str) -> str:
    """Ask for the change as edits, after a whole-file reply looked like a fragment."""
    llm = next_llm()
    if llm is None:
        return ""
    return reply_text(llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
        AIMessage(content=content),
        HumanMessage(content=(
            "That reply would have replaced the entire widget, but "
            f"{reason}. Writing it would delete working code.\n\n"
            "This is the current code, still unchanged:\n"
            f"```tsx\n{code}\n```\n"
            "Send the same change as SEARCH/REPLACE blocks against that code. Copy "
            "each SEARCH text exactly from it, keep every block to the lines you are "
            "actually changing, and do not send a tsx block. No explanation."
        )),
    ]))


def _vet_rewrite(next_llm, system_prompt: str, user_prompt: str, content: str,
                 base_code: str, new_code: str,
                 *, job_id: Optional[str] = None) -> tuple[Optional[str], List[str]]:
    """Decide what to do with a whole-file reply to an edit request.

    Returns the code to write — None to keep what the user already has — and notes
    explaining the decision. A fragment is never written: we ask for the change as
    edits instead, which is the same thing users found they had to ask for by hand.
    """
    risk = assess_rewrite(base_code, new_code)
    if not risk:
        return new_code, []

    if not risk.blocking:
        # A complete widget, just a much smaller one. Asking for it as edits instead
        # would be second-guessing a request to simplify or start over, so write it
        # and make sure the user knows the old version is still reachable.
        _trace(job_id, f"it replaced the whole widget and {risk.reason} — writing it, and pointing at History")
        return new_code, [
            f"This replaced the entire widget — {risk.reason}. "
            "If that wasn't what you wanted, open History in the TSX Editor toolbar and restore the previous version."
        ]

    _trace(job_id, f"refused a whole-file reply — {risk.reason}; asking for the change as edits instead")
    edits = parse_edits(_demand_edits(next_llm, system_prompt, user_prompt, content, base_code, risk.reason))
    if edits:
        result = apply_edits(base_code, edits)
        if result.applied:
            notes = [
                f"The first reply would have replaced the whole widget — {risk.reason} — "
                "so I applied the change as a targeted edit instead."
            ]
            notes.extend(result.warnings)
            if result.failures:
                notes.append("Some of those edits could not be placed and were skipped: "
                             + " ".join(result.failures))
            return result.code, notes

    return None, [
        f"Your code is unchanged. The reply looked like part of a widget rather than a whole one — {risk.reason} — "
        "and overwriting the file with it would have deleted the rest. Ask again, naming the part you want changed."
    ]


def _widget_max_tokens() -> int:
    """Output ceiling for one Widget Studio reply (Admin Panel → Settings)."""
    return get_int_setting("widget_max_tokens")


def _widget_timeout() -> int:
    """Wall-clock allowance for one whole generation (Admin Panel → Settings)."""
    return get_int_setting("widget_timeout")


class _Budget:
    """The wall-clock allowance for one generation, shared by every call it makes.

    A widget request is not one model call: it can be a tool round, a continuation
    for a cut-off file, and a follow-up asking for edits instead of a rewrite. Each
    of those gets whatever time is left rather than a timeout of its own, so a slow
    first call can't leave the studio waiting several multiples of the configured
    limit — and once the allowance is gone the optional rounds are skipped and the
    work applied so far is kept.
    """

    def __init__(self, seconds: int) -> None:
        self.total = max(1, int(seconds))
        self.deadline = time.monotonic() + self.total

    @property
    def left(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    @property
    def spent(self) -> int:
        return int(self.total - self.left)

    def has(self, seconds: float = 5.0) -> bool:
        """Enough time left for another round to be worth starting."""
        return self.left >= seconds


def _widget_llm(api_key: str, base_url: str, model: str, budget: _Budget,
                params: Optional[Dict[str, Any]] = None,
                limit: Optional[float] = None) -> DatabricksChatOpenAI:
    """A client for one call, bounded by the time this generation has left.

    Parameters come from `llm_params`, not from here: this used to pin
    `temperature=0.1`, so pointing the Settings page at a model that refuses
    temperature — the newer Claude and reasoning endpoints all do — failed every
    generation while the chat agent, which never sent it, carried on working.

    `limit` caps this one call below the remaining allowance, for a call whose
    job is to be quick (planning) and which must not be able to spend everything
    the actual work needs.

    `max_retries=0` is load-bearing, not a preference. `timeout` is per attempt,
    and both langchain and the OpenAI client leave retries at 2 by default, so a
    client built with `timeout=budget.left` could spend three times the whole
    allowance on one call and blow through the deadline this class exists to
    hold. A generation is long and expensive; retrying it silently is the wrong
    default anyway — a timeout should surface as a timeout.
    """
    if params is None:
        params = llm_params.langchain_params(model, _widget_max_tokens())
    seconds = budget.left if limit is None else min(budget.left, limit)
    return chat_client(api_key=api_key, base_url=base_url, model=model,
                       timeout=max(5.0, seconds), max_retries=0, **params)


# How many steps a plan may hold. Fewer than two is not a plan; more than six means
# the model has itemised a to-do list rather than divided the work, and each step
# costs a round trip.
MIN_STAGES = 2
MAX_STAGES = 6

# Requests that get planned rather than answered in one pass. A short instruction
# ("make the header blue") is one edit and planning it would only add a round trip;
# the ones that time out ask for several things at once, and say so — in their
# length, or in a list, or with "and also".
_STAGE_HINTS = ("\n-", "\n*", "\n1.", "\n2.", " and ", " also ", " then ", ";", "additionally")

# Planning is a few dozen words of JSON, so it is capped well below the generation
# allowance. Uncapped it was handed `budget.left` like every other call, and a slow
# plan could return with nothing left to build anything with: every step would be
# skipped for want of time and the user would wait out the full timeout for no code
# at all. Planning is also the one call whose failure is free — there is always the
# one-pass path — so it is the right place to be impatient.
PLAN_SECONDS = 45

# How many graph steps a planned step's agent may take: a model call and a tool
# call are one each, so this is room for a handful of lookups and a query check.
# The clock bounds a step too; this bounds an agent that keeps looking.
STEP_RECURSION_LIMIT = 14

# Below this there is no point starting a one-pass generation; say so instead of
# spending what's left to arrive at the same timeout with nothing to show.
MIN_ONE_PASS_SECONDS = 30

# The small jobs — tightening the request, summarising the conversation, deciding
# whether to ask a question — are each a few dozen words in and out, so they are
# capped hard and separately from the work. On a small model they cost a second
# or two; on the generation model they would cost a third of a minute each, which
# is why every one of them is optional and skipped when the budget is thin.
HELPER_SECONDS = 20
HELPER_MAX_TOKENS = 700

# History older than this many messages is summarised rather than replayed. Two
# turns is enough for "no, the other column" to make sense; the rest is what the
# summary is for. This used to be a flat last-six slice, and six of these
# messages is not a small payload — an assistant turn carries a step-by-step
# summary and every italic warning the run produced.
HISTORY_VERBATIM = 2


def _helper_model() -> str:
    """The endpoint for the cheap side-calls, falling back to the main one.

    Also falls back while the configured helper is known not to exist here: the
    default names a `system.ai` model that not every workspace serves, and without
    this every side-call on such a workspace would fail, be skipped, and take the
    history summary and the question gate with it.
    """
    configured = get_setting("widget_helper_model")
    if configured and time.monotonic() < _helper_missing.get(configured, 0.0):
        configured = ""
    return configured or get_setting("widget_model")


# Helpers whose endpoint answered "not found", until when. Retried after a while so
# serving the model later, or fixing a typo in Settings, takes effect unprompted.
_helper_missing: Dict[str, float] = {}
HELPER_MISSING_SECONDS = 600

# The side-calls are short, well-specified text tasks where thinking only costs
# latency, so the helper is asked not to reason. "none" is OpenAI's vocabulary,
# hence only sent to those models; one that refuses the value is remembered here
# and asked without it, for the rest of the process.
HELPER_REASONING_EFFORT = "none"
_helper_no_effort: set = set()


def _helper_params(model: str, max_tokens: Optional[int] = None) -> Dict[str, Any]:
    """`llm_params.langchain_params`, plus the helper's reasoning effort.

    Anything that already has a say about the effort wins over this default: an
    admin override in `model_params` (including "never send it"), a rejection the
    endpoint already gave, or the built-in policy supplying a value of its own.
    """
    params = llm_params.langchain_params(model, max_tokens)
    if model in _helper_no_effort or native_files.flavor(model) != "openai":
        return params
    if "reasoning_effort" in params or "reasoning_effort" in llm_params.describe(model)["omitted"]:
        return params
    if {"reasoning_effort", "reasoning"} & set(llm_params.configured(model)):
        return params
    params["reasoning_effort"] = HELPER_REASONING_EFFORT
    return params


def quick_helper_reply(db_client: WorkspaceClient, messages: List[Any], max_tokens: int = HELPER_MAX_TOKENS) -> str:
    """One helper-model call outside a generation (View settings' Describe the look).

    The same model, limits and fallbacks as the studio's side-calls, but it raises
    rather than returning "": here the reply is the whole job, not an optional step.
    """
    api_key, host = _llm_credentials(db_client)
    budget = _Budget(HELPER_SECONDS + 5)
    model_name = get_setting("widget_model")
    name = _helper_model()
    while True:
        try:
            return llm_params.with_adaptation(
                name,
                lambda params: reply_text(_widget_llm(api_key, _base_url(host, name), name, budget, params, HELPER_SECONDS).invoke(messages)),
                max_tokens=max_tokens,
                params_fn=_helper_params,
            )
        except Exception as exc:  # noqa: BLE001 — each recovery once, then surfaced
            if "reasoning" in str(exc).lower() and name not in _helper_no_effort:
                _helper_no_effort.add(name)
                continue
            if _endpoint_missing(exc) and name != model_name:
                _helper_missing[name] = time.monotonic() + HELPER_MISSING_SECONDS
                name = model_name
                continue
            raise


def _endpoint_missing(exc: Exception) -> bool:
    """Whether a call failed because the model isn't served here at all."""
    if exc.__class__.__name__ == "NotFoundError" or getattr(exc, "status_code", None) == 404:
        return True
    lowered = str(exc).lower()
    return any(marker in lowered for marker in (
        "endpoint_not_found", "resource_does_not_exist", "does not exist", "no such endpoint",
    ))


def _base_url(host: str, model: str) -> str:
    """Where to call `model`. Derived per model, not per job.

    `system.ai.…` names only resolve on the AI Gateway route and plain endpoint
    names only on `/serving-endpoints`, so a job that uses two models cannot share
    one URL between them — that combination 404s whichever of the two didn't
    choose it.
    """
    if not host:
        return os.environ.get("OPENAI_BASE_URL", "https://adb-1234.1.azuredatabricks.net/serving-endpoints")
    return f"{host}{base_path_for_model(model)}"


def _attachments(req: GenerateRequest) -> List[Dict[str, Any]]:
    """Metadata for the files on this turn, skipping any that failed to be read.

    Ownership is not checked here because it cannot be: the generation runs as a
    background task with no caller to check against, which is why `username` is
    `None` rather than a blank — a blank is a filter that matches nobody. It is
    enforced at the point the ids are minted: `/api/agent/uploads` writes the
    caller's username onto the row, and only that caller can read it back.
    """
    if not req.attachment_ids:
        return []
    from services import upload_store

    out: List[Dict[str, Any]] = []
    for upload_id in req.attachment_ids[:5]:
        try:
            meta = upload_store.get_upload(req.env, upload_id, None)
        except Exception as exc:  # noqa: BLE001 — a missing file is not a failed turn
            print(f"Could not read attachment {upload_id}: {exc}")
            continue
        if meta and meta.get("status") == "ready":
            out.append(meta)
    return out


def _turn_message(model: str, env: str, prompt: str, attachments: List[Dict[str, Any]],
                  screenshot: Optional[str] = None) -> HumanMessage:
    """This turn's message, carrying any files the model can read for itself.

    A screenshot is the case that matters: there is no text in it to extract, so
    "the header is misaligned" only means something if the picture travels with
    it. `native_files` decides the content-part shape per provider. `screenshot`
    is the studio's own capture of the preview, which it sends with review and
    runtime-fix turns so the model sees what the user sees.
    """
    parts = native_files.parts(model, env, attachments)
    shot = native_files.image_part(model, screenshot)
    if shot:
        parts = parts + [shot]
    if not parts:
        return HumanMessage(content=prompt)
    return HumanMessage(content=[{"type": "text", "text": prompt}] + parts)


def _compact_history(ask_helper, history: List[Message]) -> List[Any]:
    """The conversation as messages to replay: recent turns, plus a digest.

    Returning the raw tail is always correct and always available, so every
    failure here — an unusable reply, no budget, no summary — falls back to it.
    """
    def replay(messages: List[Message]) -> List[Any]:
        out: List[Any] = []
        for msg in messages:
            if msg.role == "user":
                out.append(HumanMessage(content=msg.content))
            elif msg.role in ("assistant", "system"):
                out.append(AIMessage(content=msg.content))
        return out

    recent = history[-HISTORY_VERBATIM:] if len(history) > HISTORY_VERBATIM else history
    older = history[:-HISTORY_VERBATIM] if len(history) > HISTORY_VERBATIM else []
    # Not worth a round trip until the tail we would be replacing is actually big.
    if len(older) < 2 or sum(len(m.content or "") for m in older) < 1200:
        return replay(history[-6:] if len(history) > 6 else history)

    summary = ask_helper([HumanMessage(content=(
        "Summarise this Widget Studio conversation for the developer picking it "
        "up. Keep what still constrains the widget — what it is for, decisions "
        "the user made, things they rejected, problems still outstanding — and "
        "drop everything about how it was built. No preamble, at most 120 words.\n\n"
        + "\n\n".join(f"{m.role}: {(m.content or '')[:1500]}" for m in older)
    ))])
    if not summary.strip():
        return replay(history[-6:] if len(history) > 6 else history)
    return [AIMessage(content=f"Earlier in this conversation:\n{summary.strip()}")] + replay(recent)


# Marks an assistant turn as a question set, so the history alone is enough to
# tell that one has already been asked.
CLARIFY_MARKER = "<!-- widget-clarify -->"


def _clarify(ask_helper, req: GenerateRequest) -> List[str]:
    """Questions worth asking before spending a generation, or `[]` to get on with it.

    Gated on `_wants_stages`, deliberately: a short instruction is one edit, and
    asking about it is slower than doing it and being told to change it. A request
    big enough to be worth planning is the one where a wrong guess costs minutes,
    and that is exactly the judgement `_wants_stages` already makes.
    """
    if not req.allow_clarify or req.error_log or not _wants_stages(req):
        return []
    # Belt as well as braces: a client that forgets to set `allow_clarify` on the
    # answering turn must not be able to produce a loop, and a conversation that
    # already contains a question set is one where the user has answered it.
    if any(CLARIFY_MARKER in (m.content or "") for m in req.history):
        return []

    reply = ask_helper([HumanMessage(content=(
        "You are about to spend several minutes building this. Before you start: "
        "is there anything you would have to guess at, where guessing wrong means "
        "the user waits for a widget they then have to ask you to change?\n\n"
        f"Request:\n{req.prompt}\n\n"
        + (f"The widget being changed:\n```tsx\n{(req.current_code or '')[:4000]}\n```\n\n"
           if (req.current_code or "").strip() else "")
        + "Ask only about things that change what you would build and that you "
        "cannot reasonably default: which measure, which grouping, what happens "
        "on a click, which of two readings of an ambiguous phrase. Never ask "
        "about styling, sizing, library choice, or anything the instructions you "
        "were given already decide — pick a sensible default for those and say so "
        "afterwards. Most requests need no questions at all.\n\n"
        'Reply with nothing but JSON: {"questions": ["...", "..."]} — at most '
        "three, each a single sentence, or an empty list if you can build this now."
    ))])

    raw = _json_reply(reply, "clarifying questions").get("questions")
    if not isinstance(raw, list):
        return []
    return [q.strip() for q in raw if isinstance(q, str) and q.strip()][:3]


def _wants_stages(req: GenerateRequest) -> bool:
    """Whether this request is big enough to be worth planning first."""
    prompt = (req.prompt or "").strip()
    if req.error_log:
        return False  # fixing a compile error is one job, however long the error is
    if len(prompt) >= 240:
        return True
    return sum(1 for hint in _STAGE_HINTS if hint in prompt.lower()) >= 2


# The plan itself is a plain model call, which can't reach a tool, so research the
# plan depends on is done up front in one short ReAct round whose findings ride along
# with the plan and every step. (Each step has the tools too — see `ask_step` — for
# what only turns up while writing it.) That round costs a model call even when it
# decides nothing needs looking up — 20 to 30 seconds on a thinking model — so it
# only runs when the request points at data: a catalog.schema.table name, or words
# that ask for the data to be looked at. A one-pass request needs none of this.
RESEARCH_SECONDS = 90
_TABLE_NAME_RE = re.compile(r"`?\b[A-Za-z_][\w-]*`?\.`?[A-Za-z_][\w-]*`?\.`?[A-Za-z_][\w-]*\b`?")
_RESEARCH_HINTS = (
    "genie", "which table", "what table", "what columns", "which columns", "look up",
    "find out", "research", "check the data", "look at the data", "from the table",
    "in the table", "the data in",
)
# Dotted names that are code, not tables. `props.data.username` is in half the
# requests people type, and each false match is a research round that finds nothing.
_CODE_PREFIXES = ("props.", "window.", "document.", "react.", "this.", "console.",
                  "math.", "json.", "object.", "array.", "e.target.", "event.")


def _wants_research(req: GenerateRequest) -> bool:
    """Whether a planned run should look at the data before it plans."""
    if req.error_log:
        return False  # a compile error is about the code, not the data
    prompt = (req.prompt or "").lower()
    for match in _TABLE_NAME_RE.finditer(req.prompt or ""):
        if not match.group(0).strip("`").lower().startswith(_CODE_PREFIXES):
            return True
    return any(hint in prompt for hint in _RESEARCH_HINTS)


_QUERYING_CODE_RE = re.compile(r"/api/(?:sql|databricks)/|genie", re.IGNORECASE)


def _may_need_data(req: GenerateRequest) -> bool:
    """Whether this turn should be offered the research tools at all.

    Offered with nothing to look up, the agent found something to run anyway:
    an edit to a page with no data source and no queries spent two warehouse
    round trips on `SELECT 1`. A new widget may still need to find its data.
    """
    code = req.current_code or ""
    if not code.strip() or req.data_source_type:
        return True
    return bool(_QUERYING_CODE_RE.search(code)) or _wants_research(req)


def _research(model: str, make_llm, tools: List[Any], prompt: str, schema_hint: str) -> str:
    """Findings about the data a planned run is about to build on, or `""`.

    Optional by construction, like the helpers: no tools, no time, a failure or a
    reply of NONE all mean "plan without it", which is what happened before this
    existed. `make_llm(params)` builds the client, so a parameter the endpoint
    refuses is dropped and retried here as it is everywhere else.
    """
    if not tools:
        return ""
    instructions = (
        "You are researching the data for a dashboard widget that is about to be "
        "built. Do not write any code. Use the tools to confirm the tables, column "
        "names and types, and the real values the widget will depend on. Then reply "
        "with the findings only, under 200 words: fully qualified table names, the "
        "exact column names with types, notable values or ranges, and anything that "
        "could not be confirmed. If nothing needs looking up, reply with the single "
        "word NONE.\n\n" + research_tools.prompt_section(tools)
    )

    def attempt(params: Dict[str, Any]) -> str:
        agent = create_react_agent(model=make_llm(params), tools=tools, prompt=instructions)
        result = agent.invoke(
            {"messages": [HumanMessage(content=f"The widget request:\n\n{prompt}{schema_hint}")]},
            config={"recursion_limit": 10},
        )
        return reply_text(result["messages"][-1]).strip()

    try:
        reply = llm_params.with_adaptation(
            model, attempt,
            # The generation ceiling, not a helper's: a thinking model spends its
            # reasoning out of this too, and a small cap ends the round mid-thought.
            max_tokens=_widget_max_tokens(),
            params_fn=llm_params.langchain_params,
        )
    except Exception as exc:  # noqa: BLE001 — research is optional, the build is not
        print(f"Widget generation research skipped: {exc}")
        return ""
    if not reply or reply.upper().startswith("NONE"):
        return ""
    return reply[:3000]


def _json_reply(reply: str, what: str) -> Dict[str, Any]:
    """The JSON object in a reply, or `{}` if there isn't a readable one.

    Every cheap side-call in this module — planning, compacting history, deciding
    whether to ask a question, reviewing — asks for JSON and must tolerate not getting it: a
    model that answers in prose, wraps the object in a fence, or adds a sentence
    after it has still done nothing worth failing a turn over. Callers treat `{}`
    as "skip this step", which is always a path they already have.
    """
    try:
        start, end = reply.find("{"), reply.rfind("}")
        parsed = json.loads(reply[start:end + 1]) if start >= 0 < end else {}
    except (ValueError, AttributeError, TypeError) as exc:
        print(f"Widget generation {what} could not be read ({exc}); skipping it")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _plan_stages(ask, system_prompt: str, prompt: str) -> List[Dict[str, str]]:
    """Ask for the request as a few ordered steps. `[]` means answer it in one pass.

    Kept deliberately cheap and deliberately fallible: anything unexpected in the
    reply means no plan, and the caller does what it always did. A plan that fails to
    parse must never cost the user their turn.
    """
    reply = ask([
        SystemMessage(content=system_prompt),
        HumanMessage(content=(
            f"Before writing any code, plan this request:\n\n{prompt}\n\n"
            f"One step per thing the request asks for, up to {MAX_STAGES}. Not one per "
            "thing you have to do to deliver it: holding a value in state, filtering by "
            "it and rendering the result are a single step, because they are one feature "
            "and none of them works without the others. A step that polishes, tidies, "
            "reviews, tests or refines is not a step at all — that work belongs inside "
            "the step it applies to.\n\n"
            "Judge the count by the request and nothing else. Too many and the person "
            "waits half a minute longer for each one; too few and a step becomes the "
            "over-long reply that gets cut off half-written, which is what planning is "
            "here to prevent. A step should be one solid change you can describe in a "
            "sentence.\n\n"
            "Each step changes one part of the widget, and they are applied in order, "
            "each building on the last. The first establishes the component and its "
            "data.\n\n"
            "Reply with nothing but JSON:\n"
            '{"steps": [{"title": "Short label", "detail": "What to change, concretely"}]}\n'
            "If the request is really a single change, reply with one step and it will "
            "be built in one go."
        )),
    ], limit=PLAN_SECONDS)

    steps = _json_reply(reply, "plan").get("steps") or []
    if not isinstance(steps, list):
        return []

    stages = [
        {"title": str(s.get("title") or f"Step {i + 1}")[:80],
         "detail": str(s.get("detail") or s.get("title") or "").strip()}
        for i, s in enumerate(steps)
        if isinstance(s, dict) and (s.get("detail") or s.get("title"))
    ][:MAX_STAGES]
    return stages if len(stages) >= MIN_STAGES else []


def _stage_instruction(stages: List[Dict[str, str]], index: int, first: bool) -> str:
    """What to ask for at one step, with the rest of the plan for context."""
    listing = "\n".join(
        f"{'→' if i == index else ('✓' if i < index else ' ')} {i + 1}. {s['title']}"
        for i, s in enumerate(stages)
    )
    step = stages[index]
    shape = (
        "Write the complete widget file in one ```tsx block."
        if first else
        "Reply with SEARCH/REPLACE blocks against the code above. Do not re-send the "
        "whole file, and do not touch anything outside this step."
    )
    return (
        f"The plan:\n{listing}\n\n"
        f"Do step {index + 1} only — {step['title']}: {step['detail']}\n\n"
        f"{shape} Later steps will handle the rest, so leave room for them and do not "
        "do them now.\n\n"
        "Begin with one sentence, outside any code block, saying what this step "
        "changed. That sentence is the whole of what the user sees for this step, so "
        "a reply that starts with a code fence ticks the step off with nothing beside "
        "it. Nothing more than the sentence."
    )


def _publish(job_id: str, **fields) -> None:
    """Update the job the studio is polling, if it is still there."""
    generation_jobs.update(job_id, **fields)


# How much narration one job may accumulate. A run cannot produce many of these —
# there is one per decision, not one per token — but a bound keeps a wedged job
# from growing without limit, in memory or in the row every poll reads.
MAX_TRACE_LINES = 60


def _trace(job_id: Optional[str], line: str) -> None:
    """Say what the generation just decided, to the log and to the user.

    Every interesting thing this module does — planning, refusing a whole-file
    rewrite, repairing an edit that wouldn't apply, giving up on a step for want
    of time — used to reach a `print()` and stop there, so the only account of a
    three-minute generation was in `backend.log`. The studio polls this and shows
    it in a thinking disclosure, which is the nearest honest equivalent of the
    chat agent's: there is no readable reasoning to stream from these models (see
    services/llm_client.reply_text), but there is plenty worth saying about the
    decisions taken around them.
    """
    print(f"Widget generation: {line}")
    if job_id is None:
        return
    job = generation_jobs.get(job_id)
    if job is None:
        return
    trace = job.setdefault("trace", [])
    if len(trace) < MAX_TRACE_LINES:
        trace.append(line)
        generation_jobs.save(job_id)


def _settle(job_id: str, **fields) -> None:
    """Replace the job with its final state, keeping the narration.

    The completion paths deliberately assign a whole new dict rather than
    updating in place, so that a stale `stage_code` or `error` from mid-run can't
    survive into the result. The trace has to be carried across by hand for that
    reason — it is the one field whose value is the whole history.
    """
    previous = generation_jobs.get(job_id) or {}
    settled = {"trace": previous.get("trace", []), **fields}
    # A Stop the running worker already saw must survive into the final state, or
    # a later poll could not tell a stopped turn from a finished one.
    if previous.get("cancelled"):
        settled["cancelled"] = True
    generation_jobs.replace(job_id, settled, final=True)


def _run_stages(job_id: str, req: GenerateRequest, stages: List[Dict[str, str]],
                ask, next_llm, budget: "_Budget", context: str = "") -> None:
    """Work through a plan, applying each step to the code the last one produced.

    Progress goes onto the job as it happens — including the code so far — so the
    studio can tick steps off and put each one in History as it lands. That is the
    point of staging: a request too big for one reply arrives in pieces that are
    each small enough to succeed, and time running out costs the remaining steps
    rather than the whole turn.
    """
    code = req.current_code or ""
    settings: Dict[str, Any] = {}
    summary: List[str] = []
    applied = 0

    _publish(job_id, status="running", stages=stages, stage_index=0)

    for index, stage in enumerate(stages):
        if generation_jobs.is_cancelled(job_id):
            for pending in stages[index:]:
                pending["status"] = "skipped"
            summary.append(f"Stopped after {applied} of {len(stages)} steps, at your request.")
            break
        # Every step is a model call plus possible follow-ups; starting one with
        # seconds left would just fail slowly.
        if not budget.has(25):
            for pending in stages[index:]:
                pending["status"] = "skipped"
            _trace(job_id, f"out of time after {budget.spent}s; skipping the remaining {len(stages) - index} step(s)")
            summary.append(
                f"Ran out of time after {applied} of {len(stages)} steps ({budget.spent}s). "
                "The steps that finished are applied — ask me to carry on, or raise the "
                "widget generation timeout in Admin Panel → Settings."
            )
            break

        stage["status"] = "running"
        _publish(job_id, stages=stages)
        _trace(job_id, f"step {index + 1} of {len(stages)} — {stage['title']}: {stage['detail']}")

        prompt_for_stage = _stage_instruction(stages, index, first=not code.strip())
        staged_req = req.model_copy(update={"current_code": code})
        # Rebuilt per step because the code changes, so anything learned before
        # the plan (research findings) has to be carried across by hand.
        stage_system = _build_system_prompt(staged_req) + context

        try:
            reply = ask([
                SystemMessage(content=stage_system),
                HumanMessage(content=prompt_for_stage),
            ])
            next_code, explanation, _raw, meta = _apply_reply(
                reply, looks_truncated(reply), code, staged_req,
                next_llm, stage_system, prompt_for_stage, budget, job_id=job_id,
            )
        except Exception as exc:  # noqa: BLE001 — one step failing must not end the run
            _trace(job_id, f"step {index + 1} failed: {exc}")
            stage["status"] = "failed"
            stage["note"] = _failure_text(exc, budget)
            _publish(job_id, stages=stages)
            continue

        if meta:
            settings.update(meta)
        if next_code:
            code = next_code
            applied += 1
            stage["status"] = "done"
            # The code travels with the progress so the studio can apply it now: each
            # step becomes its own History entry, and a later failure leaves the
            # earlier steps standing.
            _publish(job_id, stage_index=applied, stage_code=code, stages=stages)
        else:
            stage["status"] = "failed"
            stage["note"] = "Nothing was changed by this step."
            _publish(job_id, stages=stages)
        # A step that says nothing still has to appear in the summary. Models that
        # reason privately put their narration somewhere we never see and answer
        # with bare code, which used to reduce the whole run to "Worked through 6
        # of 6 steps" — the plan carried out invisibly. Falling back to what the
        # step was asked to do is worth more than a blank line.
        told = explanation.strip() or (stage["detail"] if stage["status"] == "done" else "")
        if told:
            summary.append(f"**{stage['title']}** — {told}")

    done = [s for s in stages if s.get("status") == "done"]
    failed = [s for s in stages if s.get("status") == "failed"]
    if failed:
        summary.append(
            "These steps did not land: " + ", ".join(s["title"] for s in failed) +
            ". Ask again for just those and I'll retry them against the current code."
        )

    _settle(job_id, **{
        "status": "completed",
        "stages": stages,
        "stage_index": len(done),
        "result": {
            # None when no step changed anything: the studio must keep what it has.
            "code": code if done and code != (req.current_code or "") else None,
            "explanation": (f"Worked through {len(done)} of {len(stages)} steps.\n\n"
                            + "\n\n".join(summary)).strip(),
            "raw": "",
            "settings": settings,
        },
    })


def _failure_text(exc: Exception, budget: "_Budget") -> str:
    """A failure the user can act on, rather than the raw exception.

    The two that actually happen are a timeout on a big request and a parameter the
    chosen model refuses, and both have a next step worth naming: raise the limit,
    ask for less, or set the parameter in Settings. `llm_params` retries what it can
    read, so anything arriving here is something it could not.
    """
    raw = str(exc) or exc.__class__.__name__
    lowered = raw.lower()
    if "timeout" in lowered or "timed out" in lowered or not budget.has(2):
        return (
            f"This took longer than the {budget.total}s allowed for one widget request. "
            "Ask for one part of the widget at a time, or raise the widget generation "
            f"timeout in Admin Panel → Settings. ({raw})"
        )
    if any(word in lowered for word in ("parameter", "unsupported", "field required", "not permitted")):
        state = llm_params.describe(get_setting("widget_model"))
        return (
            f"{raw}\n\nThat looks like a parameter this model will not take. It is currently "
            f"sent {state['added'] or 'no extra parameters'} and asked for its output as "
            f"{state['token_parameter']}; adjust it under Model parameter overrides in "
            "Admin Panel → Settings."
        )
    return raw


def run_generation_task(job_id: str, req: GenerateRequest, api_key: str, host: str,
                        research_ws: Optional[WorkspaceClient] = None):
    """One Widget Studio turn.

    `research_ws` is the caller's OBO client, for the research tools. Inference is
    signed by the service principal (`api_key`); the data those tools read never
    is. Without it the turn simply has no research tools, which is what a caller
    that predates them expects.
    """
    budget = _Budget(_widget_timeout())
    try:
        # Admin-settable (Admin Panel → Settings), falling back to LLM_MODEL. The
        # base path follows each model name independently: a `system.ai.…` helper
        # alongside a plain generation endpoint resolves on different routes, and
        # deriving one URL from one of them 404s the other.
        model_name = get_setting("widget_model")
        helper_name = _helper_model()
        base_url = _base_url(host, model_name)
        helper_base_url = _base_url(host, helper_name)

        def ask_helper(messages: List[Any]) -> str:
            """One quick side-call, or `""` if there is no time for it.

            Every caller treats an empty reply as "skip this step", so the helper
            is never the reason a turn fails: it either saves the generation model
            some work or it gets out of the way.
            """
            nonlocal helper_name, helper_base_url
            # One retry for each of the two recoveries below, at most.
            for _ in range(3):
                if not budget.has(HELPER_SECONDS + 10):
                    return ""
                sent_effort = False
                try:
                    def attempt(params: Dict[str, Any]) -> str:
                        nonlocal sent_effort
                        sent_effort = "reasoning_effort" in params
                        llm = _widget_llm(api_key, helper_base_url, helper_name, budget,
                                          params, HELPER_SECONDS)
                        return reply_text(llm.invoke(messages))

                    return llm_params.with_adaptation(
                        helper_name, attempt,
                        max_tokens=HELPER_MAX_TOKENS,
                        params_fn=_helper_params,
                    )
                except Exception as exc:  # noqa: BLE001 — an optional step, by design
                    # `llm_params` learns a parameter the endpoint won't take, but not a
                    # value it won't take ("'none' is not one of low, medium, high").
                    if sent_effort and "reasoning" in str(exc).lower() and helper_name not in _helper_no_effort:
                        _helper_no_effort.add(helper_name)
                        _trace(job_id, f"{helper_name} won't skip reasoning; asking it normally")
                        continue
                    if _endpoint_missing(exc) and helper_name != model_name:
                        _helper_missing[helper_name] = time.monotonic() + HELPER_MISSING_SECONDS
                        _trace(job_id, f"the helper model {helper_name} isn't served here; "
                                       f"using {model_name} for quick checks instead")
                        helper_name, helper_base_url = model_name, base_url
                        continue
                    _trace(job_id, f"skipped a quick check ({helper_name} said: {exc})")
                    return ""
            return ""

        # Asked before anything is built, and only for requests big enough that a
        # wrong guess costs real time. Nothing is generated and no code is
        # touched: the studio shows the questions and the next turn answers them.
        questions = _clarify(ask_helper, req)
        if questions:
            _trace(job_id, f"this looks big enough to be worth {len(questions)} question(s) first")
            _settle(job_id, status="completed", result={
                "code": None,
                "explanation": (
                    "Before I spend a few minutes on this, a couple of things I'd otherwise "
                    "have to guess at:\n\n"
                    + "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
                    + "\n\nAnswer what matters and ignore the rest — or press **Build it anyway** "
                    "and I'll pick sensible defaults.\n" + CLARIFY_MARKER
                ),
                "raw": "",
                "settings": {},
                "questions": questions,
            })
            return

        prompt = req.prompt
        system_prompt = _build_system_prompt(req)
        lc_history = _compact_history(ask_helper, req.history)
        # Files the user attached ride on this turn's message only, so re-sending
        # never compounds them across a conversation.
        attachments = _attachments(req)
        turn = _turn_message(model_name, req.env, prompt, attachments, req.preview_screenshot)
        if attachments:
            _trace(job_id, "reading " + ", ".join(a.get("filename") or "a file" for a in attachments))
            system_prompt += "\n\n" + attachments_prompt(attachments)

        # Read-only SQL and Genie, as the user, narrated into the Thinking panel and
        # held to this job's clock. Empty when an admin has switched both off.
        research = research_tools.langchain_tools(
            research_ws,
            note=lambda line: _trace(job_id, line),
            seconds_left=lambda: budget.left,
        ) if _may_need_data(req) else []
        research_prompt = research_tools.prompt_section(research)
        tool_prompt = ("\n\n" + research_prompt if research_prompt else "") + _sql_check_hint(research)
        agent_tools = [search_widgets, *research]

        # The first call is where a parameter the endpoint refuses shows up, so it
        # runs under `with_adaptation`: the offending parameter is dropped and the
        # call retried, and every later call in this job inherits the lesson.
        def generate(params: Dict[str, Any]):
            llm = _widget_llm(api_key, base_url, model_name, budget, params)
            agent = create_react_agent(
                model=llm,
                tools=agent_tools,
                prompt=system_prompt + tool_prompt,
            )
            return agent.invoke({"messages": lc_history + [turn]})

        # Every follow-up round asks for a client here, and gets None once the
        # allowance is spent — so a generation that runs long returns the work it
        # managed rather than dying on a timeout with nothing to show.
        def next_llm() -> Optional[DatabricksChatOpenAI]:
            # The studio has already stopped listening, so a follow-up now would
            # be spent on an answer nobody reads.
            if generation_jobs.is_cancelled(job_id):
                _trace(job_id, "stopped; skipping the follow-up round")
                return None
            if not budget.has(15):
                _trace(job_id, f"out of time after {budget.spent}s; skipping the follow-up round")
                return None
            return _widget_llm(api_key, base_url, model_name, budget)

        def ask(messages: List[Any], limit: Optional[float] = None) -> str:
            """One plain call, with the parameters this model accepts.

            Wrapped in `with_adaptation` like the ReAct path, so a staged run learns
            from a refused parameter on its first call rather than failing. `limit`
            caps this call below the remaining allowance; a step takes what is left.
            """
            def attempt(params: Dict[str, Any]) -> str:
                llm = _widget_llm(api_key, base_url, model_name, budget, params, limit)
                return reply_text(llm.invoke(messages))

            return llm_params.with_adaptation(
                model_name, attempt,
                max_tokens=_widget_max_tokens(),
                params_fn=llm_params.langchain_params,
            )

        def ask_step(messages: List[Any], limit: Optional[float] = None) -> str:
            """One step of a plan, with the same tools the one-pass path has.

            Steps are where most of a large widget gets written, and they used to be
            plain calls: a step that added a query could not look up a column name or
            run the statement it had just written. The first message is the step's
            system prompt; the rest are the conversation.
            """
            if not agent_tools:
                return ask(messages, limit)
            system, conversation = messages[0], messages[1:]

            def attempt(params: Dict[str, Any]) -> str:
                llm = _widget_llm(api_key, base_url, model_name, budget, params, limit)
                agent = create_react_agent(model=llm, tools=agent_tools,
                                           prompt=system.content + tool_prompt)
                out = agent.invoke({"messages": conversation},
                                   config={"recursion_limit": STEP_RECURSION_LIMIT})
                return reply_text(out["messages"][-1])

            try:
                return llm_params.with_adaptation(
                    model_name, attempt,
                    max_tokens=_widget_max_tokens(),
                    params_fn=llm_params.langchain_params,
                )
            except GraphRecursionError:
                # Research that never converges must not cost the step itself.
                _trace(job_id, "stopped researching this step; writing it with what is known")
                return ask(messages, limit)

        # A request asking for several things at once is planned and applied a step
        # at a time: each call is small enough to finish, progress is visible, and
        # what lands stays landed. One instruction still goes straight to the model.
        if _wants_stages(req):
            findings = ""
            if research and _wants_research(req) and budget.has(RESEARCH_SECONDS + MIN_ONE_PASS_SECONDS):
                _trace(job_id, "looking at the data before planning")
                # Its own clock, inside the job's: a slow Genie answer may cost the
                # research, never the time the plan and its steps need.
                window = _Budget(RESEARCH_SECONDS)
                scoped = research_tools.langchain_tools(
                    research_ws,
                    note=lambda line: _trace(job_id, line),
                    seconds_left=lambda: min(window.left, budget.left - MIN_ONE_PASS_SECONDS),
                )
                schema_hint = (
                    f"\n\nThe configured data source already returns: {json.dumps(req.data_source_schema)}"
                    if req.data_source_schema else ""
                )
                findings = _research(
                    model_name,
                    lambda params: _widget_llm(api_key, base_url, model_name, window, params),
                    scoped, prompt, schema_hint,
                )
                if findings:
                    _trace(job_id, "research found: " + " ".join(findings.split())[:300])
            context = (
                "\n\nWhat research into the user's data found before this plan was made "
                "(trust it over guesses; it was checked against the live tables):\n" + findings
                if findings else ""
            )
            stages = _plan_stages(ask, system_prompt + context, prompt)
            if stages:
                _trace(job_id, "planned this in "
                       + ", ".join(f"{i + 1}) {s['title']}" for i, s in enumerate(stages)))
                _run_stages(job_id, req, stages, ask_step, next_llm, budget, context)
                return
            # No plan, and planning took the allowance with it. Starting a one-pass
            # generation now would spend the rest arriving at the same timeout with
            # nothing to show, so say what happened while it can still be read.
            if not budget.has(MIN_ONE_PASS_SECONDS):
                _settle(job_id, status="failed", error=(
                    f"Planning this request used the {budget.total}s allowed for it, leaving no "
                    "time to build anything. Ask for one part of the widget at a time, or raise "
                    "the widget generation timeout in Admin Panel → Settings."
                ))
                return
            _trace(job_id, "no usable plan came back; building it in one pass")

        response = llm_params.with_adaptation(
            model_name, generate,
            max_tokens=_widget_max_tokens(),
            params_fn=llm_params.langchain_params,
        )

        last_message = response["messages"][-1]
        truncated = (_finish_reason(last_message) == "length"
                     or looks_truncated(reply_text(last_message)))

        code, explanation, content, meta = _apply_reply(
            reply_text(last_message), truncated, req.current_code or "", req,
            next_llm, system_prompt, prompt, budget, job_id=job_id,
        )

        _settle(job_id, status="completed", result={
            "code": code,
            "explanation": explanation,
            "raw": content,
            "settings": meta,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        _settle(job_id, status="failed", error=_failure_text(e, budget))


# A review is one reading pass plus, at most, one round of fixes. It gets a
# fraction of the generation allowance because it runs *after* the user already
# has working code: a review that takes as long as the build is not worth waiting
# for, and one that runs out of time simply reports what it found.
REVIEW_SECONDS = 120
# A page is several cards' worth of code, read alongside a screenshot of a whole
# tab; at the card allowance its review runs out of time before it answers.
PAGE_REVIEW_SECONDS = 240


def _review_seconds(layout_kind: str, timeout: int) -> int:
    return min(PAGE_REVIEW_SECONDS if layout_kind == "page" else REVIEW_SECONDS, timeout)


def _review_evidence(req: GenerateRequest, screenshot: bool) -> str:
    """What the studio saw when the widget ran, pointed out to the reviewer, or "".

    Reading code finds what code reading can find. The studio has also run the
    widget, and a query that 400'd or a panel that rendered empty is worth more
    than any amount of inference about whether it might.
    """
    lines: List[str] = []
    if screenshot:
        lines.append(
            "A screenshot of the widget as it rendered in the preview is attached. Look "
            "at it before the code: text you can't read, a chart with no visible data, "
            "an empty panel that should have rows, clipped or overlapping content."
        )
    if any(str(line).strip() for line in req.runtime_log):
        lines.append(
            "The system message lists what happened when it last ran in the preview. A "
            "failed request, an error it threw or logged, or a query that returned no "
            "rows is a finding — the first one to fix, not a guess to hedge."
        )
    if any(str(line).strip() for line in req.lint_findings):
        lines.append(
            "The system message also lists what the studio's automated checks flagged. "
            "Treat each as a defect and fix it, unless it is plainly a false positive."
        )
    return ("\n\n".join(lines) + "\n\n") if lines else ""


def _review_instruction(req: GenerateRequest, screenshot: bool = False) -> str:
    """What to look for. Names no rules — it points back at the ones already given.

    Restating the widget contract here would be a second copy of
    `agent_instructions.md` to keep in step with the first, and the reviewer is
    already holding it: `_build_system_prompt` puts it in the system message.

    Two halves, because checking the code against the request can only ever
    confirm the request. Asked for a supplier table with a search box, a model
    reviewing its own work reported six paragraphs of things that were correct
    and stopped — while the widget had no way to sort, which is the first thing
    anyone would want from a scorecard and something nobody had thought to ask
    for. So the first half hunts defects and may fix them, and the second asks
    whether the widget is any good and may not touch anything: a review that
    builds what it just suggested is one users switch off.
    """
    asked = (req.prompt or "").strip()
    return (
        "Review the widget above as a second pair of eyes. It compiles and renders "
        "— that has already been checked, so do not comment on syntax.\n\n"
        + (f"What the user asked for:\n{asked}\n\n" if asked else "")
        + _review_evidence(req, screenshot)
        + "Answer in two parts, under those headings.\n\n"
        "## What's wrong\n\n"
        "Judge it against the instructions you were given:\n"
        "1. **Does it do what was asked?** Every part of the request, not most of "
        "it. A silently dropped requirement is the finding that matters most.\n"
        "2. **Data.** Does it read the configured source correctly, show the reason "
        "when a query is refused rather than an empty panel, and do its filtering "
        "and aggregating on the side it was told to?\n"
        "3. **States.** Loading, empty, error and too-much-data — is each one a "
        "thing the user can read, or does the widget just sit blank?\n"
        "4. **Layout.** Does it still work squashed narrow and stretched wide, and "
        "does it fill the space it is given rather than assuming a size?\n"
        "5. **Legibility.** Go through every text and icon colour in the file, not "
        "only the ones the request drew attention to: placeholder, helper, "
        "disabled, empty-state and hover text are where the unreadable ones "
        "survive. Name any that is 400 or lighter on a light background. Also "
        "flag arbitrary Tailwind values.\n"
        "6. **Correctness in the small.** Effects cleaned up, keys on lists, no "
        "work repeated on every render that could be held.\n\n"
        "Report findings only, worst first, one sentence of why each. **Do not "
        "walk back through those six confirming what is fine.** A list of things "
        "that are correct is not a review — it is padding that buries the one "
        "line that mattered, and it reads as work done rather than work found. If "
        "a choice is a fair reading of an ambiguous request rather than a defect, "
        "leave it alone. If there is genuinely nothing, one line saying so is the "
        "whole of this part.\n\n"
        "Fix what you found, as SEARCH/REPLACE blocks against the code above. "
        "Defects and omissions only — do not restyle, rename, reorganise or add "
        "features nobody asked for, and do not send a tsx block.\n\n"
        "## Worth considering\n\n"
        "Now stop comparing the code to the request, which can only ever tell you "
        "the request was followed, and judge the widget as the person who has to "
        "use it every day. Open with one line: is this good at the job it exists "
        "to do? Then name up to three changes that would most improve it, best "
        "first, each with what it would be worth and roughly what it would take.\n\n"
        "Look for what the request could not tell you:\n"
        "- **The question someone opens this widget with.** Can they answer it at "
        "a glance, or must they read every row and hold it in their head?\n"
        "- **Ranking and comparison.** A table nothing sorts by cannot answer "
        "\"which are the worst\", and a headline number with no target, total or "
        "prior period cannot be judged good or bad by the person reading it.\n"
        "- **The next move it invites and does not support** — a filter for the "
        "category it just colour-coded, a click through to the row behind a "
        "figure, a way to take the finding somewhere else.\n"
        "- **Whether it holds up at real size.** Demo data is small and sorted "
        "conveniently; production data is neither.\n"
        "- **Anything on screen that carries no information** — a chart with no "
        "scale, a colour that encodes a rule it never reveals.\n\n"
        "Be concrete: name the control, the column or the number you would add, "
        "not a quality like \"improve usability\". A widget can satisfy every word "
        "of the request and still stop one step short of being useful, and that "
        "gap is invisible to the first part of this review — it is the whole "
        "reason this part exists. Only conclude there is nothing worth doing if "
        "you have genuinely looked and the widget is complete for its purpose, "
        "and say why you think so.\n\n"
        "These are suggestions, not work: do not implement them and do not send "
        "SEARCH/REPLACE blocks for them. A review that quietly grows the widget "
        "is one nobody can leave switched on.\n\n"
        "## Finally, make them actionable\n\n"
        "End your reply with a ```widget-next block: a JSON array turning what "
        "you just wrote into things the user can click, in the order you argued "
        "for them. This is not code and is not an edit — it is stripped out "
        "before anyone sees it, and each entry becomes a button that writes its "
        "prompt into the message box.\n\n"
        "```widget-next\n"
        '[{"kind": "idea", "label": "Sortable columns",\n'
        '  "prompt": "Make the columns sortable, defaulting to risk descending, '
        'so the suppliers that need attention are at the top."}]\n'
        "```\n\n"
        f"At most {MAX_SUGGESTIONS} entries. `kind` is \"idea\" for anything from "
        "Worth considering, and \"fix\" for a defect you reported but did not "
        "fix — never for one you already fixed, since there is nothing left to "
        "do. `label` is a few words for the button. `prompt` is the instruction "
        "written as the user would write it to you, specific enough to act on "
        "without the rest of this review for context. Send no block at all if "
        "you had nothing to report and nothing to suggest."
    )


def run_review_task(job_id: str, req: GenerateRequest, api_key: str, host: str):
    """Read the generated widget back and fix what's wrong with it.

    Off by default, because it is another model call on top of a generation that
    has already finished. Findings that come back as edits go through
    `_apply_reply` like any other reply, so the fragment vetting and the failed-edit
    repair apply here too — a review is not allowed to eat the widget it was
    checking.
    """
    budget = _Budget(_review_seconds(req.layout_kind, _widget_timeout()))
    code = req.current_code or ""
    try:
        if not code.strip():
            _settle(job_id, status="completed", result={"code": None, "explanation": "", "raw": "", "settings": {}})
            return

        model_name = get_setting("widget_model")
        base_url = _base_url(host, model_name)
        system_prompt = _build_system_prompt(req)
        shot = native_files.image_part(model_name, req.preview_screenshot)
        instruction = _review_instruction(req, screenshot=shot is not None)
        review_message = (
            HumanMessage(content=[{"type": "text", "text": instruction}, shot])
            if shot else HumanMessage(content=instruction)
        )
        _trace(job_id, "reviewing the widget against what you asked for"
                       + (", with a screenshot of how it rendered" if shot else ""))

        def next_llm() -> Optional[DatabricksChatOpenAI]:
            if not budget.has(15):
                return None
            return _widget_llm(api_key, base_url, model_name, budget)

        def attempt(params: Dict[str, Any]) -> str:
            llm = _widget_llm(api_key, base_url, model_name, budget, params)
            return reply_text(llm.invoke([SystemMessage(content=system_prompt), review_message]))

        reply = llm_params.with_adaptation(
            model_name, attempt,
            max_tokens=_widget_max_tokens(),
            params_fn=llm_params.langchain_params,
        )

        fixed, explanation, content, _meta = _apply_reply(
            reply, looks_truncated(reply), code, req,
            next_llm, system_prompt, instruction, budget, job_id=job_id,
        )
        suggestions, explanation = _extract_next(explanation)
        _trace(job_id, "fixed what the review found" if fixed else "the review found nothing worth changing")
        if suggestions:
            _trace(job_id, f"offered {len(suggestions)} thing(s) you can do next in one click")

        _settle(job_id, status="completed", result={
            "code": fixed,
            "explanation": ("**Review**\n\n" + explanation).strip() if explanation.strip() else "",
            "raw": content,
            "suggestions": suggestions,
            # A review never proposes Configuration-tab values: those were settled
            # when the widget was built, and second-guessing them here would
            # overwrite what the user has since typed.
            "settings": {},
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        # A failed review must never look like a failed generation — the code the
        # user is holding is fine, and this was an optional extra pass over it.
        _settle(job_id, status="completed", result={
            "code": None,
            "explanation": f"_I couldn't finish the review pass ({_failure_text(e, budget)}). Your widget is unchanged._",
            "raw": "",
            "settings": {},
        })


def _apply_reply(reply: str, truncated: bool, base_code: str, req: GenerateRequest,
                 next_llm, system_prompt: str, user_prompt: str,
                 budget: "_Budget",
                 *, job_id: Optional[str] = None) -> tuple[Optional[str], str, str, Dict[str, Any]]:
    """Turn one model reply into code, an explanation, and proposed settings.

    Shared by the single-pass path and each step of a staged run, so a step gets the
    same protections as a whole turn: failed edits are repaired once, a cut-off file
    is continued, and a whole-file reply to an edit request is vetted before it is
    allowed to become the entire widget.

    Returns `(code or None, explanation, raw content, settings)`. `None` code means
    nothing was applied and the caller must keep what the user already had.
    """
    meta, content = _extract_meta(reply, req)
    notes: List[str] = []

    edits = parse_edits(content)
    if edits and base_code.strip():
        result = apply_edits(base_code, edits)
        notes.extend(result.warnings)

        if result.failures:
            _trace(job_id, f"{len(result.failures)} of its edits didn't match the file; asking for corrected search text")
            repair = _repair_edits(next_llm, system_prompt, user_prompt, content,
                                   result.code, result.failures)
            retry_edits = parse_edits(repair)
            if retry_edits:
                retried = apply_edits(result.code, retry_edits)
                result = result._replace(
                    code=retried.code,
                    applied=result.applied + retried.applied,
                    failures=retried.failures,
                    warnings=result.warnings + retried.warnings,
                )
                notes.extend(retried.warnings)

        code = result.code if result.applied else None
        explanation = strip_edit_blocks(content)
        if code and sloc(base_code) >= 25 and sloc(code) * 2 < sloc(base_code):
            # Edits that delete most of the file are legal but rarely intended.
            notes.append(
                f"These edits cut the widget from {sloc(base_code)} lines to {sloc(code)}. "
                "If that's more than you asked for, restore the previous version from History."
            )
        if truncated:
            notes.append("The response was cut off, so some requested changes may be missing.")
        if result.failures:
            notes.append(
                "Some edits could not be placed and were skipped: "
                + " ".join(result.failures)
            )
        if code is None:
            notes.append("No changes were applied — the code is unchanged.")
    else:
        if edits:
            # Edits arrived with nothing to apply them to. Don't show the raw
            # markers to the user; say what happened instead.
            content = strip_edit_blocks(content)
            notes.append(
                "The model replied with edits, but there is no existing code to apply "
                "them to. Ask again and it will write the widget from scratch."
            )
        # Whole-file response: either a new widget or a rewrite the model
        # judged too pervasive to express as edits.
        if truncated:
            content = _continue_truncated(next_llm, system_prompt, user_prompt, content, job_id=job_id)
        code, explanation = extract_code_block(content)
        if code:
            # Failsafe cleanup of any lingering backticks just in case
            code = re.sub(r'^```[a-zA-Z]*\n?', '', code)
            code = re.sub(r'\n?```$', '', code)
            if base_code.strip():
                # Editing, not creating: whatever this block holds is about to
                # become the whole widget, so make sure it is one.
                code, vet_notes = _vet_rewrite(next_llm, system_prompt, user_prompt, content,
                                               base_code, code, job_id=job_id)
                notes.extend(vet_notes)
        if looks_truncated(content):
            notes.append(
                f"The widget is still incomplete after {budget.spent}s, so the code may be "
                "cut off. Ask for it in smaller pieces, or raise the widget generation "
                "timeout in Admin Panel → Settings."
                if not budget.has(15) else
                "The response was still incomplete after "
                f"{MAX_CONTINUATIONS} continuation attempts, so the code may be "
                "cut off. Ask for the widget in smaller pieces."
            )

    if notes:
        explanation = (explanation + "\n\n" + "\n".join(f"_{n}_" for n in notes)).strip()
    return code, explanation, content, meta


def _llm_credentials(db_client: WorkspaceClient) -> tuple[str, str]:
    """(api_key, host) for the LLM calls a job will make.

    Inference is signed by the app's service principal here for the same reason
    it is in the chat runtime: per-user foundation-model entitlements produced
    403s. No user data passes through it — the widget code and the request are
    the whole payload.
    """
    try:
        host = db_client.config.host
        # Databricks Python SDK encapsulates dynamic tokens (like OAuth/SP) inside authenticate()
        auth_headers_fn = db_client.config.authenticate()
        auth_headers = auth_headers_fn() if callable(auth_headers_fn) else auth_headers_fn
        api_key = auth_headers.get("Authorization", "").replace("Bearer ", "") if auth_headers else ""
        # Some dev setups might not have a token directly accessible, fallback to env
        api_key = api_key or db_client.config.token or os.environ.get("OPENAI_API_KEY") or os.environ.get("DATABRICKS_TOKEN") or "dummy"
        return api_key, host
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI client init failed: {e}")


# The handlers below are plain `def` because each one blocks — on the job table,
# and on the SDK's token fetch — and FastAPI runs those on a thread pool. As
# `async def` they would stall every other request on the worker while they wait.

@router.post("/generate")
def start_generate_widget(req: GenerateRequest, background_tasks: BackgroundTasks,
                          db_client: WorkspaceClient = Depends(get_db_client_sp),
                          user_client: WorkspaceClient = Depends(get_db_client)):
    # Two identities on purpose: the service principal signs inference (see
    # `_llm_credentials`), and the user's own OBO client runs the research tools,
    # so what the studio can read is exactly what Unity Catalog grants this user.
    api_key, host = _llm_credentials(db_client)

    job_id = str(uuid.uuid4())
    generation_jobs.create(job_id, {"status": "pending", "result": None, "error": None, "trace": []})

    # The host, not a URL: this job may call two models on two different routes,
    # so each one derives its own base path. See `_base_url`.
    background_tasks.add_task(run_generation_task, job_id, req, api_key, host, user_client)

    # The studio sizes its own polling from this rather than from a hardcoded
    # number, so raising the limit in Settings is enough — the client used to give
    # up at five minutes no matter what the server was still willing to do.
    return {"job_id": job_id, "timeout_seconds": _widget_timeout()}

@router.post("/review")
def start_review_widget(req: GenerateRequest, background_tasks: BackgroundTasks, db_client: WorkspaceClient = Depends(get_db_client_sp)):
    """Queue a QA pass over code that has just been generated and compiled.

    Deliberately a second request rather than a tail on the generation job: the
    only compiler this app has is the browser's, so the studio is the one that
    knows whether the code it was handed actually builds. Reviewing before that
    would mean auditing code that may not run.

    The job shape is identical to `/generate`, so the studio polls it with the
    same code and a finding that comes back as an edit lands in History like any
    other change.
    """
    api_key, host = _llm_credentials(db_client)
    job_id = str(uuid.uuid4())
    generation_jobs.create(job_id, {"status": "pending", "result": None, "error": None, "trace": []})
    background_tasks.add_task(run_review_task, job_id, req, api_key, host)
    return {"job_id": job_id, "timeout_seconds": _widget_timeout()}


@router.get("/generate/{job_id}")
def get_generate_status(job_id: str):
    # Answered by whichever worker the poll reached; the one running the job
    # writes it through to the table the other reads from.
    job = generation_jobs.snapshot(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/generate/{job_id}")
def stop_generate(job_id: str):
    """Ask a generation to wind down without spending anything more.

    A model call already in flight can't be interrupted, so the job finishes it
    and stops there: a planned run skips its remaining steps, and a single pass
    skips its optional follow-up rounds (`next_llm` answers None). The studio uses
    this two ways. "Stop after this step" keeps polling so the step in flight
    still lands; the composer's Stop button stops listening at once and settles
    the turn itself, so whatever the job finishes after that is never applied.
    Either way the steps already applied are kept — stopping is for "that's
    enough", not "undo it".

    The Stop is recorded on the job's row, so it reaches the job even when this
    request lands on the other worker; the running one checks it between calls.
    """
    job = generation_jobs.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": job.get("status", "running"), "cancelled": True}

def _row_estimate(sql_api, warehouse_id: str, query: str) -> Optional[int]:
    """How many rows the configured query returns, or None if we couldn't find out.

    Deliberately best-effort and short-fused. It is the difference between the
    agent writing a widget that pages in SQL and one that pulls 40,000 rows into
    the browser, but it is not worth failing a data-source test over: a query the
    warehouse won't wrap, or one slow enough to outlast the wait, leaves the
    estimate unknown and the prompt says so.
    """
    from databricks.sdk.service.sql import Disposition

    counted = query.strip().rstrip(";")
    if not counted:
        return None
    # A LIMIT inside the wrapped query is honoured by the count, which is what we
    # want: the widget sees that result set, not the table behind it.
    try:
        statement = sql_api.execute_statement(
            warehouse_id=warehouse_id,
            statement=f"SELECT COUNT(*) AS n FROM (\n{counted}\n) AS _row_estimate",
            wait_timeout="30s",
            disposition=Disposition.INLINE,
        )
        data = statement.result.data_array if statement.result else None
        return int(data[0][0]) if data and data[0] and data[0][0] is not None else None
    except Exception as exc:  # noqa: BLE001 — an unknown count is a supported outcome
        print(f"Could not estimate row count for the configured query: {exc}")
        return None


def extract_schema_from_json(data):
    if isinstance(data, list) and len(data) > 0:
        item = data[0]
        if isinstance(item, dict):
            return {k: type(v).__name__ if v is not None else "string" for k, v in item.items()}
        else:
            return {"value": type(item).__name__}
    elif isinstance(data, dict):
        return {k: type(v).__name__ if v is not None else "string" for k, v in data.items()}
    return {"data": type(data).__name__}

# How much of a tested source's output is kept: enough rows to show formats and
# typical values to the agent and the user, cut short so one wide JSON column
# can't turn every later prompt into a payload.
SAMPLE_ROWS = 5
SAMPLE_CELL_CHARS = 200


def _column_types(manifest) -> Dict[str, str]:
    """Column name to its SQL type, from a statement's manifest.

    Statement Execution returns every value as a string, so the types inferred
    from the values themselves were "str" for everything — telling the agent
    nothing, and suggesting it could compare dates and sum amounts as they came.
    """
    columns = getattr(getattr(manifest, "schema", None), "columns", None) or []
    out: Dict[str, str] = {}
    for col in columns:
        type_name = getattr(col, "type_name", None)
        type_name = getattr(type_name, "value", type_name)
        out[col.name] = str(getattr(col, "type_text", None) or type_name or "STRING").upper()
    return out


def _column_names(manifest) -> List[str]:
    """Every column name in result order, repeats included.

    Not `list(_column_types(...))`: a join can return two `id` columns, the dict
    keeps one, and indexing rows by the shorter list puts each later value under
    the previous column's name.
    """
    columns = getattr(getattr(manifest, "schema", None), "columns", None) or []
    return [col.name for col in columns]


def _sample_rows(columns: List[str], data_array) -> List[Dict[str, Any]]:
    """The first few rows as dicts, long values cut."""
    rows: List[Dict[str, Any]] = []
    for row in (data_array or [])[:SAMPLE_ROWS]:
        record: Dict[str, Any] = {}
        for i, name in enumerate(columns):
            value = row[i] if i < len(row) else None
            if isinstance(value, str) and len(value) > SAMPLE_CELL_CHARS:
                value = value[: SAMPLE_CELL_CHARS - 1] + "…"
            record[name] = value
        rows.append(record)
    return rows


def _probe_statement(query: str) -> str:
    """The configured query, bounded to a few rows where it can be.

    Only a query can be wrapped; SHOW and DESCRIBE run as written. The newline
    before the closing parenthesis keeps a trailing `-- comment` from swallowing
    it.
    """
    words = re.findall(r"[a-z]+", sql_safety.strip_noise(query).lower())
    if words and words[0] in ("select", "with", "values", "table"):
        return f"SELECT * FROM (\n{query}\n) AS _schema_probe LIMIT {SAMPLE_ROWS}"
    return query


@router.post("/datasource/test")
def test_datasource(req: DataSourceTestRequest, db_client: WorkspaceClient = Depends(get_db_client)):
    """Run the configured data source once, as the signed-in user.

    OBO like every other data path, so the test shows exactly what the widget
    will see: a table this user can't read fails here rather than working in the
    studio and 403ing in the view. SQL is classified first and only a read is
    run — the test is a probe, and a MERGE typed into this box must not execute
    just because someone pressed Test.

    A plain `api` source is not fetched here. The widget will fetch it from the
    browser, so the browser is the only place a test means anything (CORS,
    the user's own session), and a server that fetches any URL it is handed is
    a way into the network it runs on.
    """
    if req.data_source_type == "api":
        raise HTTPException(
            status_code=400,
            detail="External APIs are tested from your browser, the way the widget will call them.",
        )
    elif req.data_source_type == "databricks_api":
        try:
            import requests
            from routes.databricks_api import _auth_headers, _error_detail, _response_data

            path = req.data_source
            if not path.startswith('/'):
                path = '/' + path

            # Use a direct HTTP response here so the SDK cannot replace a useful
            # non-JSON 4xx body with its generic "unable to parse response" error.
            url = f"{db_client.config.host.rstrip('/')}{path}"
            response = requests.get(url, headers=_auth_headers(db_client), timeout=90)
            data = _response_data(response)
            if not response.ok:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Databricks API request failed: {_error_detail(response, data)}",
                )

            schema = extract_schema_from_json(data)
            return {"schema": schema, "sample": data[:SAMPLE_ROWS] if isinstance(data, list) else data}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Databricks API request failed: {e}")
    elif req.data_source_type == "sql":
        query = req.data_source.strip().rstrip(";").strip()
        kind, verb = sql_safety.classify_statement(query)
        if kind == "empty":
            raise HTTPException(status_code=400, detail="Enter a SQL statement to test.")
        if kind == "write":
            # Not an error: an executable widget legitimately has a write as its
            # source. There is simply nothing a test can safely learn from it.
            return {
                "schema": None,
                "sample": [],
                "row_estimate": None,
                "note": (
                    f"This statement changes data ({(verb or 'write').upper()}), so it was not run. "
                    "Only read statements are tested; the widget's own action runs the write, "
                    "with its confirmation prompt."
                ),
            }
        try:
            from databricks.sdk.service.sql import StatementExecutionAPI, Disposition

            sql_api = StatementExecutionAPI(db_client.api_client)
            warehouse_id = os.environ.get("SQL_WAREHOUSE_ID", "")
            if not warehouse_id:
                raise HTTPException(status_code=500, detail="No SQL Warehouse ID configured. Set SQL_WAREHOUSE_ID in environment.")

            statement = sql_api.execute_statement(
                warehouse_id=warehouse_id,
                statement=_probe_statement(query),
                wait_timeout="50s",
                disposition=Disposition.INLINE,
            )
            state = getattr(getattr(statement, "status", None), "state", None)
            state_name = getattr(state, "value", state)
            if state_name in ("PENDING", "RUNNING"):
                raise HTTPException(
                    status_code=400,
                    detail="SQL Query failed: still running after 50 seconds. Test a narrower "
                           "query, or check the warehouse is running.",
                )
            if state_name and state_name != "SUCCEEDED":
                error = getattr(getattr(statement, "status", None), "error", None)
                message = getattr(error, "message", None) or f"the statement ended {state_name}"
                raise HTTPException(status_code=400, detail=f"SQL Query failed: {message}")

            schema = _column_types(statement.manifest)
            rows = _sample_rows(_column_names(statement.manifest),
                                statement.result.data_array if statement.result else None)
            return {
                "schema": schema,
                "sample": rows,
                "row_estimate": _row_estimate(sql_api, warehouse_id, query),
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"SQL Query failed: {e}")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown data source type: {req.data_source_type}")
