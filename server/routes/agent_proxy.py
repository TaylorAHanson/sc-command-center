"""
Agent proxy routes.

Forwards chat traffic from the Command Center frontend to the external
Supply Chain Agent service. The agent lives in its own codebase/deployment so
it can be reused as a template; the Command Center only ever talks to its HTTP
API. Routing through this backend (rather than calling the agent directly from
the browser) keeps the agent's URL/credentials server-side, per the governance
rules in the README.
"""
import os
import json
import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Base URL of the external agent service. Defaults to the agent's local dev
# backend. NOTE: the agent backend must run on a different port than the
# Command Center backend (which uses 8000) when developing locally. In
# production, set this in app.yaml to the deployed agent App's URL.
AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8001").rstrip("/")

# A single AsyncClient reused across requests. Creating a fresh client per call
# (the old behaviour) paid a new TCP + TLS handshake every time — wasteful at
# scale and especially for the Genie polling loop, which fires repeatedly. The
# client is created lazily inside the running event loop and closed on app
# shutdown via close_http_client(). Each uvicorn worker gets its own instance.
_client: "httpx.AsyncClient | None" = None


def get_http_client() -> "httpx.AsyncClient":
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            # Default per-request timeout; streaming endpoints override read=None.
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


def _forwarded_headers(request: Request) -> dict:
    """
    Build the headers we forward to the agent. Critically this carries the
    user's OBO token through so the agent acts on behalf of the signed-in user
    (per the README's OBO governance rule) rather than its own service
    principal. Databricks Apps inject the token as `x-forwarded-access-token`.
    """
    headers = {"Content-Type": "application/json"}
    token = (
        request.headers.get("x-forwarded-access-token")
        or request.headers.get("X-Forwarded-Access-Token")
    )
    if token:
        # The agent is a separate Databricks App; its OAuth proxy STRIPS/overwrites the standard
        # X-Forwarded-* headers, so the agent never sees the user token there. Forward it under a
        # custom header the platform leaves untouched (the agent reads X-OBO-Token first).
        headers["X-OBO-Token"] = token
        headers["X-Forwarded-Access-Token"] = token
        # Also pass as a Bearer token so the protected agent App accepts the call.
        headers["Authorization"] = f"Bearer {token}"
    return headers


@router.post("/chat")
async def proxy_chat(request: Request):
    """
    Proxy a chat request to the agent and stream its Server-Sent Events back to
    the browser unchanged.
    """
    try:
        body = await request.body()
    except Exception as e:
        return JSONResponse({"error": f"Invalid request body: {e}"}, status_code=400)

    forwarded = _forwarded_headers(request)

    async def event_stream():
        try:
            client = get_http_client()
            # read=None: token gaps between SSE events can be long, so we don't
            # want a read timeout killing a healthy stream — but we keep a connect
            # timeout so an unreachable agent fails fast.
            async with client.stream(
                "POST",
                f"{AGENT_BASE_URL}/chat",
                content=body,
                headers=forwarded,
                timeout=httpx.Timeout(30.0, read=None),
            ) as upstream:
                if upstream.status_code >= 400:
                    text = await upstream.aread()
                    detail = text.decode("utf-8", errors="replace")
                    logger.warning("Agent /chat returned %s: %s", upstream.status_code, detail)
                    yield f"data: {json.dumps({'type': 'chunk', 'content': f'Agent error ({upstream.status_code}).'})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                async for chunk in upstream.aiter_raw():
                    if chunk:
                        yield chunk
        except httpx.ConnectError:
            logger.error("Could not connect to agent at %s", AGENT_BASE_URL)
            yield f"data: {json.dumps({'type': 'chunk', 'content': 'Could not reach the agent service. Is it running?'})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:  # noqa: BLE001
            logger.exception("Error proxying agent chat")
            yield f"data: {json.dumps({'type': 'chunk', 'content': f'Agent proxy error: {e}'})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/genie/poll")
async def proxy_genie_poll(request: Request):
    """Proxy a single Genie poll to the agent (short request; the client loops these).

    Carries the user's OBO token so Genie runs as the signed-in user and the conversation
    shows up in their Databricks One history.
    """
    try:
        body = await request.body()
        resp = await get_http_client().post(
            f"{AGENT_BASE_URL}/genie/poll",
            content=body,
            headers=_forwarded_headers(request),
            timeout=60.0,
        )
        return JSONResponse(
            content=resp.json() if resp.content else {"status": "failed", "error": "empty response"},
            status_code=resp.status_code,
        )
    except httpx.ConnectError:
        return JSONResponse({"status": "failed", "error": "Could not reach the agent service."}, status_code=502)
    except Exception as e:  # noqa: BLE001
        logger.exception("Error proxying genie poll")
        return JSONResponse({"status": "failed", "error": str(e)}, status_code=500)


@router.post("/genie/resume")
async def proxy_genie_resume(request: Request):
    """Proxy a Genie resume (records the completed answer in the agent's session history)."""
    try:
        body = await request.body()
        resp = await get_http_client().post(
            f"{AGENT_BASE_URL}/genie/resume",
            content=body,
            headers=_forwarded_headers(request),
        )
        return JSONResponse(
            content=resp.json() if resp.content else {"status": "ok"},
            status_code=resp.status_code,
        )
    except httpx.ConnectError:
        return JSONResponse({"error": "Could not reach the agent service."}, status_code=502)
    except Exception as e:  # noqa: BLE001
        logger.exception("Error proxying genie resume")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/clear_chat")
async def proxy_clear_chat(request: Request):
    """Proxy a clear-chat request to the agent."""
    try:
        body = await request.body()
        resp = await get_http_client().post(
            f"{AGENT_BASE_URL}/clear_chat",
            content=body,
            headers=_forwarded_headers(request),
        )
        return JSONResponse(
            content=resp.json() if resp.content else {"status": "ok"},
            status_code=resp.status_code,
        )
    except httpx.ConnectError:
        return JSONResponse({"error": "Could not reach the agent service."}, status_code=502)
    except Exception as e:  # noqa: BLE001
        logger.exception("Error proxying clear_chat")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/tools-and-skills")
async def proxy_tools_and_skills(request: Request):
    """
    Proxy the agent's tool/skill discovery. Forwards the user's OBO token so the
    agent returns only the Unity Catalog functions/volumes the signed-in user is
    entitled to (per-user governance).
    """
    try:
        resp = await get_http_client().get(
            f"{AGENT_BASE_URL}/tools-and-skills",
            headers=_forwarded_headers(request),
            timeout=60.0,
        )
        return JSONResponse(
            content=resp.json() if resp.content else {"tools": [], "skills": []},
            status_code=resp.status_code,
        )
    except httpx.ConnectError:
        return JSONResponse(
            {"tools": [], "skills": [], "error": "Could not reach the agent service."},
            status_code=502,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Error proxying tools-and-skills")
        return JSONResponse({"tools": [], "skills": [], "error": str(e)}, status_code=500)


@router.get("/user-skills")
async def proxy_list_user_skills(request: Request):
    """List the signed-in user's personal skills (stored in their workspace folder)."""
    try:
        resp = await get_http_client().get(
            f"{AGENT_BASE_URL}/user-skills",
            headers=_forwarded_headers(request),
        )
        return JSONResponse(content=resp.json() if resp.content else {"skills": []}, status_code=resp.status_code)
    except httpx.ConnectError:
        return JSONResponse({"skills": [], "error": "Could not reach the agent service."}, status_code=502)
    except Exception as e:  # noqa: BLE001
        logger.exception("Error proxying list user-skills")
        return JSONResponse({"skills": [], "error": str(e)}, status_code=500)


@router.get("/user-skills/{name}")
async def proxy_get_user_skill(name: str, request: Request):
    """Read the content of one personal skill."""
    try:
        resp = await get_http_client().get(
            f"{AGENT_BASE_URL}/user-skills/{name}",
            headers=_forwarded_headers(request),
        )
        return JSONResponse(content=resp.json() if resp.content else {}, status_code=resp.status_code)
    except httpx.ConnectError:
        return JSONResponse({"error": "Could not reach the agent service."}, status_code=502)
    except Exception as e:  # noqa: BLE001
        logger.exception("Error proxying get user-skill")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.put("/user-skills")
async def proxy_save_user_skill(request: Request):
    """Create or update a personal skill."""
    try:
        body = await request.body()
        resp = await get_http_client().put(
            f"{AGENT_BASE_URL}/user-skills",
            content=body,
            headers=_forwarded_headers(request),
        )
        return JSONResponse(content=resp.json() if resp.content else {"status": "saved"}, status_code=resp.status_code)
    except httpx.ConnectError:
        return JSONResponse({"error": "Could not reach the agent service."}, status_code=502)
    except Exception as e:  # noqa: BLE001
        logger.exception("Error proxying save user-skill")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/user-skills/{name}")
async def proxy_delete_user_skill(name: str, request: Request):
    """Delete a personal skill."""
    try:
        resp = await get_http_client().delete(
            f"{AGENT_BASE_URL}/user-skills/{name}",
            headers=_forwarded_headers(request),
        )
        return JSONResponse(content=resp.json() if resp.content else {"status": "deleted"}, status_code=resp.status_code)
    except httpx.ConnectError:
        return JSONResponse({"error": "Could not reach the agent service."}, status_code=502)
    except Exception as e:  # noqa: BLE001
        logger.exception("Error proxying delete user-skill")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/health")
async def agent_health():
    """Report whether the configured agent service is reachable."""
    try:
        resp = await get_http_client().get(f"{AGENT_BASE_URL}/", timeout=5.0)
        return {"reachable": resp.status_code < 500, "agent_url": AGENT_BASE_URL}
    except Exception:  # noqa: BLE001
        return {"reachable": False, "agent_url": AGENT_BASE_URL}
