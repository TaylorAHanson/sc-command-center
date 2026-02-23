from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from openai import OpenAI
import os
import re
from typing import List, Optional, Dict, Any
from middleware.auth import get_db_client
from databricks.sdk import WorkspaceClient

router = APIRouter()

class Message(BaseModel):
    role: str
    content: str

class GenerateRequest(BaseModel):
    prompt: str
    history: List[Message] = []
    error_log: Optional[str] = None
    current_code: Optional[str] = None
    data_source_schema: Optional[Dict[str, Any]] = None
    data_source: Optional[str] = None
    data_source_type: Optional[str] = None

class DataSourceTestRequest(BaseModel):
    data_source_type: str
    data_source: str

@router.post("/generate")
async def generate_widget(req: GenerateRequest, db_client: WorkspaceClient = Depends(get_db_client)):
    # Use the WorkspaceClient config to initialize the OpenAI client securely
    try:
        host = db_client.config.host
        
        # Databricks Python SDK encapsulates dynamic tokens (like OAuth/SP) inside authenticate()
        auth_headers_fn = db_client.config.authenticate()
        auth_headers = auth_headers_fn() if callable(auth_headers_fn) else auth_headers_fn
        api_key = auth_headers.get("Authorization", "").replace("Bearer ", "") if auth_headers else ""
        
        # Some dev setups might not have a token directly accessible, fallback to env
        api_key = api_key or db_client.config.token or os.environ.get("OPENAI_API_KEY") or os.environ.get("DATABRICKS_TOKEN") or "dummy"
        base_url = f"{host}/serving-endpoints" if host else os.environ.get("OPENAI_BASE_URL", "https://adb-1234.1.azuredatabricks.net/serving-endpoints")
        
        client = OpenAI(api_key=api_key, base_url=base_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI client init failed: {e}")
        
    try:
        instructions_path = os.path.join(os.path.dirname(__file__), "agent_instructions.md")
        with open(instructions_path, "r") as f:
            system_prompt = f.read()
    except Exception as e:
        print(f"Failed to load agent instructions: {e}")
    
    if req.error_log:
        system_prompt += f"\n\nPrevious attempt failed with error:\n{req.error_log}\nPlease fix the issue."
        
    if req.current_code:
        system_prompt += f"\n\nHere is the CURRENT state of the widget code:\n```tsx\n{req.current_code}\n```\nModify this code according to the user's instructions."

    if req.data_source:
        # Always tell the LLM what data source is configured so it can wire it up correctly
        ds_label = "SQL query" if req.data_source_type == "sql" else "API endpoint URL"
        system_prompt += f"\n\nThe widget has a configured data source ({ds_label}):\n```\n{req.data_source}\n```\nYou MUST use `props.data.dataSource` directly in your fetch/query call — do NOT hardcode the SQL or URL."

    if req.data_source_schema:
        import json
        schema_str = json.dumps(req.data_source_schema, indent=2)
        system_prompt += f"\n\nThe data source returns the following schema (use these exact field names in your component):\n```json\n{schema_str}\n```"

    messages = [{"role": "system", "content": system_prompt}]
    for msg in req.history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": req.prompt})

    try:
        # Databricks DBRX/Llama endpoints generally use a corresponding model string
        model_name = os.environ.get("LLM_MODEL", "databricks-claude-sonnet-4-6")
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.1,
            max_tokens=4096
        )
        
        content = response.choices[0].message.content

        # Prefer explicitly tagged tsx/ts/jsx/js code blocks to avoid matching SQL or other plain ``` blocks
        code_match = re.search(r'```(?:tsx|jsx|typescript|javascript|ts|js)\n(.*?)```', content, re.DOTALL | re.IGNORECASE)
        if not code_match:
            # Fall back to any labeled block (but not plain ```)
            code_match = re.search(r'```[a-zA-Z]+\n(.*?)```', content, re.DOTALL)
        if code_match:
            code = code_match.group(1).strip()
            explanation = content.replace(code_match.group(0), "").strip()
        else:
            # Maybe it's truncated, look for an opening typed block without a closing block
            partial_match = re.search(r'```(?:tsx|jsx|typescript|javascript|ts|js)\n(.*)', content, re.DOTALL | re.IGNORECASE)
            if partial_match:
                code = partial_match.group(1).strip()
                explanation = content[:partial_match.start()].strip()
            else:
                code = None
                explanation = content.strip()
                
        # Failsafe cleanup of any lingering backticks just in case
        if code:
            code = re.sub(r'^```[a-zA-Z]*\n?', '', code)
            code = re.sub(r'\n?```$', '', code)
            
        return {"code": code, "explanation": explanation, "raw": content}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

def extract_schema_from_json(data):
    if isinstance(data, list) and len(data) > 0:
        item = data[0]
        if isinstance(item, dict):
            return {k: type(v).__name__ if v is not None else "string" for k, v in item.items()}
        else:
            return {"value": type(item).__name__}
    elif isinstance(data, dict):
        return {k: type(v).__name__ if v is not None else "string" for k, v in data.items()}
    return {"data": type(data).__name__}

@router.post("/datasource/test")
async def test_datasource(req: DataSourceTestRequest, db_client: WorkspaceClient = Depends(get_db_client)):
    import httpx
    if req.data_source_type == "api":
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(req.data_source)
                res.raise_for_status()
                data = res.json()
                schema = extract_schema_from_json(data)
                return {"schema": schema, "sample": data[:2] if isinstance(data, list) else data}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"API request failed: {e}")
    elif req.data_source_type == "sql":
        try:
            from databricks.sdk.service.sql import StatementExecutionAPI, Disposition
            import os

            sql_api = StatementExecutionAPI(db_client.api_client)
            warehouse_id = os.environ.get("SQL_WAREHOUSE_ID", "")
            if not warehouse_id:
                raise HTTPException(status_code=500, detail="No SQL Warehouse ID configured. Set SQL_WAREHOUSE_ID in environment.")

            # For schema detection, apply LIMIT 1 if no LIMIT clause already present
            schema_query = req.data_source.strip().rstrip(";")
            if not re.search(r'\bLIMIT\b', schema_query, re.IGNORECASE):
                schema_query = f"SELECT * FROM ({schema_query}) AS _schema_probe LIMIT 1"

            statement = sql_api.execute_statement(
                warehouse_id=warehouse_id,
                statement=schema_query,
                wait_timeout="50s",
                disposition=Disposition.INLINE,
            )

            columns = []
            rows = []

            if statement.manifest and statement.manifest.schema and statement.manifest.schema.columns:
                columns = [col.name for col in statement.manifest.schema.columns]

            if statement.result and statement.result.data_array:
                for row_data in statement.result.data_array[:5]:
                    row_dict = {}
                    for i, col_name in enumerate(columns):
                        row_dict[col_name] = row_data[i] if i < len(row_data) else None
                    rows.append(row_dict)

            schema = {col: type(rows[0].get(col)).__name__ if rows and rows[0].get(col) is not None else "string" for col in columns}
            return {"schema": schema, "sample": rows}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"SQL Query failed: {e}")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown data source type: {req.data_source_type}")
