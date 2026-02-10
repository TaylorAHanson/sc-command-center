from middleware.auth import get_db_client
import os

class DatabricksService:
    def __init__(self):
        # Initialize client only if configured, otherwise mock or handle gracefully
        try:
            # In dev mode, this uses SP. In prod, this will fail unless we pass a token later.
            # We call with None to let it check DEV_MODE internally.
            self.client = get_db_client(None) 
            self.is_connected = True
        except Exception as e:
            print(f"Warning: Could not connect to Databricks during startup: {e}")
            self.client = None
            self.is_connected = False

    def trigger_job(self, job_id: int, params: dict = None):
        if not self.is_connected:
            return {"status": "mocked", "message": f"Mock triggered job {job_id}"}
        
        try:
            # tailored to actual SDK usage
            run = self.client.jobs.run_now(job_id=job_id, job_parameters=params)
            return {"run_id": run.run_id, "status": "triggered"}
        except Exception as e:
            return {"error": str(e)}

    def get_cluster_status(self):
        if not self.is_connected:
             return {"status": "mocked", "clusters": []}
        # implementation placeholder
        return list(self.client.clusters.list())

db_service = DatabricksService()

