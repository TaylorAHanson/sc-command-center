"""Standalone tests for what promotion treats as "already up to date"."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import json  # noqa: E402

from routes.promotion import same_content, same_view_content  # noqa: E402
from services.app_spec import legacy_spec  # noqa: E402

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
    custom_widgets._get_user_permissions = lambda w, env: {
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


if __name__ == "__main__":
    tests = [
        test_same_number_in_another_env_is_not_the_same_widget,
        test_a_promoted_copy_matches_despite_bookkeeping,
        test_empty_and_missing_values_compare_equal,
        test_views_compare_by_layout_not_number,
        test_a_view_saved_since_apps_matches_its_untouched_copy,
        test_a_change_on_another_tab_is_a_change,
        test_reading_a_widget_by_id_still_checks_its_domain,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
