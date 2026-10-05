"""Tests for what an app is: reading stored rows, validating saves, composing, access.

Most of what is pinned here is about the deployment that already exists. Every
row in it was written before apps, holds only `widgets_json`, and must read as
exactly the one-canvas view it was — same id, same layout, same sidebar — with no
migration having run. The rest is the write path refusing what it would otherwise
have to guess at, and the access rule that decides who may open an app at all.
"""
import copy
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import app_spec  # noqa: E402
from services.app_spec import (  # noqa: E402
    MAX_IMAGE_CHARS, MAX_TABS, SpecError, all_widgets, can_read, compose_spec, dumps,
    first_tab_widgets, legacy_spec, read_spec, validate_spec,
)

APP = "5b7e6f0a-1c2d-4e3f-8a9b-0c1d2e3f4a5b"
ME = "taylor@example.com"
# What the store writes for a widget dropped at the bottom of the grid: `y` is
# Infinity in the browser, which JSON turns into null.
DROPPED = {"i": "w-1", "x": 0, "y": None, "w": 4, "h": 3, "type": "iframe", "props": {"url": "https://x"}}


def ids():
    counter = itertools.count(1)
    return lambda: f"new-{next(counter)}"


def refuses(raw, fragment, app_id=APP):
    try:
        validate_spec(raw, app_id, new_id=ids())
    except SpecError as e:
        assert fragment in str(e), f"{fragment!r} not in {str(e)!r}"
        return
    raise AssertionError("the spec was accepted")


def two_tabs(**overrides):
    spec = legacy_spec(APP, [DROPPED])
    spec["tabs"].append({"id": "t2", "name": "Second", "widgets": [{"i": "w-2", "type": "chart"}], "pinned_agent_id": None})
    spec.update(overrides)
    return spec


# ------------------------------------------------------------ reading old rows

def test_a_view_from_before_apps_reads_as_its_one_tab_app():
    spec = read_spec(APP, None, json.dumps([DROPPED]))
    assert [t["id"] for t in spec["tabs"]] == [APP], "the tab takes the app's id so old links still land"
    assert spec["tabs"][0]["widgets"] == [DROPPED]
    assert spec["presentation"] == "workspace", "an existing view must keep the sidebar"
    assert spec["assistant"] == "on"


def test_an_empty_or_unreadable_spec_falls_back_to_the_layout():
    for stored in (None, "", "{not json", "[1, 2]", "42", json.dumps({"tabs": "nope"})):
        spec = read_spec(APP, stored, json.dumps([DROPPED]))
        assert [t["id"] for t in spec["tabs"]] == [APP], stored
        assert spec["tabs"][0]["widgets"] == [DROPPED], stored


def test_reading_never_raises_on_junk():
    junk = [
        (None, None), (None, "garbage"), ("{}", None), (json.dumps({"tabs": [None, 3, "x"]}), None),
        (json.dumps({"tabs": [{"id": 9, "widgets": "no"}]}), None),
        (json.dumps({"tabs": [{"id": "a"}, {"id": "a"}], "presentation": "sideways"}), None),
        (json.dumps({"tabs": [{}], "branding": {"logo": "javascript:alert(1)"}}), None),
    ]
    for spec_json, widgets_json in junk:
        spec = read_spec(APP, spec_json, widgets_json)
        assert spec["tabs"], "there is always a tab to render"
        assert len({t["id"] for t in spec["tabs"]}) == len(spec["tabs"])
        assert spec["presentation"] in app_spec.PRESENTATIONS
        assert spec["branding"] is None or spec["branding"].get("logo") is None


def test_reading_keeps_widget_entries_verbatim():
    # The read path is not the place to decide a layout is wrong; dropping an
    # entry here would delete it on the next save.
    odd = [DROPPED, {"no_i": True}, "a-string"]
    assert read_spec(APP, None, json.dumps(odd))["tabs"][0]["widgets"] == odd


def test_a_saved_spec_round_trips():
    spec = validate_spec(two_tabs(presentation="standalone"), APP, new_id=ids())
    assert read_spec(APP, dumps(spec), "[]") == spec


# --------------------------------------------------------------- validating

def test_an_app_needs_a_tab():
    refuses({"tabs": []}, "at least one tab")
    refuses({}, "at least one tab")
    refuses("tabs", "must be an object")


def test_too_many_tabs_are_refused():
    refuses({"tabs": [{"id": f"t{n}"} for n in range(MAX_TABS + 1)]}, f"at most {MAX_TABS}")


def test_tabs_without_ids_get_one_and_duplicates_are_refused():
    spec = validate_spec({"tabs": [{"name": "A"}, {"name": "B"}]}, APP, new_id=ids())
    assert [t["id"] for t in spec["tabs"]] == ["new-1", "new-2"]
    refuses({"tabs": [{"id": "a"}, {"id": "a"}]}, "share the id")


def test_a_widget_on_two_tabs_is_refused_but_a_repeat_within_one_tab_is_not():
    refuses({"tabs": [{"id": "a", "widgets": [{"i": "w"}]}, {"id": "b", "widgets": [{"i": "w"}]}]}, "more than one tab")
    validate_spec({"tabs": [{"id": "a", "widgets": [{"i": "w"}, {"i": "w"}]}]}, APP)


def test_widgets_must_be_objects_on_write():
    refuses({"tabs": [{"id": "a", "widgets": ["w"]}]}, "not an object")
    refuses({"tabs": [{"id": "a", "widgets": "w"}]}, "must be a list")


def test_unknown_choices_are_refused_on_write():
    refuses(two_tabs(presentation="sideways"), "presentation")
    refuses(two_tabs(assistant="maybe"), "assistant")


def test_there_is_no_link_access_setting():
    # Apps inherit the views' access model unchanged; a stored field that looked
    # like it widened or narrowed access, and did nothing, would be worse than none.
    assert "link_access" not in validate_spec(two_tabs(link_access="workspace"), APP)


def test_a_spec_from_a_newer_schema_is_not_overwritten():
    refuses(two_tabs(schema=app_spec.SCHEMA_VERSION + 1), "newer version")


def test_branding_images_are_https_or_bounded_data_urls():
    ok = validate_spec(two_tabs(branding={"title": " Ops ", "logo": "https://cdn.example.com/l.png",
                                           "favicon": "data:image/png;base64,iVBORw0KGgo="}), APP)
    assert ok["branding"]["title"] == "Ops"
    assert ok["branding"]["favicon"].startswith("data:image/png")
    for bad in ("http://example.com/l.png", "javascript:alert(1)", "data:text/html;base64,PHNjcmlwdD4=",
                "data:image/png;base64," + "A" * MAX_IMAGE_CHARS):
        refuses(two_tabs(branding={"logo": bad}), "branding.logo")


def test_empty_branding_is_no_branding():
    assert validate_spec(two_tabs(branding={"title": "  ", "logo": ""}), APP)["branding"] is None


def test_reserved_fields_are_carried_not_interpreted():
    spec = validate_spec(two_tabs(nav={"style": "rail"}, filters=[{"key": "region"}]), APP)
    assert spec["nav"] == {"style": "rail"} and spec["filters"] == [{"key": "region"}]
    refuses(two_tabs(filters={"key": "region"}), "filters")


def test_validating_does_not_mutate_the_request():
    raw = two_tabs()
    before = copy.deepcopy(raw)
    validate_spec(raw, APP)["tabs"][0]["widgets"].append({"i": "extra"})
    assert raw == before


# ----------------------------------------------------- the rollback copy

def test_widgets_json_mirrors_the_first_tab_and_checks_see_every_tab():
    spec = validate_spec(two_tabs(), APP)
    assert first_tab_widgets(spec) == [DROPPED]
    assert [w["i"] for w in all_widgets(spec)] == ["w-1", "w-2"]


def test_an_app_names_each_widget_it_places_once_and_every_version_it_pins():
    spec = two_tabs()
    spec["tabs"][0]["widgets"] += [
        {"i": "w-3", "type": "chart", "props": {"_version": 2}},
        {"i": "w-4", "type": "chart", "props": {"_version": "5"}},
        {"i": "w-5", "type": "table", "props": {"_version": True}},
        {"i": "w-6", "type": "table", "props": {"_version": 0}},
        {"i": "w-7", "props": {"_version": 9}},
        "junk",
    ]
    placed, pinned = app_spec.placed_widgets(read_spec(APP, dumps(spec), None))
    assert placed == ["iframe", "chart", "table"], "in order of first appearance, across every tab"
    assert pinned == ["chart@2", "chart@5"], "a pin is a positive version, saved as a number or as text"


# ----------------------------------------------------------------- composing

def source(name, widgets, pin=None, tabs=None):
    spec = legacy_spec("src-" + name, widgets)
    if tabs:
        spec["tabs"] = tabs
    return {"name": name, "pinned_agent_id": pin, "spec": spec}


def test_composing_views_gives_one_tab_per_view_in_order():
    spec = compose_spec([source("Orders", [{"i": "a"}], pin="agent-1"), source("Margins", [{"i": "b"}])], new_id=ids())
    assert [t["name"] for t in spec["tabs"]] == ["Orders", "Margins"]
    assert [t["pinned_agent_id"] for t in spec["tabs"]] == ["agent-1", None]
    assert all(t["id"].startswith("new-") for t in spec["tabs"]), "tabs never reuse a source's id"
    assert spec["presentation"] == "workspace"


def test_composing_an_app_keeps_its_tab_names_and_tab_pins():
    multi = source("Hub", [], pin="hub-agent", tabs=[
        {"id": "x", "name": "Today", "widgets": [], "pinned_agent_id": None},
        {"id": "y", "name": "Week", "widgets": [], "pinned_agent_id": "week-agent"},
    ])
    spec = compose_spec([multi], new_id=ids())
    assert [(t["name"], t["pinned_agent_id"]) for t in spec["tabs"]] == [("Today", "hub-agent"), ("Week", "week-agent")]


def test_composing_re_keys_only_colliding_widget_instances():
    original = source("A", [{"i": "same", "type": "t"}])
    copy_of_it = source("A (Copy)", [{"i": "same", "type": "t"}, {"i": "unique", "type": "t"}])
    before = copy.deepcopy(copy_of_it)
    spec = compose_spec([original, copy_of_it], new_id=ids())
    assert spec["tabs"][0]["widgets"][0]["i"] == "same"
    assert spec["tabs"][1]["widgets"][0]["i"].startswith("new-")
    assert spec["tabs"][1]["widgets"][1]["i"] == "unique"
    assert copy_of_it == before, "the source is copied, never changed"


def test_composing_refuses_nothing_and_too_much():
    try:
        compose_spec([])
        raise AssertionError("an empty composition was accepted")
    except SpecError:
        pass
    try:
        compose_spec([source(str(n), []) for n in range(MAX_TABS + 1)])
        raise AssertionError("too many tabs were accepted")
    except SpecError as e:
        assert "at most" in str(e)


def test_composing_checks_the_presentation():
    assert compose_spec([source("A", [])], presentation="standalone")["presentation"] == "standalone"
    try:
        compose_spec([source("A", [])], presentation="kiosk")
        raise AssertionError("an unknown presentation was accepted")
    except SpecError:
        pass


# --------------------------------------------------------------- who may read

PERSONAL = {"username": ME, "is_global": 0, "domain": "General"}
GLOBAL = {"username": "system", "is_global": 1, "domain": "Sales"}
NOBODY = {"is_admin": False, "domain_permissions": {}}


def test_a_personal_app_opens_for_anyone_holding_its_id_as_a_view_always_did():
    # `?shared_view=<id>` subscribes any caller to any personal view, so the id
    # has always been the key. Apps keep that, neither wider nor narrower.
    assert can_read(PERSONAL, perms=NOBODY)


def test_a_global_app_needs_a_role_in_its_domain_as_a_global_view_does():
    assert can_read(GLOBAL, perms={"is_admin": False, "domain_permissions": {"Sales": "viewer"}})
    assert not can_read(GLOBAL, perms={"is_admin": False, "domain_permissions": {"Finance": "editor"}})
    assert not can_read(GLOBAL, perms=NOBODY)
    assert can_read(GLOBAL, perms={"is_admin": True, "domain_permissions": {}})
    assert can_read({**GLOBAL, "domain": None}, perms={"is_admin": False, "domain_permissions": {"General": "viewer"}})


def test_pin_semantics_are_unchanged():
    assert app_spec.pin_value(None, "a") == "a"
    assert app_spec.pin_value("", "a") is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
