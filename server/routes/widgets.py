from fastapi import APIRouter, Depends, HTTPException
from databricks.sdk import WorkspaceClient

from database import log_widget_run, get_popularity_scores
from middleware.auth import get_db_client
from routes.roles import _get_current_username
from services import creator_stats

router = APIRouter(
    prefix="/api/widgets",
    tags=["widgets"]
)

@router.post("/{widget_id}/run")
def record_widget_run(widget_id: str, w: WorkspaceClient = Depends(get_db_client)):
    try:
        # Who added it, not just that it was added: the creator leaderboard counts
        # how many people reach for a widget, which a bare tally can't answer.
        return log_widget_run(widget_id, username=_get_current_username(w))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/popularity")
def get_widget_popularity():
    try:
        return get_popularity_scores()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/creators")
def get_widget_creators(env: str = "dev", limit: int = 10):
    """Leaderboard of widget creators, ranked by output and by real usage."""
    try:
        return creator_stats.leaderboard(env=env, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
