"""
Agent chat routes for the Command Center EDH drawer.

Primary path (``AGENT_LOCAL_RUNTIME=true``, the default): the chat turn runs
**in this process** via ``services.agent_runtime`` — a small tool-calling loop
over the AI Gateway (LLM + MCP tools) plus author Python tools, all executed
under the caller's own OBO token. This removes the previous app->app hop to the
Self-Service runtime, whose second Databricks App front door produced per-user
401/403s (it authorized the *calling app's* service principal, not the user).

Fallback path (``AGENT_LOCAL_RUNTIME=false``): forward to the **consolidated
Self-Service agent runtime** (``qc-selfservice-v3`` ``/api/v1/agent``) at
``CONSOLIDATED_AGENT_URL``, adapting between the two wire shapes.

Either way the drawer frontend (``useAgentChat``) is unchanged: it POSTs
``/api/agent/chat`` and consumes ``data: {type, content}`` SSE events. Resolving
saved profiles in-process (under the user's OBO token) is shared by both paths.

Cutover notes:
- The legacy standalone "Supply Chain Agent" is retired; ``CONSOLIDATED_AGENT_URL``
  must point at the Self-Service app. ``AGENT_BASE_URL`` is still honored as a
  fallback for existing deployments.
- Genie async: the Self-Service runtime emits a ``pending_poll`` event and is
  drained by the drawer's existing poll loop, which we adapt to the runtime's
  ``/poll/genie`` endpoint.
- Multi-turn history: the drawer owns the transcript and forwards it as
  ``conversation_history`` on each call, which we pass through to the stateless
  runtime so it has prior-turn context.
"""
import os
import json
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Base URL of the consolidated Self-Service agent runtime. In production set
# CONSOLIDATED_AGENT_URL in databricks.yml to the deployed Self-Service App URL. For
# local dev it must point at the Self-Service backend (a different port than the
# Command Center backend). AGENT_BASE_URL is kept as a fallback for compatibility
# with the pre-cutover configuration.
CONSOLIDATED_AGENT_URL = (
    os.environ.get("CONSOLIDATED_AGENT_URL")
    or os.environ.get("AGENT_BASE_URL")
    or "http://localhost:8000"
).rstrip("/")

# All Self-Service agent endpoints live under this prefix.
API = "/api/v1"

# House style appended to every agent turn. The consolidated runtime is shared
# infrastructure we don't own, and individual profiles shouldn't have to repeat
# basic formatting rules, so we inject them here for every turn — saved profile,
# Agent Studio "Try it" draft, or the default agent. Driven by an env flag so it
# can be tuned/disabled without a code change.
HOUSE_STYLE = (
    "\n\n## Output style (non-negotiable)\n"
    "- Do NOT use emojis, emoticons, or decorative Unicode symbols anywhere in "
    "your responses — not in prose, headings, bullets, tables, or status lines. "
    "Use plain text only.\n"
    "- Prefer clear, professional prose over emoji-driven formatting."
)
# Run the agent IN THIS PROCESS (no app->app hop to the Self-Service runtime).
# Default on: this is now the primary path. Set AGENT_LOCAL_RUNTIME=false to fall
# back to forwarding to CONSOLIDATED_AGENT_URL. Running locally consumes the
# browser's x-forwarded-access-token in-process, so there is no second Databricks
# App front door to authorize — which is what produced the per-user 401/403s.
LOCAL_RUNTIME = os.environ.get("AGENT_LOCAL_RUNTIME", "true").lower() not in (
    "0",
    "false",
    "no",
)

INJECT_HOUSE_STYLE = os.environ.get("AGENT_INJECT_HOUSE_STYLE", "true").lower() not in (
    "0",
    "false",
    "no",
)

_client: "httpx.AsyncClient | None" = None


def get_http_client() -> "httpx.AsyncClient":
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _client


async def close_http_client() -> None:
    """Close the shared client. Wired to FastAPI shutdown in main.py."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


# Saved-profile resolution cache. A selected Agent Studio profile is resolved
# to its full content HERE (in-process, under the user's own OBO token) and
# forwarded to the runtime as an ``inline_profile`` — the same path the Studio
# "Try it" uses, which avoids making the runtime re-read the profile file under
# a forwarded, app-to-app token (Databricks Apps re-derives the forwarded token
# on app->app calls, so the runtime would often read as its own SP and fail to
# see the user's personal ``.agents`` folder). Keyed by (token fingerprint,
# profile_ref) so each caller only ever resolves what their own grants permit.
_PROFILE_RESOLVE_TTL_S = 30.0
_profile_resolve_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _resolve_inline_profile(token: Optional[str], profile_ref: str, env: str = "dev") -> Optional[Dict[str, Any]]:
    """Resolve a saved ``profile_ref`` (a DB profile id) to an inline profile spec.

    Returns the runtime's inline_profile shape (name/prompt/tools/skills/
    python_tools/model/base). On any failure (not found, no access) returns None
    so the caller can fall back to forwarding the raw ``profile_ref`` (and the
    runtime's own "profile unavailable" fail-safe still applies). The store
    enforces read visibility under the caller's own token, so a user can only
    resolve agents they're allowed to see.
    """
    if not profile_ref:
        return None
    key = hashlib.sha256(f"{token or 'anon'}|{env}|{profile_ref}".encode("utf-8")).hexdigest()
    now = time.monotonic()
    hit = _profile_resolve_cache.get(key)
    if hit and (now - hit[0]) < _PROFILE_RESOLVE_TTL_S:
        return hit[1]
    try:
        from agent_studio_store import get_agent_studio_store

        ref = get_agent_studio_store().get_profile(token, profile_ref, env=env)
        spec: Dict[str, Any] = {
            "name": ref.name,
            "prompt": ref.prompt or "",
            "tools": list(ref.tools or []),
            "model": ref.model or "",
            "base": getattr(ref, "base", "full") or "full",
            "skills": [
                {"name": s.name, "content": s.content}
                for s in (ref.skills or [])
            ],
            "python_tools": [
                {"name": t.name, "description": t.description, "code": t.code}
                for t in (getattr(ref, "python_tools", None) or [])
            ],
        }
    except Exception as exc:  # noqa: BLE001 - never break chat on resolve failure
        logger.warning("Could not resolve profile_ref %s to inline: %s", profile_ref, exc)
        return None
    if len(_profile_resolve_cache) > 200:
        _profile_resolve_cache.clear()
    _profile_resolve_cache[key] = (now, spec)
    return spec


def _forwarded_headers(request: Request) -> dict:
    """Headers forwarded to the runtime; carries the user's OBO token.

    The Self-Service runtime's ``AuthMiddleware`` reads ``x-forwarded-access-token``.
    We also send a Bearer token so its App OAuth proxy accepts the call.
    """
    headers = {"Content-Type": "application/json"}
    token = (
        request.headers.get("x-forwarded-access-token")
        or request.headers.get("X-Forwarded-Access-Token")
    )
    if token:
        headers["X-Forwarded-Access-Token"] = token
        headers["X-OBO-Token"] = token
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ------------------------------------------------------------------ SSE adapt

def _frame(payload: Dict[str, Any]) -> bytes:
    """Render one drawer-shaped SSE frame (``data: {json}\\n\\n``)."""
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


def _iter_sse_events(buffer: str):
    """Yield (event_type, data_dict) for complete frames in ``buffer``.

    Returns the unparsed remainder so the caller can carry it across chunks.
    Self-Service frames look like ``event: <type>\\ndata: <json>\\n\\n``.
    """
    events: List[tuple] = []
    while "\n\n" in buffer:
        raw_frame, buffer = buffer.split("\n\n", 1)
        event_type: Optional[str] = None
        data_lines: List[str] = []
        for line in raw_frame.split("\n"):
            line = line.rstrip("\r")
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip())
        if not data_lines:
            continue
        try:
            data = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        events.append((event_type or data.get("type"), data))
    return events, buffer


@router.post("/chat")
async def proxy_chat(request: Request):
    """Proxy a chat turn to the Self-Service runtime, adapting both wire shapes."""
    try:
        incoming = await request.json()
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"Invalid request body: {e}"}, status_code=400)

    query = (incoming.get("query") or "").strip()
    user_prompt = incoming.get("user_prompt") or ""
    # The drawer's dashboard context + custom instructions ride in user_prompt;
    # forward them as request context so the runtime appends them to the prompt.
    context: Dict[str, Any] = {}
    if user_prompt:
        context["ui_context"] = user_prompt
    profile_ref = incoming.get("profile_ref")  # Phase 4 agent picker
    # Agent Studio "Try it": an UNSAVED draft profile to run this turn as. The
    # runtime applies it with the same governance as a saved profile.
    inline_profile = incoming.get("inline_profile")

    forwarded = _forwarded_headers(request)

    # Diagnostics for the app->app auth handoff. A 401 from the consolidated app
    # with NO logs on its side means its front-door OAuth proxy rejected us
    # before the request reached its code. The two distinguishable causes are:
    #   (a) obo_forwarded=False -> the incoming request into THIS app had no
    #       x-forwarded-access-token, so we sent no Authorization -> front door
    #       401s. Root cause is on the Command Center side (the user hasn't been
    #       granted / hasn't consented to this app's user_api_scopes, so no OBO
    #       token is minted for them).
    #   (b) obo_forwarded=True but still 401 -> the token is fine to reach us but
    #       the consolidated app's front door won't authorize THAT user (they
    #       lack "Can Use" on the consolidated app itself).
    caller_email = (
        request.headers.get("x-forwarded-email")
        or request.headers.get("X-Forwarded-Email")
        or request.headers.get("x-forwarded-user")
        or "unknown"
    )
    obo_forwarded = "Authorization" in forwarded
    logger.info(
        "proxy_chat: caller=%s obo_forwarded=%s -> %s",
        caller_email, obo_forwarded, CONSOLIDATED_AGENT_URL,
    )

    # Resolve a SAVED profile here (in-process, under the user's own OBO token)
    # and send it inline, so the runtime never has to re-read the profile file
    # under a forwarded app->app token. If resolution fails we fall back to
    # forwarding the raw ref and let the runtime's fail-safe surface the error.
    if profile_ref and not inline_profile:
        token = (
            request.headers.get("x-forwarded-access-token")
            or request.headers.get("X-Forwarded-Access-Token")
        )
        env = (incoming.get("env") or "dev").strip() or "dev"
        resolved = _resolve_inline_profile(token, profile_ref, env)
        if resolved is not None:
            inline_profile = resolved
            profile_ref = None  # inline takes precedence; avoid an ambiguous body

    # Inject global house style (e.g. "no emojis") so every agent obeys it
    # without each profile having to restate it. When a profile is active we
    # append to its system prompt (most authoritative); for the default agent
    # (no inline profile) we ride along on ui_context, which the runtime appends
    # to the prompt.
    if INJECT_HOUSE_STYLE:
        if isinstance(inline_profile, dict):
            inline_profile["prompt"] = f"{(inline_profile.get('prompt') or '').rstrip()}{HOUSE_STYLE}"
        else:
            existing = context.get("ui_context") or ""
            context["ui_context"] = f"{existing.rstrip()}{HOUSE_STYLE}" if existing else HOUSE_STYLE.lstrip()

    # Forward the drawer's transcript so the stateless runtime has multi-turn
    # context. The drawer sends ChatMessage-shaped entries (id/type/content/
    # timestamp); pass them through verbatim (already bounded client-side).
    conversation_history = incoming.get("conversation_history") or None

    # --- In-process runtime (primary path) --------------------------------
    # Run the chat loop here, under the caller's own OBO token, instead of
    # forwarding to a second app. Same SSE wire shape the drawer already reads.
    if LOCAL_RUNTIME:
        from services.agent_runtime import stream_chat

        obo_token = (
            request.headers.get("x-forwarded-access-token")
            or request.headers.get("X-Forwarded-Access-Token")
        )
        # The drawer maps its transcript to {role, content}; normalize the
        # runtime's expected shape (accept either `role` or `type`).
        norm_history = None
        if conversation_history:
            norm_history = [
                {
                    "role": (m.get("role") or m.get("type") or ""),
                    "content": m.get("content") or "",
                }
                for m in conversation_history
                if isinstance(m, dict)
            ]
        logger.info("proxy_chat[local]: caller=%s obo_forwarded=%s", caller_email, bool(obo_token))
        return StreamingResponse(
            stream_chat(
                obo_token=obo_token,
                query=query,
                ui_context=context.get("ui_context") or "",
                profile=inline_profile if isinstance(inline_profile, dict) else None,
                history=norm_history,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    body = {
        "query": query,
        "context": context or None,
        "profile_ref": profile_ref,
        "inline_profile": inline_profile,
        "conversation_history": conversation_history,
    }
    last_query = query

    async def event_stream():
        # Accumulated tool-call pills, surfaced to the drawer as a replaceable list.
        tool_calls: List[Dict[str, str]] = []
        tool_index: Dict[str, int] = {}
        try:
            client = get_http_client()
            async with client.stream(
                "POST",
                f"{CONSOLIDATED_AGENT_URL}{API}/agent/conversation/stream",
                content=json.dumps(body).encode("utf-8"),
                headers=forwarded,
                timeout=httpx.Timeout(30.0, read=None),
            ) as upstream:
                if upstream.status_code >= 400:
                    text = await upstream.aread()
                    detail = text.decode("utf-8", errors="replace")
                    # www-authenticate / a redirect to a login page are tell-tale
                    # signs the front-door proxy (not the app) rejected us.
                    logger.warning(
                        "Runtime /conversation/stream %s for caller=%s (obo_forwarded=%s) "
                        "www-authenticate=%r content-type=%r body=%s",
                        upstream.status_code,
                        caller_email,
                        obo_forwarded,
                        upstream.headers.get("www-authenticate"),
                        upstream.headers.get("content-type"),
                        detail[:500],
                    )
                    if upstream.status_code in (401, 403):
                        hint = (
                            "Authentication token was not forwarded — you may need to grant this "
                            "user the app's user API scopes."
                            if not obo_forwarded
                            else "Your account may not have 'Can Use' access to the agent app."
                        )
                        yield _frame({"type": "error", "content": f"Agent access denied ({upstream.status_code}). {hint}"})
                    else:
                        yield _frame({"type": "error", "content": f"Agent error ({upstream.status_code})."})
                    yield b"data: [DONE]\n\n"
                    return

                buffer = ""
                async for chunk in upstream.aiter_text():
                    buffer += chunk
                    events, buffer = _iter_sse_events(buffer)
                    for etype, data in events:
                        if etype == "reasoning":
                            yield _frame({"type": "reasoning", "content": data.get("text", "")})
                        elif etype == "message":
                            yield _frame({"type": "final", "content": data.get("content", "")})
                        elif etype == "tool_call":
                            tid = data.get("id") or data.get("name") or str(len(tool_calls))
                            label = data.get("friendly_label") or data.get("name") or "tool"
                            if tid not in tool_index:
                                tool_index[tid] = len(tool_calls)
                                tool_calls.append({"tool_name": label, "status": "running"})
                            yield _frame({"type": "tool_calls", "content": tool_calls})
                        elif etype == "tool_result":
                            tid = data.get("id") or data.get("name")
                            idx = tool_index.get(tid)
                            if idx is not None:
                                tool_calls[idx]["status"] = "done" if data.get("ok", True) else "error"
                                yield _frame({"type": "tool_calls", "content": tool_calls})
                        elif etype == "pending_poll":
                            ids = data.get("ids") or {}
                            yield _frame({
                                "type": "pending_poll",
                                "conversation_id": ids.get("conversation_id"),
                                "response_id": ids.get("message_id") or ids.get("response_id"),
                                "space_id": ids.get("space_id") or "",
                                "question": ids.get("question") or last_query,
                            })
                        elif etype == "route":
                            path = data.get("path") or ""
                            title = data.get("title") or "Continue"
                            if path:
                                yield _frame({"type": "chunk", "content": f"\n\n[{title}]({path})"})
                        elif etype == "error":
                            yield _frame({"type": "error", "content": data.get("message", "Unknown error")})
                        elif etype == "done":
                            if data.get("trace_id"):
                                yield _frame({"type": "trace_id", "content": data["trace_id"]})
                yield b"data: [DONE]\n\n"
        except httpx.ConnectError:
            logger.error("Could not connect to runtime at %s", CONSOLIDATED_AGENT_URL)
            yield _frame({"type": "error", "content": "Could not reach the agent service. Is it running?"})
            yield b"data: [DONE]\n\n"
        except Exception as e:  # noqa: BLE001
            logger.exception("Error proxying agent chat")
            yield _frame({"type": "error", "content": f"Agent proxy error: {e}"})
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


def _genie_answer_text(payload: Dict[str, Any]) -> str:
    """Pull a human-readable answer from a Self-Service Genie poll payload."""
    if not isinstance(payload, dict):
        return ""
    for key in ("final_answer", "text", "_stream_narration"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


@router.post("/genie/poll")
async def proxy_genie_poll(request: Request):
    """Adapt the drawer's Genie poll to the runtime's ``/poll/genie`` endpoint."""
    try:
        incoming = await request.json()
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"status": "failed", "error": f"Invalid body: {e}"}, status_code=400)

    body = {
        "conversation_id": incoming.get("conversation_id"),
        "message_id": incoming.get("response_id"),
        "space_id": incoming.get("space_id") or None,
        "question": incoming.get("question"),
    }
    try:
        resp = await get_http_client().post(
            f"{CONSOLIDATED_AGENT_URL}{API}/agent/poll/genie",
            content=json.dumps(body).encode("utf-8"),
            headers=_forwarded_headers(request),
            timeout=60.0,
        )
        data = resp.json() if resp.content else {}
    except httpx.ConnectError:
        return JSONResponse({"status": "failed", "error": "Could not reach the agent service."}, status_code=502)
    except Exception as e:  # noqa: BLE001
        logger.exception("Error proxying genie poll")
        return JSONResponse({"status": "failed", "error": str(e)}, status_code=500)

    status = data.get("status")
    if status == "complete":
        result = data.get("result") or {}
        return JSONResponse({
            "status": "complete",
            "answer": _genie_answer_text(result),
            "final": result.get("final_answer") if isinstance(result, dict) else None,
            "deep_link": result.get("_deep_link") if isinstance(result, dict) else None,
        })
    if status == "failed":
        return JSONResponse({"status": "failed", "error": data.get("error") or "Genie query failed."})
    partial = data.get("partial") or {}
    return JSONResponse({
        "status": "running",
        "answer": _genie_answer_text(partial),
        "final": partial.get("final_answer") if isinstance(partial, dict) else "",
        "attempt_after_ms": data.get("attempt_after_ms") or 3000,
    })


@router.post("/genie/resume")
async def proxy_genie_resume(request: Request):
    """No-op under the consolidated runtime (it is stateless per call)."""
    return JSONResponse({"status": "ok"})


@router.post("/clear_chat")
async def proxy_clear_chat(request: Request):
    """No-op: the consolidated runtime keeps no server-side session."""
    return JSONResponse({"status": "ok"})


@router.get("/tools-and-skills")
async def proxy_tools_and_skills(request: Request):
    """Aggregate the runtime's EDH tools + skills into the drawer's shape."""
    headers = _forwarded_headers(request)
    tools: List[Dict[str, Any]] = []
    skills: List[str] = []
    try:
        tr = await get_http_client().get(
            f"{CONSOLIDATED_AGENT_URL}{API}/agent/tools", headers=headers, timeout=30.0
        )
        if tr.status_code < 400 and tr.content:
            for t in (tr.json().get("tools") or []):
                tools.append({"name": t.get("name"), "type": "tool", "always_on": False})
    except Exception as e:  # noqa: BLE001
        logger.warning("tools fetch failed: %s", e)

    try:
        sr = await get_http_client().get(
            f"{CONSOLIDATED_AGENT_URL}{API}/skills", headers=headers, timeout=30.0
        )
        if sr.status_code < 400 and sr.content:
            payload = sr.json()
            items = payload.get("skills") if isinstance(payload, dict) else payload
            for s in (items or []):
                name = s.get("name") if isinstance(s, dict) else s
                if name:
                    skills.append(name)
    except Exception as e:  # noqa: BLE001
        logger.warning("skills fetch failed: %s", e)

    return JSONResponse({
        "tools": tools,
        "skills": skills,
        "default_tools": [t["name"] for t in tools if t.get("name")],
        "default_skills": [],
    })


@router.get("/user-skills")
async def proxy_list_user_skills(request: Request):
    """List the user's skills (read-only; authoring lives in the Agent Studio)."""
    try:
        resp = await get_http_client().get(
            f"{CONSOLIDATED_AGENT_URL}{API}/skills", headers=_forwarded_headers(request), timeout=30.0
        )
        if resp.status_code < 400 and resp.content:
            payload = resp.json()
            items = payload.get("skills") if isinstance(payload, dict) else payload
            return JSONResponse({"skills": items or []})
    except Exception as e:  # noqa: BLE001
        logger.warning("user-skills list failed: %s", e)
    return JSONResponse({"skills": []})


@router.get("/health")
async def agent_health():
    """Report whether the consolidated runtime is reachable."""
    try:
        resp = await get_http_client().get(f"{CONSOLIDATED_AGENT_URL}/health", timeout=5.0)
        return {"reachable": resp.status_code < 500, "agent_url": CONSOLIDATED_AGENT_URL}
    except Exception:  # noqa: BLE001
        return {"reachable": False, "agent_url": CONSOLIDATED_AGENT_URL}
