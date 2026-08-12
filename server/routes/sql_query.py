"""
SQL Query Router - Execute SQL queries with OBO authentication.

This router provides endpoints to execute pre-configured SQL queries
using the user's Databricks token (On-Behalf-Of authentication).
"""
import os
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError, STATUS_CODE_MAPPING
from databricks.sdk.service.sql import StatementExecutionAPI, Disposition, StatementState
from typing import Optional, List, Dict, Any

from config.sql_queries import get_sql_query_config, get_all_sql_query_configs, SqlQueryConfig
from middleware.auth import get_user_token
from services.sql_advice import quoting_hint

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
def list_sql_queries():
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


# NOTE: defined as a sync `def` (not `async def`). The Databricks SDK call below
# is blocking and waits up to 50s; FastAPI runs sync handlers in a worker thread,
# so this no longer stalls the event loop (and the agent's SSE streams) while it
# waits. Do not add `await` here without also reverting to `async def`.
@router.post("/execute", response_model=SqlQueryResponse, summary="Execute a SQL query")
@router.post("/execute/", response_model=SqlQueryResponse, summary="Execute a SQL query (trailing slash)")
def execute_sql_query(
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
                detail="No SQL Warehouse ID configured. Set SQL_WAREHOUSE_ID in databricks.yml"
            )
       
        # Execute the SQL statement
        statement = sql_api.execute_statement(
            warehouse_id=warehouse_id,
            statement=sql,
            wait_timeout="50s",  # Wait up to 30 seconds for results
            disposition=Disposition.INLINE,  # Return results inline
        )
       
        logging.info(f"Statement executed: {statement.statement_id}, status: {statement.status}")
        _raise_if_unsuccessful(statement, sql)

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
       
    except SqlStatementError as e:
        return e.response()
    except DatabricksError as e:
        logging.warning("Warehouse refused a statement (%s): %s", type(e).__name__, e)
        return _refusal(e, sql).response()
    except HTTPException:
        # Already carries the status the caller needs to branch on — a 400 naming
        # the query's own mistake, a 404 for a missing parameter, the 504 for a
        # query still running. Without this they were caught below and re-raised as
        # a 500, so a fixable SQL error arrived looking like a server fault and the
        # quoting hint arrived buried in a traceback. `execute_raw_sql` has always
        # done this; the two endpoints must agree.
        raise
    except ValueError as e:
        # Query config not found
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # Catch any SDK or other errors
        logging.exception(f"Error executing SQL query: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error executing SQL query: {str(e)}")


@router.post("/execute/{query_id}", response_model=SqlQueryResponse, summary="Execute a SQL query by ID")
def execute_sql_query_by_id(
    query_id: str,
    parameters: Optional[Dict[str, Any]] = None,
    w: WorkspaceClient = Depends(get_db_client)
):
    """
    Convenience endpoint to execute a query by ID without a request body.
    Parameters can be passed as query parameters or in the request body.
    """
    query_request = SqlQueryRequest(query_id=query_id, parameters=parameters or {})
    return execute_sql_query(query_request, w)


class SqlStatementError(HTTPException):
    """A statement the warehouse refused, in a body both kinds of caller can read.

    Anything written against the current contract branches on the status code and
    reads `detail` — that is what lets Widget Studio's auto-fix see the real error
    and repair the query. Widgets generated before that contract existed do
    `const d = await res.json(); setRows(d.rows)` without looking at the status, and
    a failure used to reach them as HTTP 200 with no rows. So the body carries that
    empty result too: an old widget on a live dashboard keeps showing "no data"
    instead of throwing on `undefined`, which would take the panel down with it.
    """

    def response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={
                "detail": self.detail,
                "error": self.detail,
                "columns": [],
                "rows": [],
                "row_count": 0,
            },
        )


#: The SDK's own view of what each of its errors means over HTTP, inverted. Kept
#: from its table rather than a second one maintained here by hand.
_SDK_STATUS = {cls: code for code, cls in STATUS_CODE_MAPPING.items()}


def _refusal(exc: DatabricksError, sql: str) -> SqlStatementError:
    """A warehouse error the request never got past, as something a widget can show.

    `execute_statement` raises rather than returns when the query never ran at all
    — a stopped or missing warehouse, an expired token, a statement the service
    turned down before planning it. Those reached the catch-all handler and came
    back as HTTP 500 with a Python traceback in `detail`, which widgets render
    into the panel exactly as given: a stack trace where the numbers should be,
    under a status code that blames the app rather than the query. A query that
    fails *after* it starts is `_raise_if_unsuccessful`'s business; between them
    every refusal now arrives in the same shape.
    """
    status = next((_SDK_STATUS[cls] for cls in type(exc).__mro__ if cls in _SDK_STATUS), 502)
    message = str(exc).strip()
    if message in ("", "None"):
        # An SDK error carrying no message stringifies as the literal "None",
        # and a widget shows `detail` to whoever is looking at the panel.
        message = type(exc).__name__
    return SqlStatementError(status_code=status, detail=message + quoting_hint(sql, message))


def _raise_if_unsuccessful(statement, sql: str) -> None:
    """Turn a statement that didn't succeed into an error the caller can see.

    `execute_statement` reports a rejected query in its status rather than by
    raising, so a query that failed — bad quoting, a missing table, no permission —
    used to come back as HTTP 200 with an empty manifest. The widget then rendered
    "no data" and Widget Studio's auto-retry never learned there was anything to
    fix, which is how a query missing its backticks turned into a silent blank
    panel instead of a fixable error.
    """
    status = getattr(statement, "status", None)
    state = getattr(status, "state", None)
    if state in (StatementState.PENDING, StatementState.RUNNING):
        raise SqlStatementError(
            status_code=504,
            detail="The query is still running after 50s. Narrow it, or pre-aggregate the data.",
        )
    if state in (StatementState.FAILED, StatementState.CANCELED, StatementState.CLOSED):
        error = getattr(status, "error", None)
        message = getattr(error, "message", "") or ""
        name = getattr(state, "value", str(state))
        detail = message or f"The query {str(name).lower()}."
        raise SqlStatementError(status_code=400, detail=detail + quoting_hint(sql, detail))


class RawSqlRequest(BaseModel):
    """Request to execute a raw SQL string against Databricks."""
    sql: Optional[str] = None
    raw_query: Optional[str] = None  # Alias accepted for convenience
    max_rows: Optional[int] = 500


@router.post("/execute-raw", summary="Execute a raw SQL string against Databricks")
def execute_raw_sql(
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
        _raise_if_unsuccessful(statement, sql_statement)

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
    except SqlStatementError as e:
        return e.response()
    except DatabricksError as e:
        logging.warning("Warehouse refused a statement (%s): %s", type(e).__name__, e)
        return _refusal(e, sql_statement).response()
    except HTTPException:
        raise
    except Exception as e:
        # The traceback goes to the log, not to the caller: widgets print `detail`
        # straight into the panel, and it is no use to whoever is reading it there.
        logging.error("Error executing raw SQL:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"SQL execution failed: {e}")