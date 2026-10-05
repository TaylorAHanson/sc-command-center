"""Tests for /api/apps and the /api/views shim that writes the same rows.

Three things are pinned, each against a fake connection that records every
statement so a refusal can be shown to have written nothing:

- that who may open, subscribe to and change an app is exactly who could do so
  to the view — apps inherit that model, they don't revise it;
- that opening an app by id or reading its history never writes;
- that the deployment already running keeps working: a view saved before apps
  opens as itself, and a single-canvas save from `/api/views` (or a browser still
  on the old bundle) changes the first tab and leaves every other tab alone.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from fastapi import HTTPException
    from routes import apps, views
    from services import app_spec, app_store, settings_store
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_apps_routes: {e}")
    sys.exit(0)

ME = "taylor@example.com"
OTHER = "someone.else@example.com"
CUSTOM = "0b5c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d"
NOBODY = {"is_admin": False, "domain_permissions": {}}


def row(app_id, *, owner=OTHER, is_global=0, domain="General", widgets=None, spec=None, version=1, pin=None, timestamp=None):
    return {
        "id": app_id, "version": version, "name": f"App {app_id}", "domain": domain,
        "username": "system" if is_global else owner, "is_global": is_global,
        "widgets_json": json.dumps(widgets or []), "spec_json": json.dumps(spec) if spec else None,
        "is_locked": 0, "pinned_agent_id": pin, "timestamp": timestamp,
    }


def three_tabs(app_id):
    spec = app_spec.legacy_spec(app_id, [{"i": "a", "type": "iframe"}])
    spec["tabs"] += [
        {"id": "t2", "name": "Two", "widgets": [{"i": "b", "type": CUSTOM}], "pinned_agent_id": None},
        {"id": "t3", "name": "Three", "widgets": [{"i": "c", "type": "iframe"}], "pinned_agent_id": "agent-3"},
    ]
    return spec


class Store:
    def __init__(self, *rows, subscriptions=(), archived=(), widgets=()):
        self.apps = {r["id"]: r for r in rows}
        self.subscriptions = set(subscriptions)
        self.archived = set(archived)
        self.widgets = list(widgets)  # (id, name, is_certified)
        self.statements = []
        self.committed = False

    def writes(self):
        return [(s, p) for s, p in self.statements if s.split()[0] in ("INSERT", "UPDATE", "DELETE")]

    def inserted_app(self):
        found = [p for s, p in self.statements if s.startswith("INSERT INTO dashboard_views")]
        assert len(found) == 1, f"expected one new version, got {len(found)}"
        cols = ("id", "version", "name", "domain", "username", "is_global",
                "widgets_json", "spec_json", "is_locked", "pinned_agent_id")
        return dict(zip(cols, found[0]))


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self.description = None
        self._rows = []

    def execute(self, sql, params=None):
        text = " ".join(sql.split())
        self.store.statements.append((text, params))
        self._rows, self.description = [], [("?column?",)]
        if text == "SELECT id FROM dashboard_views WHERE id = %s":
            self._rows = [(params[0],)] if params[0] in self.store.apps else []
        elif text.startswith("SELECT id, version, name") and "FROM dashboard_views WHERE id" in text:
            r = self.store.apps.get(params[0])
            self.description = [(c,) for c in app_store.HEAD_COLUMNS]
            self._rows = [tuple(r.get(c) for c in app_store.HEAD_COLUMNS)] if r else []
        elif text.startswith("SELECT 1 FROM archived_views"):
            self._rows = [(1,)] if params[0] in self.store.archived else []
        elif text.startswith("SELECT 1 FROM shared_views"):
            self._rows = [(1,)] if (params[0], params[1]) in self.store.subscriptions else []
        elif "FROM widgets w" in text:
            self._rows = [w for w in self.store.widgets if w[0] in params[0]]
        elif text.startswith("SELECT version, name, username, timestamp"):
            self.description = [("version",), ("name",), ("username",), ("timestamp",)]
            r = self.store.apps.get(params[0])
            self._rows = [(r["version"], r["name"], r["username"], None)] if r else []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self, store):
        self.store = store

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.store.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def run(store, fn, *args, user=ME, perms=None, editor_of=(), certified_only=False, **kwargs):
    """Call a route with the database, identity, permissions and settings faked."""
    perms = perms or NOBODY

    def require_editor(_w, domain, _env="dev"):
        if not (perms.get("is_admin") or domain in editor_of):
            raise HTTPException(status_code=403, detail=f"Forbidden: Editor required for '{domain}'")
        return True

    patches = [
        (apps, "get_db_connection", lambda _env: FakeConn(store)),
        (views, "get_db_connection", lambda _env: FakeConn(store)),
        (apps, "_get_current_username", lambda _w: user),
        (views, "_get_current_username", lambda _w: user),
        (apps, "_get_user_permissions", lambda _w, _env: perms),
        (apps, "require_domain_editor", require_editor),
        (views, "require_domain_editor", require_editor),
        (app_store, "require_domain_editor", require_editor),
        (settings_store, "get_bool_setting", lambda key, *a, **k: certified_only if key == "require_certified_for_global_views" else False),
    ]
    saved = [(mod, name, getattr(mod, name)) for mod, name, _ in patches]
    for mod, name, value in patches:
        setattr(mod, name, value)
    try:
        return fn(*args, w=None, env="dev", **kwargs)
    finally:
        for mod, name, value in saved:
            setattr(mod, name, value)


def refused(store, fn, *args, **kwargs):
    try:
        run(store, fn, *args, **kwargs)
    except HTTPException as exc:
        return exc
    raise AssertionError("the request was not refused")


# ------------------------------------------------------------- opening an app

def test_a_view_saved_before_apps_opens_as_itself():
    store = Store(row("v1", owner=ME, widgets=[{"i": "a", "type": "iframe"}], pin="agent-1"))
    app = run(store, apps.get_app, "v1")["app"]
    assert [t["id"] for t in app["spec"]["tabs"]] == ["v1"]
    assert app["spec"]["tabs"][0]["widgets"] == [{"i": "a", "type": "iframe"}]
    assert app["spec"]["presentation"] == "workspace"
    assert app["pinned_agent_id"] == "agent-1"


def test_opening_an_app_writes_nothing():
    store = Store(row("v1", spec=three_tabs("v1")))
    run(store, apps.get_app, "v1")
    run(store, apps.app_history, app_id="v1")
    assert store.writes() == [] and not store.committed, "reading an app must not subscribe or save"


def test_someone_elses_personal_app_opens_by_id_as_a_shared_view_does():
    store = Store(row("v1"))
    app = run(store, apps.get_app, "v1")["app"]
    assert app["id"] == "v1" and app["is_shared"] is False, "not subscribed, so not in the sidebar"


def test_a_subscriber_sees_a_personal_app_as_shared():
    store = Store(row("v1"), subscriptions={(ME, "v1")})
    assert run(store, apps.get_app, "v1")["app"]["is_shared"] is True


def test_a_global_app_needs_a_role_in_its_domain():
    store = Store(row("g1", is_global=1, domain="Sales"))
    hidden = refused(store, apps.get_app, "g1")
    missing = refused(store, apps.get_app, "nope")
    assert (hidden.status_code, hidden.detail) == (missing.status_code, missing.detail) == (404, "App not found")
    seller = {"is_admin": False, "domain_permissions": {"Sales": "viewer"}}
    assert run(store, apps.get_app, "g1", perms=seller)["app"]["is_global"] is True


def test_an_archived_app_reads_as_missing():
    store = Store(row("v1", owner=ME), archived={"v1"})
    assert refused(store, apps.get_app, "v1").status_code == 404


def test_history_follows_the_same_rule():
    assert refused(Store(row("g1", is_global=1, domain="Sales")), apps.app_history, app_id="g1").status_code == 404


# ------------------------------------------------------------ subscribing

def test_subscribing_is_the_same_act_as_subscribing_to_a_shared_view():
    store = Store(row("v1"))
    run(store, apps.subscribe_app, "v1")
    assert [p for s, p in store.writes() if s.startswith("INSERT INTO shared_views")] == [(ME, "v1")]


# ------------------------------------------ the deployment that already exists

def test_a_single_canvas_save_from_api_views_keeps_the_other_tabs():
    store = Store(row("v1", owner=ME, spec=three_tabs("v1"), version=7))
    run(store, views.update_view, "v1", views.ViewUpdate(widgets=[{"i": "moved", "type": "iframe"}]))
    saved = store.inserted_app()
    spec = json.loads(saved["spec_json"])
    assert saved["version"] == 8
    assert spec["tabs"][0]["widgets"] == [{"i": "moved", "type": "iframe"}]
    assert spec["tabs"][1:] == three_tabs("v1")["tabs"][1:], "tabs the old client never saw survive its save"
    assert json.loads(saved["widgets_json"]) == [{"i": "moved", "type": "iframe"}], "widgets_json mirrors tab one"


def test_a_save_that_sends_no_widgets_keeps_the_whole_spec():
    store = Store(row("v1", owner=ME, spec=three_tabs("v1"), pin="agent-1"))
    run(store, views.update_view, "v1", views.ViewUpdate(name="Renamed"))
    saved = store.inserted_app()
    assert saved["name"] == "Renamed"
    assert json.loads(saved["spec_json"]) == app_spec.read_spec("v1", json.dumps(three_tabs("v1")), None)
    assert saved["pinned_agent_id"] == "agent-1", "an absent pin keeps the pin"


def test_saving_a_legacy_view_writes_its_spec_for_the_first_time():
    store = Store(row("v1", owner=ME, widgets=[{"i": "a", "type": "iframe"}]))
    run(store, views.update_view, "v1", views.ViewUpdate(is_locked=True))
    spec = json.loads(store.inserted_app()["spec_json"])
    assert [t["id"] for t in spec["tabs"]] == ["v1"] and spec["tabs"][0]["widgets"] == [{"i": "a", "type": "iframe"}]


def test_creating_a_view_writes_a_one_tab_app():
    store = Store()
    result = run(store, views.create_view, views.ViewCreate(id="new", name="Mine", widgets=[{"i": "a", "type": "x"}]))
    saved = store.inserted_app()
    assert result["id"] == "new" and saved["username"] == ME
    assert json.loads(saved["spec_json"])["tabs"][0]["id"] == "new"


def test_nobody_else_can_save_your_view():
    store = Store(row("v1", owner=ME))
    assert refused(store, views.update_view, "v1", views.ViewUpdate(name="x"), user=OTHER).status_code == 403
    assert store.writes() == []


# ------------------------------------------------------------- saving apps

def test_saving_a_spec_replaces_it_whole():
    store = Store(row("v1", owner=ME, spec=three_tabs("v1")))
    two = {"tabs": [{"id": "v1", "widgets": []}, {"id": "t9", "name": "New"}], "presentation": "standalone"}
    run(store, apps.update_app, "v1", apps.AppUpdate(spec=two))
    spec = json.loads(store.inserted_app()["spec_json"])
    assert [t["id"] for t in spec["tabs"]] == ["v1", "t9"] and spec["presentation"] == "standalone"


def test_an_invalid_spec_is_refused_and_writes_nothing():
    store = Store(row("v1", owner=ME))
    exc = refused(store, apps.update_app, "v1", apps.AppUpdate(spec={"tabs": []}))
    assert exc.status_code == 400 and "at least one tab" in exc.detail
    assert store.writes() == []


def test_making_an_app_global_needs_editor_rights_where_it_lands():
    store = Store(row("v1", owner=ME))
    exc = refused(store, apps.update_app, "v1", apps.AppUpdate(is_global=True, domain="Finance"))
    assert exc.status_code == 403 and store.writes() == []
    run(store, apps.update_app, "v1", apps.AppUpdate(is_global=True, domain="Finance"), editor_of=("Finance",))
    assert store.inserted_app()["username"] == "system"


def test_moving_a_global_app_to_another_domain_needs_rights_in_both():
    store = Store(row("g1", is_global=1, domain="Sales"))
    exc = refused(store, apps.update_app, "g1", apps.AppUpdate(domain="Finance"), editor_of=("Sales",))
    assert exc.status_code == 403 and store.writes() == []


def test_the_certified_check_reads_every_tab():
    store = Store(row("g1", is_global=1, domain="Sales", spec=three_tabs("g1")),
                  widgets=[(CUSTOM, "Margins", 0)])
    exc = refused(store, apps.update_app, "g1", apps.AppUpdate(name="x"), editor_of=("Sales",), certified_only=True)
    assert exc.status_code == 400 and "Margins" in exc.detail, "the uncertified widget is on tab two"
    assert store.writes() == []


def test_every_app_the_api_hands_out_saves_back_unchanged():
    # The browser saves an app by sending back the spec it was given with one
    # tab's layout changed. If any row read leniently failed strict validation,
    # every drag on that app would start failing the day the client moved here.
    long_id = "imported-" + "x" * 80
    rows = [
        row("v1", owner=ME, widgets=[{"i": "a", "type": "iframe", "x": 0, "y": None, "w": 4, "h": 4}]),
        row("v2", owner=ME, widgets=[{"i": "a", "type": "iframe"}, {"i": "a", "type": "iframe"}]),
        row(long_id, owner=ME, widgets=[{"i": "a", "type": "iframe"}]),
        row("v3", owner=ME, spec=three_tabs("v3"), pin="agent-1"),
        row("v4", owner=ME, spec={"tabs": [{"id": "t", "widgets": []}], "branding": {"title": "Ops"}, "nav": {"x": 1}}),
    ]
    for r in rows:
        store = Store(r)
        given = run(store, apps.get_app, r["id"])["app"]
        run(store, apps.update_app, r["id"], apps.AppUpdate(spec=given["spec"]))
        assert json.loads(store.inserted_app()["spec_json"]) == given["spec"], r["id"]


def test_an_app_says_when_it_was_last_saved():
    import datetime
    saved_at = datetime.datetime(2026, 10, 5, 12, 30)
    app = run(Store(row("v1", owner=ME, timestamp=saved_at)), apps.get_app, "v1")["app"]
    assert app["timestamp"] == "2026-10-05T12:30:00"


def test_creating_an_app_over_an_existing_id_is_refused():
    store = Store(row("v1", owner=ME))
    assert refused(store, apps.create_app, apps.AppCreate(id="v1", name="Dup")).status_code == 409
    assert store.writes() == []


# ------------------------------------------------------- composing from views

def test_composing_copies_views_into_one_new_app_and_leaves_them_alone():
    store = Store(row("v1", owner=ME, widgets=[{"i": "a", "type": "iframe"}], pin="agent-1"),
                  row("g1", is_global=1, domain="Sales", widgets=[{"i": "b", "type": "iframe"}]))
    seller = {"is_admin": False, "domain_permissions": {"Sales": "viewer"}}
    result = run(store, apps.compose_app, apps.AppCompose(name="Hub", source_ids=["v1", "g1", "v1"]), perms=seller)
    saved = store.inserted_app()
    spec = json.loads(saved["spec_json"])
    assert result["tabs"] == 2, "a repeated source is one tab"
    assert [t["name"] for t in spec["tabs"]] == ["App v1", "App g1"]
    assert spec["tabs"][0]["pinned_agent_id"] == "agent-1"
    assert saved["username"] == ME and saved["is_global"] == 0 and saved["id"] not in ("v1", "g1")
    assert len(store.writes()) == 1, "the sources are copied, not changed, archived or subscribed"


def test_composing_refuses_a_view_the_caller_cannot_open():
    store = Store(row("v1", owner=ME), row("g1", is_global=1, domain="Finance"))
    exc = refused(store, apps.compose_app, apps.AppCompose(name="Hub", source_ids=["v1", "g1"]))
    assert exc.status_code == 404 and "g1" in exc.detail
    assert store.writes() == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
