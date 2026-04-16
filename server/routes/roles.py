from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List, Dict, Any
from pydantic import BaseModel
import psycopg2
import datetime
from database import get_db_connection
from middleware.auth import get_db_client, get_user_token
from databricks.sdk import WorkspaceClient

router = APIRouter()

class DomainRoleMapping(BaseModel):
    id: int
    external_role: str
    domain: str
    permission_level: str

class RoleMappingCreate(BaseModel):
    external_role: str
    domain: str
    permission_level: str = "editor"

def _get_current_username(w: WorkspaceClient) -> str:
    if w is None:
        import os
        return "dev" if os.environ.get('DEV_MODE', '').lower() == 'true' else "unknown"
    try:
        return w.current_user.me().user_name or "unknown"
    except Exception as e:
        return "unknown"

def get_user_entitlements(w: WorkspaceClient) -> List[str]:
    """Helper to fetch all Databricks groups and roles for the current user."""
    if w is None:
        return []
    
    # Check if we're dealing with an OBO client that has 'config.token' but maybe no groups returned
    try:
        me_data = w.api_client.do("GET", "/api/2.0/preview/scim/v2/Me")
        groups = [g.get("display") for g in me_data.get("groups", []) if g.get("display")]
        roles = [r.get("display") for r in me_data.get("roles", []) if r.get("display")]
        return groups + roles
    except Exception as e:
        print(f"Warning: Failed to fetch user entitlements via API: {e}")
        try:
            me = w.current_user.me()
            groups = [g.display for g in me.groups] if me.groups else []
            roles = [r.display for r in me.roles] if me.roles else []
            return groups + roles
        except Exception as e2:
            print(f"Warning: Failed to fetch user entitlements via SDK: {e2}")
            return []

@router.get("/me", summary="Get my current roles/groups from Databricks SCIM API")
def get_my_roles(db_client: WorkspaceClient = Depends(get_db_client)):
    try:
        me = db_client.current_user.me()
        
        groups = []
        if me.groups:
            groups = [g.display for g in me.groups if g.display]
            
        roles = []
        if me.roles:
            roles = [r.display for r in me.roles if r.display]
            
        return {
            "username": me.user_name,
            "groups": groups,
            "roles": roles,
            "all_entitlements": groups + roles
        }
    except Exception as e:
        # Fallback to direct API call if SDK method fails
        try:
            me_data = db_client.api_client.do("GET", "/api/2.0/preview/scim/v2/Me")
            groups = [g.get("display") for g in me_data.get("groups", []) if g.get("display")]
            roles = [r.get("display") for r in me_data.get("roles", []) if r.get("display")]
            return {
                "username": me_data.get("userName"),
                "groups": groups,
                "roles": roles,
                "all_entitlements": groups + roles
            }
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"Failed to fetch user roles from SCIM API: {e2}")

@router.get("/my-domains")
async def get_my_domains(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """
    Returns a list of domains the current user has access to based on their Databricks groups.
    If they are an admin or map to a global role, they might get all domains or a wildcard.
    """
    try:
        username = _get_current_username(w)
        user_entitlements = get_user_entitlements(w)
        
        # Include username as a role for exact-user mappings (e.g. mapping specifically taylhans@qualcomm.com to a domain)
        user_entitlements.append(username)
        
        conn = get_db_connection(env)
        c = conn.cursor()
        
        c.execute("SELECT DISTINCT domain, external_role FROM role_mappings")
        rows = c.fetchall()
        conn.close()
        
        my_domains = {"General"}
        for row in rows:
            # Handle both RealDictCursor and sqlite3.Row / tuple
            domain = row['domain'] if hasattr(row, 'keys') else row[0]
            role = row['external_role'] if hasattr(row, 'keys') else row[1]
            
            # If the required role for this domain is one of the user's groups, roles, or their username
            if role in user_entitlements:
                my_domains.add(domain)
                
        return {"domains": sorted(list(my_domains))}
    except Exception as e:
        print(f"Error fetching my domains: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def _get_user_permissions(w: WorkspaceClient, env: str) -> dict:
    """Helper function to fetch user permissions so it can be reused."""
    import os
    if os.environ.get('DEV_MODE', '').lower() == 'true':
        return {
            "is_admin": True,
            "domain_permissions": {}
        }

    username = _get_current_username(w)
    user_entitlements = get_user_entitlements(w)
    user_entitlements.append(username)
    
    conn = get_db_connection(env)
    c = conn.cursor()
    
    format_strings = ','.join(['%s'] * len(user_entitlements))
    c.execute(f"SELECT domain, permission_level FROM role_mappings WHERE external_role IN ({format_strings})", tuple(user_entitlements))
    rows = c.fetchall()
    conn.close()
    
    domain_permissions = {}
    is_global_admin = False
    
    for row in rows:
        domain = row['domain'] if hasattr(row, 'keys') else row[0]
        perm = row['permission_level'] if hasattr(row, 'keys') else row[1]
        
        if domain.lower() in ['global', 'all', 'app'] and perm == 'admin':
            is_global_admin = True
            
        # If multiple mappings exist for same domain, keep the highest privilege
        levels = {'viewer': 1, 'editor': 2, 'admin': 3}
        current_level = levels.get(domain_permissions.get(domain, 'none'), 0)
        new_level = levels.get(perm, 0)
        
        if new_level > current_level:
            domain_permissions[domain] = perm
            
    return {
        "is_admin": is_global_admin,
        "domain_permissions": domain_permissions
    }

def require_global_admin(w: WorkspaceClient, env: str = "dev"):
    perms = _get_user_permissions(w, env)
    if not perms.get("is_admin"):
        raise HTTPException(status_code=403, detail="Forbidden: Global Admin access required")
    return True

def require_domain_editor(w: WorkspaceClient, domain: str, env: str = "dev"):
    perms = _get_user_permissions(w, env)
    if perms.get("is_admin"):
        return True
    domain_perm = perms.get("domain_permissions", {}).get(domain, "none")
    if domain_perm not in ["editor", "admin"]:
        raise HTTPException(status_code=403, detail=f"Forbidden: Editor or Admin access required for domain '{domain}'")
    return True

def require_domain_admin(w: WorkspaceClient, domain: str, env: str = "dev"):
    perms = _get_user_permissions(w, env)
    if perms.get("is_admin"):
        return True
    domain_perm = perms.get("domain_permissions", {}).get(domain, "none")
    if domain_perm != "admin":
        raise HTTPException(status_code=403, detail=f"Forbidden: Admin access required for domain '{domain}'")
    return True

def require_domain_viewer(w: WorkspaceClient, domain: str, env: str = "dev"):
    perms = _get_user_permissions(w, env)
    if perms.get("is_admin"):
        return True
    domain_perm = perms.get("domain_permissions", {}).get(domain, "none")
    if domain_perm not in ["viewer", "editor", "admin"]:
        raise HTTPException(status_code=403, detail=f"Forbidden: Viewer, Editor or Admin access required for domain '{domain}'")
    return True

@router.get("/my-permissions")
async def get_my_permissions(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    """
    Returns the user's detailed permission structure.
    {
      "is_admin": bool, # true if they have 'admin' on 'Global' or 'All'
      "domain_permissions": { "DomainName": "admin" | "editor" | "viewer" }
    }
    """
    try:
        return _get_user_permissions(w, env)
    except Exception as e:
        print(f"Error fetching my permissions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/mapping")
async def get_role_mappings(env: str = "dev"):
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        c.execute("SELECT id, external_role, domain, permission_level, timestamp FROM role_mappings ORDER BY domain, external_role")
        rows = c.fetchall()
        mappings = [dict(row) for row in rows]
            
        conn.close()
        return {"mappings": mappings}
    except Exception as e:
        print(f"Error fetching role mappings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/mapping")
async def create_role_mapping(mapping: RoleMappingCreate, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    require_global_admin(w, env)
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        # Check if exists
        c.execute("SELECT id FROM role_mappings WHERE external_role = %s AND domain = %s AND permission_level = %s", 
                  (mapping.external_role, mapping.domain, mapping.permission_level))
            
        if c.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail="Role mapping already exists")
            
        c.execute(
            "INSERT INTO role_mappings (external_role, domain, permission_level) VALUES (%s, %s, %s) RETURNING id",
            (mapping.external_role, mapping.domain, mapping.permission_level)
        )
        new_id = c.fetchone()['id']
            
        conn.commit()
        conn.close()
        
        return {"status": "success", "id": new_id}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating role mapping: {str(e)}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/mapping/{mapping_id}")
async def delete_role_mapping(mapping_id: int, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    require_global_admin(w, env)
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        c.execute("DELETE FROM role_mappings WHERE id = %s", (mapping_id,))
        deleted = c.rowcount
        conn.commit()
            
        conn.close()
        
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Role mapping not found")
            
        return {"status": "success", "message": "Role mapping deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting role mapping: {str(e)}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/mapping/{mapping_id}")
async def update_role_mapping(mapping_id: int, mapping: RoleMappingCreate, w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    require_global_admin(w, env)
    try:
        conn = get_db_connection(env)
        c = conn.cursor()
        
        # Check if identical mapping exists for another ID
        c.execute("SELECT id FROM role_mappings WHERE external_role = %s AND domain = %s AND permission_level = %s AND id != %s", 
                  (mapping.external_role, mapping.domain, mapping.permission_level, mapping_id))
            
        if c.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail="Role mapping already exists")
            
        c.execute(
            "UPDATE role_mappings SET external_role = %s, domain = %s, permission_level = %s WHERE id = %s",
            (mapping.external_role, mapping.domain, mapping.permission_level, mapping_id)
        )
        updated = c.rowcount
            
        conn.commit()
        conn.close()
        
        if updated == 0:
            raise HTTPException(status_code=404, detail="Role mapping not found")
            
        return {"status": "success", "message": "Role mapping updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating role mapping: {str(e)}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))
