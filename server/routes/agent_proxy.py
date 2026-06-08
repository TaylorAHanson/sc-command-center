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
        headers["X-Forwarded-Access-Token"] = token
        # Also pass as a Bearer token so a protected agent App accepts the call.
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
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{AGENT_BASE_URL}/chat",
                    content=body,
                    headers=forwarded,
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


@router.post("/clear_chat")
async def proxy_clear_chat(request: Request):
    """Proxy a clear-chat request to the agent."""
    try:
        body = await request.body()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
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


@router.get("/health")
async def agent_health():
    """Report whether the configured agent service is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AGENT_BASE_URL}/")
        return {"reachable": resp.status_code < 500, "agent_url": AGENT_BASE_URL}
    except Exception:  # noqa: BLE001
        return {"reachable": False, "agent_url": AGENT_BASE_URL}
