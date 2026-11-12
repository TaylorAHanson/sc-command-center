"""Standalone tests for Discover's per-person signals (services/view_signals.py).

Pinned against fake connections: that an open is one autocommitted statement
which counts a viewer only on the person's first open of the day and never
raises; the trend's damping; that New for you leaves out shares with everyone,
grants you made and views you've opened; that curation is checked before it
writes; and that the sidebar's working set is re-checked against access.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from fastapi import HTTPException
    from services import access, view_catalog, view_signals as vs
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_view_signals: {e}")
    sys.exit(0)

ME = access.Caller("Ana@Example.com", ("planners",), False)
T0 = datetime(2026, 11, 1, 9, 0)


class FakeCursor:
    """Answers by the first matching fragment in `answers`; anything else is a test bug."""

    def __init__(self, conn):
        self.conn, self.description, self.rowcount, self._rows = conn, None, 0, []

    def execute(self, sql, params=None):
        self.conn.statements.append((sql, params, self.conn.autocommit))
        if self.conn.fail:
            raise RuntimeError("connection reset")
        for fragment, (columns, rows) in self.conn.answers.items():
            if fragment in sql:
                self.description = [(c,) for c in columns]
                self._rows = list(rows)
                self.rowcount = len(self._rows)
                return
        if sql.lstrip().upper().startswith(("SELECT", "WITH")) and "INSERT" not in sql and "UPDATE" not in sql:
            raise AssertionError(f"unexpected query: {sql[:120]}")
        self.description, self._rows, self.rowcount = None, [], 1

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, answers=None, fail=False):
        self.answers, self.fail = answers or {}, fail
        self.statements, self.autocommit, self.closed, self.commits, self.rollbacks = [], False, False, 0, 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class patched:
    """Swap module attributes for the length of a with-block."""

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


def ready(flag=True):
    view_catalog._ready = flag


# ------------------------------------------------------------------------ visits

def test_an_open_counts_a_viewer_only_on_the_first_open_of_the_day():
    sql = " ".join(vs.VISIT_SQL.split())
    assert "ON CONFLICT (username, app_id, day) DO UPDATE SET last_opened_at = now(), opens = view_visits.opens + 1" in sql
    assert "RETURNING (xmax = 0) AS first" in sql
    assert "INSERT INTO view_daily (app_id, day, viewers) SELECT %(a)s, CURRENT_DATE, 1 FROM v WHERE v.first" in sql
    assert sql.count(";") == 0


def test_an_open_is_one_autocommitted_statement():
    conn = FakeConn()
    ready()
    try:
        with patched((vs, "_content", lambda: conn)):
            vs.record_visit(" Ana@Example.com ", "view-1")
    finally:
        ready(False)
    assert conn.rollbacks == 1, "the pool's ping can leave a transaction open"
    assert [(s is vs.VISIT_SQL, p, auto) for s, p, auto in conn.statements] == \
        [(True, {"u": "ana@example.com", "a": "view-1"}, True)]
    assert conn.autocommit is False and conn.closed


def test_an_open_never_raises_and_skips_what_it_cant_attribute():
    opened = []
    ready()
    try:
        with patched((vs, "_content", lambda: opened.append(1) or FakeConn())):
            for user, app_id in (("unknown", "v"), ("", "v"), ("ana@example.com", ""), ("ana@example.com", "x" * 201)):
                vs.record_visit(user, app_id)
        assert opened == []
        failing = FakeConn(fail=True)
        with patched((vs, "_content", lambda: failing)):
            vs.record_visit("ana@example.com", "v")
        assert failing.closed

        def unreachable():
            raise RuntimeError("could not connect")
        with patched((vs, "_content", unreachable)):
            vs.record_visit("ana@example.com", "v")
    finally:
        ready(False)
    with patched((vs, "_content", lambda: opened.append(1))):
        vs.record_visit("ana@example.com", "v")
    assert opened == []


def test_trend_is_damped_growth():
    assert vs.trend(0, 0) == 0
    assert vs.trend(3, 0) == 0.6
    assert vs.trend(200, 100) == 0.952
    assert vs.trend(200, 100) > vs.trend(3, 0)
    assert vs.trend(10, 20) < 0
    assert "/ (COALESCE(d.p7, 0) + 5)" in vs.ROLLUP_SQL


def test_the_rollup_writes_only_rows_whose_numbers_changed():
    sql = " ".join(vs.ROLLUP_SQL.split())
    assert "IS DISTINCT FROM (f.v30, f.v7, f.trend, f.favs, f.opened_at)" in sql
    assert "WHERE day > CURRENT_DATE - 30" in sql


# --------------------------------------------------------------- new for you

def test_new_for_you_is_direct_shares_you_havent_opened():
    settings = FakeConn({"FROM object_permissions": (("object_id", "at"), [("v3", T0), ("v1", T0), ("v2", T0)])})
    content = FakeConn({"FROM view_catalog vc WHERE vc.id = ANY": (("id",), [("v1",), ("v3",)])})
    with patched((vs, "_settings", lambda: settings), (vs, "_content", lambda: content)):
        assert vs.new_for_you_ids(ME) == ["v3", "v1"]
        assert vs.new_for_you_ids(ME, limit=1) == ["v3"]
    sql, params, _ = settings.statements[0]
    assert "principal <> '*' AND principal_type <> 'all'" in sql
    assert "LOWER(granted_by) <> %(me)s" in sql
    assert params["me"] == "ana@example.com" and params["groups"] == ["planners"] and params["days"] == 14
    sql, params, _ = content.statements[0]
    assert "vc.owner_key IS DISTINCT FROM %(me)s" in sql and "view_visits" in sql and "view_hidden" in sql
    assert params["ids"] == ["v3", "v1", "v2"]


def test_new_for_you_skips_the_content_query_when_nothing_was_shared():
    settings = FakeConn({"FROM object_permissions": (("object_id", "at"), [])})
    with patched((vs, "_settings", lambda: settings), (vs, "_content", lambda: 1 / 0)):
        assert vs.new_for_you_ids(ME) == []
    assert vs.new_for_you_ids(access.Caller("", (), False)) == []


# ------------------------------------------------------------------ curation

def test_a_featured_position_out_of_range_writes_nothing():
    for position in (-1, vs.MAX_FEATURED_POSITION + 1):
        with patched((vs, "_content", lambda: 1 / 0)):
            try:
                vs.curate(ME, "v1", {"featured_position": position})
                raise AssertionError(position)
            except HTTPException as e:
                assert e.status_code == 400


def test_curating_a_view_that_was_never_published_is_404():
    conn = FakeConn({"FROM dashboard_views WHERE id": (("one",), [])})
    with patched((vs, "_content", lambda: conn)):
        try:
            vs.curate(ME, "draft-only", {"certified": True})
            raise AssertionError("curated a missing view")
        except HTTPException as e:
            assert e.status_code == 404
    assert conn.commits == 0 and conn.closed


def test_curation_changes_only_the_fields_sent_and_updates_the_catalog_row():
    existing = (("featured_position", "featured_by", "featured_at", "certified", "certified_by", "certified_at"),
                [(4, "root@example.com", T0, True, "root@example.com", T0)])
    conn = FakeConn({"FROM dashboard_views WHERE id": (("one",), [(1,)]),
                     "FROM view_curation WHERE app_id": existing,
                     "SELECT now()": (("now",), [(datetime(2026, 11, 12),)])})
    with patched((vs, "_content", lambda: conn)):
        out = vs.curate(ME, "v1", {"featured_position": None})
    assert out["featured_position"] is None and out["featured_by"] == ME.username
    assert out["certified"] is True and out["certified_by"] == "root@example.com"
    update = [p for s, p, _ in conn.statements if s.startswith("UPDATE view_catalog")]
    assert update == [(None, True, "v1")] and conn.commits == 1


# ---------------------------------------------------------- favorites, hidden

def test_reordering_favorites_puts_the_named_ones_first():
    conn = FakeConn({"SELECT app_id FROM user_favorites": (("app_id",), [("b",), ("a",), ("c",)])})
    with patched((vs, "_content", lambda: conn)):
        assert vs.order_favorites(ME, ["b", "a", "b", ""]) == ["b", "a", "c"]
    first, second = conn.statements[0], conn.statements[1]
    assert "WITH ORDINALITY" in first[0] and first[1] == (["b", "a"], "ana@example.com")
    assert second[1] == (2, "ana@example.com", ["b", "a"])


def test_a_favorite_needs_access_to_the_view():
    def refuse(who, object_type, object_id, level="USE", not_found="Not found"):
        raise HTTPException(status_code=404, detail=not_found)

    with patched((access, "require", refuse), (vs, "_content", lambda: 1 / 0)):
        try:
            vs.add_favorite(ME, "secret")
            raise AssertionError("starred a view without access")
        except HTTPException as e:
            assert e.status_code == 404


def test_hiding_needs_a_plausible_id():
    for bad in ("", "x" * 201):
        try:
            vs.hide(ME, bad)
            raise AssertionError(bad)
        except HTTPException as e:
            assert e.status_code == 400


# ---------------------------------------------------------------------- home

def test_home_is_rechecked_and_merges_never_published_drafts():
    light = ["id", "ref", "name", "description", "owner", "domain", "presentation", "updated_at", "published_at",
             "viewers_30d", "trend", "favorites", "featured_position", "certified", "favorite", "hidden",
             "my_opened", "has_draft", "listed"]

    def lrow(i, updated, listed=True):
        return (i, i, i.upper(), "", "ana@example.com", None, "workspace", updated, updated, 0, 0, 0, None, False,
                False, False, None, False, listed)

    conn = FakeConn({
        "SELECT app_id FROM user_favorites": (("app_id",), [("fav",), ("gone",)]),
        "FROM view_visits WHERE username": (("app_id", "at"), [("rec",), ("fav",)]),
        "WHERE vc.id = ANY": (light, [lrow("fav", T0), lrow("rec", T0), lrow("gone", T0, listed=False)]),
        "WHERE vc.owner_key = %(me)s ORDER BY": (light, [lrow("mine", datetime(2026, 11, 5))]),
        "SELECT COUNT(*) FROM view_catalog WHERE owner_key": (("n",), [(1,)]),
        "SELECT d.object_id AS id": (("id", "name", "domain", "updated_at", "favorite"),
                                     [("draft1", "Draft", None, datetime(2026, 11, 9), False)]),
        "SELECT COUNT(*) \nFROM object_drafts": (("n",), [(1,)]),
    })
    levels = {"fav": "USE", "rec": "USE", "mine": "MANAGE", "draft1": "MANAGE"}
    dirty = []
    with patched((vs, "_content", lambda: conn), (vs, "new_for_you_ids", lambda who, limit=None: ["x", "y"]),
                 (access, "levels_for", lambda who, t, ids: {i: levels[i] for i in ids if i in levels}),
                 (view_catalog, "mark_dirty", lambda t, i: dirty.append(i))):
        out = vs.home(ME)
    assert dirty == [], "a favorite the caller lost access to is dropped, not queued: its catalog row is right"
    assert [r["id"] for r in out["favorites"]] == ["fav"]
    assert [r["id"] for r in out["recent"]] == ["rec", "fav"]
    assert [r["id"] for r in out["mine"]] == ["draft1", "mine"]
    assert out["mine"][0]["state"] == "draft_only" and out["mine"][1]["state"] == "published"
    assert [r["id"] for r in out["drafts"]] == ["draft1"]
    assert out["mine_total"] == 2 and out["new_for_you_count"] == 2


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} passed")
