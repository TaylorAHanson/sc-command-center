"""What this deployment can do, for the browser and the Admin Panel's Setup card.

The checks themselves are in `services/capabilities.py`. Everyone signed in may
ask, because the UI needs to know which buttons to disable; only administrators
see what's missing, the next step, and when each background job last ran.
"""

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends

from middleware.auth import get_db_client
from services import access, background, capabilities

router = APIRouter()


@router.get("")
@router.get("/")
def list_capabilities(refresh: bool = False, w: WorkspaceClient = Depends(get_db_client)):
    who = access.caller(w)
    body = {"capabilities": capabilities.describe(admin=who.is_admin, force=refresh and who.is_admin)}
    if who.is_admin:
        body["jobs"] = background.describe()
    return body
