"""In-process agent runtime for the EDH drawer chat.

Replaces the app->app hop to the Self-Service ("ssc") runtime. This is a small,
self-contained streaming tool-calling loop that runs entirely inside Command
Center under the caller's OBO token — so there is no second Databricks App front
door to authorize, which was the source of the per-user 403s.

Scope is intentionally minimal (this app is a chatbot, not the full Self-Service
platform):
  * a user-defined system prompt + inlined skills (from the saved/inline profile)
  * AI Gateway MCP tools (discovered and invoked under OBO)
  * author-written Python tools (run in the existing credential-free sandbox)

Data access runs as the signed-in user: every MCP tool uses the forwarded OBO
token, so Unity Catalog governs data access per user. The LLM (inference) call
is signed by the app service principal by default (see ``_llm_auth_mode``) so
users don't each need a foundation-model entitlement — inference touches no user
data, only the messages we hand it. The loop streams drawer-shaped SSE frames
(``chunk`` / ``tool_calls`` / ``final`` / ``error``) that the existing
``useAgentChat`` hook already renders.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------- config

def _model_default() -> str:
    return os.environ.get("AGENT_RUNTIME_MODEL", "databricks-claude-sonnet-4-6")


def _llm_base_path() -> str:
    bp = os.environ.get("AGENT_RUNTIME_LLM_BASE_PATH", "/serving-endpoints")
    return bp if bp.startswith("/") else "/" + bp


def _llm_auth_mode() -> str:
    """Which identity signs the LLM (chat-completions) call: ``sp`` or ``obo``.

    Default ``sp``: the LLM call is authorized by the app's service principal so
    every signed-in user can chat without needing an individual foundation-model
    entitlement (the FM gateway otherwise returns 403 "Unauthorized access to
    Org" under some users' OBO tokens). This ONLY affects model inference — every
    data-touching tool still runs under the user's OBO token, so Unity Catalog
    governs data access per user exactly as before. Set to ``obo`` to sign the
    LLM call with the user's token instead.
    """
    mode = (os.environ.get("AGENT_RUNTIME_LLM_AUTH", "sp") or "sp").strip().lower()
    return "sp" if mode == "sp" else "obo"


def _max_steps() -> int:
    # Default 8 (not 6) leaves room for a few model-driven poll rounds on a
    # long-running SQL query: `execute_sql` returns rows inline for normal
    # queries, but for slow ones it hands back a statement_id that the model
    # drains via `poll_sql_result` — each poll costs one step.
    try:
        return int(os.environ.get("AGENT_RUNTIME_MAX_STEPS", "8"))
    except ValueError:
        return 8


def _max_tokens() -> int:
    try:
        return int(os.environ.get("AGENT_RUNTIME_MAX_TOKENS", "4000"))
    except ValueError:
        return 4000


def _tool_timeout() -> int:
    try:
        return int(os.environ.get("AGENT_RUNTIME_TOOL_TIMEOUT", "90"))
    except ValueError:
        return 90


def _heartbeat_secs() -> float:
    try:
        return float(os.environ.get("AGENT_RUNTIME_HEARTBEAT_SECS", "10") or "10")
    except ValueError:
        return 10.0


def _default_tool_cap() -> int:
    """Max MCP tools bound for the DEFAULT agent (no profile picks a subset)."""
    try:
        return int(os.environ.get("AGENT_RUNTIME_DEFAULT_TOOL_CAP", "40"))
    except ValueError:
        return 40


def _genie_timeout() -> float:
    """Wall-clock budget for the internal Genie ask->poll loop (seconds)."""
    try:
        return float(os.environ.get("AGENT_RUNTIME_GENIE_TIMEOUT", "150"))
    except ValueError:
        return 150.0


def _genie_poll_interval() -> float:
    """Delay between Genie poll round-trips (seconds)."""
    try:
        return float(os.environ.get("AGENT_RUNTIME_GENIE_POLL_MS", "3000")) / 1000.0
    except ValueError:
        return 3.0


# The neutral runtime contract layered UNDER a profile persona (base: "full").
# This is deliberately NOT a persona of its own — it carries only the output /
# tool / auth rules every agent on this surface must obey, so a custom profile
# (e.g. a Supply-Chain analyst) defines its OWN identity and does not fight a
# competing default persona. Mirrors the Self-Service app's PROFILE_BASE_SCAFFOLD
# so agents authored against that behavior keep behaving the same in-process.
RUNTIME_CONTRACT = """The following runtime rules apply regardless of your persona:

## Output formatting (the UI renders GitHub-flavored markdown)
- Use GFM markdown: **bold**, *italic*, `inline code`, fenced code blocks for code/SQL/JSON, and `|`-separated tables with a `| --- |` divider for tabular data.
- Prefer `##` / `###` headings; avoid `#` (the chat bubble already provides emphasis).
- Links use [text](url); never wrap a markdown link in backticks and never escape backticks. Do NOT output raw HTML.

## Tools & authentication
- Use ONLY the provided tools to take actions or fetch data; never fabricate data a tool is meant to provide. Prefer calling a tool over guessing.
- Prefer SQL for read-only data discovery, metadata inspection, and tabular retrieval when the same result is available through SQL. For example, use `SHOW CATALOGS`, `SHOW SCHEMAS`, `SHOW TABLES`, `DESCRIBE`, or `SELECT` through the SQL tool instead of calling Unity Catalog REST APIs. SQL uses the configured warehouse and the user's existing SQL/Unity Catalog permissions and avoids requiring a separate REST OAuth scope.
- Use a Databricks REST API tool only when SQL cannot perform the operation (for example: jobs, serving endpoint invocation/configuration, workspace files, volume file transfer, or other control-plane actions). Do not infer an OAuth scope name from an API family, and do not retry a REST call with a guessed scope after an invalid-scope or missing-scope response; use an equivalent SQL operation when one exists.
- Tools execute with On-Behalf-Of (OBO) authentication — they use the signed-in user's own identity and permissions. NEVER ask the user for passwords, tokens, or credentials.
- A permission/authorization failure from a tool (e.g. "User does not have USE SCHEMA...", "permission denied") reflects the USER's own access, not yours. Say "You don't have access to X yet" (second person), never "I don't have access". Remember it for the rest of the conversation: don't retry the blocked scope, and use it to inform next steps (offer to request access, or suggest an asset they can access)."""


# Persona used ONLY for the default agent (no profile selected). A saved/inline
# profile REPLACES this with its own persona (layered over RUNTIME_CONTRACT).
DEFAULT_AGENT_PERSONA = """## Your role
You are a helpful data assistant embedded in the Command Center dashboard. Help the user understand and act on their data using the tools available to you. Be concise and direct. If a tool fails or the user lacks access, say so plainly rather than inventing an answer."""


# ------------------------------------------------------------------- clients

def _obo_ws(obo_token: Optional[str]):
    """Build a WorkspaceClient under the caller's OBO token (reuses the store's
    builder so dev/prod auth behaves identically to the rest of the app)."""
    from agent_studio_store import get_agent_studio_store

    return get_agent_studio_store()._client(obo_token)


def _sp_ws():
    """Build a WorkspaceClient under the app's OWN identity (service principal in
    the App runtime; local profile in dev). Reuses the store's builder with a
    None OBO token so auth resolves identically to the rest of the app."""
    from agent_studio_store import get_agent_studio_store

    return get_agent_studio_store()._client(None)


def _bearer(ws) -> Optional[str]:
    """Extract a raw bearer token from a WorkspaceClient's resolved auth headers."""
    try:
        auth = ws.config.authenticate()
        headers = auth() if callable(auth) else auth
        if headers:
            tok = (headers.get("Authorization", "") or "").replace("Bearer ", "")
            if tok:
                return tok
    except Exception as exc:  # noqa: BLE001
        logger.debug("bearer extraction failed: %s", exc)
    return None


def _llm_api_key(ws, obo_token: Optional[str]) -> str:
    """The bearer used for the LLM call under OBO mode.

    OBO (user token) is preferred so the model call runs as the user; falls back
    to the client's own credentials in dev / when no token was forwarded.
    """
    if obo_token:
        return obo_token
    return _bearer(ws) or ws.config.token or os.environ.get("DATABRICKS_TOKEN") or "dummy"


def _openai_client(ws, obo_token: Optional[str]):
    """OpenAI-compatible client for the AI Gateway serving endpoints.

    Auth for the LLM (inference) call is chosen by ``_llm_auth_mode``:
      * ``sp`` (default): sign with the app service principal so every user can
        chat without an individual FM entitlement. Inference does NOT touch user
        data — tools still run under the caller's OBO token (unchanged).
      * ``obo``: sign with the caller's forwarded token.
    Falls back to OBO/local creds if an SP bearer can't be resolved (e.g. dev).
    """
    from openai import OpenAI

    host = (ws.config.host or os.environ.get("DATABRICKS_HOST") or "").rstrip("/")
    api_key: Optional[str] = None
    if _llm_auth_mode() == "sp":
        sp = _sp_ws()
        api_key = _bearer(sp)
        host = ((sp.config.host if sp else None) or host).rstrip("/")
        if not api_key:
            logger.warning(
                "AGENT_RUNTIME_LLM_AUTH=sp but no service-principal bearer was "
                "available; falling back to OBO/local creds for the LLM call."
            )
    if not api_key:
        api_key = _llm_api_key(ws, obo_token)
    base_url = f"{host}{_llm_base_path()}"
    return OpenAI(api_key=api_key, base_url=base_url)


# --------------------------------------------------------------------- tools

def _sanitize(name: str) -> str:
    """OpenAI function names allow only [a-zA-Z0-9_-]; MCP ids contain '/'."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name or "")[:64] or "tool"


def _parse_python_signature(code: str) -> Tuple[Optional[str], List[str]]:
    """Return (function_name, [param_names]) for the first top-level def."""
    m = re.search(r"^\s*def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", code or "", re.M)
    if not m:
        return None, []
    func = m.group(1)
    params: List[str] = []
    for raw in m.group(2).split(","):
        p = raw.strip()
        if not p or p.startswith("*") or p == "self":
            continue
        params.append(p.split(":")[0].split("=")[0].strip())
    return func, [p for p in params if p]


# ------------------------------------------------------------------- Genie
# The AI Gateway Genie MCP server is ASYNCHRONOUS: `genie_ask` returns only a
# {conversation_id, response_id} handle, and the answer must be drained by
# polling `genie_poll_response`. `DatabricksMCPClient.call_tool` does a single
# round-trip (no polling), so a naive synchronous call hands the model a useless
# handle. We therefore detect Genie and drive the poll loop INSIDE tool
# execution — the model calls `genie_ask` once and gets the finished answer. The
# outer stream emits `: keepalive` heartbeats while this blocks, so the (30-120s)
# wait never trips a proxy/browser timeout.

def _is_genie_server(url: str) -> bool:
    from urllib.parse import urlparse

    return "/mcp/genie" in (urlparse(url or "").path or "")


def _is_genie_poll_tool(name: str) -> bool:
    return "poll" in (name or "").lower()


def _is_genie_ask_tool(name: str) -> bool:
    n = (name or "").lower()
    return n in ("genie_ask", "ask_your_data") or n.endswith("_ask")


_GENIE_URL_FIELDS = (
    "conversation_url", "share_url", "share_link", "deep_link",
    "deeplink", "permalink", "link", "url",
)


def _parse_mcp_result(res) -> Tuple[Optional[Dict[str, Any]], str, bool]:
    """(structured_payload | None, joined_text, is_error) from a CallToolResult."""
    structured = getattr(res, "structuredContent", None)
    parts: List[str] = []
    for block in (getattr(res, "content", None) or []):
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
        elif getattr(block, "data", None) is not None:
            parts.append(json.dumps(block.data))
    return (
        structured if isinstance(structured, dict) else None,
        "\n".join(p for p in parts if p),
        bool(getattr(res, "isError", False)),
    )


def _payload_of(structured: Optional[Dict[str, Any]], text: str) -> Dict[str, Any]:
    if isinstance(structured, dict):
        return structured
    if text and text.strip():
        try:
            decoded = json.loads(text)
            if isinstance(decoded, dict):
                return decoded
        except json.JSONDecodeError:
            pass
    return {}


def _genie_deep_link(payload: Dict[str, Any]) -> Optional[str]:
    for k in _GENIE_URL_FIELDS:
        v = payload.get(k)
        if isinstance(v, str) and v.startswith(("http://", "https://")) and "databricks" in v:
            return v
    return None


def _exec_genie(client, ask_tool: str, args: Dict[str, Any]) -> str:
    """Run the full Genie ask->poll->answer cycle and return the answer text."""
    import time

    structured, text, is_err = _parse_mcp_result(client.call_tool(ask_tool, args or {}))
    if is_err:
        return f"Genie could not start the query: {text or 'unknown error'}"
    handle = _payload_of(structured, text)
    conv = handle.get("conversation_id") or handle.get("conversationId") or handle.get("conversation")
    resp = (
        handle.get("response_id") or handle.get("responseId")
        or handle.get("message_id") or handle.get("messageId")
        or handle.get("query_id") or handle.get("id")
    )
    if not (conv and resp):
        return "Genie did not return a query handle. Raw: " + (text or json.dumps(handle))[:1000]

    deadline = time.monotonic() + _genie_timeout()
    interval = _genie_poll_interval()
    last_answer = ""
    while time.monotonic() < deadline:
        time.sleep(interval)
        pstruct, ptext, perr = _parse_mcp_result(
            client.call_tool("genie_poll_response", {"conversation_id": conv, "response_id": resp})
        )
        if perr:
            return f"Genie poll error: {ptext or 'unknown error'}"
        payload = _payload_of(pstruct, ptext)
        status = str(payload.get("status") or payload.get("state") or "").upper()
        answer = payload.get("final_answer") or ""
        if answer:
            last_answer = answer
        if status in ("COMPLETED", "SUCCESS", "DONE"):
            final = last_answer or ptext or "(Genie returned no answer text.)"
            link = _genie_deep_link(payload)
            return final + (f"\n\n[Open in Databricks Genie]({link})" if link else "")
        if status in ("FAILED", "ERROR", "CANCELLED", "CANCELED"):
            return "Genie query failed: " + (
                payload.get("error") or payload.get("error_message")
                or payload.get("status_message") or ptext or "unknown error"
            )
    if last_answer:
        return last_answer + "\n\n(Genie was still finalizing when the time limit was reached.)"
    return (
        f"Genie did not finish within {int(_genie_timeout())}s. Try a more specific "
        "question, or pin a Genie space."
    )


def _exec_mcp(ws, server_url: str, real_name: str, args: Dict[str, Any]) -> str:
    from databricks_mcp import DatabricksMCPClient

    client = DatabricksMCPClient(server_url=server_url, workspace_client=ws)

    # Genie: one ask call, driven to completion internally (see note above).
    if _is_genie_server(server_url) and _is_genie_ask_tool(real_name):
        return _exec_genie(client, real_name, args)[:8000]

    structured, text, is_err = _parse_mcp_result(client.call_tool(real_name, args or {}))
    out = text or (json.dumps(structured) if structured else "(tool returned no content)")
    if is_err:
        out = f"Tool reported an error: {out}"
    return out[:8000]


def _exec_python(code: str, func_name: str, args: Dict[str, Any]) -> str:
    from routes.agent_studio_profiles import _run_python_sandbox

    driver = (
        f"{code}\n\n"
        "import json as _json\n"
        f"_args = _json.loads({json.dumps(json.dumps(args or {}))})\n"
        f"_res = {func_name}(**_args)\n"
        "print(_json.dumps(_res, default=str))\n"
    )
    result = _run_python_sandbox(driver, _tool_timeout() if _tool_timeout() <= 30 else 30)
    if result.get("exit_code") == 0:
        return (result.get("stdout") or "(no output)")[:8000]
    return f"Python tool failed (exit {result.get('exit_code')}): {(result.get('stderr') or '').strip()[:4000]}"


def _build_tools(
    ws,
    profile: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Return (openai_tool_specs, dispatch) for the active profile.

    ``dispatch`` maps a sanitized function name to a descriptor:
      {"kind": "mcp"|"python", "friendly": str, ...invocation fields}
    """
    from routes.agent_studio_profiles import discover_mcp_tools

    specs: List[Dict[str, Any]] = []
    dispatch: Dict[str, Dict[str, Any]] = {}

    # --- MCP tools (AI Gateway) -------------------------------------------
    try:
        catalog = discover_mcp_tools(ws)
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP discovery failed: %s", exc)
        catalog = []

    wanted = list((profile or {}).get("tools") or [])
    if wanted:
        by_id = {t["id"]: t for t in catalog}
        by_name = {t["name"]: t for t in catalog}
        selected = []
        for ref in wanted:
            entry = by_id.get(ref) or by_name.get(ref) or by_name.get(str(ref).split("/")[-1])
            if entry:
                selected.append(entry)
    else:
        # Default agent: expose the whole discovered catalog (bounded).
        selected = catalog[: _default_tool_cap()]

    for entry in selected:
        server_url = entry.get("server") or ""
        # Genie's poll tool is an internal mechanism — `genie_ask` drives it for
        # us (see _exec_genie). Never expose it to the model, or it will try to
        # poll by hand and burn tool-call rounds on a handle it can't manage.
        if _is_genie_server(server_url) and _is_genie_poll_tool(entry["name"]):
            continue
        fn = _sanitize(entry["id"])
        if fn in dispatch:
            continue
        schema = entry.get("input_schema") or {"type": "object", "properties": {}}
        if "type" not in schema:
            schema = {"type": "object", "properties": schema.get("properties", {})}
        is_genie_ask = _is_genie_server(server_url) and _is_genie_ask_tool(entry["name"])
        specs.append({
            "type": "function",
            "function": {
                "name": fn,
                "description": (entry.get("description") or entry["name"])[:1024],
                "parameters": schema,
            },
        })
        dispatch[fn] = {
            "kind": "mcp",
            "friendly": "Asking Genie" if is_genie_ask else (entry.get("name") or entry["id"]),
            "server_url": server_url,
            "real_name": entry["name"],
        }

    # --- Author-written Python tools --------------------------------------
    for pt in (profile or {}).get("python_tools") or []:
        code = pt.get("code") or ""
        func_name, params = _parse_python_signature(code)
        if not func_name:
            continue
        fn = _sanitize("py_" + (pt.get("name") or func_name))
        if fn in dispatch:
            continue
        # Leave the type UNCONSTRAINED (valid JSON Schema: omitting "type" allows
        # any) so the model passes natural JSON types (numbers stay numbers). We
        # only parsed the signature to advertise the parameter NAMES.
        properties = {p: {"description": f"The '{p}' argument."} for p in params}
        specs.append({
            "type": "function",
            "function": {
                "name": fn,
                "description": (pt.get("description") or pt.get("name") or func_name)[:1024],
                "parameters": {"type": "object", "properties": properties},
            },
        })
        dispatch[fn] = {
            "kind": "python",
            "friendly": pt.get("name") or func_name,
            "code": code,
            "func_name": func_name,
        }

    return specs, dispatch


def _run_tool(ws, desc: Dict[str, Any], args: Dict[str, Any]) -> str:
    try:
        if desc["kind"] == "mcp":
            return _exec_mcp(ws, desc["server_url"], desc["real_name"], args)
        return _exec_python(desc["code"], desc["func_name"], args)
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool %s failed: %s", desc.get("friendly"), exc)
        return f"Tool '{desc.get('friendly')}' failed: {exc}"


# --------------------------------------------------------------- prompt build

def _system_prompt(profile: Optional[Dict[str, Any]], ui_context: str) -> str:
    profile = profile or {}
    body = (profile.get("prompt") or "").strip()
    base = (profile.get("base") or "full").strip().lower()

    if body and base in ("none", "standalone", "replace"):
        # Standalone: the profile prompt is the ENTIRE system prompt (no scaffold).
        prompt = body
    elif body:
        # base "full" (default): layer the neutral runtime contract UNDER the
        # profile's persona — the profile is the authoritative identity.
        prompt = (
            f"{RUNTIME_CONTRACT}\n\n"
            "## ACTIVE AGENT PROFILE (authoritative persona & task instructions)\n"
            f"{body}"
        )
    else:
        # No profile: the default agent = runtime contract + default persona.
        prompt = f"{RUNTIME_CONTRACT}\n\n{DEFAULT_AGENT_PERSONA}"

    skills = profile.get("skills") or []
    if skills:
        blocks = []
        for s in skills:
            name = (s.get("name") or "").strip()
            content = (s.get("content") or "").strip()
            if content:
                blocks.append(f"### {name}\n{content}" if name else content)
        if blocks:
            prompt += "\n\n## Skills\nApply these when relevant:\n\n" + "\n\n".join(blocks)

    if ui_context:
        prompt += f"\n\n## Current dashboard context\n{ui_context.strip()}"
    return prompt


def _history_messages(history: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for m in (history or [])[-20:]:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


# ------------------------------------------------------------------- the loop

def _sse(payload: Dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


def _run_loop(put: Callable[[Optional[bytes]], None], *, obo_token: Optional[str],
              query: str, ui_context: str, profile: Optional[Dict[str, Any]],
              history: Optional[List[Dict[str, Any]]]) -> None:
    """Synchronous tool-calling loop. Pushes SSE frames via ``put``."""
    try:
        ws = _obo_ws(obo_token)
        client = _openai_client(ws, obo_token)
        model = (profile or {}).get("model") or _model_default()

        specs, dispatch = _build_tools(ws, profile)

        messages: List[Dict[str, Any]] = [{"role": "system", "content": _system_prompt(profile, ui_context)}]
        messages.extend(_history_messages(history))
        messages.append({"role": "user", "content": query})

        used_tools: List[Dict[str, str]] = []
        full_text = ""

        for _ in range(_max_steps()):
            kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": True,
                "max_tokens": _max_tokens(),
            }
            if specs:
                kwargs["tools"] = specs
                kwargs["tool_choice"] = "auto"

            stream = client.chat.completions.create(**kwargs)

            turn_text = ""
            tool_acc: Dict[int, Dict[str, str]] = {}
            finish = None
            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if getattr(delta, "content", None):
                    turn_text += delta.content
                    full_text += delta.content
                    put(_sse({"type": "chunk", "content": delta.content}))
                for tc in (getattr(delta, "tool_calls", None) or []):
                    slot = tool_acc.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn and fn.name:
                        slot["name"] = fn.name
                    if fn and fn.arguments:
                        slot["args"] += fn.arguments
                if choice.finish_reason:
                    finish = choice.finish_reason

            if not tool_acc:
                # No tools requested this turn -> this is the final answer.
                put(_sse({"type": "final", "content": full_text.strip() or turn_text.strip()}))
                put(None)
                return

            # Append the assistant's tool-call turn, then execute each tool.
            messages.append({
                "role": "assistant",
                "content": turn_text or None,
                "tool_calls": [
                    {
                        "id": s["id"] or f"call_{i}",
                        "type": "function",
                        "function": {"name": s["name"], "arguments": s["args"] or "{}"},
                    }
                    for i, s in sorted(tool_acc.items())
                ],
            })

            for i, s in sorted(tool_acc.items()):
                fn = s["name"]
                desc = dispatch.get(fn)
                try:
                    args = json.loads(s["args"]) if s["args"].strip() else {}
                except json.JSONDecodeError:
                    args = {}
                if desc is None:
                    result = f"Unknown tool '{fn}'."
                    friendly = fn
                else:
                    friendly = desc["friendly"]
                    result = _run_tool(ws, desc, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": s["id"] or f"call_{i}",
                    "content": result,
                })
                used_tools.append({"tool_name": friendly, "status": "done"})

            # Emit the cumulative pill list (the UI replaces the whole array).
            put(_sse({"type": "tool_calls", "content": list(used_tools)}))

        # Ran out of steps — surface whatever we have.
        put(_sse({"type": "final", "content": (full_text.strip() or "I wasn't able to complete that within the step limit.")}))
        put(None)
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent runtime loop failed")
        put(_sse({"type": "error", "content": str(exc)}))
        put(None)


async def stream_chat(*, obo_token: Optional[str], query: str, ui_context: str = "",
                      profile: Optional[Dict[str, Any]] = None,
                      history: Optional[List[Dict[str, Any]]] = None):
    """Async SSE generator wrapping the sync loop.

    The blocking loop (LLM stream + tool calls) runs on a worker thread and
    pushes frames onto an asyncio queue; the async side drains it and emits a
    ``: keepalive`` comment during idle gaps (e.g. a 30-60s Genie tool call) so
    no intermediary drops the connection.
    """
    loop = asyncio.get_running_loop()
    q: "asyncio.Queue[Optional[bytes]]" = asyncio.Queue()

    def _put(item: Optional[bytes]) -> None:
        loop.call_soon_threadsafe(q.put_nowait, item)

    def _worker() -> None:
        _run_loop(
            _put,
            obo_token=obo_token,
            query=query,
            ui_context=ui_context,
            profile=profile,
            history=history,
        )

    threading.Thread(target=_worker, daemon=True).start()

    hb = _heartbeat_secs()
    try:
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=hb)
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
                continue
            if item is None:
                break
            yield item
    finally:
        yield b"data: [DONE]\n\n"
