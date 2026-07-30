
"""
Authentication middleware for handling OBO (On-Behalf-Of) tokens from Databricks Apps.
"""
from fastapi import Request, HTTPException, Depends
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional

class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to extract and validate user tokens from Databricks App proxy headers.
    The token is stored in request.state for use in downstream handlers.
    """

    async def dispatch(self, request: Request, call_next):
        # Extract the user token from the forwarded header
        user_token = request.headers.get('x-forwarded-access-token')

        # Store the token in request state for use in route handlers
        request.state.user_token = user_token
        request.state.user_authenticated = user_token is not None

        # Log authentication status (remove in production or use proper logging)
        if user_token:
            print(f"Authenticated request to {request.url.path}")
        else:
            print(f"Unauthenticated request to {request.url.path}")

        response = await call_next(request)
        return response

def get_user_token(request: Request) -> Optional[str]:
    """
    Dependency function to extract user token from request state.
    """
    return getattr(request.state, 'user_token', None)

import hashlib
import os
import logging
import threading
import time
from databricks.sdk import WorkspaceClient

# Building a WorkspaceClient is not free: its constructor resolves the auth
# configuration and then instantiates the whole surface of Databricks service
# wrappers. Measured at over 100ms per request against a route that does nothing
# else, and it is CPU under the GIL, so concurrent requests queue behind each
# other rather than overlapping. Clients are cached per credential instead.
#
# Keyed by a hash of the credential, so one user's client is never handed to
# another. Reuse across requests is not new here — `services.databricks_service`
# has always held one for the life of the process — and the SDK is safe to share.
# The TTL bounds both staleness and how long a token stays in memory.
_CLIENT_TTL_SECONDS = float(os.environ.get("WORKSPACE_CLIENT_TTL_SECONDS", "300"))
_MAX_CACHED_CLIENTS = 200
_client_cache: dict = {}
_client_cache_lock = threading.Lock()


def _cached_client(key: str, build):
    now = time.monotonic()
    with _client_cache_lock:
        hit = _client_cache.get(key)
        if hit and now - hit[0] < _CLIENT_TTL_SECONDS:
            return hit[1]

    client = build()

    with _client_cache_lock:
        if len(_client_cache) >= _MAX_CACHED_CLIENTS:
            # Cheap sweep: drop everything expired, and if that frees nothing,
            # start over rather than grow without bound.
            for k in [k for k, (t, _) in _client_cache.items() if now - t >= _CLIENT_TTL_SECONDS]:
                _client_cache.pop(k, None)
            if len(_client_cache) >= _MAX_CACHED_CLIENTS:
                _client_cache.clear()
        _client_cache[key] = (now, client)
    return client


def _token_key(prefix: str, token: str) -> str:
    return f"{prefix}:{hashlib.sha256(token.encode('utf-8')).hexdigest()[:32]}"


def get_db_client(user_token: Optional[str] = Depends(get_user_token)) -> WorkspaceClient:
    """
    Unified factory for WorkspaceClient.
    If DEV_MODE=true, it uses the Service Principal (from env vars).
    Otherwise, it uses the provided OBO token.
    """
    dev_mode = os.environ.get('DEV_MODE', '').lower() == 'true'
    
    # Workaround for Databricks SDK in environments where $HOME is not set
    if 'HOME' not in os.environ:
        logging.info("OBO: $HOME not set, defaulting to /tmp")
        os.environ['HOME'] = '/tmp'

    if dev_mode:
        logging.info("OBO: Running in DEV_MODE, using Service Principal credentials")
        # Use Service Principal (Databricks SDK will pick up DATABRICKS_CLIENT_ID, etc.)
        try:
            return _cached_client("dev-mode", WorkspaceClient)
        except Exception as e:
            logging.error(f"OBO: Failed to initialize WorkspaceClient in DEV_MODE: {e}")
            raise HTTPException(status_code=401, detail=f"Invalid local Databricks credentials: {e}")
    
    if not user_token:
        logging.error("OBO: Authentication required but no user token found in request headers")
        raise HTTPException(
            status_code=401,
            detail="Authentication required. No user token found."
        )

    logging.info(f"OBO: Initializing WorkspaceClient with user token (length: {len(user_token)})")

    # We explicitly provide the host to avoid the SDK trying to discover it via
    # Config() (which can trigger credential searches and fail if HOME is missing).
    host = os.environ.get('DATABRICKS_HOST')

    if not host:
        logging.info("OBO: DATABRICKS_HOST not in env, attempting Config() fallback")
        try:
            from databricks.sdk.config import Config
            host = Config().host
            logging.info(f"OBO: Discovered host from Config(): {host}")
        except Exception as e:
            logging.warning(f"OBO: Failed to discover host from Config(): {e}")
            host = None

    logging.info(f"OBO: Creating WorkspaceClient for host: {host}")
    try:
        # auth_type="pat" pins token auth so the SP env creds
        # (DATABRICKS_CLIENT_ID/SECRET) don't trigger the SDK's "more than one
        # authorization method configured" error.
        #
        # This replaces an earlier workaround that os.environ.pop()'d the SP creds
        # around construction. os.environ is PROCESS-GLOBAL and sync routes run in
        # a thread pool, so that pop raced with concurrent SP-based clients — most
        # visibly database.get_db_connection()'s WorkspaceClient(), which would
        # intermittently fail with "default auth: cannot configure default
        # credentials" whenever it ran during another request's OBO window. It
        # looked user-specific but was really request-timing-specific.
        return _cached_client(
            _token_key("obo", user_token),
            lambda: WorkspaceClient(host=host, token=user_token, auth_type="pat"),
        )
    except Exception as e:
        logging.error(f"OBO: Failed to initialize WorkspaceClient: {e}")
        raise HTTPException(status_code=401, detail=f"Databricks authentication failed: {e}")

def require_auth(request: Request) -> str:
    """
    Dependency function that requires authentication.
    Raises HTTPException if no token is present, UNLESS DEV_MODE=true.
    """
    dev_mode = os.environ.get('DEV_MODE', '').lower() == 'true'
    
    token = getattr(request.state, 'user_token', None)
    if not token and not dev_mode:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. No user token found."
        )
    return token

def get_db_client_for_jobs(user_token: Optional[str] = Depends(get_user_token)) -> WorkspaceClient:
    """
    Specialized factory for WorkspaceClient for job/notebook execution.
    Checks USE_SP_FOR_JOBS env var to decide between SP and OBO authentication.
    
    This allows job execution to use SP (which has broader permissions) 
    while keeping SQL/Genie on OBO for proper user-level access control.
    """
    use_sp_for_jobs = os.environ.get('USE_SP_FOR_JOBS', '').lower() == 'true'
    
    if use_sp_for_jobs:
        logging.info("🔧 Using Service Principal for job execution (USE_SP_FOR_JOBS=true)")
        # Workaround for $HOME issue
        if not os.environ.get('HOME'):
            os.environ['HOME'] = '/tmp'
        
        try:
            return _cached_client("sp", lambda: WorkspaceClient(
                host=os.environ.get('DATABRICKS_HOST'),
                client_id=os.environ.get('DATABRICKS_CLIENT_ID'),
                client_secret=os.environ.get('DATABRICKS_CLIENT_SECRET')
            ))
        except Exception as e:
            logging.error(f"Failed to initialize SP client for jobs: {e}")
            raise HTTPException(status_code=401, detail=f"Databricks SP authentication failed: {e}")
    else:
        # Use OBO token - same logic as get_db_client but inline
        logging.info("👤 Using OBO token for job execution")
        
        if not user_token:
            logging.error("OBO: Authentication required but no user token found in request headers")
            raise HTTPException(
                status_code=401,
                detail="Authentication required. No user token found."
            )

        host = os.environ.get('DATABRICKS_HOST')

        if not host:
            from databricks.sdk.config import Config
            host = Config().host

        try:
            # auth_type="pat" pins token auth so the SP env creds don't conflict —
            # no process-global os.environ mutation (see get_db_client for why).
            return _cached_client(
                _token_key("obo", user_token),
                lambda: WorkspaceClient(host=host, token=user_token, auth_type="pat"),
            )
        except Exception as e:
            logging.error(f"OBO: Failed to initialize WorkspaceClient for jobs: {e}")
            raise HTTPException(status_code=401, detail=f"Databricks authentication failed: {e}")

def get_db_client_sp() -> WorkspaceClient:
    """
    Specialized factory for WorkspaceClient that ALWAYS uses Service Principal authentication.
    Used for routes like the Agent Studio that must have strict SP scopes to reach Databricks AI endpoints.
    """
    logging.info("🤖 Using strict Service Principal authentication")
    
    # Workaround for $HOME issue
    if not os.environ.get('HOME'):
        os.environ['HOME'] = '/tmp'
        
    # Explicitly map the SP credentials to avoid any fallback to local databricks CLI configs
    try:
        return _cached_client("sp", lambda: WorkspaceClient(
            host=os.environ.get('DATABRICKS_HOST'),
            client_id=os.environ.get('DATABRICKS_CLIENT_ID'),
            client_secret=os.environ.get('DATABRICKS_CLIENT_SECRET')
        ))
    except Exception as e:
        logging.error(f"Failed to initialize strict SP client: {e}")
        raise HTTPException(status_code=401, detail=f"Databricks Service Principal authentication failed: {e}")
