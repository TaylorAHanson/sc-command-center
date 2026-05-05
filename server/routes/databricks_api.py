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
        import requests
        from urllib.parse import urlparse
        
        parsed_url = urlparse(req.path)
        
        # If the user provided a full URL, use it directly. Otherwise append path to workspace host.
        if parsed_url.scheme and parsed_url.netloc:
            url = req.path
        else:
            path = parsed_url.path
            if not path.startswith('/'):
                path = '/' + path
            url = f"{w.config.host.rstrip('/')}{path}"

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
            path = urlparse(url).path
            response = w.api_client.do(
                method=req.method.upper(),
                path=path,
                body=req.body
            )
            return response
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error proxying Databricks API: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error proxying Databricks API: {str(e)}")
