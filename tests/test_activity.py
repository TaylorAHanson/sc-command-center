"""Tests for the admin activity log (services/activity.py).

The log is metadata only: who did what to which object. Prompts, chat text,
generated code and email bodies belong to the user's work under its own access
list, so they must never be copied into a table every administrator can read.
And recording must never break the action being recorded.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    import database
    from services import activity
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_activity: {e}")
    sys.exit(0)


class FakeConn:
    def __init__(self, fail=False):
        self.fail = fail
        self.rows = []
        self.closed = False

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                if conn.fail:
                    raise RuntimeError("connection reset")
                conn.rows.append(params)

        return C()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def _with_conn(conn):
    original = database.get_db_connection
    database.get_db_connection = lambda *a, **k: conn
    return original


def test_content_never_reaches_the_log():
    detail = activity.clean_detail({
        "prompt": "show me revenue by customer",
        "message": "hi",
        "SQL": "select * from salaries",
        "body": "Quarterly numbers attached",
        "tab_count": 3,
        "kind": "email_report",
    })
    assert detail == {"tab_count": 3, "kind": "email_report"}


def test_only_short_scalars_are_kept():
    detail = activity.clean_detail({
        "name": "x" * 500,
        "ok": True,
        "nested": {"a": 1},
        "ids": [1, 2, 3],
        "nothing": None,
        "ratio": 0.5,
    })
    assert len(detail["name"]) == 200
    assert detail["ok"] is True and detail["nothing"] is None and detail["ratio"] == 0.5
    assert "nested" not in detail and "ids" not in detail


def test_detail_is_capped_in_size():
    detail = activity.clean_detail({f"k{i}": i for i in range(50)})
    assert len(detail) == 20


def test_record_writes_one_row():
    conn = FakeConn()
    original = _with_conn(conn)
    try:
        activity.record("ana@example.com", "view.publish", "app", "v-1", {"version": 4, "prompt": "secret"})
    finally:
        database.get_db_connection = original
    assert len(conn.rows) == 1
    who, verb, otype, oid, detail = conn.rows[0]
    assert (who, verb, otype, oid) == ("ana@example.com", "view.publish", "app", "v-1")
    assert json.loads(detail) == {"version": 4}
    assert conn.closed


def test_a_database_failure_never_escapes():
    conn = FakeConn(fail=True)
    original = _with_conn(conn)
    try:
        activity.record("ana@example.com", "view.publish", "app", "v-1")
    finally:
        database.get_db_connection = original
    assert conn.closed


def test_a_malformed_verb_is_dropped():
    conn = FakeConn()
    original = _with_conn(conn)
    try:
        activity.record("ana@example.com", "Published A View!", "app", "v-1")
    finally:
        database.get_db_connection = original
    assert conn.rows == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
