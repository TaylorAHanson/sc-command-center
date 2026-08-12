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
    looks_truncated,
    parse_edits,
    sloc,
    strip_edit_blocks,
)
from services import llm_params
from services.settings_store import base_path_for_model, get_int_setting, get_setting
from services.llm_client import DatabricksChatOpenAI, chat_client, reply_text

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

class DataSourceTestRequest(BaseModel):
    data_source_type: str
    data_source: str

# A response that gets cut off mid-file is the classic failure for large widgets.
# When we detect one we ask the model to carry on from where it stopped rather
# than starting over, which would just hit the same ceiling.
MAX_CONTINUATIONS = int(os.environ.get("WIDGET_AGENT_MAX_CONTINUATIONS", "3"))

_META_BLOCK_RE = re.compile(r"```widget-meta[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)

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
        system_prompt += (
            f"\n\nHere is the CURRENT state of the widget code:\n```tsx\n{req.current_code}\n```\n"
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


def _continue_truncated(next_llm, system_prompt: str, user_prompt: str, content: str) -> str:
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
        print(f"Widget generation looks truncated; requesting continuation {round_no + 1}")
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
                 base_code: str, new_code: str) -> tuple[Optional[str], List[str]]:
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
        print(f"Whole-file reply is a large shrink: {risk.reason}")
        return new_code, [
            f"This replaced the entire widget — {risk.reason}. "
            "If that wasn't what you wanted, open History in the TSX Editor toolbar and restore the previous version."
        ]

    print(f"Whole-file reply refused: {risk.reason}")
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


def _wants_stages(req: GenerateRequest) -> bool:
    """Whether this request is big enough to be worth planning first."""
    prompt = (req.prompt or "").strip()
    if req.error_log:
        return False  # fixing a compile error is one job, however long the error is
    if len(prompt) >= 240:
        return True
    return sum(1 for hint in _STAGE_HINTS if hint in prompt.lower()) >= 2


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

    try:
        text = reply
        start, end = text.find("{"), text.rfind("}")
        parsed = json.loads(text[start:end + 1]) if start >= 0 < end else {}
        steps = parsed.get("steps") or []
    except (ValueError, AttributeError) as exc:
        print(f"Widget generation plan could not be read ({exc}); answering in one pass")
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
            summary.append(
                f"Ran out of time after {applied} of {len(stages)} steps ({budget.spent}s). "
                "The steps that finished are applied — ask me to carry on, or raise the "
                "widget generation timeout in Admin Panel → Settings."
            )
            break

        stage["status"] = "running"
        _publish(job_id, stages=stages)

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
                next_llm, stage_system, prompt_for_stage, budget,
            )
        except Exception as exc:  # noqa: BLE001 — one step failing must not end the run
            print(f"Widget generation step {index + 1} failed: {exc}")
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

    generation_jobs[job_id] = {
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
    }


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


def run_generation_task(job_id: str, req: GenerateRequest, api_key: str, base_url: str):
    budget = _Budget(_widget_timeout())
    try:
        # Admin-settable (Admin Panel → Settings), falling back to LLM_MODEL.
        model_name = get_setting("widget_model")
        system_prompt = _build_system_prompt(req)

        # Limit history to the last 6 messages to avoid massive context payloads causing timeouts
        history_to_keep = req.history[-6:] if len(req.history) > 6 else req.history
        lc_history = []
        for msg in history_to_keep:
            if msg.role == 'user':
                lc_history.append(HumanMessage(content=msg.content))
            elif msg.role in ('assistant', 'system'):
                lc_history.append(AIMessage(content=msg.content))

        # The first call is where a parameter the endpoint refuses shows up, so it
        # runs under `with_adaptation`: the offending parameter is dropped and the
        # call retried, and every later call in this job inherits the lesson.
        def generate(params: Dict[str, Any]):
            llm = _widget_llm(api_key, base_url, model_name, budget, params)
            agent = create_react_agent(model=llm, tools=[search_widgets], prompt=system_prompt)
            return agent.invoke({"messages": lc_history + [HumanMessage(content=req.prompt)]})

        # Every follow-up round asks for a client here, and gets None once the
        # allowance is spent — so a generation that runs long returns the work it
        # managed rather than dying on a timeout with nothing to show.
        def next_llm() -> Optional[DatabricksChatOpenAI]:
            if not budget.has(15):
                print(f"Widget generation budget spent after {budget.spent}s; skipping follow-up round")
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
        if _wants_stages(req):
            stages = _plan_stages(ask, system_prompt, req.prompt)
            if stages:
                print(f"Widget generation planned in {len(stages)} steps")
                _run_stages(job_id, req, stages, ask, next_llm, budget)
                return
            # No plan, and planning took the allowance with it. Starting a one-pass
            # generation now would spend the rest arriving at the same timeout with
            # nothing to show, so say what happened while it can still be read.
            if not budget.has(MIN_ONE_PASS_SECONDS):
                generation_jobs[job_id] = {"status": "failed", "error": (
                    f"Planning this request used the {budget.total}s allowed for it, leaving no "
                    "time to build anything. Ask for one part of the widget at a time, or raise "
                    "the widget generation timeout in Admin Panel → Settings."
                )}
                return

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
            next_llm, system_prompt, req.prompt, budget,
        )

        generation_jobs[job_id] = {
            "status": "completed",
            "result": {
                "code": code,
                "explanation": explanation,
                "raw": content,
                "settings": meta,
            }
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        generation_jobs[job_id] = {"status": "failed", "error": _failure_text(e, budget)}


def _apply_reply(reply: str, truncated: bool, base_code: str, req: GenerateRequest,
                 next_llm, system_prompt: str, user_prompt: str,
                 budget: "_Budget") -> tuple[Optional[str], str, str, Dict[str, Any]]:
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
            content = _continue_truncated(next_llm, system_prompt, user_prompt, content)
        code, explanation = extract_code_block(content)
        if code:
            # Failsafe cleanup of any lingering backticks just in case
            code = re.sub(r'^```[a-zA-Z]*\n?', '', code)
            code = re.sub(r'\n?```$', '', code)
            if base_code.strip():
                # Editing, not creating: whatever this block holds is about to
                # become the whole widget, so make sure it is one.
                code, vet_notes = _vet_rewrite(next_llm, system_prompt, user_prompt, content,
                                               base_code, code)
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


@router.post("/generate")
async def start_generate_widget(req: GenerateRequest, background_tasks: BackgroundTasks, db_client: WorkspaceClient = Depends(get_db_client_sp)):
    # Use the WorkspaceClient config to initialize the OpenAI client securely
    try:
        host = db_client.config.host
        
        # Databricks Python SDK encapsulates dynamic tokens (like OAuth/SP) inside authenticate()
        auth_headers_fn = db_client.config.authenticate()
        auth_headers = auth_headers_fn() if callable(auth_headers_fn) else auth_headers_fn
        api_key = auth_headers.get("Authorization", "").replace("Bearer ", "") if auth_headers else ""
        
        # Some dev setups might not have a token directly accessible, fallback to env
        api_key = api_key or db_client.config.token or os.environ.get("OPENAI_API_KEY") or os.environ.get("DATABRICKS_TOKEN") or "dummy"
        # Base path follows the configured model: `system.ai.…` names only resolve
        # on the AI Gateway route, plain endpoint names only on /serving-endpoints.
        base_path = base_path_for_model(get_setting("widget_model"))
        base_url = f"{host}{base_path}" if host else os.environ.get("OPENAI_BASE_URL", "https://adb-1234.1.azuredatabricks.net/serving-endpoints")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI client init failed: {e}")
        
    job_id = str(uuid.uuid4())
    generation_jobs[job_id] = {"status": "pending", "result": None, "error": None}
    
    background_tasks.add_task(run_generation_task, job_id, req, api_key, base_url)

    # The studio sizes its own polling from this rather than from a hardcoded
    # number, so raising the limit in Settings is enough — the client used to give
    # up at five minutes no matter what the server was still willing to do.
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
            return {"schema": schema, "sample": rows}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"SQL Query failed: {e}")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown data source type: {req.data_source_type}")
