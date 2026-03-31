import os
from databricks.sdk import WorkspaceClient
import json

def get_current_user_roles():
    """Fetch the current user/service principal's roles and groups."""
    try:
        # Re-using the same authentication strategy from your middleware
        from server.middleware.auth import get_db_client_sp
        
        # This will use env vars like DATABRICKS_HOST, DATABRICKS_CLIENT_ID, etc.
        db_client = get_db_client_sp()
        
        # 1. Try the SCIM Me endpoint first
        try:
            print("Trying /api/2.0/preview/scim/v2/Me...")
            me = db_client.api_client.do("GET", "/api/2.0/preview/scim/v2/Me")
            print("Response:")
            print(json.dumps(me, indent=2))
        except Exception as e:
            print(f"Me endpoint failed: {e}")
            
    except Exception as e:
        print(f"Auth initialization failed: {e}")

if __name__ == "__main__":
    get_current_user_roles()
