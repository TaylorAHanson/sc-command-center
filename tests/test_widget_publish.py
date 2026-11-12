"""Tests for the widget library's sharing and publishing rules.

What matters is who sees what: people who can use a widget get its published
versions and nothing a manager is halfway through; managers also get their
draft; a view shared with someone lends them exactly the versions it places.
The routes run against a small in-memory fake of the statements they issue,
with the access list stubbed, so no Databricks or Postgres is needed.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from fastapi import HTTPException
    from routes import custom_widgets as cw
    from services import access
    from services import activity
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_widget_publish: {e}")
    sys.exit(0)

WIDGET_COLUMNS = ["id", "version", "name", "description", "category", "domain", "default_w", "default_h",
                  "tsx_code", "configuration_mode", "config_schema", "data_source_type", "data_source",
                  "help_text", "open_in_new_tab_link", "layout_kind", "is_executable", "snapshot",
                  "created_by", "is_certified", "is_deprecated", "timestamp", "published_by", "published_at"]
NOW = datetime.datetime(2026, 11, 9)


# --------------------------------------------------------------------- fakes

class FakeCursor:
    """The statements custom_widgets.py and drafts.py issue, over in-memory tables."""

    def __init__(self, db):
        self.db = db
        self.description = None
        self._result = []
        self.rowcount = 0

    def _set(self, names, rows):
        self.description = [(n,) for n in names]
        self._result = [tuple(r.get(n) for n in names) for r in rows]

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        params = list(params or ())
        widgets, held = self.db["widgets"], self.db["drafts"]
        if s.startswith("SELECT payload, base_version"):
            d = held.get(tuple(params))
            self._set(["payload", "base_version", "updated_by", "updated_at"], [d] if d else [])
        elif s.startswith("SELECT object_id, payload"):
            ids = params[1] if len(params) > 1 else None
            rows = [{"object_id": k[1], **v} for k, v in held.items()
                    if k[0] == params[0] and (ids is None or k[1] in ids)]
            self._set(["object_id", "payload", "base_version", "updated_by", "updated_at"], rows)
        elif s.startswith("INSERT INTO object_drafts"):
            t, i, payload, base, user = params
            held[(t, i)] = {"payload": payload.adapted, "base_version": base, "updated_by": user, "updated_at": NOW}
        elif s.startswith("DELETE FROM object_drafts"):
            self.rowcount = 1 if held.pop(tuple(params), None) else 0
        elif s.startswith("UPDATE object_drafts SET payload = jsonb_set"):
            snapshot, t, i = params
            d = held.get((t, i))
            self.rowcount = 1 if d else 0
            if d:
                d["payload"] = {**d["payload"], "snapshot": snapshot}
        elif s.startswith("SELECT * FROM widgets LIMIT 0"):
            self._set(WIDGET_COLUMNS, [])
        elif s.startswith("SELECT * FROM widgets WHERE id = %s AND version = %s"):
            self._set(WIDGET_COLUMNS, [r for r in widgets if (r["id"], r["version"]) == tuple(params)])
        elif s.startswith("SELECT * FROM widgets WHERE id = %s"):
            rows = [r for r in widgets if r["id"] == params[0] and not r.get("is_deprecated")]
            self._set(WIDGET_COLUMNS, sorted(rows, key=lambda r: -r["version"])[:1])
        elif s.startswith("SELECT 1 FROM widgets WHERE id = %s"):
            self._set(["one"], [{"one": 1}] if any(r["id"] == params[0] for r in widgets) else [])
        elif s.startswith("SELECT COALESCE(MAX(version), 0)"):
            versions = [r["version"] for r in widgets if r["id"] == params[0]]
            self._set(["v"], [{"v": max(versions or [0])}])
        elif s.startswith("INSERT INTO widgets"):
            names = s[s.index("(") + 1:s.index(")")].split(", ")
            row = {n: None for n in WIDGET_COLUMNS}
            row.update(zip(names, list(params) + [NOW]))
            row["timestamp"] = NOW
            widgets.append(row)
        elif s.startswith("UPDATE widgets SET is_certified"):
            flag, i, v = params
            hit = [r for r in widgets if (r["id"], r["version"]) == (i, v) and not r.get("is_deprecated")]
            for r in hit:
                r["is_certified"] = flag
            self.rowcount = len(hit)
        elif s.startswith("UPDATE widgets SET is_deprecated = 1"):
            hit = [r for r in widgets if r["id"] == params[0]]
            for r in hit:
                r["is_deprecated"] = 1
            self.rowcount = len(hit)
        elif s.startswith("UPDATE widgets SET snapshot"):
            snapshot, i, v = params
            for r in widgets:
                if (r["id"], r["version"]) == (i, v):
                    r["snapshot"] = snapshot
        elif s.startswith("UPDATE widgets SET created_by"):
            me, i, *_ = params
            hit = [r for r in widgets if r["id"] == i and r.get("created_by") in (None, "", "dev", "unknown")]
            for r in hit:
                r["created_by"] = me
            self.rowcount = len(hit)
        else:
            raise AssertionError(f"unexpected SQL: {s}")

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None


class FakeConn:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return FakeCursor(self.db)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class World:
    """One fake deployment: the tables, the access list, and who is calling."""

    def __init__(self, me="ana@example.com", admin=False):
        self.db = {"widgets": [], "drafts": {}}
        self.acl = {}  # widget id -> {username: level}
        self.me, self.admin = me, admin
        self.lent = (set(), set())
        self.activity = []  # what activity.record was given
        self._saved = {}

    def publish(self, widget_id, version, **cols):
        row = {n: None for n in WIDGET_COLUMNS}
        row.update({"id": widget_id, "version": version, "name": widget_id.title(),
                    "tsx_code": f"{widget_id} v{version}", "created_by": "ana@example.com",
                    "is_certified": 0, "is_deprecated": 0, "timestamp": NOW, **cols})
        self.db["widgets"].append(row)

    def library_rows(self, c, ids=None, pinned=()):
        live = [r for r in self.db["widgets"] if not r["is_deprecated"] and (ids is None or r["id"] in ids)]
        newest = {}
        for r in live:
            newest[r["id"]] = max(newest.get(r["id"], 0), r["version"])
        out = []
        for r in live:
            is_latest = r["version"] == newest[r["id"]]
            row = {k: r.get(k) for k in cw.LIBRARY_FIELDS}
            row.update(is_latest=is_latest, has_snapshot=bool(r.get("snapshot")),
                       tsx_code=r["tsx_code"] if is_latest or f"{r['id']}@{r['version']}" in pinned else None)
            out.append(row)
        return out

    def levels(self, ids=None):
        held = {i: by.get(self.me) for i, by in self.acl.items() if by.get(self.me)}
        return held if ids is None else {i: lv for i, lv in held.items() if i in ids}

    def __enter__(self):
        me = access.Caller(self.me, (), self.admin)
        patches = {
            (cw, "get_db_connection"): lambda env="dev", pooled=True, physical=False: FakeConn(self.db),
            (cw, "_get_current_username"): lambda w: self.me,
            (cw, "library_rows"): self.library_rows,
            (cw, "lent_by_views"): lambda c, who: self.lent,
            (access, "caller"): lambda w: me,
            (access, "grants_for"): lambda who, t: self.levels(),
            (access, "levels_for"): lambda who, t, ids: self.levels(set(ids)),
            (access, "level_for"): lambda who, t, i: access.MANAGE if self.admin else self.levels().get(i),
            (access, "grant_owner"): lambda t, i, u: self.acl.setdefault(i, {}).update({u: access.MANAGE}),
            (access, "delete_acl"): lambda t, i: self.acl.pop(i, None),
            (activity, "record"): lambda *args, **kwargs: self.activity.append(args),
            (access, "acl_summaries"): lambda t=None: {
                (t, i): {"entries": len(by), "everyone": "*" in by} for i, by in self.acl.items()},
        }
        for (module, name), fake in patches.items():
            self._saved[(module, name)] = getattr(module, name)
            setattr(module, name, fake)
        return self

    def __exit__(self, *exc):
        for (module, name), real in self._saved.items():
            setattr(module, name, real)


def expect(status, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except HTTPException as e:
        assert e.status_code == status, (e.status_code, e.detail)
        return e
    raise AssertionError(f"expected a {status}")


def ids_of(rows):
    return sorted((r["id"], r["version"]) for r in rows)


# --------------------------------------------------------------------- pure rules

def test_a_save_keeps_whatever_the_body_leaves_out():
    held = {"name": "Stock", "tsx_code": "old", "domain": "Ops", "default_w": 4, "created_by": "ana",
            "snapshot": "png", "layout_kind": "page", "is_executable": 1}
    out = cw.widget_payload({"tsx_code": "new"}, held, "bo")
    assert out["tsx_code"] == "new" and out["name"] == "Stock" and out["default_w"] == 4
    assert out["snapshot"] == "png" and out["layout_kind"] == "page" and out["is_executable"] == 1


def test_the_author_is_never_taken_from_the_body():
    assert cw.widget_payload({"created_by": "mallory"}, {"created_by": "ana"}, "bo")["created_by"] == "ana"
    assert cw.widget_payload({"created_by": "mallory"}, None, "bo")["created_by"] == "bo"


def test_a_new_widget_starts_from_the_defaults_and_accepts_camel_case():
    out = cw.widget_payload({"defaultW": 3, "configurationMode": "custom", "isExecutable": True}, None, "bo")
    assert out["default_w"] == 3 and out["default_h"] == 6 and out["configuration_mode"] == "custom"
    assert out["is_executable"] == 1 and out["layout_kind"] == "card" and out["category"] == "Custom"


def test_a_parsed_config_schema_is_stored_as_text():
    # Publish copies the draft into a TEXT column, where a list can't go.
    out = cw.widget_payload({"configSchema": [{"key": "k"}]}, None, "bo")
    assert out["config_schema"] == '[{"key": "k"}]'


def test_sharing_summaries_mirror_the_browser():
    assert cw.summary_of(None) == "private"
    assert cw.summary_of({"entries": 1, "everyone": False}) == "private"
    assert cw.summary_of({"entries": 2, "everyone": False}) == "shared"
    assert cw.summary_of({"entries": 2, "everyone": True}) == "everyone"


def test_a_draft_row_is_version_zero_with_its_whole_source():
    draft = {"payload": {"name": "New", "tsx_code": "draft code"}, "base_version": 2,
             "updated_by": "bo", "updated_at": NOW}
    row = cw.draft_row("w1", draft, {"id": "w1", "version": 2, "name": "Old", "domain": "Ops",
                                     "is_certified": 1, "tsx_code": "v2"})
    assert row["version"] == 0 and row["is_draft"] is True and row["tsx_code"] == "draft code"
    assert row["name"] == "New" and row["domain"] == "Ops"
    # The plain id stays the published version, and a draft has not been reviewed.
    assert row["is_latest"] is False and row["is_certified"] == 0
    assert cw.draft_row("w9", draft, None)["is_latest"] is True


def test_views_lend_what_they_place_and_the_versions_they_pin():
    spec = {"id": "v1", "tabs": [{"id": "t1", "name": "One", "widgets": [
        {"i": "a", "type": "w1", "props": {}},
        {"i": "b", "type": "w2", "props": {"_version": 3}},
    ]}]}
    latest, pins = cw.view_grants([spec])
    assert latest == {"w1", "w2"} and pins == {"w2@3"}


def _rows():
    return [
        {"id": "w1", "version": 2, "is_latest": True, "tsx_code": "v2"},
        {"id": "w1", "version": 1, "is_latest": False, "tsx_code": None},
        {"id": "w2", "version": 5, "is_latest": True, "tsx_code": "w2"},
        {"id": "w2", "version": 3, "is_latest": False, "tsx_code": "w2 v3"},
    ]


def test_users_see_published_versions_and_never_a_draft():
    pending = {"w1": {"payload": {"tsx_code": "wip"}, "base_version": 2}}
    out = cw.shape_rows(_rows(), pending, {"w1": access.USE})
    assert ids_of(out) == [("w1", 1), ("w1", 2)]
    assert all(r["access"] == "USE" and r["state"] == "published" and not r["is_draft"] for r in out)


def test_managers_get_one_extra_row_for_their_draft():
    pending = {"w1": {"payload": {"tsx_code": "wip"}, "base_version": 2}}
    out = cw.shape_rows(_rows(), pending, {"w1": access.MANAGE}, sharing={"w1": "shared"})
    assert ids_of(out) == [("w1", 0), ("w1", 1), ("w1", 2)]
    draft = next(r for r in out if r["is_draft"])
    assert draft["tsx_code"] == "wip" and draft["is_latest"] is False
    assert all(r["state"] == "published_with_draft" and r["sharing"] == "shared" for r in out)


def test_a_draft_only_widget_is_one_row_and_the_latest():
    pending = {"w9": {"payload": {"name": "New", "tsx_code": "x"}, "base_version": None}}
    out = cw.shape_rows([], pending, {"w9": access.MANAGE})
    assert len(out) == 1 and out[0]["is_latest"] is True and out[0]["state"] == "draft_only"
    assert out[0]["published_version"] is None


def test_an_admin_manages_everything():
    pending = {"w9": {"payload": {"tsx_code": "x"}, "base_version": None}}
    out = cw.shape_rows(_rows(), pending, None)
    assert {r["access"] for r in out} == {"MANAGE"} and ("w9", 0) in ids_of(out)


def test_a_view_lends_only_the_latest_and_its_pins():
    out = cw.shape_rows(_rows(), {}, {}, lent_latest={"w1", "w2"}, lent_pins={"w2@3"})
    assert ids_of(out) == [("w1", 2), ("w2", 3), ("w2", 5)]
    assert all(r["in_library"] is False and r["access"] is None and "sharing" not in r for r in out)


def test_nothing_reachable_yields_nothing():
    pending = {"w1": {"payload": {"tsx_code": "wip"}, "base_version": 2}}
    assert cw.shape_rows(_rows(), pending, {}) == []


# --------------------------------------------------------------------- flows

def test_a_new_widget_is_a_draft_its_creator_manages():
    with World() as world:
        out = cw.create_custom_widget({"name": "Stock", "tsx_code": "x"}, w=None)
        assert out["state"] == "draft_only" and out["created_by"] == "ana@example.com"
        assert world.acl[out["id"]] == {"ana@example.com": "MANAGE"}
        rows = cw.get_custom_widgets(w=None)["widgets"]
        assert [(r["id"], r["is_draft"], r["is_latest"]) for r in rows] == [(out["id"], True, True)]


def test_someone_else_never_sees_another_persons_draft():
    with World() as world:
        new = cw.create_custom_widget({"name": "Stock", "tsx_code": "x"}, w=None)["id"]
        world.me = "bo@example.com"
        assert cw.get_custom_widgets(w=None)["widgets"] == []
        expect(404, cw.get_widget_draft, new, w=None)


def test_naming_a_widget_you_cannot_manage_is_refused():
    with World(me="bo@example.com") as world:
        world.publish("w1", 1)
        world.acl["w1"] = {"ana@example.com": "MANAGE", "bo@example.com": "USE"}
        expect(403, cw.create_custom_widget, {"id": "w1", "name": "Mine", "tsx_code": "x"}, w=None)
        expect(403, cw.update_custom_widget, "w1", {"name": "Mine", "tsx_code": "x"}, w=None)


def test_a_retired_id_cannot_be_taken_over():
    with World(me="bo@example.com") as world:
        world.publish("w1", 1, is_deprecated=1)
        world.acl["w1"] = {"ana@example.com": "MANAGE"}
        expect(404, cw.create_custom_widget, {"id": "w1", "name": "Mine", "tsx_code": "x"}, w=None)
        assert not world.db["drafts"]


def test_saving_changes_nothing_users_see_until_publish():
    with World() as world:
        world.publish("w1", 1)
        world.acl["w1"] = {"ana@example.com": "MANAGE", "bo@example.com": "USE"}
        assert cw.update_custom_widget("w1", {"tsx_code": "v2 code"}, w=None)["state"] == "published_with_draft"

        world.me = "bo@example.com"
        rows = cw.get_custom_widgets(w=None)["widgets"]
        assert [(r["version"], r["tsx_code"]) for r in rows] == [(1, "w1 v1")]
        assert cw.get_widget_draft("w1", w=None)["draft"] is None

        world.me = "ana@example.com"
        out = cw.publish_widget("w1", w=None)
        assert out["version"] == 2 and out["state"] == "published"

        world.me = "bo@example.com"
        latest = next(r for r in cw.get_custom_widgets(w=None)["widgets"] if r["is_latest"])
        assert latest["version"] == 2 and latest["tsx_code"] == "v2 code" and latest["name"] == "W1"


def test_the_draft_endpoint_says_where_a_widget_stands():
    with World() as world:
        world.publish("w1", 1)
        world.acl["w1"] = {"ana@example.com": "MANAGE"}
        out = cw.get_widget_draft("w1", w=None)
        assert out["draft"] is None and out["published_version"] == 1 and out["state"] == "published"
        cw.update_custom_widget("w1", {"tsx_code": "wip"}, w=None)
        out = cw.get_widget_draft("w1", w=None)
        assert out["draft"]["tsx_code"] == "wip" and out["draft"]["is_draft"] is True
        assert out["state"] == "published_with_draft" and out["access"] == "MANAGE"


def test_publish_rechecks_the_draft_for_safety():
    with World() as world:
        world.publish("w1", 1)
        world.acl["w1"] = {"ana@example.com": "MANAGE"}
        # A draft that arrived without passing a save, as an import's would.
        world.db["drafts"][("widget", "w1")] = {
            "payload": {"name": "x", "tsx_code": "fetch('https://evil.example.com')"},
            "base_version": 1, "updated_by": "ana", "updated_at": NOW}
        expect(400, cw.publish_widget, "w1", w=None)
        assert len(world.db["widgets"]) == 1


def test_discard_goes_back_to_the_published_version():
    with World() as world:
        world.publish("w1", 1)
        world.acl["w1"] = {"ana@example.com": "MANAGE"}
        cw.update_custom_widget("w1", {"tsx_code": "wip"}, w=None)
        assert cw.discard_widget_draft("w1", w=None)["discarded"] is True
        assert cw.get_widget_draft("w1", w=None)["state"] == "published"


def test_discarding_a_never_published_widget_is_refused():
    # Its draft is the whole widget; Delete is the way to remove it.
    with World() as world:
        new = cw.create_custom_widget({"name": "Stock", "tsx_code": "x"}, w=None)["id"]
        expect(409, cw.discard_widget_draft, new, w=None)


def test_revert_puts_an_old_version_in_the_draft():
    with World() as world:
        world.publish("w1", 1)
        world.publish("w1", 2)
        world.acl["w1"] = {"ana@example.com": "MANAGE"}
        assert cw.revert_widget("w1", cw.VersionBody(version=1), w=None)["state"] == "published_with_draft"
        assert cw.get_widget_draft("w1", w=None)["draft"]["tsx_code"] == "w1 v1"


def test_certifying_is_for_managers_and_defaults_to_the_latest():
    with World() as world:
        world.publish("w1", 1)
        world.publish("w1", 2)
        world.acl["w1"] = {"ana@example.com": "MANAGE", "bo@example.com": "USE"}
        assert cw.certify_widget("w1", cw.CertifyBody(), w=None)["version"] == 2
        assert [r["is_certified"] for r in world.db["widgets"]] == [0, 1]
        cw.certify_widget("w1", cw.CertifyBody(version=2, certified=False), w=None)
        assert world.db["widgets"][1]["is_certified"] == 0
        world.me = "bo@example.com"
        expect(403, cw.certify_widget, "w1", cw.CertifyBody(), w=None)


def test_certifying_an_unpublished_widget_is_a_conflict():
    with World() as world:
        new = cw.create_custom_widget({"name": "Stock", "tsx_code": "x"}, w=None)["id"]
        expect(409, cw.certify_widget, new, cw.CertifyBody(), w=None)


def test_deleting_needs_manage_and_retires_every_version():
    with World(me="bo@example.com") as world:
        world.publish("w1", 1)
        world.acl["w1"] = {"ana@example.com": "MANAGE", "bo@example.com": "USE"}
        expect(403, cw.delete_custom_widget, "w1", w=None)
        world.me = "ana@example.com"
        cw.update_custom_widget("w1", {"tsx_code": "wip"}, w=None)
        cw.delete_custom_widget("w1", w=None)
        assert world.db["widgets"][0]["is_deprecated"] == 1 and not world.db["drafts"]
        # It was published, so views that pinned it may still name it; the list stays.
        assert "w1" in world.acl


def test_deleting_a_draft_only_widget_removes_its_access_list():
    with World() as world:
        new = cw.create_custom_widget({"name": "Stock", "tsx_code": "x"}, w=None)["id"]
        cw.delete_custom_widget(new, w=None)
        assert new not in world.acl and not world.db["drafts"]


def test_a_shared_view_lends_its_pinned_version():
    with World(me="bo@example.com") as world:
        world.publish("w1", 1)
        world.publish("w1", 2)
        world.acl["w1"] = {"ana@example.com": "MANAGE"}
        world.lent = ({"w1"}, {"w1@1"})
        rows = cw.get_custom_widgets(w=None)["widgets"]
        assert ids_of(rows) == [("w1", 1), ("w1", 2)]
        assert all(r["in_library"] is False and r["tsx_code"] for r in rows)
        world.lent = (set(), set())
        assert cw.get_custom_widgets(w=None)["widgets"] == []


def test_a_view_lends_a_version_for_reading_in_full():
    with World(me="bo@example.com") as world:
        world.publish("w1", 1)
        world.publish("w1", 2)
        world.acl["w1"] = {"ana@example.com": "MANAGE"}
        expect(404, cw.get_widget_version, "w1", 1, w=None)
        world.lent = (set(), {"w1@1"})
        assert cw.get_widget_version("w1", 1, w=None)["widget"]["tsx_code"] == "w1 v1"
        expect(404, cw.get_widget_version, "w1", 2, w=None)
        world.lent = ({"w1"}, set())
        assert cw.get_widget_version("w1", 2, w=None)["widget"]["version"] == 2


def test_a_view_bundle_carries_drafts_only_in_draft_mode():
    with World() as world:
        world.publish("w1", 1)
        world.acl["w1"] = {"ana@example.com": "MANAGE"}
        cw.update_custom_widget("w1", {"tsx_code": "wip"}, w=None)
        who, c = access.caller(None), FakeCursor(world.db)
        assert ids_of(cw.bundle_rows(c, who, ["w1"])) == [("w1", 1)]
        assert ids_of(cw.bundle_rows(c, who, ["w1"], draft=True)) == [("w1", 0), ("w1", 1)]


def test_claiming_fills_in_a_missing_author():
    with World() as world:
        world.publish("w1", 1, created_by="dev")
        world.acl["w1"] = {"ana@example.com": "MANAGE"}
        cw.update_custom_widget("w1", {"tsx_code": "wip"}, w=None)
        out = cw.claim_custom_widget("w1", w=None)
        assert out["created_by"] == "ana@example.com" and out["versions"] == 2
        assert world.db["widgets"][0]["created_by"] == "ana@example.com"
        assert world.db["drafts"][("widget", "w1")]["payload"]["created_by"] == "ana@example.com"
        expect(409, cw.claim_custom_widget, "w1", w=None)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
