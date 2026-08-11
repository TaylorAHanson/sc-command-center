"""Tests for what a caller gets back when a SQL statement doesn't succeed.

`execute_statement` reports a rejected query in its status rather than by raising,
so a failure used to arrive as HTTP 200 with no rows: the widget rendered "no data"
and Widget Studio's auto-fix never saw anything to fix. Reporting it as an error is
the point — but widgets already stored in the database were generated against the
old shape and read `payload.rows` without checking the status, so the error body
has to carry an empty result as well as the reason. Both halves are pinned here.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from databricks.sdk.service.sql import StatementState
    from routes.sql_query import SqlStatementError, _raise_if_unsuccessful
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_sql_errors: {e}")
    sys.exit(0)


class Statement:
    """The shape of the SDK's response, with only what the check reads."""

    def __init__(self, state, message=""):
        error = type("Error", (), {"message": message})() if message else None
        self.status = type("Status", (), {"state": state, "error": error})()
        self.statement_id = "01ef-abc"


def failure(statement, sql=""):
    try:
        _raise_if_unsuccessful(statement, sql)
    except SqlStatementError as e:
        return e
    raise AssertionError("the statement should have been reported as a failure")


def body(error):
    return json.loads(error.response().body)


def test_a_successful_statement_passes_straight_through():
    # Including one that legitimately returned nothing: empty is not an error.
    assert _raise_if_unsuccessful(Statement(StatementState.SUCCEEDED), "SELECT 1") is None


def test_a_failed_statement_reports_the_reason_the_warehouse_gave():
    error = failure(Statement(StatementState.FAILED, "[TABLE_OR_VIEW_NOT_FOUND] `sales`"), "SELECT * FROM sales")
    assert error.status_code == 400
    assert "TABLE_OR_VIEW_NOT_FOUND" in error.detail


def test_a_quoting_failure_arrives_with_the_rule_that_explains_it():
    error = failure(
        Statement(StatementState.FAILED, "[UNRESOLVED_COLUMN] A column with name `Order` cannot be resolved"),
        "SELECT Order Number FROM t",
    )
    assert "backtick" in error.detail.lower()


def test_a_query_still_running_is_a_timeout_not_a_bad_request():
    assert failure(Statement(StatementState.RUNNING)).status_code == 504


def test_the_error_body_still_looks_like_an_empty_result_set():
    # What keeps a widget written against the old contract from throwing on
    # `undefined` and taking its dashboard panel down: it sees no rows, as it
    # always did on a failure, while anything checking the status gets the reason.
    error = failure(Statement(StatementState.FAILED, "[UNRESOLVED_COLUMN] nope"), "SELECT x FROM t")
    payload = body(error)
    assert payload["rows"] == [] and payload["columns"] == [] and payload["row_count"] == 0
    assert payload["detail"] == error.detail
    assert error.response().status_code == 400


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
