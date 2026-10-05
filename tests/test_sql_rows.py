"""Tests for how many rows `/api/sql/execute-raw` hands back, and whether it says so.

The endpoint answers 500 rows unless the request asks for more. That is a sensible
default and a poor secret: a widget that fetched a table to sort it in the browser
got the first 500 rows, `row_count: 500`, and no hint that anything was missing.
What is pinned here is that asking for more works across result chunks, and that a
shortfall is always reported.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from routes.sql_query import DEFAULT_MAX_ROWS, gather_rows, result_window
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_sql_rows: {e}")
    sys.exit(0)


def chunk(rows, next_index=None):
    return SimpleNamespace(data_array=rows, next_chunk_index=next_index)


def table(n, start=0):
    return [[str(i)] for i in range(start, start + n)]


def test_the_default_is_still_500():
    assert DEFAULT_MAX_ROWS == 500


def test_a_single_chunk_is_returned_whole():
    rows, more = gather_rows(chunk(table(10)), lambda _i: None, 500)
    assert len(rows) == 10 and not more


def test_a_result_over_the_cap_is_cut_and_says_so():
    rows, more = gather_rows(chunk(table(800)), lambda _i: None, 500)
    assert len(rows) == 500 and more


def test_later_chunks_are_followed_when_more_rows_are_asked_for():
    """Reading only the first chunk is what made a bigger max_rows change nothing."""
    chunks = {1: chunk(table(300, 300), 2), 2: chunk(table(100, 600))}
    rows, more = gather_rows(chunk(table(300), 1), lambda i: chunks[i], 10_000)
    assert len(rows) == 700 and not more
    assert rows[-1] == ["699"]


def test_chunks_are_not_fetched_once_the_cap_is_met():
    fetched = []

    def fetch(index):
        fetched.append(index)
        return chunk(table(300, 300), None)

    rows, more = gather_rows(chunk(table(500), 1), fetch, 500)
    assert fetched == [] and len(rows) == 500 and more


def test_a_pointer_that_never_ends_cannot_hold_a_request_open():
    forever = lambda i: chunk(table(1), i + 1)  # noqa: E731
    rows, more = gather_rows(chunk(table(1), 1), forever, 10**9)
    assert more and len(rows) <= 201


def test_an_empty_result_is_not_truncated():
    rows, more = gather_rows(SimpleNamespace(data_array=None, next_chunk_index=None), lambda _i: None, 500)
    assert rows == [] and not more
    assert result_window(0, 0, more) == {"total_rows": 0, "truncated": False}


def test_the_warehouses_total_decides_when_it_gives_one():
    assert result_window(500, 12_000, True) == {"total_rows": 12_000, "truncated": True}
    assert result_window(12_000, 12_000, False) == {"total_rows": 12_000, "truncated": False}


def test_without_a_total_more_rows_still_means_truncated():
    assert result_window(500, None, True) == {"total_rows": None, "truncated": True}
    assert result_window(40, None, False) == {"total_rows": 40, "truncated": False}


def test_a_cut_the_warehouse_made_is_reported_too():
    assert result_window(10, 10, False, warehouse_truncated=True)["truncated"] is True


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
