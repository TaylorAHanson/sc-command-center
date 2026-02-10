from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any, List, Dict
import json
from database import log_user_action, get_action_logs

router = APIRouter(
    prefix="/api/actions",
    tags=["actions"]
)

class ActionLogRequest(BaseModel):
    widget_id: str
    widget_name: str
    explanation: str
    context: Any  # Receives JSON object, will be stringified

@router.post("/log")
async def log_action(request: ActionLogRequest):
    try:
        # Ensure context is stored as a string
        context_str = json.dumps(request.context) if not isinstance(request.context, str) else request.context
        
        return log_user_action(
            widget_id=request.widget_id,
            widget_name=request.widget_name,
            explanation=request.explanation,
            context=context_str
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/")
async def get_actions(limit: int = 100, offset: int = 0):
    try:
        return get_action_logs(limit, offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
