
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

import os
import logging
from databricks.sdk import WorkspaceClient

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
        return WorkspaceClient()
    
    if not user_token:
        logging.error("OBO: Authentication required but no user token found in request headers")
        raise HTTPException(
            status_code=401,
            detail="Authentication required. No user token found."
        )

    logging.info(f"OBO: Initializing WorkspaceClient with user token (length: {len(user_token)})")

    # Temporarily remove OAuth env vars so WorkspaceClient doesn't pick them up for OBO
    saved_client_id = os.environ.pop('DATABRICKS_CLIENT_ID', None)
    saved_client_secret = os.environ.pop('DATABRICKS_CLIENT_SECRET', None)
    
    if saved_client_id:
        logging.info("OBO: Temporarily suppressing DATABRICKS_CLIENT_ID to prevent auth conflict")

    try:
        # In deployment, we want to use the user's OBO token.
        # We explicitly provide the host to avoid the SDK trying to discover it 
        # via Config() which can trigger credential searches and fail if HOME is missing.
        host = os.environ.get('DATABRICKS_HOST')
        
        if not host:
            logging.info("OBO: DATABRICKS_HOST not in env, attempting Config() fallback")
            try:
                # Fallback to config discovery if host is not in env
                from databricks.sdk.config import Config
                host = Config().host
                logging.info(f"OBO: Discovered host from Config(): {host}")
            except Exception as e:
                logging.warning(f"OBO: Failed to discover host from Config(): {e}")
                host = None

        logging.info(f"OBO: Creating WorkspaceClient for host: {host}")
        return WorkspaceClient(
            host=host,
            token=user_token
        )
    finally:
        # Restore env vars
        if saved_client_id:
            logging.info("OBO: Restoring DATABRICKS_CLIENT_ID")
            os.environ['DATABRICKS_CLIENT_ID'] = saved_client_id
        if saved_client_secret:
            os.environ['DATABRICKS_CLIENT_SECRET'] = saved_client_secret

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
