"""Tests for folding the old Dev and Test workspaces into the one content store.

What is pinned here is what decides whether the fold is safe: nothing in Prod
changes, only work that differs from Prod becomes a draft, Dev is preferred to
Test, a store that is really the content store is never read as a second one,
a view's widget pins still name the code they named, and Prod's own archive
markers and link names win. The SQL runs against a database and is exercised
by hand, not here.
"""
import contextlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from services import consolidation as cons
    from services.access import AGENT, APP, WIDGET
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_consolidation: {e}")
    sys.exit(0)


# ------------------------------------------------------------------ diff vs Prod

def widget(**kw):
    row = {"id": "w1", "version": 3, "name": "Sales", "tsx_code": "export default 1", "domain": "Supply",
           "created_by": "a@x.com", "timestamp": "2026-01-01", "is_deprecated": 0}
    row.update(kw)
    return row


def test_identical_work_needs_no_draft():
    # Versions are numbered per store and stamped when written; neither is content.
    prod = widget()
    dev = widget(version=9, timestamp="2026-05-05", created_by="b@x.com")
    assert cons.decide(WIDGET, prod, dev) == cons.UNCHANGED


def test_changed_work_becomes_the_draft():
    assert cons.decide(WIDGET, widget(), widget(tsx_code="export default 2")) == cons.DRAFT


def test_work_prod_never_had_is_a_draft_only_object():
    assert cons.decide(WIDGET, None, widget()) == cons.DRAFT_ONLY


def test_empty_and_null_are_the_same_content():
    assert cons.decide(AGENT, {"id": "a", "description": ""}, {"id": "a", "description": None}) == cons.UNCHANGED


def test_a_column_only_one_store_has_is_not_a_difference():
    # The old Test schema stopped being initialised, so it can lack a column
    # added since; that alone must not give every Test object a draft.
    prod = widget(published_by="p@x.com", shiny_new="value")
    assert cons.decide(WIDGET, prod, widget()) == cons.UNCHANGED


def test_bytes_compare_as_their_text():
    assert cons.same_content({"tsx_code": b"abc"}, {"tsx_code": "abc"})


def test_views_stored_before_and_after_apps_compare_by_meaning():
    layout = [{"type": "w1", "props": {}, "layout": {"x": 0, "y": 0, "w": 4, "h": 3}}]
    old = {"id": "v1", "name": "Ops", "widgets_json": json.dumps(layout), "spec_json": None}
    try:
        from services.app_spec import read_spec
    except Exception:  # pragma: no cover
        return
    spec = read_spec("v1", None, json.dumps(layout))
    new = {"id": "v1", "name": "Ops", "widgets_json": json.dumps(layout), "spec_json": json.dumps(spec, default=str)}
    assert cons.decide(APP, old, new) == cons.UNCHANGED
    assert cons.decide(APP, old, {**new, "name": "Ops 2"}) == cons.DRAFT


def test_dev_is_preferred_to_test():
    picked = cons.pick_sources([
        ("dev", {"w1": {"id": "w1", "name": "from dev"}}),
        ("test", {"w1": {"id": "w1", "name": "from test"}, "w2": {"id": "w2", "name": "only test"}}),
    ])
    assert picked["w1"][0] == "dev" and picked["w1"][1]["name"] == "from dev"
    assert picked["w2"][0] == "test"


# ------------------------------------------------------------------ same store

PROD = ("host", "5432", "databricks_postgres", "prod")


def test_a_store_that_is_the_content_store_is_not_read_again():
    # APP_DB_SCHEMA points every env at one schema; reading it as Dev would turn
    # every published object into its own draft.
    keep, notes = cons.distinct_sources(PROD, [("dev", PROD), ("test", PROD)])
    assert keep == [] and len(notes) == 2 and "same database and schema" in notes[0]


def test_bundle_schemas_and_legacy_databases_are_separate_stores():
    dev = ("host", "5432", "databricks_postgres", "dev")
    legacy_test = ("host", "5432", "command-center-test", "public")
    keep, notes = cons.distinct_sources(PROD, [("dev", dev), ("test", legacy_test)])
    assert keep == ["dev", "test"] and notes == []


def test_two_envs_on_one_store_are_read_once_dev_first():
    shared = ("host", "5432", "databricks_postgres", "public")
    keep, notes = cons.distinct_sources(PROD, [("dev", shared), ("test", shared)])
    assert keep == ["dev"] and len(notes) == 1 and notes[0].startswith("Test")


def test_an_env_without_a_schema_is_skipped_with_a_note():
    keep, notes = cons.distinct_sources(PROD, [("test", None)])
    assert keep == [] and "no schema" in notes[0]


# ------------------------------------------------------------------ pins

def test_pins_are_read_as_the_renderer_reads_them():
    assert cons.pin_of({"_version": 3}) == 3
    assert cons.pin_of({"_version": " 4 "}) == 4
    for unpinned in ({}, {"_version": 0}, {"_version": True}, {"_version": "x"}, None):
        assert cons.pin_of(unpinned) is None


def view(widgets, spec_widgets=None):
    return {
        "id": "v1", "name": "Ops",
        "widgets_json": json.dumps(widgets),
        "spec_json": json.dumps({"tabs": [{"id": "t1", "widgets": spec_widgets if spec_widgets is not None else widgets}]}),
    }


def test_a_pin_is_listed_once_from_both_columns():
    row = view([{"type": "w1", "props": {"_version": 2}}, {"type": "w2", "props": {}}])
    assert cons.view_pins(row) == [("w1", 2)]


def test_remap_moves_pins_in_both_columns_and_none_unpins():
    row = view([{"type": "w1", "props": {"_version": 2, "title": "T"}}, {"type": "w2", "props": {"_version": 5}}])
    out = cons.remap_pins(row, {("w1", 2): 7, ("w2", 5): None})
    for widgets in (json.loads(out["widgets_json"]), json.loads(out["spec_json"])["tabs"][0]["widgets"]):
        assert widgets[0]["props"] == {"_version": 7, "title": "T"}
        assert widgets[1]["props"] == {}


def test_a_view_with_nothing_to_remap_keeps_its_exact_text():
    # Rewritten JSON could differ in spacing from Prod's copy and look changed.
    row = view([{"type": "w1", "props": {"_version": 2}}])
    row["widgets_json"] = '[{"type":"w1","props":{"_version":2}}]'
    out = cons.remap_pins(row, {("w9", 1): 3})
    assert out == row


def test_the_version_with_the_same_code_is_chosen_newest_live_first():
    candidates = [(1, "A", False), (2, "B", False), (3, "A", False), (4, "A", True)]
    assert cons.choose_version("A", candidates) == 3
    assert cons.choose_version("A", [(4, "A", True), (5, "B", False)]) == 4
    assert cons.choose_version("C", candidates) is None
    assert cons.choose_version(None, candidates) is None


class Cursor:
    """Answers the two widget lookups `PinResolver` makes, from dicts."""

    def __init__(self, versions):
        self.versions = versions
        self.result = []
        self.description = [("version",), ("tsx_code",), ("dep",)]

    def execute(self, sql, params=()):
        assert "FROM widgets WHERE id" in sql, sql
        self.result = [dict(r) for r in self.versions.get(params[0], [])]

    def fetchall(self):
        return self.result


def test_resolver_maps_dev_versions_to_prod_versions_by_code():
    dev = Cursor({"w1": [{"version": 1, "tsx_code": "A"}, {"version": 2, "tsx_code": "B"}]})
    prod = Cursor({"w1": [{"version": 5, "tsx_code": "B", "dep": 0}, {"version": 6, "tsx_code": "C", "dep": 0}]})
    r = cons.PinResolver(dev, prod)
    assert r.resolve("w1", 2) == 5
    assert r.resolve("w1", 1) is None  # that code was never promoted
    assert r.resolve("w1", 9) is None  # Dev has no such version
    assert r.resolve("builtin", 1) == cons.PinResolver.KEEP


def test_pin_mapping_reports_what_it_drops():
    row = view([{"type": "w1", "props": {"_version": 1}}, {"type": "w1", "props": {"_version": 2}},
                {"type": "builtin", "props": {"_version": 1}}])
    answers = {("w1", 1): None, ("w1", 2): 5, ("builtin", 1): cons.PinResolver.KEEP}
    mapping, dropped = cons.pin_mapping(row, lambda w, v: answers[(w, v)])
    assert mapping == {("w1", 1): None, ("w1", 2): 5}
    assert dropped == [("w1", 1)]


# ------------------------------------------------------------------ merging

def test_prod_keeps_its_live_views_and_link_names():
    archived = {"columns": ["id", "username"], "rows": [["v-live", "a"], ["v-dev-only", "a"]]}
    body, held = cons.held_back("archived_views", archived, published_apps={"v-live"}, named_apps=set())
    assert body["rows"] == [["v-dev-only", "a"]] and held == 1

    links = {"columns": ["slug", "app_id"], "rows": [["ops", "v-named"], ["new", "v-other"]]}
    body, held = cons.held_back("app_links", links, published_apps=set(), named_apps={"v-named"})
    assert body["rows"] == [["new", "v-other"]] and held == 1


def test_other_tables_merge_whole():
    body = {"columns": ["name"], "rows": [["x"]]}
    assert cons.held_back("widget_domains", body, published_apps={"x"}, named_apps={"x"}) == (body, 0)


def test_merged_tables_are_ones_snapshots_know_how_to_merge():
    from services import data_migration as dm

    assert all(t in dm.SPECS for t in cons.MERGED)
    assert not {t for _, t in cons.VERSIONED} & set(cons.MERGED)


# ------------------------------------------------------------------ the report

def empty_report(**kw):
    report = {"sources": ["dev", "test"], "drafts": {}, "draft_only": {}, "kept_existing_drafts": 0,
              "pins_remapped": 0, "pins_dropped": [], "merged": []}
    report.update(kw)
    return report


def test_notes_name_what_became_a_draft():
    notes = cons.notes_for(empty_report(drafts={WIDGET: 2}, draft_only={APP: 1, AGENT: 3}))
    assert any("2 widgets had newer work in Dev and Test" in n for n in notes)
    assert any("1 view and 3 agents existed only in Dev and Test" in n for n in notes)


def test_each_dropped_pin_is_named_up_to_a_limit():
    pins = [{"app_id": f"v{i}", "name": "", "env": "dev", "widget_id": "w", "version": i} for i in range(25)]
    notes = cons.notes_for(empty_report(pins_dropped=pins))
    assert sum(n.startswith("View ") for n in notes) == 20
    assert notes[-1] == "…and 5 more pins like that."


def test_a_quiet_fold_has_no_notes():
    assert cons.notes_for(empty_report()) == []


def test_counts_read_as_english():
    assert cons.counts_phrase({WIDGET: 1}) == "1 widget"
    assert cons.counts_phrase({APP: 2, WIDGET: 1, AGENT: 1}) == "2 views, 1 widget and 1 agent"
    assert cons.counts_phrase({}) == "nothing"


# ------------------------------------------------------------------ run once

class Log:
    def __init__(self, held=None):
        self.rows = dict(held or {})

    def install(self):
        saved = (cons.step_lock, cons.read_step, cons.record)

        @contextlib.contextmanager
        def lock(step):
            yield Conn()

        cons.step_lock = lock
        cons.read_step = lambda c, step: self.rows.get(step)
        cons.record = lambda c, step, status, report, error=None: self.rows.__setitem__(
            step, {"status": status, "report": report, "error": error})
        return saved

    @staticmethod
    def restore(saved):
        cons.step_lock, cons.read_step, cons.record = saved


class Conn:
    def cursor(self):
        return None

    def commit(self):
        pass

    def rollback(self):
        pass


def test_a_logged_step_is_not_run_again():
    log = Log({"x": {"status": cons.DONE}})
    saved = log.install()
    try:
        ran = []
        assert cons.run_step("x", lambda c: ran.append(1) or (cons.DONE, {}))["status"] == cons.DONE
        assert ran == []
    finally:
        Log.restore(saved)


def test_a_failure_is_recorded_and_its_fallback_runs():
    log = Log()
    saved = log.install()
    try:
        fallback = []

        def boom(c):
            raise RuntimeError("no table")

        out = cons.run_step("x", boom, on_failure=lambda c: fallback.append(1))
        assert out["status"] == cons.FAILED and "no table" in out["error"] and fallback == [1]
    finally:
        Log.restore(saved)


def test_startup_survives_an_unreachable_store():
    saved = cons.step_lock

    def lock(step):
        raise ConnectionError("down")

    cons.step_lock = lock
    try:
        assert cons.run_step("x", lambda c: (cons.DONE, {})) is None
    finally:
        cons.step_lock = saved


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
