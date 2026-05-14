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

        if "/serving-endpoints/" in url:
            headers = w.config.authenticate()
            logging.info(f"Proxying serving endpoint request. Method: {req.method.upper()}, URL: {url}, Payload keys: {list(req.body.keys()) if req.body else []}")
            
            resp = requests.request(
                method=req.method.upper(),
                url=url,
                json=req.body,
                headers=headers
            )
            try:
                data = resp.json()
            except Exception:
                data = {"result": resp.text}
            
            if not resp.ok:
                logging.error(f"Serving endpoint error response: {resp.status_code} - {resp.text}")
                raise HTTPException(status_code=resp.status_code, detail=str(data))
            return data
        else:
            if req.fileUpload and req.fileBase64:
                import base64
                
                # Handle data URI scheme if present (e.g., data:image/png;base64,...)
                b64_data = req.fileBase64
                if "," in b64_data:
                    b64_data = b64_data.split(",", 1)[1]
                    
                file_data = base64.b64decode(b64_data)
                response = w.api_client.do(
                    method=req.method.upper(),
                    url=url,
                    data=file_data,
                    headers={"Content-Type": "application/octet-stream"}
                )
                return response
            else:
                response = w.api_client.do(
                    method=req.method.upper(),
                    url=url,
                    body=req.body
                )
                return response
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error proxying Databricks API: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error proxying Databricks API: {str(e)}")
