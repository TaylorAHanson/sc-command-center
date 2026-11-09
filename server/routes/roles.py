"""Who the caller is (/api/roles).

Access itself is per object now — see `services/access.py` and `routes/sharing.py`.
What is left here is identity: the username rows are owned by, the groups access
lists match against, and whether the caller is an app administrator.
"""
from typing import Any, Dict, List

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import get_db_client
from services import access, caller_identity
from services.settings_store import settings_env

router = APIRouter()

#: Domain names the retired role mappings treated as "every domain". Only the
#: one-time access migration still reads mappings.
GLOBAL_DOMAINS = ("global", "all", "app")


def roles_env() -> str:
    """The env whose schema holds the deployment-wide access tables (and the legacy `role_mappings`)."""
    return settings_env()


def _permissions_disabled() -> bool:
    return access.permissions_disabled()


def _get_current_username(w: WorkspaceClient) -> str:
    """The caller's Databricks username.

    Every route that owns rows by user goes through here, so it is one of the
    hottest calls in the app; ``caller_identity`` resolves it once per credential
    per few minutes instead of once per request. See that module for why — it also
    handles a missing client, and returns "unknown" rather than guessing at a name
    that would then be written to a table as though it were a person.
    """
    return caller_identity.username(w)


def get_user_entitlements(w: WorkspaceClient) -> List[str]:
    """The caller's Databricks groups and roles, the names access lists match against."""
    if w is None:
        return []
    return caller_identity.entitlements(w)


def _get_user_permissions(w: WorkspaceClient) -> Dict[str, Any]:
    """The caller's identity and whether they administer the app.

    Whose identity this is matters beyond access control: it's the `username` the
    frontend holds, so it ends up stamped on views, on widgets, and in whatever a
    widget writes to a table. Bypassing the permission *checks* must not bypass
    identity.
    """
    who = access.caller(w)
    return {"username": who.username, "is_admin": who.is_admin, "groups": list(who.groups)}


def require_global_admin(w: WorkspaceClient) -> bool:
    access.require_app_admin(w)
    return True


@router.get("/me", summary="Get my current roles/groups from Databricks SCIM API")
def get_my_roles(db_client: WorkspaceClient = Depends(get_db_client)):
    try:
        me = db_client.current_user.me()
        groups = [g.display for g in (me.groups or []) if g.display]
        roles = [r.display for r in (me.roles or []) if r.display]
        return {"username": me.user_name, "groups": groups, "roles": roles, "all_entitlements": groups + roles}
    except Exception:
        try:
            me_data = db_client.api_client.do("GET", "/api/2.0/preview/scim/v2/Me")
            groups = [g.get("display") for g in me_data.get("groups", []) if g.get("display")]
            roles = [r.get("display") for r in me_data.get("roles", []) if r.get("display")]
            return {"username": me_data.get("userName"), "groups": groups, "roles": roles,
                    "all_entitlements": groups + roles}
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"Failed to fetch user roles from SCIM API: {e2}")


@router.get("/my-permissions")
def get_my_permissions(w: WorkspaceClient = Depends(get_db_client)):
    """`{username, is_admin, groups}` — the same in every view, since access is per object."""
    try:
        return _get_user_permissions(w)
    except Exception as e:
        print(f"Error fetching my permissions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
