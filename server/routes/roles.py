from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import psycopg2
import os
from database import get_db_connection
from middleware.auth import get_db_client
from databricks.sdk import WorkspaceClient

router = APIRouter()

class RoleMappingCreate(BaseModel):
    external_role: str
    domain: str
    permission_level: str = "editor"

def _get_current_username(w: WorkspaceClient) -> str:
    if w is None:
        return "dev" if os.environ.get('DEV_MODE', '').lower() == 'true' else "unknown"
    try:
        return w.current_user().user_name or "unknown"
    except Exception as e:
        return "unknown"

def has_role(username: str, role_name: str) -> bool:
    """Mock implementation for checking if a user has an external role"""
    return True

@router.get("/my-domains")
async def get_my_domains(w: WorkspaceClient = Depends(get_db_client), env: str = "dev"):
    try:
        username = _get_current_username(w)
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
            if has_role(username, role):
                my_domains.add(domain)
                
        return {"domains": sorted(list(my_domains))}
    except Exception as e:
        print(f"Error fetching my domains: {str(e)}")
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
async def create_role_mapping(mapping: RoleMappingCreate, env: str = "dev"):
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
async def delete_role_mapping(mapping_id: int, env: str = "dev"):
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
async def update_role_mapping(mapping_id: int, mapping: RoleMappingCreate, env: str = "dev"):
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
