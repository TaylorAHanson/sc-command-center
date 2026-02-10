from fastapi import APIRouter, HTTPException
from database import log_widget_run, get_popularity_scores

router = APIRouter(
    prefix="/api/widgets",
    tags=["widgets"]
)

@router.post("/{widget_id}/run")
async def record_widget_run(widget_id: str):
    try:
        return log_widget_run(widget_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/popularity")
async def get_widget_popularity():
    try:
        return get_popularity_scores()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
