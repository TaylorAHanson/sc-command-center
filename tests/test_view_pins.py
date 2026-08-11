"""Tests for the agent a view pins the assistant to.

Views are saved as a whole: dragging a widget one square PUTs the entire view.
That makes the pin easy to lose by accident, so what is pinned here is the
difference between a save that doesn't mention the pin (keep it) and one that
deliberately empties it (clear it) — JSON null cannot tell those apart, since an
absent field arrives as null too.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from routes.views import pin_value
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_view_pins: {e}")
    sys.exit(0)

AGENT = "3f7c1a52-9d0e-4b18-8a44-0c2b6de91f77"
OTHER = "b1d9e402-77aa-4c31-9f60-5e8ad3c14b29"


def test_a_save_that_says_nothing_about_the_pin_keeps_it():
    # Every widget move takes this path. Losing the pin here would look like the
    # feature randomly forgetting itself.
    assert pin_value(None, AGENT) == AGENT


def test_an_empty_string_is_how_a_view_is_unpinned():
    assert pin_value("", AGENT) is None


def test_a_new_agent_replaces_the_old_one():
    assert pin_value(OTHER, AGENT) == OTHER


def test_pinning_a_view_that_had_no_pin():
    assert pin_value(AGENT, None) == AGENT


def test_nothing_in_nothing_out():
    assert pin_value(None, None) is None
    assert pin_value("", None) is None


def test_whitespace_is_not_an_agent():
    # A trimmed-to-empty id would otherwise be stored and then never match a
    # profile, leaving a view pinned to something that cannot exist.
    assert pin_value("   ", AGENT) is None
    assert pin_value(f"  {AGENT} ", None) == AGENT
    assert pin_value(None, f" {AGENT} ") == AGENT


def test_the_default_agent_is_a_pin_like_any_other():
    # "Open this view with the built-in agent" has to survive as a real value,
    # or it would be indistinguishable from having no pin at all.
    assert pin_value("default", None) == "default"
    assert pin_value(None, "default") == "default"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
