"""What the move to sharing did on this deployment (/api/sharing/migration).

The two startup steps (`services/consolidation.py`, `services/access_migration.py`)
run once and log their outcome; this reads that log back for the Admin Panel's
banner and report, and lets an admin rerun a step that failed. Mounted ahead of
the sharing router, whose `/{object_type}/{object_id}` would otherwise claim
`/migration/report`.
"""
from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends

from middleware.auth import get_db_client
from services import access, access_migration, consolidation

router = APIRouter()


@router.get("/report")
def report(w: WorkspaceClient = Depends(get_db_client)):
    access.require_app_admin(w)
    return access_migration.build_report(consolidation.read_logs())


@router.post("/retry")
def retry(w: WorkspaceClient = Depends(get_db_client)):
    """Run the failed steps again. Both only add rows, so rerunning one is safe."""
    access.require_app_admin(w)
    return access_migration.retry()
