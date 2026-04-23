from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Any, Dict, Optional
from databricks.sdk import WorkspaceClient
import logging

from middleware.auth import get_db_client

router = APIRouter()

class DatabricksApiRequest(BaseModel):
    path: str
    method: str = "GET"
    body: Optional[Dict[str, Any]] = None

@router.post("/proxy", summary="Proxy an arbitrary API request to Databricks using OBO")
async def databricks_api_proxy(
    req: DatabricksApiRequest,
    w: WorkspaceClient = Depends(get_db_client)
):
    """
    Proxies an arbitrary API request (like Model Serving endpoints) to Databricks
    using the user's OBO token.
    """
    try:
        # Ensure path starts with /
        path = req.path
        if not path.startswith('/'):
            path = '/' + path

        logging.info(f"Proxying {req.method} request to Databricks path: {path}")

        # Perform the API request using the authenticated SDK client
        response = w.api_client.do(
            method=req.method.upper(),
            path=path,
            body=req.body
        )
        
        return response
    except Exception as e:
        logging.exception(f"Error proxying Databricks API: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error proxying Databricks API: {str(e)}")
