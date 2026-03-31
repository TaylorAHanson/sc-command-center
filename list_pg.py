from databricks.sdk import WorkspaceClient
import json

def run():
    w = WorkspaceClient()
    try:
        print("Trying /api/2.0/postgres/projects ...")
        res = w.api_client.do("GET", "/api/2.0/postgres/projects")
        print(json.dumps(res, indent=2))
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    run()
