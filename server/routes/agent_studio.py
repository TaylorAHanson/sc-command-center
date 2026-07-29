from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from openai import OpenAI
import os
import re
import uuid
from typing import List, Optional, Dict, Any
from middleware.auth import get_db_client, get_db_client_sp
from databricks.sdk import WorkspaceClient
from database import get_db_connection
from services.code_patch import (
    apply_edits,
    continuation_anchor,
    extract_code_block,
    looks_truncated,
    parse_edits,
    strip_edit_blocks,
)

# LangChain imports
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

@tool
def search_widgets(query: str) -> str:
    """Search for existing widgets by name or description to suggest before creating a new one."""
    try:
        conn = get_db_connection("dev")
        c = conn.cursor()
        search_term = f"%{query}%"
        # We query the widgets table.
        c.execute("SELECT id, name, description FROM widgets WHERE (name ILIKE %s OR description ILIKE %s) AND is_deprecated = 0 LIMIT 5", (search_term, search_term))
        results = c.fetchall()
        conn.close()
        
        if not results:
            return f"No matching widgets found for '{query}'."
            
        output = f"Found the following widgets matching '{query}':\n"
        for r in results:
            # handle both RealDictCursor or tuple
            if hasattr(r, 'keys'):
                output += f"- Name: {r['name']}, Description: {r['description']}\n"
            else:
                output += f"- Name: {r[1]}, Description: {r[2]}\n"
        return output
    except Exception as e:
        return f"Error searching widgets: {str(e)}"

router = APIRouter()

# Store for generation jobs. In a real app, use Redis or DB, but in-memory is fine for this tool.
generation_jobs: Dict[str, Any] = {}

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
    configuration_mode: Optional[str] = "none"
    config_schema: Optional[List[Dict[str, Any]]] = None
    # Constrains the settings the model may propose, so it can't suggest a
    # category or domain that isn't selectable in the UI.
    available_categories: List[str] = []
    available_domains: List[str] = []
    # Metadata fields the user has already filled in themselves. The model is
    # told not to bother proposing values for these.
    locked_settings: List[str] = []

class DataSourceTestRequest(BaseModel):
    data_source_type: str
    data_source: str

# A response that gets cut off mid-file is the classic failure for large widgets.
# When we detect one we ask the model to carry on from where it stopped rather
# than starting over, which would just hit the same ceiling.
MAX_CONTINUATIONS = int(os.environ.get("WIDGET_AGENT_MAX_CONTINUATIONS", "3"))

_META_BLOCK_RE = re.compile(r"```widget-meta[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)

# Bounds on what the model may propose for the Configuration tab. Anything not
# listed here is dropped rather than trusted.
_META_TEXT_LIMITS = {"name": 120, "description": 600, "helpText": 2000}


def _extract_meta(content: str, req: GenerateRequest) -> tuple[Dict[str, Any], str]:
    """Pull the proposed widget settings out of a response.

    Returns the sanitized settings and the content with the block removed, so the
    block never reaches the code extractor or the user-visible explanation.
    """
    import json

    match = _META_BLOCK_RE.search(content or "")
    if not match:
        return {}, content or ""

    # Collapse the gap the removed block leaves behind, so the explanation the
    # user sees doesn't have a hole in it.
    remainder = re.sub(r"\n{3,}", "\n\n", content[:match.start()] + content[match.end():]).strip()
    try:
        raw = json.loads(match.group(1).strip())
    except Exception as e:
        print(f"Ignoring malformed widget-meta block: {e}")
        return {}, remainder
    if not isinstance(raw, dict):
        return {}, remainder

    def pick(options: List[str], value: Any) -> Optional[str]:
        """Resolve a proposed category/domain to one the UI actually offers."""
        if not isinstance(value, str):
            return None
        wanted = value.strip().lower()
        for option in options:
            if option.strip().lower() == wanted:
                return option
        return None

    meta: Dict[str, Any] = {}
    for key, limit in _META_TEXT_LIMITS.items():
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            meta[key] = value.strip()[:limit]

    category = pick(req.available_categories, raw.get("category"))
    if category:
        meta["category"] = category
    domain = pick(req.available_domains, raw.get("domain"))
    if domain:
        meta["domain"] = domain

    for key, hi in (("defaultW", 12), ("defaultH", 40)):
        try:
            value = int(raw.get(key))
        except (TypeError, ValueError):
            continue
        if 1 <= value <= hi:
            meta[key] = value

    if isinstance(raw.get("isExecutable"), bool):
        meta["isExecutable"] = raw["isExecutable"]

    # The user's own choices win; don't even return a competing suggestion.
    for key in req.locked_settings:
        meta.pop(key, None)

    return meta, remainder


def _build_system_prompt(req: GenerateRequest) -> str:
    import json

    try:
        instructions_path = os.path.join(os.path.dirname(__file__), "agent_instructions.md")
        with open(instructions_path, "r") as f:
            system_prompt = f.read()
    except Exception as e:
        print(f"Failed to load agent instructions: {e}")
        system_prompt = "You are an expert React developer."

    system_prompt += "\n\nIf the user is asking to build a widget that sounds like it might already exist, use the search_widgets tool to find similar widgets and suggest them before proceeding. If they explicitly want to build it anyway, then generate the code."

    if req.error_log:
        system_prompt += f"\n\nPrevious attempt failed with error:\n{req.error_log}\nPlease fix the issue."

    if req.current_code:
        system_prompt += (
            f"\n\nHere is the CURRENT state of the widget code:\n```tsx\n{req.current_code}\n```\n"
            "Modify this code according to the user's instructions using SEARCH/REPLACE blocks "
            "as described in Output Format. Do not re-send the parts you aren't changing."
        )

    if req.data_source:
        # Always tell the LLM what data source is configured so it can wire it up correctly
        if req.data_source_type == "sql":
            ds_label = "SQL query"
        elif req.data_source_type == "databricks_api":
            ds_label = "Databricks API path"
        else:
            ds_label = "API endpoint URL"
        system_prompt += f"\n\nThe widget has a configured data source ({ds_label}):\n```\n{req.data_source}\n```\nYou MUST use `props.data.dataSource` directly in your fetch/query call — do NOT hardcode the SQL or URL."

    if req.data_source_schema:
        schema_str = json.dumps(req.data_source_schema, indent=2)
        system_prompt += f"\n\nThe data source returns the following schema (use these exact field names in your component):\n```json\n{schema_str}\n```"

    if req.configuration_mode != "none" and req.config_schema:
        config_schema_str = json.dumps(req.config_schema, indent=2)
        system_prompt += f"\n\nThe user has configured the following dynamic configuration inputs for this widget:\n```json\n{config_schema_str}\n```\nYou MUST expect these exact keys in `props.data` (e.g. `props.data.myKey`). Provide reasonable fallback values if they are undefined or empty. Do NOT hardcode colors/text if a dynamic config key exists for it."

    system_prompt += "\n\nThe widget receives the current user's username via `props.data.username`. You can use this to personalize the widget or make user-specific API calls."

    if req.available_categories:
        system_prompt += f"\n\nAllowed `category` values for the widget-meta block: {json.dumps(req.available_categories)}."
    if req.available_domains:
        system_prompt += f"\nAllowed `domain` values for the widget-meta block: {json.dumps(req.available_domains)}."
    if req.locked_settings:
        system_prompt += (
            f"\nThe user has already set these settings themselves: {', '.join(req.locked_settings)}. "
            "Leave those keys out of the widget-meta block entirely."
        )

    return system_prompt


def _finish_reason(message: Any) -> str:
    metadata = getattr(message, "response_metadata", None) or {}
    return metadata.get("finish_reason") or ""


def _continue_truncated(llm, system_prompt: str, user_prompt: str, content: str) -> str:
    """Extend a response that ran out of room, one continuation at a time."""
    for round_no in range(MAX_CONTINUATIONS):
        if not looks_truncated(content):
            break
        code_so_far, _ = extract_code_block(content)
        anchor = continuation_anchor(code_so_far or content)
        print(f"Widget generation looks truncated; requesting continuation {round_no + 1}")
        follow_up = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
            AIMessage(content=content),
            HumanMessage(content=(
                "Your response was cut off before the file was finished. These were "
                f"its last lines:\n\n{anchor}\n\n"
                "Continue the file from exactly that point. Output the remaining code "
                "only — do not repeat any line you already sent, do not re-open a code "
                "fence, and do not explain anything. Close the ``` fence when the "
                "component is complete."
            )),
        ])
        addition = getattr(follow_up, "content", "") or ""
        # A continuation that opens with a fence is restating, not continuing.
        addition = re.sub(r"^\s*```[a-zA-Z]*\n", "", addition)
        if not addition.strip():
            break
        content = content.rstrip("\n") + "\n" + addition
    return content


def _repair_edits(llm, system_prompt: str, user_prompt: str, content: str,
                  code: str, failures: List[str]) -> str:
    """Ask for corrected SEARCH text when a block didn't match the file."""
    return getattr(llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
        AIMessage(content=content),
        HumanMessage(content=(
            "Some of your edits could not be applied:\n" + "\n".join(f"- {f}" for f in failures) +
            "\n\nThis is the code as it stands now, after the edits that did apply:\n"
            f"```tsx\n{code}\n```\n"
            "Re-send only the blocks that failed, copying their SEARCH text exactly "
            "from the code above. No explanation."
        )),
    ]), "content", "") or ""


def run_generation_task(job_id: str, req: GenerateRequest, api_key: str, base_url: str):
    try:
        # Databricks DBRX/Llama endpoints generally use a corresponding model string
        model_name = os.environ.get("LLM_MODEL", "databricks-claude-sonnet-4-6")

        llm = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model_name,
            temperature=0.1,
            max_tokens=16000
        )

        system_prompt = _build_system_prompt(req)

        agent = create_react_agent(
            model=llm,
            tools=[search_widgets],
            prompt=system_prompt
        )

        # Limit history to the last 6 messages to avoid massive context payloads causing timeouts
        history_to_keep = req.history[-6:] if len(req.history) > 6 else req.history
        lc_history = []
        for msg in history_to_keep:
            if msg.role == 'user':
                lc_history.append(HumanMessage(content=msg.content))
            elif msg.role in ('assistant', 'system'):
                lc_history.append(AIMessage(content=msg.content))

        response = agent.invoke({
            "messages": lc_history + [HumanMessage(content=req.prompt)]
        })

        last_message = response["messages"][-1]
        content = last_message.content
        truncated = _finish_reason(last_message) == "length" or looks_truncated(content)

        meta, content = _extract_meta(content, req)
        notes: List[str] = []
        base_code = req.current_code or ""

        edits = parse_edits(content)
        if edits and base_code.strip():
            result = apply_edits(base_code, edits)
            notes.extend(result.warnings)

            if result.failures:
                repair = _repair_edits(llm, system_prompt, req.prompt, content,
                                       result.code, result.failures)
                retry_edits = parse_edits(repair)
                if retry_edits:
                    retried = apply_edits(result.code, retry_edits)
                    result = result._replace(
                        code=retried.code,
                        applied=result.applied + retried.applied,
                        failures=retried.failures,
                        warnings=result.warnings + retried.warnings,
                    )
                    notes.extend(retried.warnings)

            code = result.code if result.applied else None
            explanation = strip_edit_blocks(content)
            if truncated:
                notes.append("The response was cut off, so some requested changes may be missing.")
            if result.failures:
                notes.append(
                    "Some edits could not be placed and were skipped: "
                    + " ".join(result.failures)
                )
            if code is None:
                notes.append("No changes were applied — the code is unchanged.")
        else:
            if edits:
                # Edits arrived with nothing to apply them to. Don't show the raw
                # markers to the user; say what happened instead.
                content = strip_edit_blocks(content)
                notes.append(
                    "The model replied with edits, but there is no existing code to apply "
                    "them to. Ask again and it will write the widget from scratch."
                )
            # Whole-file response: either a new widget or a rewrite the model
            # judged too pervasive to express as edits.
            if truncated:
                content = _continue_truncated(llm, system_prompt, req.prompt, content)
            code, explanation = extract_code_block(content)
            if code:
                # Failsafe cleanup of any lingering backticks just in case
                code = re.sub(r'^```[a-zA-Z]*\n?', '', code)
                code = re.sub(r'\n?```$', '', code)
            if looks_truncated(content):
                notes.append(
                    "The response was still incomplete after "
                    f"{MAX_CONTINUATIONS} continuation attempts, so the code may be "
                    "cut off. Ask for the widget in smaller pieces."
                )

        if notes:
            explanation = (explanation + "\n\n" + "\n".join(f"_{n}_" for n in notes)).strip()

        generation_jobs[job_id] = {
            "status": "completed",
            "result": {
                "code": code,
                "explanation": explanation,
                "raw": content,
                "settings": meta,
            }
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        generation_jobs[job_id] = {"status": "failed", "error": str(e)}

@router.post("/generate")
async def start_generate_widget(req: GenerateRequest, background_tasks: BackgroundTasks, db_client: WorkspaceClient = Depends(get_db_client_sp)):
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
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI client init failed: {e}")
        
    job_id = str(uuid.uuid4())
    generation_jobs[job_id] = {"status": "pending", "result": None, "error": None}
    
    background_tasks.add_task(run_generation_task, job_id, req, api_key, base_url)
    
    return {"job_id": job_id}

@router.get("/generate/{job_id}")
async def get_generate_status(job_id: str):
    if job_id not in generation_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return generation_jobs[job_id]

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
async def test_datasource(req: DataSourceTestRequest, db_client: WorkspaceClient = Depends(get_db_client_sp)):
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
    elif req.data_source_type == "databricks_api":
        try:
            import requests
            from routes.databricks_api import _auth_headers, _error_detail, _response_data

            path = req.data_source
            if not path.startswith('/'):
                path = '/' + path

            # Use a direct HTTP response here so the SDK cannot replace a useful
            # non-JSON 4xx body with its generic "unable to parse response" error.
            url = f"{db_client.config.host.rstrip('/')}{path}"
            response = requests.get(url, headers=_auth_headers(db_client), timeout=90)
            data = _response_data(response)
            if not response.ok:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Databricks API request failed: {_error_detail(response, data)}",
                )

            schema = extract_schema_from_json(data)
            return {"schema": schema, "sample": data[:2] if isinstance(data, list) else data}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Databricks API request failed: {e}")
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
