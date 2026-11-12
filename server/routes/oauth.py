"""Connecting someone's account so their scheduled work runs as them.

The vault is `services/token_vault.py`; these are its four doors, mounted at
`/api/oauth`. `connect` and `callback` are top-level browser navigations, so every
outcome is a redirect back into the app with `oauth=connected` or
`oauth_error=<reason>` on the return address, never a JSON error page. `status` and
`disconnect` are ordinary calls. All four act only for the signed-in caller,
identified by their forwarded token, and none of them returns a token.
"""

import logging
from datetime import datetime
from typing import Optional

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from middleware.auth import get_db_client
from services import caller_identity, token_vault

logger = logging.getLogger(__name__)

router = APIRouter()


def _redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=302)
    # Carries a sign-in's state or outcome; a cached copy replayed later would be wrong.
    response.headers["Cache-Control"] = "no-store"
    return response


def _back(return_to: str, error: str = "") -> RedirectResponse:
    if error:
        return _redirect(token_vault.with_outcome(return_to, "oauth_error", error))
    return _redirect(token_vault.with_outcome(return_to, "oauth", "connected"))


def callback_url_for(request: Request) -> str:
    url = token_vault.callback_url(
        forwarded_host=request.headers.get("x-forwarded-host"),
        host=request.headers.get("host"),
        scheme=request.headers.get("x-forwarded-proto") or request.url.scheme,
    )
    expected = token_vault.callback_url()
    if url and expected and url != expected:
        # The browser reached the app at an address other than the one the Setup
        # card tells admins to register, so the workspace will refuse the redirect.
        logger.warning("Sign-in redirect URL %s differs from the expected %s; set OAUTH_REDIRECT_URI if the "
                       "integration has only the latter", url, expected)
    return url


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


@router.get("/connect")
def connect(request: Request, return_to: str = "/", w: WorkspaceClient = Depends(get_db_client)):
    target = token_vault.safe_return_to(return_to) or "/"
    try:
        url = token_vault.begin_connect(caller_identity.username(w), callback_url_for(request), target)
    except token_vault.ConnectError as e:
        return _back(e.return_to, e.reason)
    return _redirect(url)


@router.get("/callback")
def callback(code: str = "", state: str = "", error: str = "", w: WorkspaceClient = Depends(get_db_client)):
    try:
        target = token_vault.complete_connect(caller_identity.username(w), code=code, state=state, error=error)
    except token_vault.ConnectError as e:
        return _back(e.return_to, e.reason)
    return _back(target)


@router.get("/status")
def connection_status(w: WorkspaceClient = Depends(get_db_client)):
    user = caller_identity.username(w)
    try:
        body = token_vault.status(user)
    except Exception as e:  # noqa: BLE001
        logger.warning("Couldn't read %s's connection status: %s", user, type(e).__name__)
        raise HTTPException(status_code=503, detail="Couldn't read your connection status. Try again shortly.")
    return {**body, "connected_at": _iso(body["connected_at"]), "expires_at": _iso(body["expires_at"])}


@router.post("/disconnect")
def disconnect(w: WorkspaceClient = Depends(get_db_client)):
    user = caller_identity.username(w)
    try:
        removed = token_vault.disconnect(user)
    except Exception as e:  # noqa: BLE001
        logger.warning("Couldn't disconnect %s: %s", user, type(e).__name__)
        raise HTTPException(status_code=503, detail="Couldn't disconnect your account. Try again shortly.")
    return {"disconnected": removed}
