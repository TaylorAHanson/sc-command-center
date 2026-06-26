"""Agent Studio — profile/skill CRUD + AI-assisted authoring.

This router powers the Command Center's Agent Studio: a place to author **agent
profiles** (an ``AGENT.md`` + ``skills/*.md``) that the consolidated agent
runtime later loads and runs. Storage lives entirely on Unity Catalog Volumes /
the user's Workspace folder (see ``agent_studio_store``) — Unity Catalog governs
visibility and edit rights, so every storage call is made under the caller's OBO
token.

Two surfaces:

  * **CRUD** (``/profiles*``, ``/locations``) — list/read/save/delete profiles,
    delegated to :class:`AgentStudioStore`, scoped by OBO.
  * **Authoring** (``/tools``, ``/generate``, ``/generate/{job_id}``) — an
    AI-assisted draft loop. A Claude (sonnet) agent proposes an ``AGENT.md`` +
    skills, *grounded* in (a) the tools actually exposed by the Unity Catalog AI
    Gateway MCP and (b) live schema probes against SQL/Genie. It returns a draft
    plus a structured **Review** so the author can see suggested tools, missing
    capabilities, ambiguities, and schema confirmations before saving.

The LLM call uses the app Service Principal (it must reach the serving
endpoint), while tool discovery and schema probes use the user's OBO token so
the Review reflects what *this user* can actually see and run.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from databricks.sdk import WorkspaceClient

from middleware.auth import get_db_client_sp, get_user_token, require_auth
from agent_studio_store import (
    AgentStudioError,
    ProfileConflictError,
    STORE_VOLUME,
    STORE_WORKSPACE,
    get_agent_studio_store,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _job_ttl_s() -> int:
    try:
        return int(os.environ.get("AGENT_STUDIO_JOB_TTL_S", "1800"))
    except ValueError:
        return 1800


def _job_max() -> int:
    try:
        return int(os.environ.get("AGENT_STUDIO_JOB_MAX", "200"))
    except ValueError:
        return 200


class _JobStore:
    """Bounded, TTL-evicting, thread-safe store for authoring jobs.

    Drop-in dict-like (``store[id] = {...}``, ``id in store``, ``store[id]``).
    Replaces a plain dict that grew unbounded and never expired. Still
    process-local: with multiple app replicas a poll may hit a replica that did
    not run the job, so callers treat a missing job as "not found". For
    cross-replica durability move this to a shared backend (e.g. Lakebase).
    """

    def __init__(self, ttl_s: int, max_jobs: int) -> None:
        self._ttl = ttl_s
        self._max = max_jobs
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _evict_locked(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._jobs.items() if now - v.get("_ts", now) > self._ttl]
        for k in expired:
            self._jobs.pop(k, None)
        if len(self._jobs) > self._max:
            overflow = sorted(self._jobs.items(), key=lambda kv: kv[1].get("_ts", 0))
            for k, _ in overflow[: len(self._jobs) - self._max]:
                self._jobs.pop(k, None)

    def __setitem__(self, job_id: str, value: Dict[str, Any]) -> None:
        with self._lock:
            stamped = dict(value)
            stamped["_ts"] = time.monotonic()
            self._jobs[job_id] = stamped
            self._evict_locked()

    def __contains__(self, job_id: str) -> bool:
        with self._lock:
            self._evict_locked()
            return job_id in self._jobs

    def __getitem__(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            v = self._jobs[job_id]
            return {k: val for k, val in v.items() if k != "_ts"}


# Authoring jobs (in-memory, bounded + TTL-evicted).
authoring_jobs = _JobStore(ttl_s=_job_ttl_s(), max_jobs=_job_max())


# --------------------------------------------------------------------- models

class SkillPayload(BaseModel):
    slug: Optional[str] = None
    name: str
    description: str = ""
    content: str = ""


class PythonToolPayload(BaseModel):
    slug: Optional[str] = None
    name: str
    description: str = ""
    code: str = ""


class SaveProfileRequest(BaseModel):
    name: str
    prompt: str
    description: str = ""
    model: str = ""
    tools: List[str] = []
    skills: Optional[List[SkillPayload]] = None
    python_tools: Optional[List[PythonToolPayload]] = None
    store: str = STORE_VOLUME
    base_path: Optional[str] = None
    profile_id: Optional[str] = None
    # Optimistic-concurrency token: the ``updated_at`` the client last loaded.
    # When present on an update, the save is refused (409) if the stored profile
    # has since changed.
    expected_updated_at: Optional[str] = None


class AuthorMessage(BaseModel):
    role: str
    content: str


class AuthorRequest(BaseModel):
    prompt: str
    history: List[AuthorMessage] = []
    current_prompt: Optional[str] = None        # existing AGENT.md body, if editing
    current_skills: Optional[List[SkillPayload]] = None
    current_python_tools: Optional[List[PythonToolPayload]] = None
    confirm_schema: bool = True                 # run live SQL/Genie probes


class PromoteRequest(BaseModel):
    profile_id: str
    target_store: str = STORE_VOLUME
    target_base_path: str


# ------------------------------------------------------------------ MCP tools

def _mcp_server_urls(host: str) -> List[str]:
    """Resolve the AI Gateway MCP server URLs to introspect.

    Configurable via ``AGENT_STUDIO_MCP_SERVERS`` (comma-separated). Entries may
    be absolute URLs or workspace-relative paths (joined to ``host``). Defaults
    to the managed SQL MCP server **and** the general Genie MCP server
    (``/api/2.0/mcp/genie``), which searches across the caller's accessible
    Genie spaces — restored after a refactor dropped it.
    """
    raw = os.environ.get("AGENT_STUDIO_MCP_SERVERS", "/api/2.0/mcp/sql,/api/2.0/mcp/genie")
    urls: List[str] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if entry.startswith("http://") or entry.startswith("https://"):
            urls.append(entry.rstrip("/"))
        elif host:
            urls.append(f"{host.rstrip('/')}/{entry.lstrip('/')}")
    return urls


def discover_mcp_tools(ws: WorkspaceClient) -> List[Dict[str, Any]]:
    """List tools exposed by the configured AI Gateway MCP servers under OBO.

    Degrades gracefully: a missing ``databricks-mcp`` package or an unreachable
    server yields a partial/empty catalog rather than failing the request.
    """
    host = ""
    try:
        host = ws.config.host or ""
    except Exception:  # noqa: BLE001
        host = os.environ.get("DATABRICKS_HOST", "")

    try:
        from databricks_mcp import DatabricksMCPClient
    except Exception as exc:  # noqa: BLE001
        logger.warning("databricks-mcp not installed; tool discovery disabled: %s", exc)
        return []

    out: List[Dict[str, Any]] = []
    for server_url in _mcp_server_urls(host):
        label = _server_label(server_url)
        try:
            client = DatabricksMCPClient(server_url=server_url, workspace_client=ws)
            for tool in client.list_tools():
                name = getattr(tool, "name", None) or ""
                if not name:
                    continue
                out.append(
                    {
                        # Canonical, server-qualified identifier authored profiles
                        # store (``<server>/<tool>``). Unambiguous when two servers
                        # expose the same tool name; the runtime matches on this id
                        # or, as a fallback, the bare ``name`` suffix.
                        "id": f"{label}/{name}",
                        "name": name,
                        "server_label": label,
                        "description": getattr(tool, "description", "") or "",
                        "server": server_url,
                        "input_schema": getattr(tool, "inputSchema", None)
                        or getattr(tool, "input_schema", None)
                        or {},
                    }
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP list_tools failed for %s: %s", server_url, exc)
    return out


def _server_label(server_url: str) -> str:
    """Short, stable label for an MCP server URL, used to qualify tool ids.

    Mirrors the managed MCP URL shapes (``/api/2.0/mcp/<kind>[/...]``): we take
    the path segments after ``mcp`` and join them, so
    ``/api/2.0/mcp/functions/main/sales`` -> ``functions.main.sales`` and
    ``/api/2.0/mcp/sql`` -> ``sql``. Falls back to the host for odd URLs.
    """
    s = (server_url or "").rstrip("/")
    s = re.sub(r"^https?://[^/]+", "", s)  # strip scheme+host
    parts = [p for p in s.split("/") if p]
    if "mcp" in parts:
        tail = parts[parts.index("mcp") + 1:]
        if tail:
            return ".".join(tail)
    return parts[-1] if parts else "mcp"


def _python_sandbox_timeout() -> int:
    try:
        return int(os.environ.get("AGENT_STUDIO_PY_SANDBOX_TIMEOUT", "6"))
    except ValueError:
        return 6


def _run_python_sandbox(code: str, timeout_s: int = 6) -> Dict[str, Any]:
    """Execute a short Python snippet in an isolated subprocess.

    This is a *validation* sandbox for authoring, not a hardened jail. It runs
    a fresh interpreter in isolated mode (``-I``: ignores PYTHON* env vars and
    user site-packages) with a **credential-free environment** (no DATABRICKS_*,
    PG*, tokens, secrets — only a minimal PATH/HOME), a wall-clock timeout, and
    (on POSIX) CPU + address-space rlimits. It lets the authoring assistant
    confirm an author's Python tool imports, runs, and returns sane output
    without exposing the app's credentials or hanging the request.
    """
    import subprocess
    import sys
    import tempfile

    if not (code or "").strip():
        return {"exit_code": -1, "stdout": "", "stderr": "No code provided."}

    safe_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    preexec = None
    if os.name == "posix":
        def _apply_limits() -> None:  # pragma: no cover - child process
            try:
                import resource
                resource.setrlimit(resource.RLIMIT_CPU, (timeout_s, timeout_s + 1))
                mem = 512 * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
                resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))  # no file writes
            except Exception:
                pass
        preexec = _apply_limits

    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=safe_env,
            cwd=tempfile.gettempdir(),
            preexec_fn=preexec,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": f"Timed out after {timeout_s}s."}
    except Exception as exc:  # noqa: BLE001
        return {"exit_code": -1, "stdout": "", "stderr": f"Sandbox error: {exc}"}


def _probe_sql_schema(ws: WorkspaceClient, sql: str) -> Dict[str, Any]:
    """Run a bounded ``LIMIT 1`` probe to confirm a query/table shape under OBO."""
    from databricks.sdk.service.sql import Disposition, StatementExecutionAPI

    warehouse_id = os.environ.get("SQL_WAREHOUSE_ID", "")
    if not warehouse_id:
        return {"error": "No SQL_WAREHOUSE_ID configured."}
    query = (sql or "").strip().rstrip(";")
    if not query:
        return {"error": "Empty query."}
    if not re.search(r"\bLIMIT\b", query, re.IGNORECASE):
        query = f"SELECT * FROM ({query}) AS _schema_probe LIMIT 1"
    try:
        sql_api = StatementExecutionAPI(ws.api_client)
        stmt = sql_api.execute_statement(
            warehouse_id=warehouse_id,
            statement=query,
            wait_timeout="50s",
            disposition=Disposition.INLINE,
        )
        columns: List[str] = []
        if stmt.manifest and stmt.manifest.schema and stmt.manifest.schema.columns:
            columns = [c.name for c in stmt.manifest.schema.columns]
        return {"columns": columns}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


# ------------------------------------------------------------ authoring agent

AUTHORING_SYSTEM_PROMPT = """\
You are the Agent Studio authoring assistant for an enterprise data platform.
Your job is to help an author design ONE agent profile: a system prompt
(AGENT.md body) plus a small set of single-file markdown skills.

Hard rules:
- Agents can ONLY use tools exposed by the Unity Catalog AI Gateway MCP. Before
  recommending any tool, call `list_available_tools` and choose ONLY from the
  returned names. Never invent tool names. If a needed capability is missing,
  record it under `review.missing` instead of pretending it exists.
- When the agent will query data, confirm the relevant schema with
  `probe_sql_schema` and reflect the confirmed columns in the prompt/skills.
  Record each probe under `review.schema_checks`.
- Skills are SINGLE markdown files. Keep each focused; do not invent folders or
  multi-file skills.
- Prefer reusing/clarifying the author's existing prompt and skills when editing.

Handling ambiguity:
- Do NOT block on missing detail. Make a reasonable, explicitly-stated
  assumption, build the draft anyway, and list the open question under
  `review.ambiguities` so the author can correct it. Only refuse to produce a
  draft if the request is impossible with the available tools.

How to write a good AGENT.md body (the `prompt` field):
- Write it as instructions TO the agent (second person), in markdown, no
  frontmatter. Aim for ~150-400 words. Include these sections, in order:
  - **Role**: one or two sentences on who the agent is and its scope.
  - **Capabilities & tools**: which tools it has and when to use each (reference
    the exact tool ids you selected).
  - **How to answer**: querying/data rules, when to use which skill, how to cite
    or show data, and the expected response format/tone.
  - **Boundaries**: what it must NOT do, how to handle out-of-scope requests,
    and how to behave when a tool errors, returns nothing, or the question is
    ambiguous (ask a brief clarifying question rather than guessing at data).
- Ground every data claim in a confirmed schema. Never reference columns or
  tables you have not seen via `probe_sql_schema`.

Skill quality and length budget:
- Add a skill only when it captures a reusable, multi-step procedure that would
  bloat the main prompt. Otherwise keep guidance in the AGENT.md body.
- Keep each skill content under ~250 words. Keep the whole draft compact to
  avoid truncation; prefer fewer, tighter skills over many long ones.

Authoring Python tools (custom code tools):
- When a needed capability is NOT available as an MCP tool, you may define a
  small Python function as a tool under `python_tools`. Each entry is a single,
  self-contained function with a typed signature and a docstring stating what it
  does and its arguments. The runtime exposes these to the agent through a
  sandboxed `execute_python`.
- ALWAYS validate a Python tool before proposing it: call the `execute_python`
  tool with the function plus a tiny test call that `print()`s a sample result.
  Iterate until it runs cleanly. Record the check under `review.schema_checks`
  (use the test snippet as the `query`) and note any remaining concerns under
  `review.safety`.
- Safety rules for Python tools (NON-NEGOTIABLE — this is the evaluation gate):
  - NEVER hardcode credentials, tokens, API keys, passwords, or connection
    strings. NEVER read secrets from environment variables, files, or args.
  - Keep tools pure and deterministic: inputs in, value out. No destructive
    filesystem writes, no shelling out / subprocess, no network calls, no
    unbounded loops.
  - Prefer the Python standard library. If a tool needs governed data, it must
    accept that data as an argument (fetched via an MCP/SQL tool upstream), not
    fetch it itself with embedded credentials.
  - If the author asks for something unsafe (e.g. "just paste my token in the
    code"), REFUSE that part, implement it the safe way, and explain why under
    `review.safety`.
- Use Python tools sparingly. Good ones are deterministic transforms or
  calculations (date math, unit conversion, parsing, formatting, scoring), NOT
  data fetchers. Prefer MCP tools for anything touching governed data.

`review.schema_checks[].ok` semantics: set `ok` to true ONLY if the probe
returned and the columns the agent relies on are present; set it to false if the
probe errored or an expected column is missing. Do not mark `ok: true` for
queries you did not actually probe.

Output contract (STRICT):
- Write a short human-readable explanation FIRST, then end your reply with a
  SINGLE fenced ```json block and nothing after it.
- The JSON must be valid: escape newlines inside string values as \\n and escape
  any double quotes. Do not include comments or trailing commas. Markdown bodies
  (`prompt`, skill `content`) go inside JSON strings — they must be properly
  escaped.
- Match this shape exactly:
```json
{
  "name": "short profile name",
  "description": "one-line description",
  "model": "serving endpoint name or empty",
  "tools": ["<exact AI Gateway MCP tool ids>"],
  "prompt": "the AGENT.md body (markdown, no frontmatter)",
  "skills": [{"name": "Skill name", "description": "one line", "content": "markdown body"}],
  "python_tools": [{"name": "Tool name", "description": "one line", "code": "def tool(x: int) -> int:\\n    \\"\\"\\"docstring\\"\\"\\"\\n    return x"}],
  "review": {
    "suggested_tools": [{"name": "tool", "why": "reason"}],
    "missing": ["capabilities requested but not available as MCP tools"],
    "ambiguities": ["questions the author should resolve"],
    "schema_checks": [{"query": "...", "columns": ["..."], "ok": true}],
    "safety": ["Python-tool safety notes: anything refused/changed, or 'No issues — no hardcoded secrets, pure functions'"]
  }
}
```
- `python_tools` is OPTIONAL — include it only when you actually defined custom
  code tools; otherwise use `[]`. The `code` value is a JSON string, so escape
  newlines as \\n and quotes as needed.

Worked example (abbreviated — your `prompt` should be fuller than this):
```json
{
  "name": "Orders Analyst",
  "description": "Answers supply-chain questions from the orders table.",
  "model": "",
  "tools": ["sql/execute_sql"],
  "prompt": "# Orders Analyst\\n\\n## Role\\nYou answer supply-chain questions about customer orders for internal ops staff.\\n\\n## Capabilities & tools\\nUse `sql/execute_sql` to query the `orders` table. Confirmed columns: order_id, status, region, total_amount, created_at.\\n\\n## How to answer\\nWrite a single SQL query scoped to the user's question, then summarize the result in plain language and show the key numbers. Default to the last 90 days unless the user gives a range.\\n\\n## Boundaries\\nOnly answer from the orders data. If a question needs data you cannot reach, say so. If a query returns no rows, say the result was empty rather than inventing numbers.",
  "skills": [],
  "python_tools": [],
  "review": {
    "suggested_tools": [{"name": "sql/execute_sql", "why": "Needed to read the orders table."}],
    "missing": [],
    "ambiguities": ["Should 'recent' default to 90 days?"],
    "schema_checks": [{"query": "SELECT * FROM orders", "columns": ["order_id", "status", "region", "total_amount", "created_at"], "ok": true}],
    "safety": []
  }
}
```
"""


def _make_tools(ws: WorkspaceClient, confirm_schema: bool):
    from langchain_core.tools import tool

    # MCP discovery is a network round-trip per server; the agent often calls
    # `list_available_tools` more than once per run, so memoize the catalog for
    # the lifetime of this tool set (one authoring run).
    _catalog_cache: Dict[str, List[Dict[str, Any]]] = {}

    def _catalog() -> List[Dict[str, Any]]:
        if "tools" not in _catalog_cache:
            _catalog_cache["tools"] = discover_mcp_tools(ws)
        return _catalog_cache["tools"]

    @tool
    def list_available_tools(query: str = "") -> str:
        """List agent tools available via the Unity Catalog AI Gateway MCP.

        Optionally filter by a substring `query`. Returns tool name + description.
        Only names returned here may be referenced in the profile.
        """
        catalog = _catalog()
        if query:
            q = query.lower()
            catalog = [t for t in catalog if q in t["name"].lower() or q in t["description"].lower()]
        if not catalog:
            return "No MCP tools discovered. Do not reference any tools; record needs under review.missing."
        lines = [f"- {t['id']}: {t['description']}" for t in catalog[:100]]
        return (
            "Available AI Gateway MCP tools. Reference tools by their exact id "
            "(the server-qualified value before the colon) in the profile's "
            "`tools` list:\n" + "\n".join(lines)
        )

    @tool
    def probe_sql_schema(sql: str) -> str:
        """Confirm a SQL query/table's columns by running a bounded LIMIT 1 probe."""
        if not confirm_schema:
            return "Schema confirmation is disabled for this run."
        result = _probe_sql_schema(ws, sql)
        if result.get("error"):
            return f"Schema probe failed: {result['error']}"
        cols = result.get("columns") or []
        return "Confirmed columns: " + (", ".join(cols) if cols else "(none returned)")

    @tool
    def execute_python(code: str) -> str:
        """Run a short Python snippet in an isolated, credential-free sandbox.

        Use this to VALIDATE an author's Python tool before proposing it: paste
        the tool function plus a tiny test call that `print()`s a sample result,
        and confirm it runs cleanly. The sandbox has no credentials and a strict
        timeout, so never rely on secrets, network, or the filesystem here.
        Returns the exit code, stdout, and stderr.
        """
        result = _run_python_sandbox(code, _python_sandbox_timeout())
        parts = [f"exit_code={result['exit_code']}"]
        if result.get("stdout"):
            parts.append("stdout:\n" + result["stdout"])
        if result.get("stderr"):
            parts.append("stderr:\n" + result["stderr"])
        return "\n".join(parts)

    return [list_available_tools, probe_sql_schema, execute_python]


def _build_authoring_system_prompt(req: AuthorRequest) -> str:
    """Compose the authoring system prompt, grounding it in the current draft."""
    system_prompt = AUTHORING_SYSTEM_PROMPT
    if req.current_prompt:
        system_prompt += f"\n\nThe author's CURRENT AGENT.md body:\n```markdown\n{req.current_prompt}\n```"
    if req.current_skills:
        existing = "\n".join(f"- {s.name}: {s.description}" for s in req.current_skills)
        system_prompt += f"\n\nExisting skills:\n{existing}"
    if req.current_python_tools:
        existing_pt = "\n".join(
            f"- {t.name}: {t.description}" for t in req.current_python_tools
        )
        system_prompt += f"\n\nExisting Python tools:\n{existing_pt}"
    return system_prompt


def _agent_studio_max_tokens() -> int:
    """Output budget for the Agent Studio LLM.

    Unlike the Widget Studio (which emits a whole TSX file and needs a large
    budget), Agent Studio only drafts a compact JSON profile — a system prompt
    plus a few short skills. A modest cap meaningfully cuts generation latency.
    """
    try:
        return int(os.environ.get("AGENT_STUDIO_MAX_TOKENS", "6000"))
    except ValueError:
        return 6000


def _build_authoring_llm(api_key: str, base_url: str):
    from langchain_openai import ChatOpenAI

    model_name = os.environ.get("AGENT_STUDIO_LLM_MODEL", "databricks-claude-sonnet-4-6")
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        temperature=0.1,
        max_tokens=_agent_studio_max_tokens(),
    )


def _llm_credentials(sp_client: WorkspaceClient) -> tuple[str, str]:
    """Resolve (api_key, base_url) for the serving endpoint from the SP client."""
    host = sp_client.config.host
    auth_headers_fn = sp_client.config.authenticate()
    auth_headers = auth_headers_fn() if callable(auth_headers_fn) else auth_headers_fn
    api_key = auth_headers.get("Authorization", "").replace("Bearer ", "") if auth_headers else ""
    api_key = (
        api_key
        or sp_client.config.token
        or os.environ.get("DATABRICKS_TOKEN")
        or "dummy"
    )
    base_url = f"{host}/serving-endpoints" if host else os.environ.get("OPENAI_BASE_URL", "")
    return api_key, base_url


def _sse(payload: Dict[str, Any]) -> bytes:
    """Render one SSE frame (``data: {json}\\n\\n``)."""
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


_FRIENDLY_TOOL = {
    "list_available_tools": "Listing available tools",
    "probe_sql_schema": "Confirming schema",
    "execute_python": "Testing Python tool",
}


def _prose_cut(content: str) -> int:
    """Index where the human prose ends and the JSON payload begins (or -1).

    The model is asked to write a short explanation, then the profile as JSON.
    The JSON is not always fenced, and its skill bodies can themselves contain
    ``` code fences — so we cut at the EARLIEST of the first ``` fence or the
    first ``{`` (JSON object start), never merely the first fence.
    """
    candidates = [i for i in (content.find("```"), content.find("{")) if i != -1]
    return min(candidates) if candidates else -1


def _split_explanation(content: str) -> str:
    """Return only the human-readable prose, dropping the JSON payload."""
    cut = _prose_cut(content)
    explanation = content if cut == -1 else content[:cut]
    return re.sub(r"\n{3,}", "\n\n", explanation).strip()


def _scan_balanced_object(text: str, start: int) -> Optional[str]:
    """Return the first balanced ``{...}`` object at/after ``start``.

    Brace counting is string-aware (ignores braces inside JSON string literals
    and respects backslash escapes), so it is robust to skill bodies that embed
    ``` code fences, ``{`` / ``}`` characters, or stray punctuation. Returns
    ``None`` if no opening brace is found or the object never closes (truncated).
    """
    i = text.find("{", start)
    if i == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return None


def _extract_json_block(content: str) -> Optional[Dict[str, Any]]:
    """Parse the profile JSON the model appended after its prose.

    The model often does NOT fence the JSON, and when it does the body can
    contain inner ``` fences that defeat a naive non-greedy regex. We therefore
    extract the JSON by balanced-brace scanning (string-aware), trying the
    fenced region first, then the whole message, then a greedy regex as a final
    fallback. The first candidate that parses wins.
    """
    candidates: List[str] = []
    fence = re.search(r"```json\s*\n", content, re.IGNORECASE)
    if fence:
        obj = _scan_balanced_object(content, fence.end())
        if obj:
            candidates.append(obj)
    obj = _scan_balanced_object(content, 0)
    if obj:
        candidates.append(obj)
    greedy = re.search(r"\{.*\}", content, re.DOTALL)
    if greedy:
        candidates.append(greedy.group(0))

    for raw in candidates:
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
    if candidates:
        logger.warning("Agent Studio: draft JSON found but failed to parse (len=%d)", len(content))
    return None


def run_authoring_task(
    job_id: str,
    req: AuthorRequest,
    api_key: str,
    base_url: str,
    obo_token: Optional[str],
) -> None:
    try:
        from langchain_core.messages import AIMessage, HumanMessage
        from langgraph.prebuilt import create_react_agent

        store = get_agent_studio_store()
        ws = store._client(obo_token)  # OBO client for tool discovery + probes

        llm = _build_authoring_llm(api_key, base_url)
        agent = create_react_agent(
            model=llm,
            tools=_make_tools(ws, req.confirm_schema),
            prompt=_build_authoring_system_prompt(req),
        )

        history = req.history[-6:] if len(req.history) > 6 else req.history
        lc_history: List[Any] = []
        for m in history:
            if m.role == "user":
                lc_history.append(HumanMessage(content=m.content))
            else:
                lc_history.append(AIMessage(content=m.content))

        response = agent.invoke({"messages": lc_history + [HumanMessage(content=req.prompt)]})
        content = response["messages"][-1].content
        draft = _extract_json_block(content)

        explanation = _split_explanation(content) if draft is not None else content

        authoring_jobs[job_id] = {
            "status": "completed",
            "result": {"draft": draft, "explanation": explanation, "raw": content},
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Authoring job %s failed", job_id)
        authoring_jobs[job_id] = {"status": "failed", "error": str(exc)}


# --------------------------------------------------------------------- routes

@router.get("/tools")
def list_tools(obo_token: Optional[str] = Depends(get_user_token)):
    """Catalog of tools the current user can use via the AI Gateway MCP."""
    store = get_agent_studio_store()
    ws = store._client(obo_token)
    return {"tools": discover_mcp_tools(ws)}


@router.get("/locations")
def list_locations(
    _: str = Depends(require_auth),
    obo_token: Optional[str] = Depends(get_user_token),
):
    store = get_agent_studio_store()
    email = _user_email(obo_token)
    try:
        locs = store.list_locations(obo_token, email)
    except AgentStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"locations": [loc.to_dict() for loc in locs]}


@router.get("/profiles")
def list_profiles(
    include_shared: bool = True,
    _: str = Depends(require_auth),
    obo_token: Optional[str] = Depends(get_user_token),
):
    store = get_agent_studio_store()
    email = _user_email(obo_token)
    try:
        profiles = store.list_profiles(obo_token, email, include_shared=include_shared)
    except AgentStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"profiles": [p.to_dict() for p in profiles]}


@router.get("/profiles/{profile_id}")
def get_profile(
    profile_id: str,
    _: str = Depends(require_auth),
    obo_token: Optional[str] = Depends(get_user_token),
):
    store = get_agent_studio_store()
    try:
        profile = store.get_profile(obo_token, profile_id)
    except AgentStudioError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return profile.to_dict()


@router.post("/profiles")
def save_profile(
    req: SaveProfileRequest,
    _: str = Depends(require_auth),
    obo_token: Optional[str] = Depends(get_user_token),
):
    store = get_agent_studio_store()
    email = _user_email(obo_token)
    skills = [s.dict() for s in req.skills] if req.skills is not None else None
    python_tools = (
        [t.dict() for t in req.python_tools] if req.python_tools is not None else None
    )
    try:
        profile = store.save_profile(
            obo_token,
            email,
            name=req.name,
            prompt=req.prompt,
            description=req.description,
            model=req.model,
            tools=req.tools,
            skills=skills,
            python_tools=python_tools,
            store=req.store,
            base_path=req.base_path,
            profile_id=req.profile_id,
            expected_updated_at=req.expected_updated_at,
        )
    except ProfileConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except AgentStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return profile.to_dict()


@router.get("/promotion/targets")
def list_promotion_targets(
    _: str = Depends(require_auth),
    obo_token: Optional[str] = Depends(get_user_token),
):
    """Shared (UC Volume) locations the user can promote a profile into.

    These are the same shared ``.agents`` locations the user can write to (UC
    governs the grant); personal Workspace folders are excluded since promotion
    means publishing to a governed/shared spot. An optional env allowlist
    (``AGENT_STUDIO_PROMOTION_TARGETS`` — comma-separated ``label=base_path``
    pairs, where ``base_path`` points at an ``.agents`` dir) overrides discovery
    so admins can pin canonical dev/prod targets.
    """
    configured = (os.environ.get("AGENT_STUDIO_PROMOTION_TARGETS") or "").strip()
    if configured:
        targets = []
        for entry in configured.split(","):
            entry = entry.strip()
            if not entry:
                continue
            label, _, base = entry.partition("=")
            base = (base or label).strip()
            targets.append({"store": STORE_VOLUME, "base_path": base.rstrip("/"), "label": label.strip() or base})
        return {"targets": targets}

    store = get_agent_studio_store()
    email = _user_email(obo_token)
    try:
        locs = store.list_locations(obo_token, email)
    except AgentStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"targets": [loc.to_dict() for loc in locs if not loc.is_personal]}


@router.post("/promote")
def promote_profile(
    req: PromoteRequest,
    _: str = Depends(require_auth),
    obo_token: Optional[str] = Depends(get_user_token),
):
    """Promote a profile by copying it into a target shared/prod location.

    Reads the source profile (under OBO) and writes a fresh copy — AGENT.md +
    all skills — under ``target_base_path/<slug>``. The write succeeds only if
    Unity Catalog grants the user write access to the target, so promotion is
    governed by UC, not re-implemented here.
    """
    store = get_agent_studio_store()
    email = _user_email(obo_token)
    try:
        source = store.get_profile(obo_token, req.profile_id)
        skills = [s.to_dict() for s in (source.skills or [])]
        python_tools = [t.to_dict() for t in (source.python_tools or [])]
        promoted = store.save_profile(
            obo_token,
            email,
            name=source.name,
            prompt=source.prompt or "",
            description=source.description,
            model=source.model,
            tools=source.tools,
            skills=skills,
            python_tools=python_tools,
            store=req.target_store,
            base_path=req.target_base_path,
            profile_id=None,  # always create/overwrite at the target path
        )
        store.record_promotion(
            obo_token,
            target_store=promoted.store,
            target_dir=req.target_base_path,
            entry={
                "at": _now_iso(),
                "by": email,
                "name": source.name,
                "from_id": req.profile_id,
                "from_label": source.location_label,
                "to_id": promoted.id,
                "to_label": promoted.location_label,
            },
        )
    except AgentStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "promoted", "profile": promoted.to_dict()}


@router.delete("/profiles/{profile_id}")
def delete_profile(
    profile_id: str,
    _: str = Depends(require_auth),
    obo_token: Optional[str] = Depends(get_user_token),
):
    store = get_agent_studio_store()
    try:
        store.delete_profile(obo_token, profile_id)
    except AgentStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "deleted"}


@router.post("/generate")
async def start_authoring(
    req: AuthorRequest,
    background_tasks: BackgroundTasks,
    obo_token: Optional[str] = Depends(get_user_token),
    sp_client: WorkspaceClient = Depends(get_db_client_sp),
):
    """Kick off the AI-assisted authoring job (LLM via SP, tools via OBO).

    Legacy background-job + polling path. Prefer ``/generate/stream`` (SSE),
    which avoids the in-memory job store entirely — polling could miss jobs
    across replicas or a ``--reload`` restart. This is kept as a fallback.
    """
    try:
        api_key, base_url = _llm_credentials(sp_client)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"LLM client init failed: {exc}")

    job_id = str(uuid.uuid4())
    authoring_jobs[job_id] = {"status": "pending", "result": None, "error": None}
    background_tasks.add_task(run_authoring_task, job_id, req, api_key, base_url, obo_token)
    return {"job_id": job_id}


@router.post("/generate/stream")
async def stream_authoring(
    req: AuthorRequest,
    obo_token: Optional[str] = Depends(get_user_token),
    sp_client: WorkspaceClient = Depends(get_db_client_sp),
):
    """Stream the AI-assisted authoring run as SSE.

    Streams the model's prose as ``chunk`` events for immediate feedback, tool
    activity as ``tool_calls`` events, and concludes with a single ``final``
    event carrying the parsed ``draft`` + cleaned ``explanation``. The request
    stays open for the whole run, so there is no job store and no cross-replica
    polling gap. LLM uses the SP credential; tools/probes use the caller's OBO.
    """
    try:
        api_key, base_url = _llm_credentials(sp_client)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"LLM client init failed: {exc}")

    async def event_stream():
        try:
            from langchain_core.messages import AIMessage, HumanMessage
            from langgraph.prebuilt import create_react_agent

            store = get_agent_studio_store()
            ws = store._client(obo_token)
            llm = _build_authoring_llm(api_key, base_url)
            agent = create_react_agent(
                model=llm,
                tools=_make_tools(ws, req.confirm_schema),
                prompt=_build_authoring_system_prompt(req),
            )

            history = req.history[-6:] if len(req.history) > 6 else req.history
            lc_history: List[Any] = []
            for m in history:
                if m.role == "user":
                    lc_history.append(HumanMessage(content=m.content))
                else:
                    lc_history.append(AIMessage(content=m.content))

            full = ""
            emitted = 0
            tool_calls: List[Dict[str, str]] = []
            tool_seen: set[str] = set()
            # Track which message produced the last prose so we can insert a
            # paragraph break between separate AI messages (the ReAct loop emits
            # one per step); otherwise their text runs together with no space.
            last_content_id: Optional[str] = None

            async for msg, _meta in agent.astream(
                {"messages": lc_history + [HumanMessage(content=req.prompt)]},
                stream_mode="messages",
            ):
                # A tool finished -> flip its pill to done.
                if getattr(msg, "type", None) == "tool":
                    name = getattr(msg, "name", None)
                    if name:
                        label = _FRIENDLY_TOOL.get(name, name)
                        for tc in tool_calls:
                            if tc["tool_name"] == label:
                                tc["status"] = "done"
                        yield _sse({"type": "tool_calls", "content": tool_calls})
                    continue

                # New tool call requested by the model.
                for tcc in getattr(msg, "tool_call_chunks", None) or []:
                    nm = tcc.get("name")
                    if nm and nm not in tool_seen:
                        tool_seen.add(nm)
                        tool_calls.append({"tool_name": _FRIENDLY_TOOL.get(nm, nm), "status": "running"})
                        yield _sse({"type": "tool_calls", "content": tool_calls})

                content = getattr(msg, "content", "") or ""
                if isinstance(content, list):
                    content = "".join(
                        p.get("text", "") if isinstance(p, dict) else str(p) for p in content
                    )
                if not content:
                    continue
                msg_id = getattr(msg, "id", None)
                if last_content_id is not None and msg_id != last_content_id:
                    full += "\n\n"
                last_content_id = msg_id
                full += content
                # Stream only the prose before the JSON payload. The boundary
                # (`{` or a ``` fence) is detected by _prose_cut and never
                # emitted. The only thing that could leak across chunks is the
                # START of a fence, so hold back ONLY a trailing run of 1-2
                # backticks (a partial ```); everything else is emitted verbatim.
                # (The old `prose[:-2]` dropped the last 2 chars of every chunk,
                # which surfaced as the final 1-2 letters going missing.)
                cut = _prose_cut(full)
                if cut != -1:
                    emittable = full[:cut]
                else:
                    stripped = full.rstrip("`")
                    trailing_ticks = len(full) - len(stripped)
                    emittable = stripped if 0 < trailing_ticks < 3 else full
                if len(emittable) > emitted:
                    yield _sse({"type": "chunk", "content": emittable[emitted:]})
                    emitted = len(emittable)

            draft = _extract_json_block(full)
            explanation = _split_explanation(full) or "Draft updated."
            yield _sse({"type": "final", "draft": draft, "explanation": explanation})
            yield b"data: [DONE]\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Authoring stream failed")
            yield _sse({"type": "error", "content": str(exc)})
            yield b"data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/generate/{job_id}")
async def get_authoring_status(job_id: str):
    if job_id not in authoring_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return authoring_jobs[job_id]


# --------------------------------------------------------------------- helper

def _user_email(obo_token: Optional[str]) -> str:
    """Best-effort caller email for the personal workspace path.

    The store re-resolves this via ``current_user.me()`` when possible, so this
    is only a fallback used to compose ``/Workspace/Users/<email>/.agents``.
    """
    return os.environ.get("AGENT_STUDIO_FALLBACK_EMAIL", "me")
