"""Tests for /api/actions.

The action log holds every user's actions, each with a snapshot of the dashboard
it was taken on, so reading it is for Administrators. Writing a row has to stay
open to every signed-in caller: an executable widget writes one before it runs,
and a failed write means the action doesn't happen.

Pinned with the log's storage and the caller's identity faked where the routes
look them up, so a refusal can be shown to have read nothing.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from fastapi import HTTPException
    from routes import actions
    from services import access
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_actions_routes: {e}")
    sys.exit(0)

ME = "taylor@example.com"
OTHER = "someone.else@example.com"


class Log:
    """The action_logs table, as far as the routes read and write it."""

    def __init__(self, *rows, broken=False):
        self.rows = list(rows)
        self.broken = broken
        self.reads = []
        self.writes = []


def entry(action_id, username):
    return {"id": action_id, "widget_id": "w1", "widget_name": "Refunds", "action_name": "approve",
            "username": username, "request_id": f"req-{action_id}", "domain": "General",
            "user_explanation": "", "dashboard_context": "{}", "timestamp": "2026-11-12T10:00:00"}


def run(log, fn, *args, user=ME, admin=False, **kwargs):
    """Call a route with the log, the caller and their admin standing faked."""
    who = access.Caller(user, (), admin)

    def get_action_logs(limit=100, offset=0, env="dev"):
        log.reads.append((limit, offset, env))
        if log.broken:
            raise RuntimeError("connection refused")
        return list(log.rows)

    def log_user_action(**row):
        log.writes.append(row)
        log.rows.insert(0, row)
        return {"status": "success", "action_id": len(log.rows)}

    def query_action_logs(filters, sort, direction, limit, offset, env="dev", with_total=False):
        log.reads.append(("search", filters, sort, direction, limit, offset))
        if log.broken:
            raise RuntimeError("connection refused")
        rows = list(log.rows)[offset:offset + limit]
        return {"rows": rows, "total": len(log.rows) if with_total else None}

    def action_log_facets():
        log.reads.append(("facets",))
        return {"widgets": [], "actions": [{"value": "approve", "label": "approve", "count": len(log.rows)}],
                "users": [], "domains": []}

    patches = [
        (actions, "get_action_logs", get_action_logs),
        (actions, "query_action_logs", query_action_logs),
        (actions, "action_log_facets", action_log_facets),
        (actions, "log_user_action", log_user_action),
        (actions, "_get_current_username", lambda _w: user),
        (access, "caller", lambda _w: who),
    ]
    saved = [(mod, name, getattr(mod, name)) for mod, name, _ in patches]
    for mod, name, value in patches:
        setattr(mod, name, value)
    try:
        return fn(*args, w=None, **kwargs)
    finally:
        for mod, name, value in saved:
            setattr(mod, name, value)


def refused(log, fn, *args, **kwargs):
    try:
        run(log, fn, *args, **kwargs)
    except HTTPException as exc:
        return exc
    raise AssertionError("the request was not refused")


def request(**changes):
    body = {"widget_id": "w1", "widget_name": "Refunds", "action_name": "approve",
            "explanation": "", "context": {"app": "Ops", "tab": "Refunds"}, "request_id": "req-9"}
    body.update(changes)
    return actions.ActionLogRequest(**body)


# ------------------------------------------------------------- reading the log

def test_someone_who_is_not_an_administrator_cannot_read_the_log():
    log = Log(entry(2, OTHER), entry(1, ME))
    exc = refused(log, actions.get_actions)
    assert exc.status_code == 403, "a refusal, not the 500 the route's own error handling would make of it"
    assert log.reads == [], "refused before anything was read"


def test_an_administrator_reads_everyone_s_actions():
    log = Log(entry(2, OTHER), entry(1, ME))
    rows = run(log, actions.get_actions, admin=True)
    assert [r["id"] for r in rows] == [2, 1]
    assert {r["username"] for r in rows} == {ME, OTHER}


def test_an_administrator_s_paging_reaches_the_store():
    log = Log(entry(1, OTHER))
    run(log, actions.get_actions, limit=25, offset=50, admin=True)
    assert log.reads == [(25, 50, "dev")]


def test_a_store_failure_for_an_administrator_is_still_reported_as_one():
    exc = refused(Log(broken=True), actions.get_actions, admin=True)
    assert exc.status_code == 500 and "connection refused" in exc.detail


# ------------------------------------------------------------- searching it

def search(**changes):
    """Every parameter, as FastAPI would fill them in; a direct call gets no defaults."""
    params = {"q": "", "widget_id": "", "action_name": "", "username": "", "domain": "",
              "since": None, "until": None, "sort": "timestamp", "direction": "desc",
              "limit": 50, "offset": 0}
    params.update(changes)
    return params


def test_someone_who_is_not_an_administrator_cannot_search_the_log_or_list_its_filters():
    log = Log(entry(1, OTHER))
    assert refused(log, actions.search_actions, **search()).status_code == 403
    assert refused(log, actions.action_facets).status_code == 403
    assert log.reads == [], "refused before anything was read"


def test_an_administrator_gets_a_page_and_how_many_match_in_all():
    log = Log(*[entry(i, ME) for i in range(5, 0, -1)])
    page = run(log, actions.search_actions, admin=True, **search(limit=2, offset=2))
    assert [r["id"] for r in page["rows"]] == [3, 2]
    assert (page["total"], page["limit"], page["offset"], page["sort"], page["dir"]) == (5, 2, 2, "timestamp", "desc")


def test_the_search_filters_and_sort_reach_the_store_cleaned():
    log = Log(entry(1, ME))
    run(log, actions.search_actions, admin=True,
        **search(q=" refund ", username=" Taylor@Example.com", sort="Username", direction="ASC",
                 since="2026-11-01T00:00:00Z"))
    _, filters, sort, direction, limit, offset = log.reads[0]
    assert (filters.q, filters.username, sort, direction) == ("refund", "Taylor@Example.com", "username", "asc")
    assert filters.since is not None and filters.since.tzinfo is not None


def test_a_bad_sort_or_date_is_a_400_and_reads_nothing():
    for bad in (search(sort="dashboard_context"), search(direction="up"), search(since="yesterday")):
        log = Log(entry(1, ME))
        exc = refused(log, actions.search_actions, admin=True, **bad)
        assert exc.status_code == 400, bad
        assert log.reads == []


def test_an_administrator_lists_each_filter_s_choices():
    log = Log(entry(2, OTHER), entry(1, ME))
    facets = run(log, actions.action_facets, admin=True)
    assert facets["actions"] == [{"value": "approve", "label": "approve", "count": 2}]


def test_a_store_failure_while_searching_is_reported_as_one():
    exc = refused(Log(broken=True), actions.search_actions, admin=True, **search())
    assert exc.status_code == 500 and "connection refused" in exc.detail


# ------------------------------------------------------------- writing to it

def test_anyone_signed_in_can_still_log_an_action():
    log = Log()
    result = run(log, actions.log_action, request())
    assert result["status"] == "success"
    assert len(log.writes) == 1
    row = log.writes[0]
    assert (row["widget_id"], row["action_name"], row["request_id"]) == ("w1", "approve", "req-9")


def test_the_logged_name_is_the_caller_s_own():
    log = Log()
    run(log, actions.log_action, request(), user=OTHER)
    assert log.writes[0]["username"] == OTHER


def test_the_dashboard_context_is_stored_as_json_text():
    log = Log()
    run(log, actions.log_action, request(context={"app": "Ops", "widgets": [{"type": "w1"}]}))
    assert json.loads(log.writes[0]["context"]) == {"app": "Ops", "widgets": [{"type": "w1"}]}
    run(log, actions.log_action, request(context='{"already": "text"}'))
    assert log.writes[1]["context"] == '{"already": "text"}'


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
