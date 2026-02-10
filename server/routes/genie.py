
import os
import datetime
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from databricks.sdk.service.dashboards import GenieAPI
from typing import Optional

from config.genies import get_genie_config, get_all_genie_configs
from middleware.auth import get_user_token

# --- Configuration & Client Setup ---

from middleware.auth import get_db_client

# Use APIRouter instead of FastAPI
router = APIRouter()
# --- Pydantic Models (API Contracts) ---

class GenieQueryRequest(BaseModel):
    """The JSON body for a user's question."""
    question: str
    conversation_id: str | None = None
    space_id: str  # Databricks Genie Space ID passed directly from widget

class GenieQueryResponse(BaseModel):
    """The JSON response from the Genie service."""
    answer: str
    conversation_id: str
    status: str
    description: str | None = None
    sql: str | None = None
    row_count: int | None = None
    rows: list[dict] | None = None
    message_id: str | None = None
    attachment_id: str | None = None
    space_id: str  # Echo back the space_id that was used

class GenieConfigResponse(BaseModel):
    """Configuration for a genie."""
    id: str
    name: str
    description: str
    icon: str
    category: str

class GenieListResponse(BaseModel):
    """List of available genies."""
    genies: list[GenieConfigResponse]

# --- API Endpoints ---

@router.get("/list", response_model=GenieListResponse, summary="List available genies")
async def list_genies():
    """
    Returns a list of all available genie configurations.
    """
    configs = get_all_genie_configs()
    return GenieListResponse(
        genies=[
            GenieConfigResponse(
                id=config.id,
                name=config.name,
                description=config.description,
                icon=config.icon,
                category=config.category
            )
            for config in configs
            if config.space_id  # Only return genies with valid space_id
        ]
    )

from databricks.sdk.errors import PermissionDenied

@router.post("/query", response_model=GenieQueryResponse, summary="Ask a question to a Genie Space")
@router.post("/query/", response_model=GenieQueryResponse, summary="Ask a question to a Genie Space (trailing slash)")
async def ask_genie(
    query: GenieQueryRequest,
    w: WorkspaceClient = Depends(get_db_client)
):
    """
    Ask a question to a Genie Space.
    """
    if not query.space_id:
        raise HTTPException(status_code=400, detail="space_id is required")
   
    try:
        genie_api = GenieAPI(w.api_client)
       
        # If there is an existing conversation, append a message; else start a conversation
        if query.conversation_id:
            created_msg = genie_api.create_message_and_wait(
                space_id=query.space_id,
                conversation_id=query.conversation_id,
                content=query.question,
                timeout=datetime.timedelta(seconds=60),
            )
        else:
            created_msg = genie_api.start_conversation_and_wait(
                space_id=query.space_id,
                content=query.question,
                timeout=datetime.timedelta(seconds=60),
            )
       
        conv_id = getattr(created_msg, "conversation_id", None)
        msg_id = getattr(created_msg, "message_id", None) or getattr(created_msg, "id", None)
        if not conv_id or not msg_id:
            raise HTTPException(status_code=500, detail="Unable to resolve conversation/message ids from GenieMessage")

        # Extract from attachments and query_result on created_msg
        attachments = getattr(created_msg, "attachments", None) or []
        query_result = getattr(created_msg, "query_result", None)
        description = None
        sql = None
        row_count = None
        text_answer = None
        statement_id = None
       
        # Get row_count and statement_id from query_result if available
        if query_result:
            row_count = getattr(query_result, "row_count", None)
            statement_id = getattr(query_result, "statement_id", None)
            logging.info(f"Found query_result: row_count={row_count}, statement_id={statement_id}")
       
        if attachments:
            att = attachments[0]
            q = getattr(att, "query", None)
            if q is not None:
                description = getattr(q, "description", None)
                sql = getattr(q, "query", None)
            t = getattr(att, "text", None)
            if t is not None:
                text_answer = getattr(t, "content", None)

        # Fetch rows using the statement_id from query_result
        rows_payload: list[dict] | None = None
        if statement_id:
            logging.info(f"Fetching query results for statement_id: {statement_id}")
            try:
                from databricks.sdk.service.sql import StatementExecutionAPI
                sql_api = StatementExecutionAPI(w.api_client)
                result = sql_api.get_statement(statement_id)
                
                # Extract data from the statement result
                if result and result.result:
                    cols = []
                    data = []
                    try:
                        if result.manifest and result.manifest.schema and result.manifest.schema.columns:
                            cols = [c.name for c in result.manifest.schema.columns]
                        if result.result.data_array:
                            data = result.result.data_array
                    except Exception as e:
                        logging.error(f"Error extracting data from statement result: {e}")
                   
                    if cols and data:
                        rows_payload = []
                        for r in data:
                            obj = {}
                            for i, col in enumerate(cols):
                                obj[col] = r[i] if i < len(r) else None
                            rows_payload.append(obj)
            except Exception as e:
                logging.error(f"Failed to get statement results: {e}")
                rows_payload = None

        answer = (text_answer or "").strip() or (description or "")
       
        response = GenieQueryResponse(
            answer=answer,
            conversation_id=conv_id,
            status=str(getattr(created_msg, "status", "COMPLETED") or "COMPLETED"),
            description=description,
            sql=sql,
            row_count=row_count,
            rows=rows_payload,
            message_id=msg_id,
            attachment_id=statement_id,
            space_id=query.space_id,
        )
       
        return response

    except PermissionDenied as e:
        logging.warning(f"PermissionDenied on Genie query: {e}")
        raise HTTPException(
            status_code=403, 
            detail=f"Permission Denied: Your Databricks user does not have 'Can View' permission on Genie Space {query.space_id}. Please contact your administrator."
        )
    except Exception as e:
        logging.exception(f"An error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
