"""Tests for /api/apps.

Pinned against a fake connection that records every statement, so a refusal can
be shown to have written nothing, and a fake access list in place of the
settings schema:

- that who may open, save, publish and close an app is its access list: Can use
  to open the published version, Can manage for the draft and every change, and
  nothing at all reading exactly like an app that doesn't exist;
- that saving writes the draft and only publishing makes a version, with the
  widgets and agents confirmed alongside it, in one transaction;
- that opening an app by id or reading its history never writes;
- that the deployment already running keeps working: a view saved before apps
  opens as itself, and saving it keeps what it held.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from fastapi import HTTPException
    from routes import apps
    from services import access, app_spec, app_store, settings_store
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_apps_routes: {e}")
    sys.exit(0)

ME = "taylor@example.com"
OTHER = "someone.else@example.com"
CUSTOM = "0b5c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d"
SECOND = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
UUID = "3f2a9c1e-0b5c-4d2e-9f40-4a5b8c6d7e8f"
MANAGE, USE = access.MANAGE, access.USE

COLUMNS = {
    "dashboard_views": app_store.HEAD_COLUMNS + ("published_by", "published_at"),
    "widgets": ("id", "version", "name", "domain", "tsx_code", "is_certified", "is_deprecated",
                "created_by", "timestamp", "published_by", "published_at"),
    "agent_profiles": ("id", "version", "name", "username", "is_deprecated", "timestamp",
                       "published_by", "published_at"),
}
TABLE_OF = {"app": "dashboard_views", "widget": "widgets", "agent": "agent_profiles"}


def row(app_id, *, owner=OTHER, widgets=None, spec=None, version=1, pin=None, timestamp=None, name=None):
    return {
        "id": app_id, "version": version, "name": name or f"App {app_id}", "domain": "General",
        "username": owner, "is_global": 0,
        "widgets_json": json.dumps(widgets or []), "spec_json": json.dumps(spec) if spec else None,
        "is_locked": 0, "pinned_agent_id": pin, "timestamp": timestamp,
    }


def draft_of(r, **changes):
    """A draft payload as the app saves one, from a row's columns."""
    payload = {k: r[k] for k in app_store.PAYLOAD_COLUMNS}
    payload.update(changes)
    return {"payload": payload, "base_version": r.get("version"), "updated_by": ME, "updated_at": None}


def three_tabs(app_id):
    spec = app_spec.legacy_spec(app_id, [{"i": "a", "type": "iframe"}])
    spec["tabs"] += [
        {"id": "t2", "name": "Two", "widgets": [{"i": "b", "type": CUSTOM}], "pinned_agent_id": None},
        {"id": "t3", "name": "Three", "widgets": [{"i": "c", "type": "iframe"}], "pinned_agent_id": "agent-3"},
    ]
    return spec


class Store:
    """The content schema and the access list, as far as the routes read them."""

    def __init__(self, *rows, drafts=None, acl=None, archived=(), hidden=(), widgets=(), agents=(),
                 library=(), links=()):
        self.tables = {t: {} for t in COLUMNS}
        for r in rows:
            self.tables["dashboard_views"].setdefault(r["id"], []).append(dict(r))
        for wid, name, certified in widgets:
            self.tables["widgets"].setdefault(wid, []).append(
                {"id": wid, "version": 1, "name": name, "domain": "General", "tsx_code": "x",
                 "is_certified": certified, "is_deprecated": 0})
        for aid, name in agents:
            self.tables["agent_profiles"].setdefault(aid, []).append(
                {"id": aid, "version": 1, "name": name, "is_deprecated": 0})
        # (object_type, id) -> draft row, as drafts.read returns it.
        self.drafts = {(k if isinstance(k, tuple) else ("app", k)): v for k, v in (drafts or {}).items()}
        # (object_type, id) -> {principal: level}; a bare id is an app.
        self.acl = {(k if isinstance(k, tuple) else ("app", k)): dict(v) for k, v in (acl or {}).items()}
        self.archived = set(archived)
        self.hidden = set(hidden)  # (username, app id)
        self.library = list(library)  # (id, domain): what the widget library holds
        # slug -> app id, in the order claimed; the last for an id is its current name.
        self.links = dict(links)
        self.statements = []
        self.committed = False
        self.granted = []  # (type, id, user, committed before?)
        self.acl_deleted = []

    def writes(self):
        return [(s, p) for s, p in self.statements if s.split()[0] in ("INSERT", "UPDATE", "DELETE")]

    def versions(self, app_id, table="dashboard_views"):
        return sorted(self.tables[table].get(app_id, []), key=lambda r: r["version"])

    def inserted(self, table="dashboard_views"):
        return [p for s, p in self.statements if s.startswith(f"INSERT INTO {table} ")]

    def draft(self, app_id, object_type="app"):
        return (self.drafts.get((object_type, app_id)) or {}).get("payload")


def _latest(rows, live=False):
    rows = [r for r in rows if not (live and r.get("is_deprecated"))]
    return max(rows, key=lambda r: r["version"]) if rows else None


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self.description = None
        self._rows = []
        self.rowcount = -1

    def _answer(self, columns, rows):
        self.description = [(c,) for c in columns]
        self._rows = [tuple(r.get(c) for c in columns) for r in rows]

    def execute(self, sql, params=None):
        text = " ".join(sql.split())
        s = self.store
        s.statements.append((text, params))
        self._rows, self.description, self.rowcount = [], [("?column?",)], -1
        table = next((t for t in COLUMNS if re.search(rf"\b{t}\b", text)), None)

        if text.startswith(("SAVEPOINT", "RELEASE", "ROLLBACK")):
            return
        # ------------------------------------------------------------ links
        if text.startswith("INSERT INTO app_links"):
            slug, app_id = params
            if s.links.get(slug, app_id) == app_id:
                s.links.pop(slug, None)
                s.links[slug] = app_id
                self._rows = [(slug,)]
        elif text.startswith("SELECT app_id FROM app_links"):
            self._rows = [(s.links[params[0]],)] if params[0] in s.links else []
        elif text.startswith("SELECT DISTINCT ON (app_id) app_id, slug FROM app_links"):
            current = {a: slug for slug, a in s.links.items() if a in params[0]}
            self._rows = list(current.items())
        elif text.startswith("DELETE FROM app_links"):
            s.links = {k: v for k, v in s.links.items() if v != params[0]}
        # ------------------------------------------------------------ drafts
        elif text.startswith("SELECT payload, base_version, updated_by, updated_at FROM object_drafts"):
            d = s.drafts.get((params[0], params[1]))
            self._answer(("payload", "base_version", "updated_by", "updated_at"), [d] if d else [])
        elif text.startswith("SELECT object_id, payload"):
            wanted = params[1] if len(params) > 1 else None
            found = [{"object_id": i, **d} for (t, i), d in s.drafts.items()
                     if t == params[0] and (wanted is None or i in wanted)]
            self._answer(("object_id", "payload", "base_version", "updated_by", "updated_at"), found)
        elif text.startswith("INSERT INTO object_drafts"):
            object_type, object_id, payload, base, user = params
            s.drafts[(object_type, object_id)] = {
                "payload": json.loads(json.dumps(payload.adapted, default=str)),
                "base_version": base, "updated_by": user, "updated_at": None,
            }
        elif text.startswith("DELETE FROM object_drafts"):
            self.rowcount = int(s.drafts.pop((params[0], params[1]), None) is not None)
        # ------------------------------------------------- versioned tables
        elif text.startswith("SELECT * FROM") and "LIMIT 0" in text:
            self._answer(COLUMNS[table], [])
        elif text.startswith("SELECT * FROM") and "AND version = %s" in text:
            found = [r for r in s.tables[table].get(params[0], []) if r["version"] == params[1]]
            self._answer(COLUMNS[table], found)
        elif text.startswith("SELECT * FROM"):
            found = _latest(s.tables[table].get(params[0], []), live="is_deprecated" in text)
            self._answer(COLUMNS[table], [found] if found else [])
        elif text.startswith("SELECT COALESCE(MAX(version), 0) AS v"):
            found = _latest(s.tables[table].get(params[0], []))
            self._answer(("v",), [{"v": found["version"] if found else 0}])
        elif text.startswith(f"INSERT INTO {table} ("):
            columns = [c.strip() for c in text.split("(", 1)[1].split(")", 1)[0].split(",")]
            values = dict(zip(columns, list(params) + [None]))
            s.tables[table].setdefault(values["id"], []).append(values)
        elif text.startswith("DELETE FROM dashboard_views"):
            s.tables["dashboard_views"].pop(params[0], None)
        elif "FROM dashboard_views dv" in text:
            heads = [_latest(v) for k, v in s.tables["dashboard_views"].items() if k in params[0]]
            self._answer(app_store.HEAD_COLUMNS, heads)
        elif text.startswith("SELECT id, version, name") and "FROM dashboard_views WHERE id" in text:
            found = _latest(s.tables["dashboard_views"].get(params[0], []))
            self._answer(app_store.HEAD_COLUMNS, [found] if found else [])
        elif text.startswith("SELECT version, name, username, published_by"):
            found = sorted(s.tables["dashboard_views"].get(params[0], []), key=lambda r: -r["version"])
            self._answer(("version", "name", "username", "published_by", "published_at", "timestamp"), found)
        elif "FROM widgets w" in text:
            heads = [_latest(v, live=True) for k, v in s.tables["widgets"].items() if k in params[0]]
            self._answer(("id", "version", "name", "domain", "is_certified"),
                         [{**h, "is_certified": h.get("is_certified") or 0} for h in heads if h])
        elif text.startswith("SELECT id, version, name, description") and "FROM widgets" in text:
            # The library query; which source it carries is Postgres's to work out.
            self.description = [("id",), ("domain",), ("version",), ("is_latest",)]
            self._rows = [(*lib, 1, True) for lib in s.library if lib[0] in params[-1]]
        # ------------------------------------------------- archive, sidebar
        elif text.startswith("SELECT 1 FROM archived_views"):
            self._rows = [(1,)] if params[0] in s.archived else []
        elif text == "SELECT id FROM archived_views":
            self._rows = [(i,) for i in s.archived]
        elif text.startswith("SELECT id, archived_by"):
            self._answer(("id", "archived_by", "archived_at"),
                         [{"id": i, "archived_by": "x@example.com", "archived_at": None} for i in sorted(s.archived)])
        elif text.startswith("INSERT INTO archived_views"):
            s.archived.add(params[0])
        elif text.startswith("DELETE FROM archived_views"):
            s.archived.discard(params[0])
        elif text.startswith("SELECT app_id FROM sidebar_hidden"):
            self._rows = [(a,) for u, a in s.hidden if u == params[0]]
        elif text.startswith("INSERT INTO sidebar_hidden"):
            s.hidden.add(tuple(params))
        elif text.startswith("DELETE FROM sidebar_hidden WHERE username"):
            s.hidden.discard(tuple(params))
        elif text.startswith("DELETE FROM sidebar_hidden"):
            s.hidden = {(u, a) for u, a in s.hidden if a != params[0]}
        else:
            raise AssertionError(f"unexpected statement: {text}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self, store):
        self.store = store
        self.snapshot = None

    def cursor(self):
        if self.snapshot is None:
            self.snapshot = json.dumps(self._state(), default=str)
        return FakeCursor(self.store)

    def _state(self):
        s = self.store
        return [s.tables, {f"{t}:{i}": d for (t, i), d in s.drafts.items()}, sorted(s.archived),
                sorted(s.hidden), s.links]

    def commit(self):
        self.store.committed = True
        self.snapshot = json.dumps(self._state(), default=str)

    def rollback(self):
        # What a rolled-back transaction leaves: the store as of the last commit.
        if self.snapshot is not None:
            tables, drafts, archived, hidden, links = json.loads(self.snapshot)
            s = self.store
            s.tables = tables
            s.drafts = {tuple(k.split(":", 1)): v for k, v in drafts.items()}
            s.archived, s.hidden, s.links = set(archived), {tuple(h) for h in hidden}, links

    def close(self):
        pass


def _matches(principal, user):
    return principal == "*" or principal.lower() == (user or "").lower()


def run(store, fn, *args, user=ME, admin=False, certified_only=False, **kwargs):
    """Call a route with the database, the access list, identity and settings faked."""
    who = access.Caller(user, (), admin)

    def levels_for(caller, object_type, ids):
        ids = [i for i in dict.fromkeys(ids) if i]
        if caller.is_admin:
            return {i: MANAGE for i in ids}
        out = {}
        for i in ids:
            held = [lvl for p, lvl in store.acl.get((object_type, i), {}).items() if _matches(p, caller.username)]
            if held:
                out[i] = MANAGE if MANAGE in held else USE
        return out

    def grants_for(caller, object_type):
        ids = [i for (t, i) in store.acl if t == object_type]
        return levels_for(access.Caller(caller.username, (), False), object_type, ids)

    def entries(object_type, object_id):
        return [{"principal": p, "principal_type": "all" if p == "*" else "user", "level": lvl}
                for p, lvl in store.acl.get((object_type, object_id), {}).items()]

    def owner_of(object_type, object_id):
        return next((p for p, lvl in store.acl.get((object_type, object_id), {}).items()
                     if p != "*" and lvl == MANAGE), None)

    def grant_owner(object_type, object_id, username):
        store.granted.append((object_type, object_id, username, store.committed))
        store.acl.setdefault((object_type, object_id), {})[username] = MANAGE

    def acl_facts(ids):
        return {i: {"owner": owner_of("app", i), "sharing": access.summary_of(entries("app", i), owner_of("app", i))}
                for i in ids if ("app", i) in store.acl}

    patches = [
        (apps, "get_db_connection", lambda *_a, **_k: FakeConn(store)),
        (apps, "_get_current_username", lambda _w: user),
        (apps, "_acl_facts", acl_facts),
        (access, "caller", lambda _w: who),
        (access, "levels_for", levels_for),
        (access, "level_for", lambda caller, t, i: levels_for(caller, t, [i]).get(i)),
        (access, "grants_for", grants_for),
        (access, "get_acl", entries),
        (access, "owner_of", owner_of),
        (access, "grant_owner", grant_owner),
        (access, "delete_acl", lambda t, i: store.acl_deleted.append((t, i))),
        (settings_store, "get_bool_setting",
         lambda key, *a, **k: certified_only if key == "require_certified_for_global_views" else False),
    ]
    saved = [(mod, name, getattr(mod, name)) for mod, name, _ in patches]
    for mod, name, value in patches:
        setattr(mod, name, value)
    try:
        return fn(*args, w=None, **kwargs)
    finally:
        for mod, name, value in saved:
            setattr(mod, name, value)


def refused(store, fn, *args, **kwargs):
    try:
        run(store, fn, *args, **kwargs)
    except HTTPException as exc:
        return exc
    raise AssertionError("the request was not refused")


def mine(*rows, **kw):
    """A store where ME manages every row given."""
    return Store(*rows, acl={r["id"]: {ME: MANAGE} for r in rows}, **kw)


# ------------------------------------------------------------- opening an app

def test_a_view_saved_before_apps_opens_as_itself():
    store = Store(row("v1", widgets=[{"i": "a", "type": "iframe"}], pin="agent-1"), acl={"v1": {ME: USE}})
    app = run(store, apps.get_app, "v1")["app"]
    assert [t["id"] for t in app["spec"]["tabs"]] == ["v1"]
    assert app["spec"]["tabs"][0]["widgets"] == [{"i": "a", "type": "iframe"}]
    assert app["spec"]["presentation"] == "workspace"
    assert app["pinned_agent_id"] == "agent-1"
    assert (app["access"], app["state"], app["published_version"]) == (USE, "published", 1)


def test_opening_an_app_writes_nothing():
    store = mine(row("v1", spec=three_tabs("v1")), drafts={"v1": draft_of(row("v1"), name="Draft")})
    run(store, apps.get_app, "v1")
    run(store, apps.get_app, "v1", mode="published")
    run(store, apps.app_history, app_id="v1")
    assert store.writes() == [] and not store.committed


def test_without_access_an_app_reads_exactly_as_missing():
    store = Store(row("v1"))
    hidden = refused(store, apps.get_app, "v1")
    missing = refused(store, apps.get_app, "nope")
    assert (hidden.status_code, hidden.detail) == (missing.status_code, missing.detail) == (404, "App not found")


def test_someone_with_can_use_sees_the_published_version_never_the_draft():
    store = Store(row("v1", name="Live"), drafts={"v1": draft_of(row("v1"), name="Halfway")},
                  acl={"v1": {OTHER: MANAGE, ME: USE}})
    app = run(store, apps.get_app, "v1", mode="draft")["app"]
    assert app["name"] == "Live" and app["has_draft"] is False and app["state"] == "published"


def test_a_manager_opens_the_draft_unless_they_ask_for_the_published_version():
    store = mine(row("v1", name="Live"), drafts={"v1": draft_of(row("v1"), name="Halfway")})
    opened = run(store, apps.get_app, "v1")
    assert opened["mode"] == "draft" and opened["app"]["name"] == "Halfway"
    assert opened["app"]["state"] == "published_with_draft" and opened["app"]["is_draft"] is True
    published = run(store, apps.get_app, "v1", mode="published")
    assert published["mode"] == "published" and published["app"]["name"] == "Live"


def test_a_view_never_published_is_missing_to_people_who_can_only_use_it():
    store = Store(drafts={"d1": draft_of(row("d1", owner=OTHER), name="Soon")},
                  acl={"d1": {OTHER: MANAGE, "*": USE}})
    assert refused(store, apps.get_app, "d1").status_code == 404
    app = run(store, apps.get_app, "d1", user=OTHER)["app"]
    assert (app["state"], app["published_version"], app["version"]) == ("draft_only", None, 0)
    assert refused(store, apps.get_app, "d1", user=OTHER, mode="published").status_code == 404


def test_an_archived_app_reads_as_missing():
    store = mine(row("v1"), archived={"v1"})
    assert refused(store, apps.get_app, "v1").status_code == 404


def test_an_unknown_mode_is_refused():
    assert refused(mine(row("v1")), apps.get_app, "v1", mode="staging").status_code == 400


def test_history_lists_published_versions_to_managers_only():
    store = Store(row("v1", version=1), row("v1", version=2), acl={"v1": {ME: MANAGE}})
    assert [h["version"] for h in run(store, apps.app_history, app_id="v1")["history"]] == [2, 1]
    viewer = Store(row("v1", version=1), acl={"v1": {ME: USE}})
    assert refused(viewer, apps.app_history, app_id="v1").status_code == 403
    assert refused(Store(row("v1")), apps.app_history, app_id="v1").status_code == 404


# ------------------------------------------------------------- the sidebar

def listed(store, **kw):
    return {a["id"]: a for a in run(store, apps.list_apps, **kw)["apps"]}


def test_the_sidebar_lists_what_is_shared_with_the_caller_and_says_how():
    store = Store(row("own", owner=ME), row("theirs", owner=OTHER), row("unshared", owner=OTHER),
                  acl={"own": {ME: MANAGE}, "theirs": {OTHER: MANAGE, ME: USE}, "unshared": {OTHER: MANAGE}})
    apps_ = listed(store)
    assert set(apps_) == {"own", "theirs"}
    assert (apps_["own"]["access"], apps_["own"]["shared_with_me"], apps_["own"]["owner"]) == (MANAGE, False, ME)
    assert (apps_["theirs"]["access"], apps_["theirs"]["shared_with_me"]) == (USE, True)
    assert apps_["theirs"]["sharing"] == "shared" and apps_["own"]["sharing"] == "private"


def test_views_shared_with_everyone_are_listed_to_everyone():
    store = Store(row("hub"), acl={"hub": {OTHER: MANAGE, "*": USE}})
    assert listed(store)["hub"]["sharing"] == "everyone"


def test_closed_and_archived_views_drop_out_of_the_sidebar():
    store = Store(row("a"), row("b"), row("c"), acl={k: {ME: USE} for k in "abc"},
                  hidden={(ME, "a")}, archived={"b"})
    assert set(listed(store)) == {"c"}


def test_managers_see_drafts_in_the_sidebar_and_others_only_published_views():
    store = Store(row("v1", name="Live"),
                  drafts={"v1": draft_of(row("v1"), name="Halfway"), "d1": draft_of(row("d1", owner=OTHER))},
                  acl={"v1": {OTHER: MANAGE, ME: USE}, "d1": {OTHER: MANAGE, ME: USE}})
    as_user = listed(store)
    assert set(as_user) == {"v1"} and as_user["v1"]["name"] == "Live"
    as_manager = listed(store, user=OTHER)
    assert as_manager["v1"]["name"] == "Halfway" and as_manager["d1"]["state"] == "draft_only"


def test_an_admin_manages_what_they_are_given_without_listing_everything():
    store = Store(row("given"), row("other"), acl={"given": {ME: USE}, "other": {OTHER: MANAGE}})
    apps_ = listed(store, admin=True)
    assert set(apps_) == {"given"} and apps_["given"]["access"] == MANAGE


def test_the_sidebar_carries_link_names_for_published_views_only():
    store = Store(row("p1"), drafts={"d1": draft_of(row("d1"))}, acl={"p1": {ME: MANAGE}, "d1": {ME: MANAGE}},
                  links={"supply-hub": "p1", "drafty": "d1"})
    apps_ = listed(store)
    assert apps_["p1"]["link"] == "supply-hub" and apps_["d1"]["link"] is None


def test_nothing_shared_is_an_empty_sidebar_without_a_query():
    store = Store(row("v1"))
    assert run(store, apps.list_apps)["apps"] == [] and store.statements == []


# ------------------------------------------------------- links by name

def test_a_view_opens_by_its_link_name_for_people_it_is_shared_with():
    store = Store(row("g1"), acl={"g1": {ME: USE}}, links={"supply-hub": "g1"})
    app = run(store, apps.get_app, "supply-hub")["app"]
    assert app["id"] == "g1" and app["link"] == "supply-hub"
    assert store.writes() == [], "opening by name writes nothing either"


def test_a_link_name_opens_nothing_for_anyone_else():
    store = Store(row("g1"), links={"supply-hub": "g1"})
    exc = refused(store, apps.get_app, "supply-hub")
    assert (exc.status_code, exc.detail) == (404, "App not found")


def test_an_old_link_name_still_opens_the_app_and_the_newest_is_handed_out():
    store = Store(row("g1"), acl={"g1": {ME: USE}}, links={"ops": "g1", "supply-hub": "g1"})
    assert run(store, apps.get_app, "ops")["app"]["link"] == "supply-hub"


def test_a_name_and_id_link_opens_the_app_it_ends_in():
    store = Store(row(UUID), acl={UUID: {ME: USE}})
    assert run(store, apps.get_app, f"q3-review-{UUID}")["app"]["id"] == UUID


# ------------------------------------------------------------ saving the draft

def test_saving_writes_the_draft_and_no_version():
    store = mine(row("v1", spec=three_tabs("v1"), version=4))
    result = run(store, apps.update_app, "v1", apps.AppUpdate(name="Renamed", is_locked=True))
    assert result == {"status": "success", "id": "v1", "state": "published_with_draft"}
    assert store.inserted() == [], "only publishing makes a version"
    draft = store.drafts[("app", "v1")]
    assert draft["payload"]["name"] == "Renamed" and draft["payload"]["is_locked"] == 1
    assert draft["base_version"] == 4, "a new draft starts from the newest published version"


def test_a_save_that_sends_no_spec_keeps_the_whole_spec_and_the_pin():
    store = mine(row("v1", spec=three_tabs("v1"), pin="agent-1"))
    run(store, apps.update_app, "v1", apps.AppUpdate(name="Renamed"))
    saved = store.draft("v1")
    assert json.loads(saved["spec_json"]) == app_spec.read_spec("v1", json.dumps(three_tabs("v1")), None)
    assert saved["pinned_agent_id"] == "agent-1", "an absent pin keeps the pin"
    run(store, apps.update_app, "v1", apps.AppUpdate(pinned_agent_id=""))
    assert store.draft("v1")["pinned_agent_id"] is None, "an empty pin clears it"


def test_a_second_save_continues_the_draft():
    store = mine(row("v1", version=2))
    run(store, apps.update_app, "v1", apps.AppUpdate(name="One"))
    run(store, apps.update_app, "v1", apps.AppUpdate(is_locked=True))
    assert store.draft("v1")["name"] == "One" and store.draft("v1")["is_locked"] == 1
    assert store.drafts[("app", "v1")]["base_version"] == 2


def test_saving_keeps_the_creator_on_the_row():
    store = Store(row("v1", owner=OTHER), acl={"v1": {OTHER: MANAGE, ME: MANAGE}})
    run(store, apps.update_app, "v1", apps.AppUpdate(name="x"))
    assert store.draft("v1")["username"] == OTHER


def test_saving_a_legacy_view_writes_its_spec_for_the_first_time():
    store = mine(row("v1", widgets=[{"i": "a", "type": "iframe"}]))
    run(store, apps.update_app, "v1", apps.AppUpdate(is_locked=True))
    spec = json.loads(store.draft("v1")["spec_json"])
    assert [t["id"] for t in spec["tabs"]] == ["v1"] and spec["tabs"][0]["widgets"] == [{"i": "a", "type": "iframe"}]


def test_saving_needs_can_manage():
    store = Store(row("v1"), acl={"v1": {ME: USE}})
    exc = refused(store, apps.update_app, "v1", apps.AppUpdate(name="x"))
    assert exc.status_code == 403 and store.writes() == []
    assert refused(Store(row("v1")), apps.update_app, "v1", apps.AppUpdate(name="x")).status_code == 404


def test_saving_a_spec_replaces_it_whole():
    store = mine(row("v1", spec=three_tabs("v1")))
    two = {"tabs": [{"id": "v1", "widgets": [{"i": "z", "type": "iframe"}]}, {"id": "t9", "name": "New"}],
           "presentation": "standalone"}
    run(store, apps.update_app, "v1", apps.AppUpdate(spec=two))
    saved = store.draft("v1")
    spec = json.loads(saved["spec_json"])
    assert [t["id"] for t in spec["tabs"]] == ["v1", "t9"] and spec["presentation"] == "standalone"
    assert json.loads(saved["widgets_json"]) == [{"i": "z", "type": "iframe"}], "widgets_json mirrors tab one, for a rollback"


def test_an_invalid_spec_is_refused_and_writes_nothing():
    store = mine(row("v1"))
    exc = refused(store, apps.update_app, "v1", apps.AppUpdate(spec={"tabs": []}))
    assert exc.status_code == 400 and "at least one tab" in exc.detail
    assert store.writes() == []


def test_every_app_the_api_hands_out_saves_back_unchanged():
    # The browser saves an app by sending back the spec it was given with one
    # tab's layout changed. If any row read leniently failed strict validation,
    # every drag on that app would start failing.
    long_id = "imported-" + "x" * 80
    rows = [
        row("v1", widgets=[{"i": "a", "type": "iframe", "x": 0, "y": None, "w": 4, "h": 4}]),
        row("v2", widgets=[{"i": "a", "type": "iframe"}, {"i": "a", "type": "iframe"}]),
        row(long_id, widgets=[{"i": "a", "type": "iframe"}]),
        row("v3", spec=three_tabs("v3"), pin="agent-1"),
        row("v4", spec={"tabs": [{"id": "t", "widgets": []}], "branding": {"title": "Ops"}, "nav": {"x": 1}}),
    ]
    for r in rows:
        store = mine(r)
        given = run(store, apps.get_app, r["id"])["app"]
        run(store, apps.update_app, r["id"], apps.AppUpdate(spec=given["spec"]))
        assert json.loads(store.draft(r["id"])["spec_json"]) == given["spec"], r["id"]


def test_an_app_says_when_it_was_last_saved():
    import datetime
    saved_at = datetime.datetime(2026, 10, 5, 12, 30)
    app = run(mine(row("v1", timestamp=saved_at)), apps.get_app, "v1")["app"]
    assert app["timestamp"] == "2026-10-05T12:30:00"


# ------------------------------------------------------------- creating

def test_creating_an_app_writes_a_draft_and_makes_the_caller_its_owner():
    store = Store()
    result = run(store, apps.create_app, apps.AppCreate(id="new", name="Mine"))
    assert result == {"status": "success", "id": "new", "state": "draft_only"}
    assert store.inserted() == [], "nothing is published until someone publishes it"
    saved = store.draft("new")
    assert saved["username"] == ME and store.drafts[("app", "new")]["base_version"] is None
    spec = json.loads(saved["spec_json"])
    assert [t["id"] for t in spec["tabs"]] == ["new"] and spec["tabs"][0]["widgets"] == []
    assert store.granted == [("app", "new", ME, True)], "the owner is granted after the content commit"


def test_creating_an_app_over_an_existing_id_is_refused():
    for store in (mine(row("v1")), Store(drafts={"v1": draft_of(row("v1"))})):
        assert refused(store, apps.create_app, apps.AppCreate(id="v1", name="Dup")).status_code == 409
        assert store.writes() == [] and store.granted == []


# ------------------------------------------------------------- publishing

def test_publishing_makes_the_draft_the_next_version_and_names_it():
    store = mine(row("v1", version=3), drafts={"v1": draft_of(row("v1"), name="Supply Hub")})
    result = run(store, apps.publish_app, "v1", apps.PublishRequest())
    assert result == {"status": "success", "version": 4}
    newest = store.versions("v1")[-1]
    assert (newest["version"], newest["name"], newest["published_by"]) == (4, "Supply Hub", ME)
    assert ("app", "v1") not in store.drafts and store.links == {"supply-hub": "v1"}
    assert store.committed


def test_publishing_with_nothing_to_publish_is_refused():
    store = mine(row("v1"))
    exc = refused(store, apps.publish_app, "v1", apps.PublishRequest())
    assert exc.status_code == 409 and store.inserted() == []


def test_publishing_needs_can_manage():
    store = Store(row("v1"), drafts={"v1": draft_of(row("v1"))}, acl={"v1": {ME: USE}})
    assert refused(store, apps.publish_app, "v1", apps.PublishRequest()).status_code == 403
    assert store.inserted() == [] and ("app", "v1") in store.drafts


def test_widgets_confirmed_in_the_dialog_are_published_with_the_view():
    spec = app_spec.legacy_spec("v1", [{"i": "a", "type": CUSTOM}])
    store = mine(row("v1", spec=spec), drafts={
        "v1": draft_of(row("v1", spec=spec), name="Next"),
        ("widget", CUSTOM): {"payload": {"name": "Margins", "tsx_code": "y"}, "base_version": 1,
                             "updated_by": ME, "updated_at": None},
    }, widgets=[(CUSTOM, "Margins", 1)])
    store.acl[("widget", CUSTOM)] = {ME: MANAGE}
    run(store, apps.publish_app, "v1",
        apps.PublishRequest(include=[apps.PublishItem(object_type="widget", object_id=CUSTOM)]))
    assert [r["version"] for r in store.versions(CUSTOM, "widgets")] == [1, 2]
    assert store.versions(CUSTOM, "widgets")[-1]["is_certified"] == 0, "a new version has had no review"
    assert ("widget", CUSTOM) not in store.drafts and store.versions("v1")[-1]["version"] == 2


def test_a_widget_the_caller_cannot_manage_is_not_published_with_the_view():
    store = mine(row("v1"), drafts={
        "v1": draft_of(row("v1")),
        ("widget", CUSTOM): {"payload": {"name": "Margins"}, "base_version": None, "updated_by": OTHER, "updated_at": None},
    })
    store.acl[("widget", CUSTOM)] = {ME: USE}
    exc = refused(store, apps.publish_app, "v1",
                  apps.PublishRequest(include=[apps.PublishItem(object_type="widget", object_id=CUSTOM)]))
    assert exc.status_code == 403 and store.inserted() == [] and store.inserted("widgets") == []


def test_only_widgets_and_agents_ride_along():
    store = mine(row("v1"), drafts={"v1": draft_of(row("v1"))})
    exc = refused(store, apps.publish_app, "v1",
                  apps.PublishRequest(include=[apps.PublishItem(object_type="app", object_id="v2")]))
    assert exc.status_code == 400


def test_a_shared_view_with_an_uncertified_widget_on_any_tab_is_refused_when_configured():
    spec = three_tabs("v1")
    store = Store(row("v1", owner=ME, spec=spec), drafts={"v1": draft_of(row("v1", owner=ME, spec=spec))},
                  acl={"v1": {ME: MANAGE, OTHER: USE}}, widgets=[(CUSTOM, "Margins", 0)])
    exc = refused(store, apps.publish_app, "v1", apps.PublishRequest(), certified_only=True)
    assert exc.status_code == 400 and "Margins" in exc.detail, "the uncertified widget is on tab two"
    assert store.inserted() == [] and ("app", "v1") in store.drafts


def test_the_certified_check_rolls_back_widgets_published_with_the_view():
    spec = app_spec.legacy_spec("v1", [{"i": "a", "type": CUSTOM}])
    store = Store(row("v1", owner=ME, spec=spec), widgets=[(CUSTOM, "Margins", 1)],
                  drafts={"v1": draft_of(row("v1", owner=ME, spec=spec)),
                          ("widget", CUSTOM): {"payload": {"name": "Margins"}, "base_version": 1,
                                               "updated_by": ME, "updated_at": None}},
                  acl={"v1": {ME: MANAGE, "*": USE}, ("widget", CUSTOM): {ME: MANAGE}})
    exc = refused(store, apps.publish_app, "v1", certified_only=True,
                  body=apps.PublishRequest(include=[apps.PublishItem(object_type="widget", object_id=CUSTOM)]))
    assert exc.status_code == 400
    assert [r["version"] for r in store.versions(CUSTOM, "widgets")] == [1], "the widget's publish rolled back too"
    assert ("widget", CUSTOM) in store.drafts


def test_a_private_view_is_not_held_to_certification():
    spec = three_tabs("v1")
    store = mine(row("v1", owner=ME, spec=spec), drafts={"v1": draft_of(row("v1", owner=ME, spec=spec))},
                 widgets=[(CUSTOM, "Margins", 0)])
    assert run(store, apps.publish_app, "v1", apps.PublishRequest(), certified_only=True)["version"] == 2


def test_a_view_shared_with_everyone_is_published_as_global_for_a_rollback():
    store = Store(row("v1", owner=ME), drafts={"v1": draft_of(row("v1", owner=ME))},
                  acl={"v1": {ME: MANAGE, "*": USE}})
    run(store, apps.publish_app, "v1", apps.PublishRequest())
    assert store.versions("v1")[-1]["is_global"] == 1


def test_the_preflight_lists_what_people_could_not_see_yet():
    spec = app_spec.legacy_spec("v1", [{"i": "a", "type": CUSTOM}, {"i": "b", "type": SECOND}])
    spec["tabs"][0]["pinned_agent_id"] = "agent-1"
    store = Store(row("v1", owner=ME, spec=spec), widgets=[(CUSTOM, "Margins", 1)],
                  drafts={"v1": draft_of(row("v1", owner=ME, spec=spec)),
                          ("widget", CUSTOM): {"payload": {"name": "Margins v2"}, "base_version": 1,
                                               "updated_by": ME, "updated_at": None},
                          ("widget", SECOND): {"payload": {"name": "Brand new"}, "base_version": None,
                                               "updated_by": OTHER, "updated_at": None},
                          ("agent", "agent-1"): {"payload": {"name": "Helper"}, "base_version": None,
                                                 "updated_by": ME, "updated_at": None}},
                  acl={"v1": {ME: MANAGE}, ("widget", CUSTOM): {ME: MANAGE}, ("widget", SECOND): {OTHER: MANAGE},
                       ("agent", "agent-1"): {ME: MANAGE}})
    result = run(store, apps.publish_preflight, "v1")
    got = {(i["object_id"], i["reason"], i["can_publish"]) for i in result["items"]}
    assert got == {(CUSTOM, "unpublished_changes", True), (SECOND, "never_published", False),
                   ("agent-1", "never_published", True)}
    assert result["blocking"] == []
    assert store.writes() == []


def test_the_preflight_names_uncertified_widgets_when_they_would_block():
    spec = three_tabs("v1")
    store = Store(row("v1", owner=ME, spec=spec), widgets=[(CUSTOM, "Margins", 0)],
                  drafts={"v1": draft_of(row("v1", owner=ME, spec=spec))},
                  acl={"v1": {ME: MANAGE, OTHER: USE}})
    result = run(store, apps.publish_preflight, "v1", certified_only=True)
    assert {(i["object_id"], i["reason"]) for i in result["items"]} == {(CUSTOM, "uncertified")}
    assert len(result["blocking"]) == 1 and "Margins" in result["blocking"][0]
    quiet = run(store, apps.publish_preflight, "v1")
    assert quiet == {"items": [], "blocking": []}


def test_the_preflight_says_when_there_is_nothing_to_publish():
    result = run(mine(row("v1")), apps.publish_preflight, "v1")
    assert result["blocking"] == ["There are no unpublished changes to publish."]


# ------------------------------------------------------- discard and revert

def test_discarding_goes_back_to_the_published_version():
    store = mine(row("v1"), drafts={"v1": draft_of(row("v1"), name="Halfway")})
    assert run(store, apps.discard_draft, "v1")["discarded"] is True
    assert ("app", "v1") not in store.drafts and len(store.versions("v1")) == 1


def test_a_view_never_published_is_deleted_not_discarded():
    store = Store(drafts={"d1": draft_of(row("d1"))}, acl={"d1": {ME: MANAGE}})
    assert refused(store, apps.discard_draft, "d1").status_code == 409
    assert ("app", "d1") in store.drafts


def test_reverting_makes_an_old_version_the_draft():
    store = mine(row("v1", version=1, name="First"), row("v1", version=2, name="Second"))
    assert run(store, apps.revert_app, "v1", apps.RevertRequest(version=1))["state"] == "published_with_draft"
    assert store.draft("v1")["name"] == "First" and store.drafts[("app", "v1")]["base_version"] == 2
    assert len(store.versions("v1")) == 2, "reverting publishes nothing"
    assert refused(store, apps.revert_app, "v1", apps.RevertRequest(version=9)).status_code == 404


# ------------------------------------------------------- closing and old links

def test_closing_a_shared_view_hides_it_for_the_caller_only():
    store = Store(row("v1"), acl={"v1": {OTHER: MANAGE, ME: USE}})
    run(store, apps.hide_app, "v1")
    assert store.hidden == {(ME, "v1")} and "v1" in listed(store, user=OTHER)
    run(store, apps.unhide_app, "v1")
    assert store.hidden == set()


def test_closing_a_view_one_cannot_see_is_not_found():
    store = Store(row("v1"))
    assert refused(store, apps.hide_app, "v1").status_code == 404 and store.writes() == []


def test_subscribing_only_checks_the_caller_can_use_the_view():
    store = Store(row("v1"), acl={"v1": {ME: USE}})
    assert run(store, apps.subscribe_app, "v1")["id"] == "v1"
    assert refused(Store(row("v1")), apps.subscribe_app, "v1").status_code == 404
    assert store.writes() == []


# ------------------------------------------------- the widgets an app places

def library_queries(store):
    return [p for s, p in store.statements if s.startswith("SELECT id, version, name, description")]


def ids(result):
    return [w["id"] for w in result["widgets"]]


def test_an_app_asks_the_library_for_what_its_tabs_place_and_nothing_else():
    spec = three_tabs("v1")
    spec["tabs"][2]["widgets"].append({"i": "d", "type": CUSTOM, "props": {"_version": 3}})
    store = Store(row("v1", spec=spec), acl={"v1": {ME: USE}},
                  library=[("iframe", "General"), (CUSTOM, "General"), ("unplaced", "General")])
    assert ids(run(store, apps.app_widgets, "v1")) == ["iframe", CUSTOM]
    (params,) = library_queries(store)
    assert params == ([f"{CUSTOM}@3"], ["iframe", CUSTOM]), "a pinned version on tab three carries its source"
    assert store.writes() == []


def test_can_use_on_the_view_is_enough_to_see_its_widgets():
    store = Store(row("v1", widgets=[{"i": "a", "type": "iframe"}, {"i": "b", "type": CUSTOM}]),
                  acl={"v1": {ME: USE}}, library=[("iframe", "General"), (CUSTOM, "Finance")])
    assert ids(run(store, apps.app_widgets, "v1")) == ["iframe", CUSTOM]


def test_an_apps_widgets_follow_the_apps_read_rule():
    placed = [{"i": "a", "type": "iframe"}]
    store = Store(row("g1", widgets=placed), row("v2", widgets=placed), archived={"v2"},
                  acl={"v2": {ME: MANAGE}}, library=[("iframe", "General")])
    assert refused(store, apps.app_widgets, "g1").status_code == 404
    assert refused(store, apps.app_widgets, "v2").status_code == 404
    assert library_queries(store) == [], "a refused app says nothing about what it holds"


def test_in_draft_mode_a_manager_also_gets_the_widget_drafts_they_manage():
    spec = app_spec.legacy_spec("v1", [{"i": "a", "type": CUSTOM}, {"i": "b", "type": SECOND}])
    store = mine(row("v1", spec=spec), library=[(CUSTOM, "General")], drafts={
        ("widget", CUSTOM): {"payload": {"name": "Mine", "tsx_code": "draft"}, "base_version": 1,
                             "updated_by": ME, "updated_at": None},
        ("widget", SECOND): {"payload": {"name": "Theirs", "tsx_code": "secret"}, "base_version": None,
                             "updated_by": OTHER, "updated_at": None},
    })
    store.acl[("widget", CUSTOM)] = {ME: MANAGE}
    store.acl[("widget", SECOND)] = {OTHER: MANAGE, ME: USE}
    rows = run(store, apps.app_widgets, "v1")["widgets"]
    drafts_ = [r for r in rows if r.get("is_draft")]
    assert [(r["id"], r["version"], r["tsx_code"], r["is_latest"]) for r in drafts_] == [(CUSTOM, 0, "draft", False)]
    assert [r for r in run(store, apps.app_widgets, "v1", mode="published")["widgets"] if r.get("is_draft")] == []


def test_an_empty_app_needs_no_library_query():
    store = mine(row("v1"))
    assert run(store, apps.app_widgets, "v1")["widgets"] == []
    assert library_queries(store) == []


# ------------------------------------------------------- composing from views

def test_composing_copies_views_into_one_new_draft_and_leaves_them_alone():
    store = Store(row("v1", owner=ME, widgets=[{"i": "a", "type": "iframe"}], pin="agent-1"),
                  row("g1", widgets=[{"i": "b", "type": "iframe"}]),
                  acl={"v1": {ME: MANAGE}, "g1": {"*": USE}})
    result = run(store, apps.compose_app, apps.AppCompose(name="Hub", source_ids=["v1", "g1", "v1"]))
    new_id = result["id"]
    saved = store.draft(new_id)
    spec = json.loads(saved["spec_json"])
    assert result["tabs"] == 2 and result["state"] == "draft_only", "a repeated source is one tab"
    assert [t["name"] for t in spec["tabs"]] == ["App v1", "App g1"]
    assert spec["tabs"][0]["pinned_agent_id"] == "agent-1"
    assert saved["username"] == ME and new_id not in ("v1", "g1")
    assert len(store.writes()) == 1, "the sources are copied, not changed or archived"
    assert store.granted == [("app", new_id, ME, True)]


def test_composing_refuses_a_view_the_caller_cannot_open():
    store = Store(row("v1", owner=ME), row("g1"), acl={"v1": {ME: MANAGE}})
    exc = refused(store, apps.compose_app, apps.AppCompose(name="Hub", source_ids=["v1", "g1"]))
    assert exc.status_code == 404 and "g1" in exc.detail
    assert store.writes() == [] and store.granted == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
