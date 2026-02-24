
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
        
        return WorkspaceClient(
            host=os.environ.get('DATABRICKS_HOST'),
            client_id=os.environ.get('DATABRICKS_CLIENT_ID'),
            client_secret=os.environ.get('DATABRICKS_CLIENT_SECRET')
        )
    else:
        # Use OBO token - same logic as get_db_client but inline
        logging.info("👤 Using OBO token for job execution")
        
        if not user_token:
            logging.error("OBO: Authentication required but no user token found in request headers")
            raise HTTPException(
                status_code=401,
                detail="Authentication required. No user token found."
            )
        
        # Temporarily suppress SP credentials to avoid SDK confusion
        saved_client_id = os.environ.pop('DATABRICKS_CLIENT_ID', None)
        saved_client_secret = os.environ.pop('DATABRICKS_CLIENT_SECRET', None)
        
        try:
            host = os.environ.get('DATABRICKS_HOST')
            
            if not host:
                from databricks.sdk.config import Config
                host = Config().host
            
            return WorkspaceClient(
                host=host,
                token=user_token
            )
        finally:
            # Restore env vars
            if saved_client_id:
                os.environ['DATABRICKS_CLIENT_ID'] = saved_client_id
            if saved_client_secret:
                os.environ['DATABRICKS_CLIENT_SECRET'] = saved_client_secret

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
    return WorkspaceClient(
        host=os.environ.get('DATABRICKS_HOST'),
        client_id=os.environ.get('DATABRICKS_CLIENT_ID'),
        client_secret=os.environ.get('DATABRICKS_CLIENT_SECRET')
    )
