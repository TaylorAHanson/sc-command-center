import json
import os
from databricks.sdk import WorkspaceClient

def main():
    w = WorkspaceClient()
    try:
        # Use SCIM Me endpoint
        res = w.api_client.do("GET", "/api/2.0/preview/scim/v2/Me")
        print("SCIM Me response:")
        print(json.dumps(res, indent=2))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
