import inspect
from databricks.sdk import WorkspaceClient
try:
    print(inspect.signature(WorkspaceClient().api_client.do))
except Exception as e:
    print(e)
