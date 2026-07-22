from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Any, Dict, Optional
from databricks.sdk import WorkspaceClient
import logging

from middleware.auth import get_db_client

router = APIRouter()


def _auth_headers(w: WorkspaceClient) -> Dict[str, str]:
    """Resolve SDK authentication into ordinary HTTP headers."""
    auth = w.config.authenticate()
    headers = auth() if callable(auth) else auth
    return dict(headers or {})


def _response_data(resp) -> Any:
    """Decode a Databricks response without losing a non-JSON response body."""
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {"result": resp.text}


def _error_detail(resp, data: Any) -> str:
    """Return the actionable Databricks error instead of an SDK parse wrapper."""
    if isinstance(data, dict):
        message = data.get("message") or data.get("error") or data.get("detail")
        error_code = data.get("error_code")
        if isinstance(message, (dict, list)):
            import json
            message = json.dumps(message)
        if message:
            return f"{error_code}: {message}" if error_code else str(message)
    if isinstance(data, str) and data.strip():
        return data.strip()
    text = (getattr(resp, "text", "") or "").strip()
    return text or f"Databricks API returned HTTP {resp.status_code}"


class DatabricksApiRequest(BaseModel):
    path: str
    method: str = "GET"
    body: Optional[Dict[str, Any]] = None
    fileUpload: Optional[bool] = False
    fileBase64: Optional[str] = None
    fileName: Optional[str] = None
    fileSize: Optional[int] = None

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
        import base64
        import requests
        from urllib.parse import urlparse
        
        parsed_url = urlparse(req.path)
        
        # If the user provided a full URL, use it directly. Otherwise append path to workspace host.
        if parsed_url.scheme and parsed_url.netloc:
            url = req.path
        else:
            path_with_query = req.path
            if not path_with_query.startswith('/'):
                path_with_query = '/' + path_with_query
                
            import re
            path_with_query = re.sub("^/api/2.0/fs/files//", "/api/2.0/fs/files/", path_with_query)
            
            url = f"{w.config.host.rstrip('/')}{path_with_query}"

        logging.info(f"Proxying {req.method} request to Databricks URL: {url}")

        headers = _auth_headers(w)
        request_kwargs: Dict[str, Any] = {
            "method": req.method.upper(),
            "url": url,
            "headers": headers,
            "timeout": 90,
        }
        if req.fileUpload and req.fileBase64:
            # Handle data URI scheme if present (e.g., data:image/png;base64,...).
            b64_data = req.fileBase64.split(",", 1)[-1]
            request_kwargs["data"] = base64.b64decode(b64_data)
            headers["Content-Type"] = "application/octet-stream"
        elif req.body is not None:
            request_kwargs["json"] = req.body

        resp = requests.request(**request_kwargs)
        data = _response_data(resp)
        if not resp.ok:
            detail = _error_detail(resp, data)
            logging.error("Databricks API error response: %s - %s", resp.status_code, detail)
            raise HTTPException(status_code=resp.status_code, detail=detail)
        return data
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error proxying Databricks API: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error proxying Databricks API: {str(e)}")
