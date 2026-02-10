"""
N8N Workflow API routes.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional
import httpx
from middleware.auth import require_auth
from config.n8n_workflows import get_n8n_workflow_config, get_all_n8n_workflow_configs

router = APIRouter(prefix="/n8n", tags=["n8n"])


class TriggerWorkflowRequest(BaseModel):
    workflow_id: str
    parameters: Optional[Dict[str, Any]] = None


class WorkflowListResponse(BaseModel):
    workflows: list


@router.get("/list")
async def list_workflows(user_token: str = Depends(require_auth)):
    """List all available N8N workflows."""
    configs = get_all_n8n_workflow_configs()
    return WorkflowListResponse(
        workflows=[
            {
                "id": config.id,
                "name": config.name,
                "description": config.description,
                "category": config.category,
                "parameters": [p.dict() for p in config.parameters] if config.parameters else []
            }
            for config in configs
        ]
    )


@router.post("/trigger")
async def trigger_workflow(request: TriggerWorkflowRequest, user_token: str = Depends(require_auth)):
    """
    Trigger an N8N workflow via webhook.
    """
    try:
        # Get workflow configuration
        config = get_n8n_workflow_config(request.workflow_id)
        
        # Get full webhook URL
        webhook_url = config.get_full_url()
        
        # Prepare payload
        payload = request.parameters or {}
        
        # Make request to N8N webhook
        async with httpx.AsyncClient(timeout=30.0) as client:
            if config.method.upper() == "GET":
                response = await client.get(webhook_url, params=payload)
            else:
                response = await client.post(webhook_url, json=payload)
            
            response.raise_for_status()
            
        return {
            "success": True,
            "message": config.success_message or f"Workflow '{config.name}' triggered successfully",
            "workflow_id": request.workflow_id,
            "response_status": response.status_code
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger workflow: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )
