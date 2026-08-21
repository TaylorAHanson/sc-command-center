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
from services import llm_params, native_files
from services.settings_store import base_path_for_model, get_int_setting, get_setting
from services.llm_client import DatabricksChatOpenAI, chat_client, reply_text
from services.upload_tools import attachments_prompt

# LangChain imports
from langchain_core.tools import tool
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

# Store for generation jobs. In a real app, use Redis or DB, but in-memory is fine for this tool.
generation_jobs: Dict[str, Any] = {}

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

    # The user's own choices win; don't even return a competing suggestion.
    for key in req.locked_settings:
        meta.pop(key, None)

    return meta, remainder


# Above this, a widget that fetches everything and works in the browser is the
# wrong shape: the payload is slow to arrive, the tab holds all of it, and sorting
# or filtering it in JavaScript re-does work the warehouse is built for. Below it,
# pushing every interaction back to SQL costs a round trip per keystroke to solve
# a problem that doesn't exist yet. The number is a judgement rather than a
# measurement, chosen because a few thousand rows of a handful of columns is still
# a fraction of a megabyte.
CLIENT_SIDE_ROW_CEILING = 2000


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
            "component. Never fetch a whole table in order to reduce it in JavaScript."
        )

    if rows <= CLIENT_SIDE_ROW_CEILING:
        return (
            f"\n\nThis query returns about {rows:,} rows, which is small enough to fetch "
            "in one go. Sort, filter and page in the component over the rows you already "
            "have — a round trip per keystroke would be slower, not faster. Still cap the "
            "rows you render at once and keep the query's own `WHERE` doing the coarse work."
        )

    return (
        f"\n\nThis query returns about {rows:,} rows. **Do the work in the database, not "
        "the browser.** Compose the SQL for `props.data.dataSource` per interaction and "
        "re-query:\n"
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
        "Wrap the configured query rather than editing it — "
        "`SELECT * FROM (<props.data.dataSource>) AS t WHERE … ORDER BY … LIMIT … OFFSET …` "
        "— so the user's own SQL keeps working. Show a loading state on each re-query and "
        "keep the previous page visible while the next one arrives."
    )


def _build_system_prompt(req: GenerateRequest) -> str:
    import json

    try:
        instructions_path = os.path.join(os.path.dirname(__file__), "agent_instructions.md")
        with open(instructions_path, "r") as f:
            system_prompt = f.read()
    except Exception as e:
        print(f"Failed to load agent instructions: {e}")
        system_prompt = "You are an expert React developer."

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

    if req.configuration_mode != "none" and req.config_schema:
        config_schema_str = json.dumps(req.config_schema, indent=2)
        system_prompt += f"\n\nThe user has configured the following dynamic configuration inputs for this widget:\n```json\n{config_schema_str}\n```\nYou MUST expect these exact keys in `props.data` (e.g. `props.data.myKey`). Provide reasonable fallback values if they are undefined or empty. Do NOT hardcode colors/text if a dynamic config key exists for it."

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

    return system_prompt


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
    """The endpoint for the cheap side-calls, falling back to the main one."""
    return get_setting("widget_helper_model") or get_setting("widget_model")


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


def _turn_message(model: str, env: str, prompt: str, attachments: List[Dict[str, Any]]) -> HumanMessage:
    """This turn's message, carrying any files the model can read for itself.

    A screenshot is the case that matters: there is no text in it to extract, so
    "the header is misaligned" only means something if the picture travels with
    it. `native_files` decides the content-part shape per provider.
    """
    parts = native_files.parts(model, env, attachments)
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


def _refine_prompt(ask_helper, req: GenerateRequest) -> str:
    """The request, restated concretely. Returns `""` to use it as written.

    Widget requests arrive as asides — "make it better", "the table is slow, also
    the colours" — and the generation model spends its first and most expensive
    call working out what was meant. A small model can do that for a fraction of
    the time, against the code that is actually open. Anything unexpected in the
    reply means the original prompt is used, which is what happened before.
    """
    prompt = (req.prompt or "").strip()
    if not prompt or req.error_log:
        return ""  # a compile error is already precise; rewriting it loses detail

    code = req.current_code or ""
    reply = ask_helper([HumanMessage(content=(
        "Restate this Widget Studio request as an instruction to a developer. Keep "
        "every thing it asks for and add nothing it does not: you are removing "
        "ambiguity, not designing. Name the parts of the code involved where the "
        "request is vague about them. If it is already clear and specific, reply "
        "with it unchanged.\n\n"
        f"Request:\n{prompt}\n\n"
        + (f"The widget being changed:\n```tsx\n{code[:6000]}\n```\n\n" if code.strip() else "")
        + 'Reply with nothing but JSON: {"request": "..."}'
    ))])

    refined = str(_json_reply(reply, "refined request").get("request") or "").strip()
    # A refinement that dropped most of the request, or ballooned into a design
    # document, has stopped being a restatement. Both have been seen; neither is
    # worth handing to the generation model in place of what the user wrote.
    if not refined or refined == prompt:
        return ""
    if len(refined) < len(prompt) // 2 or len(refined) > max(1200, len(prompt) * 6):
        return ""
    return refined


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


def _json_reply(reply: str, what: str) -> Dict[str, Any]:
    """The JSON object in a reply, or `{}` if there isn't a readable one.

    Every cheap side-call in this module — planning, refining, deciding whether to
    ask a question, reviewing — asks for JSON and must tolerate not getting it: a
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
    job = generation_jobs.get(job_id)
    if job is not None:
        job.update(fields)


# How much narration one job may accumulate. A run cannot produce many of these —
# there is one per decision, not one per token — but a bound keeps a wedged job
# from growing without limit in a dict that lives for the process.
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


def _settle(job_id: str, **fields) -> None:
    """Replace the job with its final state, keeping the narration.

    The completion paths deliberately assign a whole new dict rather than
    updating in place, so that a stale `stage_code` or `error` from mid-run can't
    survive into the result. The trace has to be carried across by hand for that
    reason — it is the one field whose value is the whole history.
    """
    previous = generation_jobs.get(job_id) or {}
    generation_jobs[job_id] = {"trace": previous.get("trace", []), **fields}


def _run_stages(job_id: str, req: GenerateRequest, stages: List[Dict[str, str]],
                ask, next_llm, budget: "_Budget") -> None:
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
        job = generation_jobs.get(job_id) or {}
        if job.get("cancelled"):
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
        stage_system = _build_system_prompt(staged_req)

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


def run_generation_task(job_id: str, req: GenerateRequest, api_key: str, host: str):
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
            if not budget.has(HELPER_SECONDS + 10):
                return ""
            try:
                def attempt(params: Dict[str, Any]) -> str:
                    llm = _widget_llm(api_key, helper_base_url, helper_name, budget,
                                      params, HELPER_SECONDS)
                    return reply_text(llm.invoke(messages))

                return llm_params.with_adaptation(
                    helper_name, attempt,
                    max_tokens=HELPER_MAX_TOKENS,
                    params_fn=llm_params.langchain_params,
                )
            except Exception as exc:  # noqa: BLE001 — an optional step, by design
                _trace(job_id, f"skipped a quick check ({helper_name} said: {exc})")
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

        refined = _refine_prompt(ask_helper, req)
        if refined:
            _trace(job_id, f"read the request as: {refined}")
        prompt = refined or req.prompt
        working = req.model_copy(update={"prompt": prompt})

        system_prompt = _build_system_prompt(working)
        lc_history = _compact_history(ask_helper, req.history)
        # Files the user attached ride on this turn's message only, so re-sending
        # never compounds them across a conversation.
        attachments = _attachments(req)
        turn = _turn_message(model_name, req.env, prompt, attachments)
        if attachments:
            _trace(job_id, "reading " + ", ".join(a.get("filename") or "a file" for a in attachments))
            system_prompt += "\n\n" + attachments_prompt(attachments)

        # The first call is where a parameter the endpoint refuses shows up, so it
        # runs under `with_adaptation`: the offending parameter is dropped and the
        # call retried, and every later call in this job inherits the lesson.
        def generate(params: Dict[str, Any]):
            llm = _widget_llm(api_key, base_url, model_name, budget, params)
            agent = create_react_agent(model=llm, tools=[search_widgets], prompt=system_prompt)
            return agent.invoke({"messages": lc_history + [turn]})

        # Every follow-up round asks for a client here, and gets None once the
        # allowance is spent — so a generation that runs long returns the work it
        # managed rather than dying on a timeout with nothing to show.
        def next_llm() -> Optional[DatabricksChatOpenAI]:
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

        # A request asking for several things at once is planned and applied a step
        # at a time: each call is small enough to finish, progress is visible, and
        # what lands stays landed. One instruction still goes straight to the model.
        if _wants_stages(working):
            stages = _plan_stages(ask, system_prompt, prompt)
            if stages:
                _trace(job_id, "planned this in "
                       + ", ".join(f"{i + 1}) {s['title']}" for i, s in enumerate(stages)))
                _run_stages(job_id, working, stages, ask, next_llm, budget)
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
            reply_text(last_message), truncated, req.current_code or "", working,
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


def _review_instruction(req: GenerateRequest) -> str:
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
    budget = _Budget(min(REVIEW_SECONDS, _widget_timeout()))
    code = req.current_code or ""
    try:
        if not code.strip():
            _settle(job_id, status="completed", result={"code": None, "explanation": "", "raw": "", "settings": {}})
            return

        model_name = get_setting("widget_model")
        base_url = _base_url(host, model_name)
        system_prompt = _build_system_prompt(req)
        instruction = _review_instruction(req)
        _trace(job_id, "reviewing the widget against what you asked for")

        def next_llm() -> Optional[DatabricksChatOpenAI]:
            if not budget.has(15):
                return None
            return _widget_llm(api_key, base_url, model_name, budget)

        def attempt(params: Dict[str, Any]) -> str:
            llm = _widget_llm(api_key, base_url, model_name, budget, params)
            return reply_text(llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=instruction),
            ]))

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


@router.post("/generate")
async def start_generate_widget(req: GenerateRequest, background_tasks: BackgroundTasks, db_client: WorkspaceClient = Depends(get_db_client_sp)):
    api_key, host = _llm_credentials(db_client)

    job_id = str(uuid.uuid4())
    generation_jobs[job_id] = {"status": "pending", "result": None, "error": None, "trace": []}

    # The host, not a URL: this job may call two models on two different routes,
    # so each one derives its own base path. See `_base_url`.
    background_tasks.add_task(run_generation_task, job_id, req, api_key, host)

    # The studio sizes its own polling from this rather than from a hardcoded
    # number, so raising the limit in Settings is enough — the client used to give
    # up at five minutes no matter what the server was still willing to do.
    return {"job_id": job_id, "timeout_seconds": _widget_timeout()}

@router.post("/review")
async def start_review_widget(req: GenerateRequest, background_tasks: BackgroundTasks, db_client: WorkspaceClient = Depends(get_db_client_sp)):
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
    generation_jobs[job_id] = {"status": "pending", "result": None, "error": None, "trace": []}
    background_tasks.add_task(run_review_task, job_id, req, api_key, host)
    return {"job_id": job_id, "timeout_seconds": _widget_timeout()}


@router.get("/generate/{job_id}")
async def get_generate_status(job_id: str):
    if job_id not in generation_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return generation_jobs[job_id]


@router.delete("/generate/{job_id}")
async def stop_generate(job_id: str):
    """Stop a staged run after its current step.

    Only meaningful for a planned run, which checks between steps; a single-pass
    generation has nothing to stop between. The steps already applied are kept —
    stopping is for "that's enough", not "undo it".
    """
    job = generation_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job["cancelled"] = True
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
            statement=f"SELECT COUNT(*) AS n FROM ({counted}) AS _row_estimate",
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

@router.post("/datasource/test")
async def test_datasource(req: DataSourceTestRequest, db_client: WorkspaceClient = Depends(get_db_client_sp)):
    import httpx
    if req.data_source_type == "api":
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(req.data_source)
                res.raise_for_status()
                data = res.json()
                schema = extract_schema_from_json(data)
                return {"schema": schema, "sample": data[:2] if isinstance(data, list) else data}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"API request failed: {e}")
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
            return {"schema": schema, "sample": data[:2] if isinstance(data, list) else data}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Databricks API request failed: {e}")
    elif req.data_source_type == "sql":
        try:
            from databricks.sdk.service.sql import StatementExecutionAPI, Disposition
            import os

            sql_api = StatementExecutionAPI(db_client.api_client)
            warehouse_id = os.environ.get("SQL_WAREHOUSE_ID", "")
            if not warehouse_id:
                raise HTTPException(status_code=500, detail="No SQL Warehouse ID configured. Set SQL_WAREHOUSE_ID in environment.")

            # For schema detection, apply LIMIT 1 if no LIMIT clause already present
            schema_query = req.data_source.strip().rstrip(";")
            if not re.search(r'\bLIMIT\b', schema_query, re.IGNORECASE):
                schema_query = f"SELECT * FROM ({schema_query}) AS _schema_probe LIMIT 1"

            statement = sql_api.execute_statement(
                warehouse_id=warehouse_id,
                statement=schema_query,
                wait_timeout="50s",
                disposition=Disposition.INLINE,
            )

            columns = []
            rows = []

            if statement.manifest and statement.manifest.schema and statement.manifest.schema.columns:
                columns = [col.name for col in statement.manifest.schema.columns]

            if statement.result and statement.result.data_array:
                for row_data in statement.result.data_array[:5]:
                    row_dict = {}
                    for i, col_name in enumerate(columns):
                        row_dict[col_name] = row_data[i] if i < len(row_data) else None
                    rows.append(row_dict)

            schema = {col: type(rows[0].get(col)).__name__ if rows and rows[0].get(col) is not None else "string" for col in columns}
            return {
                "schema": schema,
                "sample": rows,
                "row_estimate": _row_estimate(sql_api, warehouse_id, req.data_source),
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"SQL Query failed: {e}")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown data source type: {req.data_source_type}")
