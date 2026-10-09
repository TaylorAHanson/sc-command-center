"""Tests for how many rows `/api/sql/execute-raw` hands back, and whether it says so.

The endpoint answers 500 rows unless the request asks for more. That is a sensible
default and a poor secret: a widget that fetched a table to sort it in the browser
got the first 500 rows, `row_count: 500`, and no hint that anything was missing.
Asking for a number didn't fix that either — a `max_rows` sized to today's data
drops rows once the data grows, and past 25 MiB the warehouse refused to return
the result inline at all. What is pinned here is that `all_rows` gets every row
(through external links when it has to), that the response stays the same JSON
while it is streamed, and that a shortfall is always reported.
"""
import asyncio
import gzip
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from databricks.sdk.service.sql import Disposition, Format, StatementState

    import routes.sql_query as sql_query
    from routes.sql_query import (
        DEFAULT_MAX_ROWS, RawSqlRequest, fetch_plans, gzip_stream, iter_json_rows,
        iter_rows, result_body, result_window, too_big_for_inline,
    )
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_sql_rows: {e}")
    sys.exit(0)


def chunk(rows, next_index=None):
    return SimpleNamespace(data_array=rows, next_chunk_index=next_index, external_links=None)


def linked(*links):
    return SimpleNamespace(data_array=None, next_chunk_index=None, external_links=list(links))


def link(name, next_index=None):
    return SimpleNamespace(external_link=name, next_chunk_index=next_index, http_headers=None)


def table(n, start=0):
    return [[str(i)] for i in range(start, start + n)]


def no_download(_link):
    raise AssertionError("an inline result never downloads anything")


def body_of(pieces):
    return json.loads("".join(pieces))


# ---------------------------------------------------------------- reading chunks

def test_the_default_is_still_500():
    assert DEFAULT_MAX_ROWS == 500


def test_a_single_chunk_is_read_whole():
    assert list(iter_rows(chunk(table(10)), lambda _i: None, no_download)) == table(10)


def test_later_inline_chunks_are_followed():
    """Reading only the first chunk is what made a bigger max_rows change nothing."""
    chunks = {1: chunk(table(300, 300), 2), 2: chunk(table(100, 600))}
    rows = list(iter_rows(chunk(table(300), 1), lambda i: chunks[i], no_download))
    assert len(rows) == 700 and rows[-1] == ["699"]


def test_external_links_are_downloaded_and_followed():
    """Past 25 MiB the rows exist only behind links, and each link names the next chunk."""
    files = {"a": json.dumps(table(3)), "b": json.dumps(table(2, 3))}
    chunks = {1: linked(link("b"))}
    rows = list(iter_rows(linked(link("a", 1)), lambda i: chunks[i], lambda l: files[l.external_link]))
    assert rows == table(5)


def test_chunks_are_fetched_only_as_rows_are_read():
    fetched = []

    def fetch(index):
        fetched.append(index)
        return chunk(table(300, 300))

    rows = iter_rows(chunk(table(500), 1), fetch, no_download)
    assert [next(rows) for _ in range(500)] == table(500)
    assert fetched == []


def test_a_pointer_that_never_ends_cannot_hold_a_request_open():
    forever = lambda i: chunk(table(1), i + 1)  # noqa: E731
    assert len(list(iter_rows(chunk(table(1), 1), forever, no_download, max_hops=200))) == 201


def test_json_rows_are_read_one_at_a_time():
    text = ' [ ["a", null] ,\n["b, ]", "[x]"],["c","d"] ] '
    assert list(iter_json_rows(text)) == [["a", None], ["b, ]", "[x]"], ["c", "d"]]
    assert list(iter_json_rows("[]")) == []
    assert list(iter_json_rows("")) == []


# ---------------------------------------------------------------- what is reported

def test_an_empty_result_is_not_truncated():
    assert result_window(0, 0, False) == {"total_rows": 0, "truncated": False}


def test_the_warehouses_total_decides_when_it_gives_one():
    assert result_window(500, 12_000, True) == {"total_rows": 12_000, "truncated": True}
    assert result_window(12_000, 12_000, False) == {"total_rows": 12_000, "truncated": False}


def test_without_a_total_more_rows_still_means_truncated():
    assert result_window(500, None, True) == {"total_rows": None, "truncated": True}
    assert result_window(40, None, False) == {"total_rows": 40, "truncated": False}


def test_a_cut_the_warehouse_made_has_no_total():
    """With `row_limit` the manifest's count is the cut, not the table — reporting it would lie."""
    assert result_window(1000, 1000, False, warehouse_truncated=True) == {"total_rows": None, "truncated": True}


# ---------------------------------------------------------------- how a read is run

def test_a_capped_read_first_runs_as_it_always_has():
    plans = fetch_plans(500, all_rows=False)
    assert plans[0] == {"disposition": Disposition.INLINE}
    assert plans[1] == {"disposition": Disposition.INLINE, "row_limit": 500}


def test_every_row_is_bounded_by_the_ceiling_and_ends_at_external_links():
    plans = fetch_plans(1_000_000, all_rows=True)
    assert all(p["row_limit"] == 1_000_000 for p in plans)
    assert plans[-1] == {"disposition": Disposition.EXTERNAL_LINKS, "format": Format.JSON_ARRAY, "row_limit": 1_000_000}


def test_only_the_inline_limit_counts_as_too_big():
    def failed(message):
        return SimpleNamespace(status=SimpleNamespace(state=StatementState.FAILED, error=SimpleNamespace(message=message)))

    assert too_big_for_inline(failed(
        "Inline byte limit exceeded. Statements executed with disposition=INLINE can have a "
        "result size of at most 26214400 bytes."))
    assert not too_big_for_inline(failed("[UNRESOLVED_COLUMN] A column cannot be resolved"))
    assert not too_big_for_inline(SimpleNamespace(status=SimpleNamespace(state=StatementState.SUCCEEDED, error=None)))


def test_all_rows_is_off_unless_asked_for():
    assert RawSqlRequest(sql="SELECT 1").all_rows is False
    assert RawSqlRequest(sql="SELECT 1", all_rows=True).all_rows is True


# ---------------------------------------------------------------- the streamed body

def test_the_body_is_the_same_json_it_always_was():
    out = body_of(result_body(["id", "name"], [["1", "a"], ["2", None]], 500, 2, False, "s1"))
    assert out == {
        "columns": ["id", "name"], "statement_id": "s1",
        "rows": [{"id": "1", "name": "a"}, {"id": "2", "name": None}],
        "row_count": 2, "total_rows": 2, "truncated": False,
    }


def test_rows_across_batches_join_into_one_array():
    saved = sql_query.STREAM_BATCH_ROWS
    sql_query.STREAM_BATCH_ROWS = 3
    try:
        out = body_of(result_body(["id"], table(10), 500, 10, False, None))
    finally:
        sql_query.STREAM_BATCH_ROWS = saved
    assert [r["id"] for r in out["rows"]] == [str(i) for i in range(10)]


def test_a_body_stopped_at_its_cap_says_so():
    summary = {}
    out = body_of(result_body(["id"], table(800), 500, None, False, None, summary))
    assert out["row_count"] == 500 and out["truncated"] is True and out["total_rows"] is None
    assert summary["row_count"] == 500


def test_a_failure_part_way_still_ends_in_valid_json_marked_partial():
    def rows():
        yield ["1"]
        yield ["2"]
        raise RuntimeError("link expired")

    out = body_of(result_body(["id"], rows(), 500, 10, False, None))
    assert out["row_count"] == 2 and out["truncated"] is True
    assert "link expired" in out["error"]


def test_an_empty_body_is_valid_json():
    assert body_of(result_body(["id"], [], 500, 0, False, None))["rows"] == []


def test_gzip_round_trips():
    pieces = [b'{"rows": [', b'{"id": "1"}' * 1000, b"]}"]
    assert gzip.decompress(b"".join(gzip_stream(pieces))) == b"".join(pieces)


# ---------------------------------------------------------------- the endpoint

def _statement(state, rows=(), message="", truncated=False):
    return SimpleNamespace(
        statement_id="s1",
        status=SimpleNamespace(state=state, error=SimpleNamespace(message=message) if message else None),
        manifest=SimpleNamespace(
            schema=SimpleNamespace(columns=[SimpleNamespace(name="id")]),
            total_row_count=len(rows), truncated=truncated, total_chunk_count=1,
        ),
        result=chunk(list(rows)),
    )


TOO_BIG = "Inline byte limit exceeded. Please execute the statement with disposition=EXTERNAL_LINKS."


def _run(endpoint, body, answers, accept="gzip"):
    """Call an endpoint with a fake warehouse that answers `answers` in turn."""
    calls = []

    class FakeApi:
        def __init__(self, _client):
            pass

        def execute_statement(self, **kwargs):
            calls.append(kwargs)
            return answers[len(calls) - 1]

        def get_statement_result_chunk_n(self, *_args):
            raise AssertionError("single-chunk results only")

    saved = (sql_query.StatementExecutionAPI, sql_query._row_ceiling, os.environ.get("SQL_WAREHOUSE_ID"))
    sql_query.StatementExecutionAPI = FakeApi
    sql_query._row_ceiling = lambda: 1000
    os.environ["SQL_WAREHOUSE_ID"] = "wh"
    try:
        response = endpoint(RawSqlRequest(**body), SimpleNamespace(headers={"accept-encoding": accept}),
                            SimpleNamespace(api_client=None))

        async def collect():
            return b"".join([piece async for piece in response.body_iterator])

        raw = asyncio.run(collect()) if hasattr(response, "body_iterator") else response.body
    finally:
        sql_query.StatementExecutionAPI, sql_query._row_ceiling = saved[0], saved[1]
        if saved[2] is None:
            os.environ.pop("SQL_WAREHOUSE_ID", None)
        else:
            os.environ["SQL_WAREHOUSE_ID"] = saved[2]
    if response.headers.get("content-encoding") == "gzip":
        raw = gzip.decompress(raw)
    return response.status_code, json.loads(raw), calls


def test_a_result_too_big_for_inline_is_asked_for_again_with_a_limit():
    status, out, calls = _run(sql_query.execute_raw_sql, {"sql": "SELECT id FROM t"}, [
        _statement(StatementState.FAILED, message=TOO_BIG),
        _statement(StatementState.SUCCEEDED, table(500), truncated=True),
    ])
    assert status == 200 and len(calls) == 2
    assert calls[1]["row_limit"] == 500
    assert out["row_count"] == 500 and out["truncated"] is True and out["total_rows"] is None


def test_all_rows_asks_for_the_ceiling_and_gets_everything_under_it():
    status, out, calls = _run(sql_query.execute_raw_sql, {"sql": "SELECT id FROM t", "all_rows": True},
                              [_statement(StatementState.SUCCEEDED, table(900))])
    assert status == 200 and calls[0]["row_limit"] == 1000
    assert out["row_count"] == 900 and out["truncated"] is False and out["total_rows"] == 900


def test_max_rows_cannot_exceed_the_ceiling():
    _status, out, _calls = _run(sql_query.execute_raw_sql, {"sql": "SELECT id FROM t", "max_rows": 10**9},
                                [_statement(StatementState.SUCCEEDED, table(1500))])
    assert out["row_count"] == 1000 and out["truncated"] is True and out["total_rows"] == 1500


def test_a_write_is_never_run_twice():
    status, _out, calls = _run(sql_query.execute_write_sql, {"sql": "INSERT INTO t VALUES (1)"},
                               [_statement(StatementState.FAILED, message=TOO_BIG)])
    assert len(calls) == 1 and status == 400


def test_a_client_that_cannot_take_gzip_gets_plain_json():
    _status, out, _calls = _run(sql_query.execute_raw_sql, {"sql": "SELECT id FROM t"},
                                [_statement(StatementState.SUCCEEDED, table(3))], accept="")
    assert out["row_count"] == 3


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
