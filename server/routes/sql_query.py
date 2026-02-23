"""
SQL Query Router - Execute SQL queries with OBO authentication.

This router provides endpoints to execute pre-configured SQL queries
using the user's Databricks token (On-Behalf-Of authentication).
"""
import os
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementExecutionAPI, Disposition
from typing import Optional, List, Dict, Any

from config.sql_queries import get_sql_query_config, get_all_sql_query_configs, SqlQueryConfig
from middleware.auth import get_user_token

# --- Configuration & Client Setup ---

from middleware.auth import get_db_client

router = APIRouter()

# --- Pydantic Models (API Contracts) ---

class SqlQueryRequest(BaseModel):
    """Request to execute a SQL query."""
    query_id: str  # ID of the pre-configured query
    parameters: Optional[Dict[str, Any]] = None  # Optional parameters for the query


class SqlQueryResponse(BaseModel):
    """Response from SQL query execution."""
    query_id: str
    status: str
    columns: List[str]
    rows: List[Dict[str, Any]]
    row_count: int
    execution_time_ms: Optional[int] = None
    statement_id: Optional[str] = None


class SqlQueryConfigResponse(BaseModel):
    """Configuration for a SQL query."""
    id: str
    name: str
    description: str
    category: str
    refresh_interval: Optional[int] = None
    has_parameters: bool = False


class SqlQueryListResponse(BaseModel):
    """List of available SQL queries."""
    queries: List[SqlQueryConfigResponse]


# --- API Endpoints ---

@router.get("/list", response_model=SqlQueryListResponse, summary="List available SQL queries")
async def list_sql_queries():
    """
    Returns a list of all available SQL query configurations.
    """
    configs = get_all_sql_query_configs()
    return SqlQueryListResponse(
        queries=[
            SqlQueryConfigResponse(
                id=config.id,
                name=config.name,
                description=config.description,
                category=config.category,
                refresh_interval=config.refresh_interval,
                has_parameters=config.parameters is not None and len(config.parameters) > 0
            )
            for config in configs
        ]
    )


@router.get("/config/{query_id}", summary="Get SQL query configuration")
async def get_query_config(query_id: str):
    """
    Returns the full configuration for a specific SQL query.
    """
    try:
        config = get_sql_query_config(query_id)
        return config
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/execute", response_model=SqlQueryResponse, summary="Execute a SQL query")
@router.post("/execute/", response_model=SqlQueryResponse, summary="Execute a SQL query (trailing slash)")
async def execute_sql_query(
    query_request: SqlQueryRequest,
    w: WorkspaceClient = Depends(get_db_client)
):
    """
    Executes a pre-configured SQL query using the user's OBO token.
   
    The query is executed on the configured SQL Warehouse and results
    are returned in a structured format suitable for tables and charts.
    """
    try:
        # Get the query configuration
        config = get_sql_query_config(query_request.query_id)
       
        # Prepare the SQL query with parameters if provided
        sql = config.sql
        if query_request.parameters and config.parameters:
            for param_config in config.parameters:
                param_name = param_config.name
                param_value = query_request.parameters.get(param_name, param_config.default)
                if param_value is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Missing required parameter: {param_name}"
                    )
                # Replace parameter placeholder in SQL
                sql = sql.replace(f"{{{param_name}}}", str(param_value))
       
        logging.info(f"Executing SQL query '{query_request.query_id}' for user")
        logging.debug(f"SQL: {sql}")
       
        sql_api = StatementExecutionAPI(w.api_client)
       
        # Get the warehouse ID (uses default if not specified in config)
        warehouse_id = config.get_warehouse_id()
        if not warehouse_id:
            raise HTTPException(
                status_code=500,
                detail="No SQL Warehouse ID configured. Set SQL_WAREHOUSE_ID in app.yaml"
            )
       
        # Execute the SQL statement
        statement = sql_api.execute_statement(
            warehouse_id=warehouse_id,
            statement=sql,
            wait_timeout="50s",  # Wait up to 30 seconds for results
            disposition=Disposition.INLINE,  # Return results inline
        )
       
        logging.info(f"Statement executed: {statement.statement_id}, status: {statement.status}")
       
        # Extract columns and data
        columns = []
        rows = []
       
        if statement.manifest and statement.manifest.schema and statement.manifest.schema.columns:
            columns = [col.name for col in statement.manifest.schema.columns]
       
        if statement.result and statement.result.data_array:
            for row_data in statement.result.data_array:
                row_dict = {}
                for i, col_name in enumerate(columns):
                    row_dict[col_name] = row_data[i] if i < len(row_data) else None
                rows.append(row_dict)
       
        logging.info(f"Query returned {len(rows)} rows with {len(columns)} columns")
       
        # Build response
        # Extract execution time safely - the attribute name may vary
        execution_time = None
        if statement.status:
            # Try different possible attribute names
            execution_time = getattr(statement.status, 'execution_time_ms', None)
            if execution_time is None:
                execution_time = getattr(statement.status, 'execution_duration_ms', None)
       
        response = SqlQueryResponse(
            query_id=query_request.query_id,
            status=str(statement.status.state) if statement.status else "COMPLETED",
            columns=columns,
            rows=rows,
            row_count=len(rows),
            execution_time_ms=execution_time,
            statement_id=statement.statement_id,
        )
       
        return response
       
    except ValueError as e:
        # Query config not found
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # Catch any SDK or other errors
        logging.exception(f"Error executing SQL query: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error executing SQL query: {str(e)}")


@router.post("/execute/{query_id}", response_model=SqlQueryResponse, summary="Execute a SQL query by ID")
async def execute_sql_query_by_id(
    query_id: str,
    parameters: Optional[Dict[str, Any]] = None,
    w: WorkspaceClient = Depends(get_db_client)
):
    """
    Convenience endpoint to execute a query by ID without a request body.
    Parameters can be passed as query parameters or in the request body.
    """
    query_request = SqlQueryRequest(query_id=query_id, parameters=parameters or {})
    return await execute_sql_query(query_request, w)


class RawSqlRequest(BaseModel):
    """Request to execute a raw SQL string against Databricks."""
    sql: Optional[str] = None
    raw_query: Optional[str] = None  # Alias accepted for convenience
    max_rows: Optional[int] = 500


@router.post("/execute-raw", summary="Execute a raw SQL string against Databricks")
async def execute_raw_sql(
    req: RawSqlRequest,
    w: WorkspaceClient = Depends(get_db_client)
):
    """
    Executes an arbitrary SQL query string on the configured SQL Warehouse.
    Used by generated widgets that receive their SQL via props.data.dataSource.
    """
    import traceback

    sql_statement = req.sql or req.raw_query
    if not sql_statement:
        raise HTTPException(status_code=400, detail="Request body must include a 'sql' field with the SQL query to execute.")

    warehouse_id = os.environ.get("SQL_WAREHOUSE_ID", "")
    if not warehouse_id:
        raise HTTPException(
            status_code=500,
            detail="No SQL Warehouse ID configured. Set SQL_WAREHOUSE_ID in environment."
        )

    try:
        sql_api = StatementExecutionAPI(w.api_client)

        statement = sql_api.execute_statement(
            warehouse_id=warehouse_id,
            statement=sql_statement,
            wait_timeout="50s",
            disposition=Disposition.INLINE,
        )

        columns = []
        rows = []

        if statement.manifest and statement.manifest.schema and statement.manifest.schema.columns:
            columns = [col.name for col in statement.manifest.schema.columns]

        max_rows = req.max_rows or 500
        if statement.result and statement.result.data_array:
            for row_data in statement.result.data_array[:max_rows]:
                row_dict = {}
                for i, col_name in enumerate(columns):
                    row_dict[col_name] = row_data[i] if i < len(row_data) else None
                rows.append(row_dict)

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "statement_id": statement.statement_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        logging.error(f"Error executing raw SQL:\n{tb}")
        raise HTTPException(status_code=500, detail=f"SQL execution failed: {str(e)}\n\nTraceback:\n{tb}")