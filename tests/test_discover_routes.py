"""Tests for /api/discover (routes/discover.py).

Handlers are called directly with the caller, the access list and the content
connection faked, to pin what the endpoints promise beyond the services:

- a search page is re-checked against the access list, so a row the catalog
  still lists for someone who has lost access never reaches them;
- searching every view is for app administrators, refused before any query;
- curating is for app administrators, and a body that changes nothing is 400;
- recording an open answers 204 whatever goes wrong;
- `/favorites/order` isn't swallowed by `/favorites/{app_id}`.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from fastapi import HTTPException
    from routes import discover
    from services import access, activity, caller_identity, view_catalog, view_signals
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_discover_routes: {e}")
    sys.exit(0)

MEMBER = access.Caller("ana@example.com", ("planners",), False)
ADMIN = access.Caller("root@example.com", (), True)
T0 = datetime(2026, 11, 1, 9, 0)
LIGHT = ["id", "ref", "name", "description", "owner", "domain", "presentation", "updated_at", "published_at",
         "viewers_30d", "trend", "favorites", "featured_position", "certified", "favorite", "hidden", "my_opened",
         "has_draft", "listed"]


def light_row(i, viewers):
    return (i, i, i.title(), "", "bob@example.com", "Finance", "workspace", T0, T0, viewers, 0.0, 0, None, False,
            False, False, None, False, True)


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.description, self._rows = conn, None, []

    def execute(self, sql, params=None):
        self.conn.statements.append((sql, params))
        for fragment, (columns, rows) in self.conn.answers.items():
            if fragment in sql:
                self.description = [(c,) for c in columns]
                self._rows = list(rows)
                return
        raise AssertionError(f"unexpected statement: {sql[:160]}")

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, answers):
        self.answers, self.statements, self.closed = answers, [], False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class patched:
    def __init__(self, *triples):
        self.triples, self.saved = triples, []

    def __enter__(self):
        for mod, name, value in self.triples:
            self.saved.append((mod, name, getattr(mod, name)))
            setattr(mod, name, value)
        return self

    def __exit__(self, *exc):
        for mod, name, value in reversed(self.saved):
            setattr(mod, name, value)


def no_connection():
    raise AssertionError("opened a connection")


def search(who, **kwargs):
    params = dict(q="", scope="all", sort="relevance", domain=[], owner=[], certified=None, standalone=None,
                  status=None, opened=None, cursor=None, limit=24, facets=False, w=None)
    params.update(kwargs)
    with patched((access, "caller", lambda w: who)):
        return discover.search(**params)


def test_a_search_page_is_rechecked_against_the_access_list():
    conn = FakeConn({
        "AS sort_value FROM view_catalog": (LIGHT + ["sort_value"],
                                            [light_row("kept", 9) + (9,), light_row("revoked", 5) + (5,)]),
        "SELECT COUNT(*) FROM view_catalog": (("n",), [(2,)]),
    })
    dirty = []
    with patched((view_catalog, "_content", lambda: conn), (view_catalog, "detected", lambda max_age=30: None),
                 (access, "levels_for", lambda who, t, ids: {"kept": "USE"}),
                 (view_catalog, "mark_dirty", lambda t, i: dirty.append(i))):
        out = search(MEMBER)
    assert [r["id"] for r in out["results"]] == ["kept"]
    assert out["results"][0]["access"] == "USE" and out["results"][0]["link"] == "#/app/kept"
    assert dirty == ["revoked"], "a row the access list refuses is queued for rebuilding"
    assert out["mode"] == "basic" and out["next_cursor"] is None and out["total"] == 2
    sql, params = conn.statements[0]
    assert "vc.readers && %(keys)s::text[]" in sql and params["keys"] == ["*", "u:ana@example.com", "g:planners"]
    assert "ORDER BY vc.viewers_30d DESC, vc.id DESC" in sql, "an empty query sorts by popularity"


def test_only_admins_may_search_every_view():
    with patched((view_catalog, "_content", no_connection), (view_catalog, "detected", lambda max_age=30: None)):
        try:
            search(MEMBER, scope="everything")
            raise AssertionError("a member searched every view")
        except HTTPException as e:
            assert e.status_code == 403
    conn = FakeConn({
        "AS sort_value FROM view_catalog": (LIGHT + ["sort_value"], [light_row("hidden-from-all", 0) + (0,)]),
        "SELECT COUNT(*) FROM view_catalog": (("n",), [(1,)]),
    })
    with patched((view_catalog, "_content", lambda: conn), (view_catalog, "detected", lambda max_age=30: None),
                 (access, "levels_for", lambda who, t, ids: {i: "MANAGE" for i in ids})):
        out = search(ADMIN, scope="everything")
    assert [r["id"] for r in out["results"]] == ["hidden-from-all"]
    sql = conn.statements[0][0]
    assert sql.count("vc.readers &&") == 1 and "AS listed" in sql, "readers only flags the row, it filters nothing"


def test_bad_search_parameters_are_400():
    with patched((view_catalog, "_content", no_connection), (view_catalog, "detected", lambda max_age=30: None)):
        for bad in ({"sort": "random"}, {"cursor": "garbage"}, {"opened": "ever"},
                    {"cursor": view_catalog.encode_cursor({"s": "name", "v": "a", "i": "b"}), "sort": "updated"}):
            try:
                search(MEMBER, **bad)
                raise AssertionError(bad)
            except HTTPException as e:
                assert e.status_code == 400, bad


def test_a_keyset_page_hands_back_a_cursor_that_carries_the_total():
    rows = [light_row(f"v{i}", 10 - i) + (10 - i,) for i in range(3)]
    conn = FakeConn({"AS sort_value FROM view_catalog": (LIGHT + ["sort_value"], rows),
                     "SELECT COUNT(*) FROM view_catalog": (("n",), [(7,)])})
    with patched((view_catalog, "_content", lambda: conn), (view_catalog, "detected", lambda max_age=30: None),
                 (access, "levels_for", lambda who, t, ids: {i: "USE" for i in ids})):
        out = search(MEMBER, sort="popular", limit=2)
    assert [r["id"] for r in out["results"]] == ["v0", "v1"]
    assert view_catalog.decode_cursor(out["next_cursor"]) == {"s": "popular", "v": 9, "i": "v1", "t": 7}


def test_curating_is_for_admins_and_must_change_something():
    def member(w):
        return MEMBER

    with patched((access, "caller", member), (view_signals, "curate", lambda *a: no_connection())):
        try:
            discover.curate("v1", discover.Curation(certified=True), w=None)
            raise AssertionError("a member curated")
        except HTTPException as e:
            assert e.status_code == 403
    recorded = []
    with patched((access, "caller", lambda w: ADMIN),
                 (view_signals, "curate", lambda who, app_id, changes: {"app_id": app_id, **changes}),
                 (activity, "record", lambda *a: recorded.append(a))):
        for body in ({}, {"certified": None}):
            try:
                discover.curate("v1", discover.Curation(**body), w=None)
                raise AssertionError(body)
            except HTTPException as e:
                assert e.status_code == 400
        out = discover.curate("v1", discover.Curation(featured_position=None), w=None)
        assert out == {"app_id": "v1", "featured_position": None}
        out = discover.curate("v1", discover.Curation(certified=False, featured_position=3), w=None)
        assert out == {"app_id": "v1", "certified": False, "featured_position": 3}
    assert recorded[0] == ("root@example.com", "view.curate", "app", "v1", {"featured_position": None})


def test_an_open_answers_204_whatever_goes_wrong():
    def boom(*a):
        raise RuntimeError("down")

    with patched((caller_identity, "username", lambda w: "ana@example.com"), (view_signals, "record_visit", boom)):
        assert discover.visit("v1", w=None).status_code == 204
    with patched((caller_identity, "username", boom)):
        assert discover.visit("v1", w=None).status_code == 204
    seen = []
    with patched((caller_identity, "username", lambda w: "ana@example.com"),
                 (view_signals, "record_visit", lambda u, a: seen.append((u, a)))):
        assert discover.visit("v1", w=None).status_code == 204
    assert seen == [("ana@example.com", "v1")]


def test_favorites_order_is_not_taken_for_an_id():
    paths = [(r.path, sorted(r.methods)) for r in discover.router.routes]
    assert paths.index(("/favorites/order", ["PUT"])) < paths.index(("/favorites/{app_id}", ["PUT"]))
    with patched((access, "caller", lambda w: MEMBER),
                 (view_signals, "order_favorites", lambda who, ids: list(reversed(ids)))):
        assert discover.order_favorites(discover.FavoriteOrder(ids=["a", "b"]), w=None) == {"ids": ["b", "a"]}


def test_every_contract_endpoint_is_mounted():
    routes = {(r.path, m) for r in discover.router.routes for m in r.methods}
    for path, method in (("/search", "GET"), ("/suggest", "GET"), ("/rails", "GET"), ("/home", "GET"),
                         ("/status", "GET"), ("/favorites", "GET"), ("/favorites/{app_id}", "PUT"),
                         ("/favorites/{app_id}", "DELETE"), ("/favorites/order", "PUT"), ("/visit/{app_id}", "POST"),
                         ("/hidden/{app_id}", "PUT"), ("/hidden/{app_id}", "DELETE"),
                         ("/curation/{app_id}", "PUT")):
        assert (path, method) in routes, (path, method)


def test_list_parameters_take_repeats_and_commas():
    assert discover._split(["Finance,Supply Chain", " HR ", ""]) == ["Finance", "Supply Chain", "HR"]


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} passed")
