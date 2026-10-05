"""Tests for removing a global view: archive first, delete permanently second.

Deleting a global view takes every version of it from every user's sidebar and
cannot be undone, so the route insists on an archive step in between. What is
pinned here is the order of those two steps and who may take them, using a fake
connection that records the statements it was given — enough to see that a refused
request wrote nothing, which is the part a mistake would get wrong.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from fastapi import HTTPException
    from routes import apps
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_view_archive: {e}")
    sys.exit(0)

ME = "taylor@example.com"


class FakeCursor:
    """Answers the few reads the routes make and remembers every write."""

    def __init__(self, store):
        self.store = store
        self.description = None
        self._row = None
        self._rows = []

    def execute(self, sql, params=None):
        text = " ".join(sql.split())
        self.store.statements.append((text, params))
        self._row, self._rows = None, []
        if "FROM dashboard_views WHERE id" in text and "ORDER BY version DESC" in text:
            view = self.store.view
            self.description = [("username",), ("is_global",), ("domain",)]
            self._row = None if view is None else (view["username"], view["is_global"], view["domain"])
        elif "SELECT 1 FROM archived_views" in text:
            self.description = [("?column?",)]
            self._row = (1,) if self.store.archived else None
        elif "FROM archived_views av" in text:
            self.description = [("id",), ("version",), ("name",), ("domain",), ("archived_by",), ("archived_at",)]
            self._rows = list(self.store.archive_listing)

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, store):
        self.store = store
        self.committed = False

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


class Store:
    def __init__(self, view, archived=False, archive_listing=()):
        self.view = view
        self.archived = archived
        self.archive_listing = archive_listing
        self.statements = []
        self.conn = FakeConn(self)

    def wrote(self, verb):
        return [s for s, _ in self.statements if s.startswith(verb)]


def global_view(domain="Sales"):
    return {"username": "system", "is_global": 1, "domain": domain}


def personal_view(owner=ME):
    return {"username": owner, "is_global": 0, "domain": "General"}


def run(store, fn, *args, editor=True, perms=None, **kwargs):
    """Call a route with the database, identity and permission checks faked."""
    saved = (apps.get_db_connection, apps._get_current_username,
             apps.require_domain_editor, apps._get_user_permissions)

    def deny(_w, domain, _env="dev"):
        if not editor:
            raise HTTPException(status_code=403, detail=f"Forbidden: Editor required for '{domain}'")
        return True

    apps.get_db_connection = lambda _env: store.conn
    apps._get_current_username = lambda _w: ME
    apps.require_domain_editor = deny
    apps._get_user_permissions = lambda _w, _env: perms or {"is_admin": False, "domain_permissions": {}}
    try:
        return fn(*args, w=None, env="dev", **kwargs)
    finally:
        (apps.get_db_connection, apps._get_current_username,
         apps.require_domain_editor, apps._get_user_permissions) = saved


def refused(store, fn, *args, **kwargs):
    try:
        run(store, fn, *args, **kwargs)
    except HTTPException as exc:
        return exc
    raise AssertionError("the request was not refused")


def test_archiving_a_global_view_records_who_and_keeps_every_version():
    store = Store(global_view())
    result = run(store, apps.archive_app, "v1")
    assert result["archived"] is True
    inserts = [(s, p) for s, p in store.statements if s.startswith("INSERT INTO archived_views")]
    assert inserts and inserts[0][1] == ("v1", ME)
    assert store.conn.committed
    # Soft: nothing is deleted from the versioned table.
    assert not store.wrote("DELETE")


def test_a_personal_view_cannot_be_archived():
    store = Store(personal_view())
    assert refused(store, apps.archive_app, "v1").status_code == 400
    assert not store.wrote("INSERT")


def test_archiving_a_view_that_does_not_exist_is_a_404():
    assert refused(Store(None), apps.archive_app, "nope").status_code == 404


def test_only_a_domain_editor_may_archive():
    store = Store(global_view())
    assert refused(store, apps.archive_app, "v1", editor=False).status_code == 403
    assert not store.wrote("INSERT")


def test_restoring_clears_the_archive_and_nothing_else():
    store = Store(global_view(), archived=True)
    run(store, apps.restore_app, "v1")
    assert store.wrote("DELETE FROM archived_views")
    assert not store.wrote("DELETE FROM dashboard_views")
    assert store.conn.committed


def test_restoring_needs_the_same_right_as_archiving():
    store = Store(global_view(), archived=True)
    assert refused(store, apps.restore_app, "v1", editor=False).status_code == 403
    assert not store.wrote("DELETE")


def test_a_global_view_cannot_be_deleted_until_it_is_archived():
    store = Store(global_view(), archived=False)
    exc = refused(store, apps.delete_app, "v1")
    assert exc.status_code == 409
    assert "Archive" in exc.detail
    assert not store.wrote("DELETE")


def test_an_archived_global_view_can_be_deleted_for_good():
    store = Store(global_view(), archived=True)
    run(store, apps.delete_app, "v1")
    assert store.wrote("DELETE FROM dashboard_views")
    # The marker goes with the view, or the id would stay hidden if it were reused.
    assert store.wrote("DELETE FROM archived_views")
    assert store.conn.committed


def test_deleting_for_good_still_needs_editor_rights():
    store = Store(global_view(), archived=True)
    assert refused(store, apps.delete_app, "v1", editor=False).status_code == 403
    assert not store.wrote("DELETE")


def test_closing_a_personal_view_is_unchanged():
    """The sidebar's Close button deletes your own view outright; archiving is for global ones."""
    store = Store(personal_view(ME))
    run(store, apps.delete_app, "v1")
    assert store.wrote("DELETE FROM dashboard_views")


def test_nobody_else_can_delete_your_personal_view():
    store = Store(personal_view("someone.else@example.com"))
    assert refused(store, apps.delete_app, "v1").status_code == 403
    assert not store.wrote("DELETE")


def test_the_archive_lists_only_domains_the_caller_edits():
    rows = [
        ("a", 3, "Orders", "Sales", "x@example.com", None),
        ("b", 1, "Margins", "Finance", "y@example.com", None),
    ]
    store = Store(global_view(), archive_listing=rows)
    perms = {"is_admin": False, "domain_permissions": {"Sales": "editor", "Finance": "viewer"}}
    listed = run(store, apps.list_archived_apps, perms=perms)["apps"]
    assert [v["id"] for v in listed] == ["a"]

    everyone = run(store, apps.list_archived_apps, perms={"is_admin": True, "domain_permissions": {}})["apps"]
    assert [v["id"] for v in everyone] == ["a", "b"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
