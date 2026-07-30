"""Pure-function tests for the conversation store.

No database and no network: these cover the helpers that decide what a
conversation is called and what the model is shown of earlier turns.

    PYTHONPATH=server python3 tests/test_conversation_store.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import conversation_store as store  # noqa: E402


def test_title_comes_from_the_opening_question():
    assert store.derive_title("  How many orders shipped late?  ") == "How many orders shipped late?"
    assert store.derive_title("") == "New conversation"
    assert store.derive_title("line one\nline two") == "line one line two"


def test_long_title_is_cut_on_a_word_boundary():
    title = store.derive_title(
        "Summarise the attached spreadsheet and tell me which region grew fastest "
        "over the last two quarters"
    )
    assert len(title) <= store.MAX_TITLE_CHARS + 1  # + the ellipsis
    assert title.endswith("…")
    assert not title[:-1].endswith(" ")
    assert " " in title  # cut at a word, not mid-word


def test_assistant_turns_replay_with_the_tools_they_ran():
    tools = json.dumps([
        {"tool_name": "Querying the attached file", "status": "done"},
        {"tool_name": "Querying the attached file", "status": "done"},
        {"tool_name": "Running SQL", "status": "done"},
    ])
    replayed = store.with_tool_evidence("assistant", "South leads at $3.9M.", tools)
    # Deduplicated, in the order they ran — this is the evidence that stops the
    # agent telling the user it invented an earlier figure.
    assert replayed == (
        "South leads at $3.9M.\n\n[tools used: Querying the attached file, Running SQL]"
    )


def test_turns_without_tools_replay_untouched():
    assert store.with_tool_evidence("assistant", "Sure.", "[]") == "Sure."
    assert store.with_tool_evidence("assistant", "Sure.", None) == "Sure."
    assert store.with_tool_evidence("assistant", "Sure.", "not json") == "Sure."
    # A user turn is never annotated, whatever it is handed.
    assert store.with_tool_evidence("user", "hi", '[{"tool_name": "x"}]') == "hi"


def test_keep_per_user_has_a_floor():
    os.environ["CHAT_KEEP_CONVERSATIONS"] = "1"
    try:
        assert store._keep_per_user() == 5
    finally:
        del os.environ["CHAT_KEEP_CONVERSATIONS"]
    os.environ["CHAT_KEEP_CONVERSATIONS"] = "nonsense"
    try:
        assert store._keep_per_user() == store.KEEP_PER_USER
    finally:
        del os.environ["CHAT_KEEP_CONVERSATIONS"]


if __name__ == "__main__":
    tests = [
        test_title_comes_from_the_opening_question,
        test_long_title_is_cut_on_a_word_boundary,
        test_assistant_turns_replay_with_the_tools_they_ran,
        test_turns_without_tools_replay_untouched,
        test_keep_per_user_has_a_floor,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
