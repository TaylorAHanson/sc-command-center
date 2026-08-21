"""Standalone tests for the widget settings the studio agent proposes."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from routes.widget_studio import GenerateRequest, _extract_meta
except Exception as e:  # pragma: no cover - needs the backend venv (langchain, fastapi)
    print(f"SKIP test_widget_agent_meta: {e}")
    sys.exit(0)


def _req(**kwargs):
    return GenerateRequest(prompt="build it", **kwargs)


def _response(body: str) -> str:
    return f"Here you go.\n\n```widget-meta\n{body}\n```\n\nLet me know."


def test_extracts_settings_and_removes_the_block():
    meta, remainder = _extract_meta(
        _response('{"name": "Open POs", "description": "Open purchase orders.", "defaultW": 8}'),
        _req(),
    )
    assert meta == {"name": "Open POs", "description": "Open purchase orders.", "defaultW": 8}
    assert "widget-meta" not in remainder
    assert remainder == "Here you go.\n\nLet me know."


def test_only_accepts_categories_and_domains_the_ui_offers():
    req = _req(available_categories=["Operations", "Finance"], available_domains=["Supply Chain"])
    meta, _ = _extract_meta(
        _response('{"category": "operations", "domain": "Marketing"}'), req
    )
    # Matched case-insensitively but stored in the UI's own casing.
    assert meta["category"] == "Operations"
    # Not a selectable domain, so it is dropped rather than passed through.
    assert "domain" not in meta


def test_drops_settings_the_user_already_owns():
    req = _req(locked_settings=["name", "defaultW"])
    meta, _ = _extract_meta(_response('{"name": "Agent Name", "defaultW": 4, "defaultH": 5}'), req)
    assert meta == {"defaultH": 5}


def test_range_checks_dimensions_and_refuses_a_non_boolean_flag():
    meta, _ = _extract_meta(
        _response('{"defaultW": 99, "defaultH": "6", "isExecutable": "yes", "name": "  Trimmed  "}'),
        _req(),
    )
    assert "defaultW" not in meta          # outside the 12-column grid
    assert meta["defaultH"] == 6           # numeric string is coerced
    assert "isExecutable" not in meta      # only a real boolean may set this
    assert meta["name"] == "Trimmed"


def test_survives_a_malformed_or_absent_block():
    meta, remainder = _extract_meta(_response("{not json at all"), _req())
    assert meta == {}
    assert "widget-meta" not in remainder

    plain = "Just an explanation, no settings."
    meta, remainder = _extract_meta(plain, _req())
    assert meta == {} and remainder == plain


if __name__ == "__main__":
    tests = [
        test_extracts_settings_and_removes_the_block,
        test_only_accepts_categories_and_domains_the_ui_offers,
        test_drops_settings_the_user_already_owns,
        test_range_checks_dimensions_and_refuses_a_non_boolean_flag,
        test_survives_a_malformed_or_absent_block,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
