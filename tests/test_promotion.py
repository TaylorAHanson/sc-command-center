"""Standalone tests for promotion: what counts as "already up to date", and promoting an app.

An app's row is copied between envs on its own, while the widgets and agents it
names are rows of their own in each env. The preflight says what the target
would be missing; the transfer can carry missing widgets along in the same
transaction. Both run here against fake connections, one per env, that
remember what was committed.
"""
import copy
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import json  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from routes import promotion  # noqa: E402
from routes.promotion import same_content, same_view_content  # noqa: E402
from services import settings_store  # noqa: E402
from services.app_spec import legacy_spec  # noqa: E402
from services.app_links import slugify  # noqa: E402

DEV_V5 = {"id": "w1", "version": 5, "name": "Orders", "tsx_code": "new code", "domain": "Sales",
          "is_certified": 0, "is_deprecated": 0, "timestamp": "2026-09-01", "created_by": "a@x.com"}


def test_same_number_in_another_env_is_not_the_same_widget():
    """Test's own v5 is an unrelated copy; promoting Dev v5 over it must copy."""
    test_v5 = {**DEV_V5, "tsx_code": "old code"}
    assert not same_content(DEV_V5, test_v5)


def test_a_promoted_copy_matches_despite_bookkeeping():
    prod_copy = {**DEV_V5, "version": 2, "is_certified": 1, "timestamp": "2026-09-20", "created_by": "b@x.com"}
    assert same_content(DEV_V5, prod_copy)


def test_empty_and_missing_values_compare_equal():
    assert same_content({**DEV_V5, "help_text": None}, {**DEV_V5, "help_text": ""})
    assert not same_content({**DEV_V5, "help_text": "Shows orders"}, DEV_V5)


def test_views_compare_by_layout_not_number():
    dev_v3 = {"id": "v1", "version": 3, "name": "Ops", "domain": "Sales", "username": "a@x.com",
              "is_global": 1, "widgets_json": '["w1","w2"]', "is_locked": 0, "pinned_agent_id": None,
              "timestamp": "2026-09-01"}
    assert not same_content(dev_v3, {**dev_v3, "widgets_json": '["w1"]'})
    assert same_content(dev_v3, {**dev_v3, "version": 1, "timestamp": "2026-09-20"})


VIEW = {"id": "v1", "version": 3, "name": "Ops", "domain": "Sales", "username": "system", "is_global": 1,
        "widgets_json": json.dumps([{"i": "a", "type": "iframe"}]), "spec_json": None, "is_locked": 0,
        "pinned_agent_id": None, "timestamp": "2026-09-01"}


def test_a_view_saved_since_apps_matches_its_untouched_copy():
    """Test still has the row from before apps; Dev saved the same layout since. Nothing changed."""
    resaved = {**VIEW, "version": 9, "spec_json": json.dumps(legacy_spec("v1", [{"i": "a", "type": "iframe"}]))}
    assert not same_content(VIEW, resaved), "column by column they differ"
    assert same_view_content(VIEW, resaved)


def test_a_change_on_another_tab_is_a_change():
    spec = legacy_spec("v1", [{"i": "a", "type": "iframe"}])
    spec["tabs"].append({"id": "t2", "name": "Two", "widgets": [], "pinned_agent_id": None})
    with_tab = {**VIEW, "spec_json": json.dumps(spec)}
    assert not same_view_content(VIEW, with_tab), "widgets_json alone would call these equal"
    assert not same_view_content(VIEW, {**VIEW, "widgets_json": "[]"})


def test_reading_a_widget_by_id_still_checks_its_domain():
    """/history and /version take a bare id, so they must apply /custom's domain filter."""
    from fastapi import HTTPException
    from routes import custom_widgets

    saved = custom_widgets._get_user_permissions
    custom_widgets._get_user_permissions = lambda w: {
        "is_admin": False, "domain_permissions": {"Sales": "viewer"},
    }
    try:
        custom_widgets._require_visible(None, "prod", "Sales")
        try:
            custom_widgets._require_visible(None, "prod", "Finance")
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("another domain's widget was readable")
    finally:
        custom_widgets._get_user_permissions = saved


# ------------------------------------------------------------ promoting apps

ORDERS = "0b5c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d"
MARGINS = "1c6d2e3f-4051-4b6c-9d7e-8f9a0b1c2d3e"
AGENT = "3f7c1a52-9d0e-4b18-8a44-0c2b6de91f77"


def widget(widget_id, version=1, *, name="Orders", domain="Sales", code="v1", certified=0, deprecated=0):
    return {"id": widget_id, "version": version, "name": name, "domain": domain, "tsx_code": code,
            "is_certified": certified, "is_deprecated": deprecated, "timestamp": "2026-09-01"}


def app_row(spec, *, version=1, pin=None, is_global=1, domain="Sales"):
    return {"id": "app1", "version": version, "name": "Ops", "domain": domain, "username": "system",
            "is_global": is_global, "widgets_json": json.dumps(spec["tabs"][0]["widgets"]),
            "spec_json": json.dumps(spec), "is_locked": 0, "pinned_agent_id": pin, "timestamp": "2026-09-01"}


def two_tab_spec(*, pin_orders_to=None, tab_agent=None):
    props = {"_version": pin_orders_to} if pin_orders_to else {}
    spec = legacy_spec("app1", [{"i": "a", "type": ORDERS, "props": props}, {"i": "b", "type": "iframe"}])
    spec["tabs"].append({"id": "t2", "name": "Two", "widgets": [{"i": "c", "type": MARGINS}], "pinned_agent_id": tab_agent})
    return spec


class Env:
    """One env's tables. Writes land in `data` and become `committed` on commit."""

    def __init__(self, *, apps=(), widgets=(), agents=()):
        self.committed = {"dashboard_views": list(apps), "widgets": list(widgets), "agent_profiles": list(agents)}
        self.data = copy.deepcopy(self.committed)
        self.statements = []

    def rows(self, table, widget_id):
        return [r for r in self.data[table] if r["id"] == widget_id]

    def writes(self):
        return [s for s in self.statements if s.split()[0] in ("INSERT", "UPDATE", "DELETE")]


class EnvCursor:
    def __init__(self, env):
        self.env = env
        self.description = None
        self._rows = []

    def _answer(self, rows):
        rows = list(rows)
        if rows:
            names = list(rows[0])
            self.description = [(n,) for n in names]
            self._rows = [tuple(r[n] for n in names) for r in rows]
        else:
            self.description, self._rows = [("?column?",)], []

    def execute(self, sql, params=()):
        text = " ".join(sql.split())
        self.env.statements.append(text)
        if "SAVEPOINT" in text:
            return
        if "app_links" in text:
            # Every name is free in a fresh fake: the claim takes the first it asks for.
            self.description, self._rows = [("slug",)], [(params[0],)] if text.startswith("INSERT") else []
            self.env.links = getattr(self.env, "links", {})
            if text.startswith("INSERT"):
                self.env.links[params[0]] = params[1]
            return
        table = ("widgets" if re.search(r"\b(FROM|INTO) widgets\b", text)
                 else "agent_profiles" if "agent_profiles" in text else "dashboard_views")
        if text.startswith("INSERT INTO"):
            cols = text[text.index("(") + 1:text.index(")")].split(", ")
            self.env.data[table].append(dict(zip(cols, params)))
            return
        if text.startswith("DELETE FROM dashboard_views"):
            self.env.data[table] = [r for r in self.env.data[table] if not (r["id"] == params[0] and r["version"] > params[1])]
            return
        if "FROM widgets w" in text:
            heads = {}
            for r in self.env.data["widgets"]:
                if r["id"] in params[0] and not r["is_deprecated"] and r["version"] > heads.get(r["id"], {}).get("version", 0):
                    heads[r["id"]] = r
            self._answer({k: r[k] for k in ("id", "version", "name", "domain", "is_certified")} for r in heads.values())
            return
        if text.startswith("SELECT id, name FROM agent_profiles"):
            live = [r for r in self.env.data[table] if r["id"] in params[0] and not r["is_deprecated"]]
            self._answer({"id": r["id"], "name": r["name"]} for r in sorted(live, key=lambda r: -r["version"]))
            return
        rows = self.env.rows(table, params[0])
        if "is_deprecated = 0" in text:
            rows = [r for r in rows if not r["is_deprecated"]]
        if "AND version = %s" in text:
            rows = [r for r in rows if r["version"] == params[1]]
        if text.startswith("SELECT MAX(version)"):
            self.description, self._rows = [("max",)], [(max((r["version"] for r in rows), default=None),)]
            return
        self._answer(sorted(rows, key=lambda r: -r["version"])[:1])

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class EnvConn:
    def __init__(self, env):
        self.env = env

    def cursor(self):
        return EnvCursor(self.env)

    def commit(self):
        self.env.committed = copy.deepcopy(self.env.data)

    def rollback(self):
        self.env.data = copy.deepcopy(self.env.committed)

    def close(self):
        pass


def promote(envs, fn, request, *, editor_of=("Sales",), certified_only=False):
    def require_editor(_w, domain):
        if domain not in editor_of:
            raise HTTPException(status_code=403, detail=f"Forbidden: Editor required for '{domain}'")
        return True

    saved = (promotion.get_db_connection, promotion.require_domain_editor, settings_store.get_bool_setting)
    promotion.get_db_connection = lambda env: EnvConn(envs[env])
    promotion.require_domain_editor = require_editor
    settings_store.get_bool_setting = lambda key, *a, **k: certified_only and key == "require_certified_for_global_views"
    try:
        return fn(request, w=None)
    finally:
        promotion.get_db_connection, promotion.require_domain_editor, settings_store.get_bool_setting = saved


def to_test(**kw):
    return promotion.AppTransferRequest(app_id="app1", source_env="dev", target_env="test", **kw)


def refused_promotion(envs, fn, request, **kw):
    try:
        promote(envs, fn, request, **kw)
    except HTTPException as exc:
        return exc
    raise AssertionError("the promotion was not refused")


def test_the_preflight_names_what_the_target_lacks_on_every_tab():
    dev = Env(apps=[app_row(two_tab_spec(tab_agent=AGENT), pin="default")],
              widgets=[widget(ORDERS), widget(MARGINS, name="Margins")],
              agents=[{"id": AGENT, "version": 2, "name": "Ops helper", "is_deprecated": 0}])
    test = Env(widgets=[widget(ORDERS, version=4)])
    found = promote({"dev": dev, "test": test}, promotion.transfer_app_preflight, to_test())["preflight"]
    assert [w["id"] for w in found["missing_widgets"]] == [MARGINS], "built-in types have no row to be missing"
    assert found["missing_widgets"][0]["name"] == "Margins"
    assert found["missing_agents"] == [{"id": AGENT, "name": "Ops helper"}], "a tab's pin counts; 'default' names no agent"
    assert found["version_pins"] == [] and found["uncertified"] == []
    assert dev.writes() == [] and test.writes() == []


def test_a_version_pin_is_checked_against_the_row_of_that_number_in_the_target():
    dev = Env(apps=[app_row(two_tab_spec(pin_orders_to=2))],
              widgets=[widget(ORDERS, 2, code="pinned"), widget(ORDERS, 3), widget(MARGINS, name="Margins")])
    absent = Env(widgets=[widget(ORDERS, 1, code="pinned"), widget(MARGINS, name="Margins")])
    other = Env(widgets=[widget(ORDERS, 2, code="something else"), widget(MARGINS, name="Margins")])
    same = Env(widgets=[widget(ORDERS, 2, code="pinned", certified=1), widget(MARGINS, name="Margins")])
    for target, problem in ((absent, "missing"), (other, "different"), (same, None)):
        pins = promote({"dev": dev, "test": target}, promotion.transfer_app_preflight, to_test())["preflight"]["version_pins"]
        assert [p["problem"] for p in pins] == ([problem] if problem else []), problem


def test_uncertified_widgets_are_named_only_where_a_global_view_needs_them_certified():
    spec = two_tab_spec()
    test = Env(widgets=[widget(ORDERS, certified=1), widget(MARGINS, name="Margins")])
    dev = Env(apps=[app_row(spec)], widgets=[widget(ORDERS), widget(MARGINS, name="Margins")])
    envs = {"dev": dev, "test": test}
    assert promote(envs, promotion.transfer_app_preflight, to_test())["preflight"]["uncertified"] == []
    found = promote(envs, promotion.transfer_app_preflight, to_test(), certified_only=True)["preflight"]
    assert [w["name"] for w in found["uncertified"]] == ["Margins"], "certified in the target is what counts"
    dev.data["dashboard_views"] = dev.committed["dashboard_views"] = [app_row(spec, is_global=0)]
    personal = promote(envs, promotion.transfer_app_preflight, to_test(), certified_only=True)["preflight"]
    assert personal["uncertified"] == []


def test_the_preflight_needs_the_right_to_promote():
    envs = {"dev": Env(apps=[app_row(two_tab_spec())]), "test": Env()}
    assert refused_promotion(envs, promotion.transfer_app_preflight, to_test(), editor_of=()).status_code == 403


def test_promoting_with_its_widgets_writes_them_and_the_view_in_one_commit():
    spec = two_tab_spec()
    dev = Env(apps=[app_row(spec, version=6)], widgets=[widget(ORDERS, 3), widget(MARGINS, 2, name="Margins")])
    test = Env(apps=[app_row(legacy_spec("app1", []), version=2)],
               widgets=[widget(ORDERS, 7, code="v1"), widget(MARGINS, 1, name="Margins", deprecated=1)])
    result = promote({"dev": dev, "test": test}, promotion.transfer_app, to_test(include_widgets=[MARGINS, ORDERS]))
    assert result["new_version"] == 3
    by_id = {w["id"]: w for w in result["widgets"]}
    assert by_id[ORDERS] == {"id": ORDERS, "name": "Orders", "version": 7, "copied": False}, "same widget, left alone"
    assert by_id[MARGINS]["version"] == 2 and by_id[MARGINS]["copied"], "next number past the deprecated row"
    head = max(test.committed["dashboard_views"], key=lambda r: r["version"])
    assert json.loads(head["spec_json"]) == spec, "every tab travels"
    assert [r["version"] for r in test.committed["widgets"] if r["id"] == MARGINS] == [1, 2]
    name = app_row(spec)["name"]
    assert getattr(test, "links", {}) == {slugify(name): "app1"}, "a promoted global view is linked by name there too"


def test_a_refused_widget_leaves_the_target_as_it_was():
    spec = two_tab_spec()
    dev = Env(apps=[app_row(spec)], widgets=[widget(ORDERS), widget(MARGINS, name="Margins", domain="Finance")])
    test = Env()
    exc = refused_promotion({"dev": dev, "test": test}, promotion.transfer_app, to_test(include_widgets=[MARGINS]))
    assert exc.status_code == 403 and "Finance" in exc.detail, "each widget needs the right promoting it alone needs"
    assert test.writes() == []


def test_only_widgets_on_the_view_can_go_with_it():
    dev = Env(apps=[app_row(two_tab_spec())], widgets=[widget(ORDERS)])
    other = "2d7e3f40-5162-4c7d-8e9f-a0b1c2d3e4f5"
    exc = refused_promotion({"dev": dev, "test": Env()}, promotion.transfer_app, to_test(include_widgets=[other]))
    assert exc.status_code == 400


def test_an_up_to_date_view_still_commits_the_widgets_sent_with_it():
    spec = two_tab_spec()
    dev = Env(apps=[app_row(spec, version=5)], widgets=[widget(ORDERS), widget(MARGINS, name="Margins")])
    test = Env(apps=[app_row(spec, version=1)], widgets=[widget(ORDERS)])
    result = promote({"dev": dev, "test": test}, promotion.transfer_app, to_test(include_widgets=[MARGINS]))
    assert result["message"].startswith("Already up to date")
    assert [r["id"] for r in test.committed["widgets"]] == [ORDERS, MARGINS]
    assert len(test.committed["dashboard_views"]) == 1


def test_rolling_back_ignores_widgets_and_drops_newer_versions():
    spec = two_tab_spec()
    test = Env(apps=[app_row(spec, version=v) for v in (1, 2, 3)])
    dev = Env(apps=[app_row(spec, version=1)], widgets=[widget(MARGINS, name="Margins")])
    promote({"dev": dev, "test": test}, promotion.transfer_app,
            to_test(version=1, is_rollback=True, include_widgets=[MARGINS]))
    assert [r["version"] for r in test.committed["dashboard_views"]] == [1]
    assert test.committed["widgets"] == []


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
