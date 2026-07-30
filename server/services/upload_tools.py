"""The tools an agent uses to interrogate a file the user attached.

The premise: a file's *content* never goes in the prompt. The prompt carries a
constant-size card (columns, row count, a few sample rows) and these tools, so a
200 MB spreadsheet costs the same context as a small one and the model pulls only
what it actually needs.

`query_file` deliberately takes a structured specification — columns, filters,
group-by, aggregations — instead of a pandas or SQL expression string. An
expression would mean evaluating model-authored code inside the web process,
which holds the caller's credentials; the structured form cannot express anything
but a query, so there is nothing to escape from. It costs the model a little
verbosity and costs us a validation layer, and in exchange the blast radius of a
badly behaved model is a confusing table.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from services import upload_store

# Enough rows to see a pattern, few enough that a careless `limit` cannot flood
# the context window. The model can page with `offset` when it needs more.
DEFAULT_ROWS = 20
MAX_ROWS = 200
MAX_COLUMNS = 24
MAX_CELL_CHARS = 80

# Document reads and searches are bounded the same way, in characters.
DEFAULT_TEXT_CHARS = 4000
MAX_TEXT_CHARS = 12000
MAX_PASSAGES = 5

_NUMERIC_AGGS = {"sum", "mean", "median", "std", "min", "max"}
_ANY_AGGS = {"count", "nunique", "first", "last"}

# Derived columns, computed before filtering and grouping. Without these the most
# ordinary spreadsheet question there is — revenue, which is quantity times price —
# cannot be expressed at all: summing each column separately is not the same
# number, and a model asked for it will either page through every row or quietly
# multiply the totals and be wrong.
_BINARY_OPS = {"add", "subtract", "multiply", "divide"}
_UNARY_OPS = {"year", "month", "day", "date", "year_month", "abs", "length", "lower"}

_STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "with", "that", "this", "from",
    "have", "has", "had", "what", "which", "when", "where", "how", "why", "does",
    "did", "you", "your", "our", "not", "all", "any", "can", "into", "about",
}


class ToolInputError(Exception):
    """Bad arguments from the model. Surfaced as text so it can self-correct."""


# ------------------------------------------------------------ prompt assembly

def attachments_prompt(attachments: List[Dict[str, Any]]) -> str:
    """The `## Attached files` block: one card per file, plus how to use them."""
    from services import file_extract

    if not attachments:
        return ""
    blocks: List[str] = []
    for meta in attachments:
        card = file_extract.file_card(
            meta.get("filename") or "file",
            meta.get("kind") or "",
            int(meta.get("size_bytes") or 0),
            meta.get("profile") or {},
        )
        blocks.append(f"**file_id `{meta['id']}`**\n{card}")
        for warning in (meta.get("warnings") or [])[:3]:
            blocks.append(f"_Note on this file: {warning}_")

    kinds = {(m.get("kind") or "") for m in attachments}
    guidance = [
        "The user attached the following files. What you see below is a summary, "
        "not the file: never claim a total, count, or conclusion from the sample "
        "rows or preview alone.",
    ]
    if "table" in kinds:
        guidance.append(
            "For anything a spreadsheet can answer — totals, counts, filters, "
            "breakdowns, outliers — call `query_file`. It runs over every row, "
            "which the sample cannot. When the figure is a per-row calculation "
            "(revenue from units and price, margin, a ratio), add a `computed` "
            "column and aggregate that; never multiply two separate totals "
            "together, and never page through rows to add them up yourself. Use "
            "`inspect_file` first if you need the full column list."
        )
    if "document" in kinds:
        guidance.append(
            "For documents, call `search_file` to find the passages that bear on "
            "the question and cite the page numbers it returns; use `read_file` "
            "to read a specific page or to continue reading."
        )
    if "image" in kinds:
        guidance.append("Attached images are included directly in the conversation; read them yourself.")

    return "## Attached files\n" + "\n".join(guidance) + "\n\n" + "\n\n".join(blocks)


# --------------------------------------------------------------- tool specs

def tool_specs(attachments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OpenAI tool specs for the kinds of file actually attached.

    Registering a table tool when only a PDF is attached invites the model to try
    it, so the list follows the attachments.
    """
    if not attachments:
        return []
    kinds = {(m.get("kind") or "") for m in attachments}
    ids = ", ".join(f"'{m['id']}' ({m.get('filename')})" for m in attachments)
    specs: List[Dict[str, Any]] = []

    file_id_prop = {"type": "string", "description": f"Which attached file. One of: {ids}."}

    specs.append({
        "type": "function",
        "function": {
            "name": "inspect_file",
            "description": (
                "Describe an attached file in full: for a spreadsheet or CSV, every column "
                "with its type, null count and distinct count, plus sheet names and row counts; "
                "for a document, its length, page count and headings. Use this when the summary "
                "in the prompt is not enough to know what you can ask for."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": file_id_prop,
                    "sheet": {"type": "string", "description": "Sheet name, for a multi-sheet workbook."},
                },
                "required": ["file_id"],
            },
        },
    })

    if "table" in kinds:
        specs.append({
            "type": "function",
            "function": {
                "name": "query_file",
                "description": (
                    "Run a query over EVERY row of an attached spreadsheet or CSV and get the "
                    "result back as a table. This is how you answer questions about the data: "
                    "derive columns, filter rows, group and aggregate, sort, and page. For a "
                    "row-by-row calculation such as revenue, add a `computed` column "
                    "(units multiply unit_price) and then aggregate THAT — summing the two "
                    "columns separately gives a different, wrong number. Never estimate from "
                    "sample rows and never page through the file by hand: query instead."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": file_id_prop,
                        "sheet": {"type": "string", "description": "Sheet name, for a multi-sheet workbook."},
                        "computed": {
                            "type": "array",
                            "description": (
                                "Columns derived per row before filtering and grouping; refer to them "
                                "later by alias. Example: {alias: 'revenue', left: 'units', "
                                "op: 'multiply', right: 'unit_price'}, or {alias: 'month', "
                                "left: 'closed_on', op: 'year_month'}."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "alias": {"type": "string", "description": "Name for the derived column."},
                                    "left": {"description": "A column name, or a number as a literal."},
                                    "op": {
                                        "type": "string",
                                        "enum": sorted(_BINARY_OPS | _UNARY_OPS),
                                        "description": (
                                            "Arithmetic (add, subtract, multiply, divide) needs `right`. "
                                            "year, month, day, date, year_month extract from a date; "
                                            "abs, length, lower take only `left`."
                                        ),
                                    },
                                    "right": {"description": "Second operand for arithmetic: a column name or a number."},
                                },
                                "required": ["alias", "left", "op"],
                            },
                        },
                        "columns": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Columns to return. Omit for all columns.",
                        },
                        "filters": {
                            "type": "array",
                            "description": "Row conditions, combined with AND.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "column": {"type": "string"},
                                    "op": {
                                        "type": "string",
                                        "enum": ["eq", "ne", "gt", "gte", "lt", "lte", "contains",
                                                 "starts_with", "ends_with", "in", "not_in",
                                                 "between", "is_null", "not_null"],
                                    },
                                    "value": {"description": "Comparison value; a list for in/not_in/between."},
                                },
                                "required": ["column", "op"],
                            },
                        },
                        "group_by": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Group rows by these columns before aggregating.",
                        },
                        "aggregations": {
                            "type": "array",
                            "description": "Aggregates to compute. With group_by, one row per group; without it, one row overall.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "column": {"type": "string", "description": "Column to aggregate, or '*' with func=count."},
                                    "func": {
                                        "type": "string",
                                        "enum": ["sum", "mean", "median", "std", "min", "max", "count", "nunique"],
                                    },
                                    "alias": {"type": "string", "description": "Name for the result column."},
                                },
                                "required": ["column", "func"],
                            },
                        },
                        "sort": {
                            "type": "array",
                            "description": "Sort order applied to the result.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "column": {"type": "string"},
                                    "desc": {"type": "boolean"},
                                },
                                "required": ["column"],
                            },
                        },
                        "limit": {"type": "integer", "description": f"Rows to return (default {DEFAULT_ROWS}, max {MAX_ROWS})."},
                        "offset": {"type": "integer", "description": "Rows to skip, for paging."},
                    },
                    "required": ["file_id"],
                },
            },
        })

    if "document" in kinds or "data" in kinds:
        specs.append({
            "type": "function",
            "function": {
                "name": "search_file",
                "description": (
                    "Find the passages of an attached document that bear on a question. Returns "
                    "the best-matching excerpts with page numbers where the file has pages, so "
                    "you can quote and cite them."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": file_id_prop,
                        "query": {"type": "string", "description": "What to look for, in the user's own terms."},
                        "max_passages": {"type": "integer", "description": f"How many excerpts (default 3, max {MAX_PASSAGES})."},
                    },
                    "required": ["file_id", "query"],
                },
            },
        })

    specs.append({
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read an attached file directly: a specific page of a document, the next stretch "
                "of its text, or a window of rows from a spreadsheet. Use it to continue reading "
                "after a search, or when a question needs the document in order rather than by "
                "relevance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": file_id_prop,
                    "page": {"type": "integer", "description": "Page number, for a PDF."},
                    "offset": {"type": "integer", "description": "Characters (documents) or rows (tables) to skip."},
                    "limit": {"type": "integer", "description": f"Characters (documents, max {MAX_TEXT_CHARS}) or rows (tables) to return."},
                    "sheet": {"type": "string", "description": "Sheet name, for a multi-sheet workbook."},
                },
                "required": ["file_id"],
            },
        },
    })

    return specs


# ------------------------------------------------------------------ dispatch

def run_tool(env: str, name: str, args: Dict[str, Any], attachments: List[Dict[str, Any]]) -> str:
    """Execute one file tool and render its result as text for the model."""
    allowed = {m["id"]: m for m in attachments}
    try:
        file_id = _resolve_file_id(args.get("file_id"), allowed)
        meta = allowed[file_id]
        if name == "inspect_file":
            return _inspect(env, meta, args)
        if name == "query_file":
            return _query(env, meta, args)
        if name == "search_file":
            return _search(env, meta, args)
        if name == "read_file":
            return _read(env, meta, args)
        return f"Unknown file tool '{name}'."
    except ToolInputError as exc:
        return str(exc)
    except upload_store.UploadError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        return f"That file operation failed: {exc}"


def _resolve_file_id(raw: Any, allowed: Dict[str, Dict[str, Any]]) -> str:
    """Accept the id, or the filename the model saw next to it."""
    value = str(raw or "").strip()
    if value in allowed:
        return value
    for upload_id, meta in allowed.items():
        if value and value.lower() == (meta.get("filename") or "").lower():
            return upload_id
    names = ", ".join(f"'{i}' ({m.get('filename')})" for i, m in allowed.items()) or "none"
    raise ToolInputError(f"No attached file '{value}'. Attached files are: {names}.")


# -------------------------------------------------------------------- tables

def _load(env: str, meta: Dict[str, Any], args: Dict[str, Any]):
    if (meta.get("kind") or "") != "table":
        raise ToolInputError(
            f"'{meta.get('filename')}' is not tabular data, so it cannot be queried. "
            "Use search_file or read_file instead."
        )
    sheet = (args.get("sheet") or "").strip() or None
    try:
        return upload_store.load_table(env, meta["id"], sheet)
    except KeyError as exc:
        raise ToolInputError(str(exc).strip("'")) from exc


def _column(frame, name: Any) -> str:
    """Resolve a column the model named, tolerating case and spacing drift."""
    wanted = str(name or "").strip()
    columns = [str(c) for c in frame.columns]
    if wanted in columns:
        return wanted
    lowered = {c.lower(): c for c in columns}
    if wanted.lower() in lowered:
        return lowered[wanted.lower()]
    squashed = {re.sub(r"[^a-z0-9]", "", c.lower()): c for c in columns}
    key = re.sub(r"[^a-z0-9]", "", wanted.lower())
    if key in squashed:
        return squashed[key]
    preview = ", ".join(columns[:MAX_COLUMNS]) + (f", … {len(columns) - MAX_COLUMNS} more" if len(columns) > MAX_COLUMNS else "")
    raise ToolInputError(f"No column '{wanted}'. Available columns: {preview}.")


def _coerce(series, value: Any) -> Any:
    """Match a literal to the column's type so "5" filters a numeric column."""
    import pandas as pd

    if value is None or not isinstance(value, str):
        return value
    if pd.api.types.is_numeric_dtype(series):
        try:
            return float(value) if "." in value else int(value)
        except ValueError:
            return value
    if pd.api.types.is_datetime64_any_dtype(series):
        try:
            return pd.to_datetime(value)
        except Exception:  # noqa: BLE001
            return value
    return value


def _apply_filters(frame, filters: Any):
    import pandas as pd

    if not filters:
        return frame
    if not isinstance(filters, list):
        raise ToolInputError("`filters` must be a list of {column, op, value} objects.")
    mask = pd.Series(True, index=frame.index)
    for spec in filters:
        if not isinstance(spec, dict):
            raise ToolInputError("Each filter must be an object with column, op and (usually) value.")
        column = _column(frame, spec.get("column"))
        op = str(spec.get("op") or "eq").strip().lower()
        series = frame[column]
        raw = spec.get("value")

        if op in ("is_null", "not_null"):
            condition = series.isna() if op == "is_null" else series.notna()
        elif op in ("in", "not_in"):
            values = raw if isinstance(raw, list) else [raw]
            coerced = [_coerce(series, v) for v in values]
            member = series.isin(coerced)
            condition = member if op == "in" else ~member
        elif op == "between":
            if not isinstance(raw, list) or len(raw) != 2:
                raise ToolInputError("`between` needs value as a two-element list [low, high].")
            low, high = (_coerce(series, raw[0]), _coerce(series, raw[1]))
            condition = series.between(low, high)
        elif op in ("contains", "starts_with", "ends_with"):
            text = series.astype(str)
            needle = str(raw if raw is not None else "")
            if op == "contains":
                condition = text.str.contains(needle, case=False, na=False, regex=False)
            elif op == "starts_with":
                condition = text.str.lower().str.startswith(needle.lower(), na=False)
            else:
                condition = text.str.lower().str.endswith(needle.lower(), na=False)
        else:
            value = _coerce(series, raw)
            comparisons = {
                "eq": lambda: series == value,
                "ne": lambda: series != value,
                "gt": lambda: series > value,
                "gte": lambda: series >= value,
                "lt": lambda: series < value,
                "lte": lambda: series <= value,
            }
            if op not in comparisons:
                raise ToolInputError(f"Unsupported filter op '{op}'.")
            try:
                condition = comparisons[op]()
            except TypeError as exc:
                raise ToolInputError(
                    f"Cannot compare column '{column}' with {raw!r}: {exc}."
                ) from exc
        mask &= condition.fillna(False)
    return frame[mask]


def _operand(frame, value: Any, label: str):
    """A computed-column operand: a JSON number is a literal, a string is a column."""
    if isinstance(value, bool):
        raise ToolInputError(f"`{label}` must be a column name or a number.")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and value.strip():
        return frame[_column(frame, value)]
    raise ToolInputError(f"`{label}` must be a column name or a number.")


def _compute(frame, computed: Any):
    """Add derived columns so they can be filtered, grouped, aggregated and sorted."""
    import pandas as pd

    if not computed:
        return frame
    if not isinstance(computed, list):
        raise ToolInputError("`computed` must be a list of {alias, left, op, right} objects.")
    frame = frame.copy()
    for spec in computed:
        if not isinstance(spec, dict):
            raise ToolInputError("Each computed column must be an object with alias, left and op.")
        op = str(spec.get("op") or "").strip().lower()
        alias = str(spec.get("alias") or "").strip()
        if not alias:
            raise ToolInputError("Each computed column needs an `alias` to refer to it by.")
        left = _operand(frame, spec.get("left"), "left")

        if op in _BINARY_OPS:
            right = _operand(frame, spec.get("right"), "right")
            try:
                if op == "add":
                    frame[alias] = left + right
                elif op == "subtract":
                    frame[alias] = left - right
                elif op == "multiply":
                    frame[alias] = left * right
                else:
                    # Division by zero yields NaN rather than an exception, which
                    # reads as "no value" in the result instead of failing the query.
                    frame[alias] = pd.Series(left, index=frame.index) / pd.Series(right, index=frame.index).replace(0, pd.NA)
            except TypeError as exc:
                raise ToolInputError(f"Cannot {op} those columns: {exc}.") from exc
        elif op in _UNARY_OPS:
            series = left if hasattr(left, "dtype") else pd.Series(left, index=frame.index)
            if op in ("year", "month", "day", "date", "year_month"):
                stamps = pd.to_datetime(series, errors="coerce")
                if op == "year":
                    frame[alias] = stamps.dt.year
                elif op == "month":
                    frame[alias] = stamps.dt.month
                elif op == "day":
                    frame[alias] = stamps.dt.day
                elif op == "date":
                    frame[alias] = stamps.dt.date.astype(str)
                else:
                    frame[alias] = stamps.dt.strftime("%Y-%m")
            elif op == "abs":
                frame[alias] = pd.to_numeric(series, errors="coerce").abs()
            elif op == "length":
                frame[alias] = series.astype(str).str.len()
            else:
                frame[alias] = series.astype(str).str.lower()
        else:
            raise ToolInputError(
                f"Unsupported computed op '{op}'. Use one of: "
                + ", ".join(sorted(_BINARY_OPS | _UNARY_OPS)) + "."
            )
    return frame


def _aggregate(frame, group_by: Any, aggregations: Any):
    """Group and aggregate, returning a DataFrame with flat column names."""
    import pandas as pd

    groups = [_column(frame, g) for g in (group_by or [])]
    specs: List[Tuple[str, str, str]] = []
    for spec in (aggregations or []):
        if not isinstance(spec, dict):
            raise ToolInputError("Each aggregation must be an object with column and func.")
        func = str(spec.get("func") or "").strip().lower()
        if func not in _NUMERIC_AGGS | _ANY_AGGS:
            raise ToolInputError(f"Unsupported aggregation '{func}'.")
        raw_column = str(spec.get("column") or "").strip()
        if raw_column in ("*", "") and func == "count":
            # count(*) has no column of its own; count over the group index.
            column = groups[0] if groups else str(frame.columns[0])
        else:
            column = _column(frame, raw_column)
        alias = str(spec.get("alias") or "").strip() or f"{func}_{column}"
        specs.append((alias, column, func))

    if not specs:
        if not groups:
            raise ToolInputError("Provide `aggregations` (and optionally `group_by`), or omit both to list rows.")
        # group_by alone reads as "how many per group", which is what a person means.
        counted = frame.groupby(groups, dropna=False).size().reset_index(name="count")
        return counted

    if groups:
        grouped = frame.groupby(groups, dropna=False)
        columns = {}
        for alias, column, func in specs:
            columns[alias] = grouped[column].agg(func)
        return pd.DataFrame(columns).reset_index()

    row = {}
    for alias, column, func in specs:
        row[alias] = [frame[column].agg(func)]
    return pd.DataFrame(row)


def _sort(frame, sort: Any):
    if not sort:
        return frame
    if not isinstance(sort, list):
        raise ToolInputError("`sort` must be a list of {column, desc} objects.")
    columns, ascending = [], []
    for spec in sort:
        if isinstance(spec, str):
            columns.append(_column(frame, spec))
            ascending.append(True)
            continue
        if not isinstance(spec, dict):
            raise ToolInputError("Each sort entry must be a column name or {column, desc}.")
        columns.append(_column(frame, spec.get("column")))
        ascending.append(not bool(spec.get("desc")))
    return frame.sort_values(by=columns, ascending=ascending, kind="mergesort")


def _query(env: str, meta: Dict[str, Any], args: Dict[str, Any]) -> str:
    frame = _load(env, meta, args)
    total_rows = len(frame)
    frame = _compute(frame, args.get("computed"))
    filtered = _apply_filters(frame, args.get("filters"))
    matched = len(filtered)

    group_by = args.get("group_by") or []
    aggregations = args.get("aggregations") or []
    if group_by or aggregations:
        result = _aggregate(filtered, group_by, aggregations)
        shape = f"{len(result)} group(s) from {matched:,} matching row(s) of {total_rows:,}"
    else:
        columns = args.get("columns") or []
        if columns:
            picked = [_column(filtered, c) for c in columns]
            result = filtered[picked]
        else:
            result = filtered
        shape = f"{matched:,} matching row(s) of {total_rows:,}"

    result = _sort(result, args.get("sort"))

    offset = max(0, int(args.get("offset") or 0))
    limit = int(args.get("limit") or DEFAULT_ROWS)
    limit = max(1, min(limit, MAX_ROWS))
    window = result.iloc[offset:offset + limit]

    header = f"{meta.get('filename')}: {shape}."
    if len(result) > len(window):
        header += f" Showing rows {offset + 1}-{offset + len(window)} of {len(result):,}."
    return header + "\n\n" + _markdown(window)


def _markdown(frame) -> str:
    """Render a DataFrame as a compact markdown table."""
    import pandas as pd

    if frame is None or frame.empty:
        return "_No rows._"
    columns = [str(c) for c in frame.columns[:MAX_COLUMNS]]
    dropped = len(frame.columns) - len(columns)

    def cell(value: Any) -> str:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ""
        if isinstance(value, pd.Timestamp):
            text = value.isoformat(sep=" ")
        elif isinstance(value, float):
            text = f"{value:,.4f}".rstrip("0").rstrip(".") if abs(value) < 1e15 else f"{value:g}"
        else:
            text = str(value)
        text = text.replace("|", "\\|").replace("\n", " ")
        return text if len(text) <= MAX_CELL_CHARS else text[:MAX_CELL_CHARS - 1] + "…"

    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for _, row in frame[frame.columns[:MAX_COLUMNS]].iterrows():
        lines.append("| " + " | ".join(cell(v) for v in row.tolist()) + " |")
    if dropped > 0:
        lines.append(f"\n_{dropped} further column(s) not shown; name them in `columns` to see them._")
    return "\n".join(lines)


# ----------------------------------------------------------------- documents

def _passages(text: str) -> List[Tuple[Optional[int], str]]:
    """Split extracted text into searchable passages, keeping page numbers.

    PDF text arrives with `[page N]` markers from the extractor, which is the only
    way to cite a page later; other formats have no pages and split on blank lines.
    """
    if not text:
        return []
    if "[page " in text:
        chunks: List[Tuple[Optional[int], str]] = []
        for part in re.split(r"\[page (\d+)\]", text)[1:]:
            if part.isdigit():
                chunks.append((int(part), ""))
            elif chunks:
                chunks[-1] = (chunks[-1][0], part.strip())
        return [(page, body) for page, body in chunks if body]

    out: List[Tuple[Optional[int], str]] = []
    current: List[str] = []
    size = 0
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        current.append(block)
        size += len(block)
        if size >= 1200:
            out.append((None, "\n\n".join(current)))
            current, size = [], 0
    if current:
        out.append((None, "\n\n".join(current)))
    return out


def _tokens(query: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", (query or "").lower())
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS]


def _search(env: str, meta: Dict[str, Any], args: Dict[str, Any]) -> str:
    text = upload_store.load_text(env, meta["id"])
    if not text.strip():
        return (
            f"'{meta.get('filename')}' has no extractable text — it is most likely a scanned "
            "image. Tell the user it cannot be read as text."
        )
    passages = _passages(text)
    tokens = _tokens(args.get("query") or "")
    if not tokens:
        return "Give `query` some words to look for."

    # Rarity weighting, so a question's distinctive term decides the match rather
    # than whichever word happens to appear on every page.
    total = max(len(passages), 1)
    weights: Dict[str, float] = {}
    for token in set(tokens):
        containing = sum(1 for _, body in passages if token in body.lower())
        weights[token] = math.log(1 + total / max(containing, 1))

    scored: List[Tuple[float, Optional[int], str]] = []
    for page, body in passages:
        lowered = body.lower()
        score = sum(min(lowered.count(token), 4) * weights[token] for token in set(tokens))
        if score > 0:
            scored.append((score, page, body))
    if not scored:
        return (
            f"Nothing in '{meta.get('filename')}' matched those terms. Try different wording, "
            "or use read_file to look through it in order."
        )
    scored.sort(key=lambda triple: triple[0], reverse=True)

    wanted = max(1, min(int(args.get("max_passages") or 3), MAX_PASSAGES))
    out: List[str] = [f"Passages from '{meta.get('filename')}' matching that:"]
    budget = DEFAULT_TEXT_CHARS
    for _, page, body in scored[:wanted]:
        label = f"[page {page}]" if page else "[excerpt]"
        excerpt = body if len(body) <= budget else body[:budget].rstrip() + "…"
        out.append(f"{label} {excerpt}")
        budget -= len(excerpt)
        if budget <= 300:
            break
    return "\n\n".join(out)


def _read(env: str, meta: Dict[str, Any], args: Dict[str, Any]) -> str:
    kind = meta.get("kind") or ""
    if kind == "table":
        frame = _load(env, meta, args)
        offset = max(0, int(args.get("offset") or 0))
        limit = max(1, min(int(args.get("limit") or DEFAULT_ROWS), MAX_ROWS))
        window = frame.iloc[offset:offset + limit]
        header = f"{meta.get('filename')}: rows {offset + 1}-{offset + len(window)} of {len(frame):,}."
        return header + "\n\n" + _markdown(window)

    text = upload_store.load_text(env, meta["id"])
    if not text.strip():
        return f"'{meta.get('filename')}' has no extractable text."

    page = args.get("page")
    if page is not None:
        try:
            wanted = int(page)
        except (TypeError, ValueError):
            raise ToolInputError("`page` must be a number.") from None
        for number, body in _passages(text):
            if number == wanted:
                clipped = body[:MAX_TEXT_CHARS]
                suffix = "\n…(page truncated)" if len(body) > len(clipped) else ""
                return f"{meta.get('filename')} page {wanted}:\n\n{clipped}{suffix}"
        pages = (meta.get("profile") or {}).get("pages")
        raise ToolInputError(f"No page {wanted}. This file has {pages or 'no numbered'} page(s).")

    offset = max(0, int(args.get("offset") or 0))
    limit = max(200, min(int(args.get("limit") or DEFAULT_TEXT_CHARS), MAX_TEXT_CHARS))
    window = text[offset:offset + limit]
    if not window:
        return f"Nothing further in '{meta.get('filename')}' past character {offset:,} of {len(text):,}."
    tail = (
        f"\n\n_Characters {offset:,}-{offset + len(window):,} of {len(text):,}. "
        f"Continue with offset={offset + len(window)}._"
        if offset + len(window) < len(text) else ""
    )
    return f"{meta.get('filename')}:\n\n{window}{tail}"


def _inspect(env: str, meta: Dict[str, Any], args: Dict[str, Any]) -> str:
    profile = meta.get("profile") or {}
    kind = meta.get("kind") or ""
    name = meta.get("filename")
    size_mb = int(meta.get("size_bytes") or 0) / 1_048_576

    if kind == "table":
        sheets = profile.get("sheets") or []
        wanted = (args.get("sheet") or "").strip().lower()
        lines = [f"{name} ({size_mb:.2f} MB), {len(sheets)} sheet(s)."]
        for sheet in sheets:
            if wanted and str(sheet.get("name", "")).lower() != wanted:
                continue
            lines.append(
                f"\n### Sheet '{sheet.get('name')}' — {int(sheet.get('rows') or 0):,} rows"
                + (" (truncated at the row cap)" if sheet.get("truncated") else "")
            )
            lines.append("| column | type | nulls | distinct | examples |")
            lines.append("| --- | --- | --- | --- | --- |")
            for column in sheet.get("columns") or []:
                examples = ", ".join(str(v)[:30] for v in (column.get("sample_values") or [])[:3])
                lines.append(
                    f"| {column.get('name')} | {column.get('dtype')} | "
                    f"{column.get('nulls')} | {column.get('unique')} | {examples} |"
                )
        return "\n".join(lines)

    if kind == "image":
        return f"{name} ({size_mb:.2f} MB) is an image and is already visible to you in the conversation."

    lines = [f"{name} ({size_mb:.2f} MB)."]
    if profile.get("pages"):
        lines.append(f"Pages: {profile['pages']}.")
    if profile.get("words"):
        lines.append(f"Words: {int(profile['words']):,}; characters: {int(profile.get('chars') or 0):,}.")
    if profile.get("headings"):
        headings = profile["headings"]
        shown = "; ".join(str(h) for h in headings[:20])
        lines.append(f"Headings: {shown}" + (f" (… {len(headings) - 20} more)" if len(headings) > 20 else ""))
    if profile.get("json_kind"):
        lines.append(f"JSON root: {profile['json_kind']}; depth {profile.get('depth')}.")
        if profile.get("keys"):
            lines.append("Top-level keys: " + ", ".join(str(k) for k in profile["keys"][:40]))
    if profile.get("preview"):
        lines.append(f"\nOpening text:\n{profile['preview']}")
    lines.append("\nUse search_file to find relevant passages, or read_file to read in order.")
    return "\n".join(lines)
