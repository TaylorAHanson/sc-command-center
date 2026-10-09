"""
SQL Query Router - Execute SQL queries with OBO authentication.

This router provides endpoints to execute pre-configured SQL queries
using the user's Databricks token (On-Behalf-Of authentication).
"""
import itertools
import json
import os
import re
import logging
import time
import zlib
import httpx
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError, STATUS_CODE_MAPPING
from databricks.sdk.service.sql import StatementExecutionAPI, Disposition, Format, StatementState
from typing import Optional, List, Dict, Any, Iterable, Iterator

from config.sql_queries import get_sql_query_config, get_all_sql_query_configs, SqlQueryConfig
from middleware.auth import get_user_token
from services.sql_advice import quoting_hint
from services.sql_safety import describe_refusal

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


#: Rows a response carries when the caller doesn't say how many it wants. A widget
#: that works on the whole result in the browser sends `all_rows: true`; `max_rows`
#: is for a deliberate cap, and the response says (`truncated`) whenever it got less.
DEFAULT_MAX_ROWS = 500

# A result bigger than one chunk arrives as a first chunk plus a pointer to the
# next. When the manifest doesn't say how many chunks there are, this bound is what
# stops a warehouse that never stops pointing from holding a request open.
MAX_CHUNK_HOPS = 200

#: How the warehouse refuses an INLINE result over 25 MiB. It fails the statement
#: rather than truncating it, so a large enough result was an error at any
#: `max_rows`; the only way to the whole of it is EXTERNAL_LINKS.
INLINE_LIMIT_ERROR = "inline byte limit exceeded"

#: Rows per piece of a streamed response.
STREAM_BATCH_ROWS = 2000

#: Fast rather than small: the rows repeat every key, so even level 1 shrinks a
#: result several times over, and this runs on the request thread.
GZIP_LEVEL = 1

#: Seconds to download one external chunk (about 20 MB).
EXTERNAL_CHUNK_TIMEOUT = 120.0

_ROW_DECODER = json.JSONDecoder()


def iter_json_rows(text: str) -> Iterator[list]:
    """The rows of a JSON_ARRAY chunk (`[["a","b"],["c",null]]`), one at a time.

    An external chunk is about 20 MB of JSON, and decoded whole it costs several
    times that in Python objects for every request, several of which a dashboard
    fires at once. A row at a time holds the text and one row.
    """
    i = text.find("[") + 1
    if i == 0:
        return
    end = len(text)
    while True:
        while i < end and text[i] in " \t\r\n,":
            i += 1
        if i >= end or text[i] == "]":
            return
        row, i = _ROW_DECODER.raw_decode(text, i)
        yield row


def iter_rows(first, fetch_chunk, download, max_hops: int = MAX_CHUNK_HOPS) -> Iterator[list]:
    """Every row of a result, following its chunks, inline or behind external links.

    `first` is the statement's `result`. An inline chunk carries its rows in
    `data_array` and points at the next with `next_chunk_index`; an external one
    carries links instead, and each link names the chunk after it. Reading only the
    first `data_array` is what made a large result look complete when it wasn't.
    One chunk is held at a time, so the result can be far larger than this server's
    memory.
    """
    result, hops = first, 0
    while result is not None:
        yield from (getattr(result, "data_array", None) or [])
        following = getattr(result, "next_chunk_index", None)
        for link in getattr(result, "external_links", None) or []:
            yield from iter_json_rows(download(link))
            following = getattr(link, "next_chunk_index", None)
        if following is None or hops >= max_hops:
            return
        result = fetch_chunk(following)
        hops += 1


def result_window(returned: int, total: Optional[int], more: bool, warehouse_truncated: bool = False) -> Dict[str, Any]:
    """What a widget needs to know about the rows it did not receive.

    Additive fields on the response, so widgets written before they existed are
    unaffected. `total_rows` is `None` when the warehouse didn't say and there is
    more than we fetched; a widget should treat that like `truncated`. A result the
    warehouse cut (`row_limit`) has no total: its count stops where its rows did.
    """
    if warehouse_truncated:
        return {"total_rows": None, "truncated": True}
    if total is not None:
        return {"total_rows": total, "truncated": bool(total > returned)}
    return {"total_rows": None if more else returned, "truncated": bool(more)}


def fetch_plans(cap: int, all_rows: bool) -> List[Dict[str, Any]]:
    """How to execute a read, in order, each tried only if the last was too big to return inline.

    A capped read first runs as it always has, so a result that fits keeps its exact
    `total_rows`. Asked again with `row_limit`, the warehouse stops at the cap and
    says it did, which fits inline unless the cap itself is over 25 MiB of rows.
    Past that the rows exist only as external links.
    """
    plans: List[Dict[str, Any]] = []
    if not all_rows:
        plans.append({"disposition": Disposition.INLINE})
    plans.append({"disposition": Disposition.INLINE, "row_limit": cap})
    plans.append({"disposition": Disposition.EXTERNAL_LINKS, "format": Format.JSON_ARRAY, "row_limit": cap})
    return plans


def too_big_for_inline(statement) -> bool:
    status = getattr(statement, "status", None)
    if getattr(status, "state", None) != StatementState.FAILED:
        return False
    message = getattr(getattr(status, "error", None), "message", "") or ""
    return INLINE_LIMIT_ERROR in message.lower()


def row_object(columns: List[str], row: list) -> Dict[str, Any]:
    return {name: row[i] if i < len(row) else None for i, name in enumerate(columns)}


def result_body(columns: List[str], rows: Iterable[list], cap: int, total: Optional[int],
                warehouse_truncated: bool, statement_id: Optional[str],
                summary: Optional[Dict[str, Any]] = None) -> Iterator[str]:
    """The response JSON, written as the rows are read; the counts come last, once known.

    The same object this endpoint has always returned, so widgets parse it as they
    did. A failure part-way through can no longer change the status, which was
    sent with the first byte, so the body ends with `truncated: true` and an
    `error` saying where it stopped. `summary` receives the final counts.
    """
    yield json.dumps({"columns": columns, "statement_id": statement_id}, ensure_ascii=False)[:-1] + ', "rows": ['
    returned, more, problem, batch = 0, False, None, []
    try:
        for row in rows:
            if returned >= cap:
                more = True
                break
            batch.append(json.dumps(row_object(columns, row), ensure_ascii=False))
            returned += 1
            if len(batch) >= STREAM_BATCH_ROWS:
                yield ("," if returned > len(batch) else "") + ",".join(batch)
                batch = []
    except Exception as exc:  # noqa: BLE001
        logging.warning("SQL result stopped after %d rows: %s", returned + len(batch), exc)
        problem = f"The result stopped after {returned:,} rows: {exc}"
    if batch:
        yield ("," if returned > len(batch) else "") + ",".join(batch)
    tail: Dict[str, Any] = {"row_count": returned, **result_window(returned, total, more, warehouse_truncated)}
    if problem:
        tail.update(truncated=True, error=problem)
    if summary is not None:
        summary.update(tail)
    yield "], " + json.dumps(tail, ensure_ascii=False)[1:]


def gzip_stream(pieces: Iterable[bytes], level: int = GZIP_LEVEL) -> Iterator[bytes]:
    packer = zlib.compressobj(level, zlib.DEFLATED, 31)  # wbits 31: a gzip container
    for piece in pieces:
        out = packer.compress(piece)
        if out:
            yield out
    yield packer.flush()


def _download(link) -> str:
    """One external chunk. The link is presigned, and storage refuses a request that
    carries a second credential, so it goes with only the headers the link names."""
    response = httpx.get(
        link.external_link,
        headers=dict(getattr(link, "http_headers", None) or {}),
        timeout=EXTERNAL_CHUNK_TIMEOUT,
    )
    response.raise_for_status()
    return response.content.decode("utf-8")


def _row_ceiling() -> int:
    from services.settings_store import get_int_setting

    return get_int_setting("widget_query_max_rows")


class RawSqlRequest(BaseModel):
    """Request to execute a raw SQL string against Databricks."""
    sql: Optional[str] = None
    raw_query: Optional[str] = None  # Alias accepted for convenience
    max_rows: Optional[int] = DEFAULT_MAX_ROWS
    #: Every row of the result, up to the deployment's `widget_query_max_rows`. What a
    #: widget that filters, sorts or totals in the browser needs: a `max_rows` sized
    #: to today's data silently drops rows once the data grows past it.
    all_rows: bool = False
    #: Correlation handle from the action confirmation, recorded in `action_logs`.
    #: Prepended to the statement as a comment so the same id appears in
    #: Databricks' own query history and the two records can be joined.
    request_id: Optional[str] = None


@router.post("/execute-raw", summary="Execute a read-only SQL string against Databricks")
def execute_raw_sql(
    req: RawSqlRequest,
    request: Request,
    w: WorkspaceClient = Depends(get_db_client)
):
    """
    Executes a **read-only** SQL query on the configured SQL Warehouse.
    Used by generated widgets that receive their SQL via props.data.dataSource.

    A statement that changes anything is refused here and belongs on
    `/execute-write`, which exists so that mutation is a deliberate choice made
    by a widget its author marked executable — not something a panel can do
    because its query happened to start with MERGE. Unity Catalog still decides
    whether the caller may write either way; this decides whether *the app* will
    carry the statement without a confirmation behind it.
    """
    sql_statement = req.sql or req.raw_query
    if not sql_statement:
        raise HTTPException(status_code=400, detail="Request body must include a 'sql' field with the SQL query to execute.")

    refusal = describe_refusal(sql_statement)
    if refusal:
        # Returned rather than raised: `.response()` carries the empty
        # rows/columns body that widgets predating the error contract read without
        # checking the status. Raising would give them `detail` alone and they
        # would throw on `undefined`, taking a live panel down over a refusal.
        return SqlStatementError(status_code=400, detail=refusal).response()

    return _run_statement(sql_statement, req, w, request, retryable=True)


@router.post("/execute-write", summary="Execute a data-modifying SQL statement")
def execute_write_sql(
    req: RawSqlRequest,
    request: Request,
    w: WorkspaceClient = Depends(get_db_client)
):
    """
    Executes a statement that may change data, under the caller's OBO token.

    Separate from `/execute-raw` so that "this widget writes" is visible in the
    widget's own code and at publish time, rather than being a property of a
    string nobody looked at. Callers should pass `request_id` from the action
    confirmation; it is stamped into the statement text so the approval recorded
    in `action_logs` can be matched to the row Databricks records in
    `system.query.history`.
    """
    sql_statement = req.sql or req.raw_query
    if not sql_statement:
        raise HTTPException(status_code=400, detail="Request body must include a 'sql' field with the SQL query to execute.")

    correlation = (req.request_id or "").strip()
    if correlation:
        # Comment rather than a parameter: it survives into the statement text
        # that query history stores, which is the only field the two records share.
        safe = re.sub(r"[^A-Za-z0-9_.:-]", "", correlation)[:80]
        if safe:
            sql_statement = f"/* cc-action: {safe} */\n{sql_statement}"

    # Never retried: re-running a write to fetch its result differently would apply it twice.
    return _run_statement(sql_statement, req, w, request, retryable=False)


def _run_statement(
    sql_statement: str,
    req: RawSqlRequest,
    w: WorkspaceClient,
    request: Request,
    retryable: bool,
):
    """Shared execution for both raw endpoints, so they cannot drift apart."""
    import traceback

    warehouse_id = os.environ.get("SQL_WAREHOUSE_ID", "")
    if not warehouse_id:
        raise HTTPException(
            status_code=500,
            detail="No SQL Warehouse ID configured. Set SQL_WAREHOUSE_ID in environment."
        )

    ceiling = _row_ceiling()
    cap = ceiling if req.all_rows else max(1, min(req.max_rows or DEFAULT_MAX_ROWS, ceiling))
    plans = fetch_plans(cap, req.all_rows)
    if not retryable:
        plans = plans[:1]

    try:
        sql_api = StatementExecutionAPI(w.api_client)
        started = time.monotonic()

        for plan in plans:
            statement = sql_api.execute_statement(
                warehouse_id=warehouse_id,
                statement=sql_statement,
                wait_timeout="50s",
                **plan,
            )
            if not too_big_for_inline(statement):
                break
        _raise_if_unsuccessful(statement, sql_statement)

        columns = []
        if statement.manifest and statement.manifest.schema and statement.manifest.schema.columns:
            columns = [col.name for col in statement.manifest.schema.columns]

        manifest = statement.manifest
        rows = iter_rows(
            statement.result,
            lambda index: sql_api.get_statement_result_chunk_n(statement.statement_id, index),
            _download,
            getattr(manifest, "total_chunk_count", None) or MAX_CHUNK_HOPS,
        )
        external = plan["disposition"] == Disposition.EXTERNAL_LINKS
        try:
            # Read before anything is sent, so a result that can't be downloaded
            # at all is an error status rather than a 200 with no rows.
            first = list(itertools.islice(rows, 1))
        except httpx.HTTPError as e:
            raise SqlStatementError(
                status_code=502,
                detail="This result is over 25 MB, so the warehouse hands it over as files in "
                       f"cloud storage, and the app couldn't download them ({type(e).__name__}). "
                       "Aggregate or filter in the query, or ask an admin whether this app may "
                       "reach the workspace's storage.",
            ) from e

        summary: Dict[str, Any] = {}
        body = result_body(
            columns,
            itertools.chain(first, rows),
            cap,
            getattr(manifest, "total_row_count", None),
            bool(getattr(manifest, "truncated", False)),
            statement.statement_id,
            summary,
        )

        def encoded() -> Iterator[bytes]:
            yield from (piece.encode("utf-8") for piece in body)
            logging.info(
                "SQL result: %s rows (%s %s)%s in %.1fs, %s",
                f"{summary.get('row_count', 0):,}",
                "all_rows, ceiling" if req.all_rows else "max_rows",
                f"{cap:,}",
                ", truncated" if summary.get("truncated") else "",
                time.monotonic() - started,
                "external links" if external else "inline",
            )

        headers = {"Vary": "Accept-Encoding"}
        if "gzip" in (request.headers.get("accept-encoding") or "").lower():
            headers["Content-Encoding"] = "gzip"
            return StreamingResponse(gzip_stream(encoded()), media_type="application/json", headers=headers)
        return StreamingResponse(encoded(), media_type="application/json", headers=headers)
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