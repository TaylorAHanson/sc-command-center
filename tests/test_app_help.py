"""Standalone tests for the app-knowledge lookup behind the `app_help` tool."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services.app_help import (  # noqa: E402
    APP_PRIMER,
    app_help,
    app_help_tool_spec,
    topics,
)


def test_guide_parses_into_topics():
    found = topics()
    assert len(found) >= 8, found
    # Section titles are advertised to the model verbatim, so a rename that drops
    # one of these is a behavior change, not a cosmetic edit.
    for expected in ("Widgets", "Roles and permissions", "Environments and promoting work"):
        assert expected in found, (expected, found)


def test_finds_the_roles_section_for_a_natural_question():
    answer = app_help("If I'm in two groups, one viewer one editor, what do I get?")
    assert "## Roles and permissions" in answer
    assert "highest level wins" in answer.lower()


def test_finds_promotion_for_a_question_that_never_says_promotion():
    answer = app_help("how do I get my widget into prod?")
    assert "Environments and promoting work" in answer


def test_question_about_widgets_does_not_return_the_whole_guide():
    answer = app_help("what is a widget")
    assert "## Widgets" in answer
    # Three sections at most, so a lookup can't blow the model's context.
    assert answer.count("\n## ") + answer.startswith("## ") <= 3


def test_unmatched_question_lists_the_topics_instead_of_guessing():
    answer = app_help("what is the airspeed velocity of an unladen swallow")
    assert "Available topics" in answer
    assert "Roles and permissions" in answer


def test_empty_question_is_not_treated_as_a_match():
    assert "Available topics" in app_help("")


def test_tool_spec_advertises_real_sections():
    spec = app_help_tool_spec()
    fn = spec["function"]
    assert fn["name"] == "app_help"
    assert len(fn["description"]) <= 1024
    assert "Roles and permissions" in fn["description"]
    assert fn["parameters"]["required"] == ["question"]


def test_primer_covers_the_vocabulary_an_agent_must_not_get_wrong():
    for term in ("widget", "view", "domain", "Viewer", "Editor", "Admin", "app_help"):
        assert term in APP_PRIMER, term


if __name__ == "__main__":
    tests = [
        test_guide_parses_into_topics,
        test_finds_the_roles_section_for_a_natural_question,
        test_finds_promotion_for_a_question_that_never_says_promotion,
        test_question_about_widgets_does_not_return_the_whole_guide,
        test_unmatched_question_lists_the_topics_instead_of_guessing,
        test_empty_question_is_not_treated_as_a_match,
        test_tool_spec_advertises_real_sections,
        test_primer_covers_the_vocabulary_an_agent_must_not_get_wrong,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
