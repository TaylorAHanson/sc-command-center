"""Standalone tests for agent runtime response normalization."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services.agent_runtime import _as_text, _history_messages, _parse_mcp_result, _system_prompt  # noqa: E402


def test_as_text_handles_structured_content_blocks():
    value = [
        {
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "private", "signature": "secret"}],
        },
        {"type": "text", "text": "Available "},
        {"type": "text", "text": ["tools", ":"]},
        {"content": " SQL"},
    ]
    assert _as_text(value) == "Available tools: SQL"


def test_as_text_hides_object_reasoning_blocks():
    block = type("Block", (), {"type": "reasoning", "text": "private chain of thought"})()
    assert _as_text(block) == ""


def test_parse_mcp_result_handles_list_text():
    block = type("Block", (), {"text": ["one", " two"], "data": None})()
    result = type(
        "Result",
        (),
        {"structuredContent": None, "content": [block], "isError": False},
    )()
    structured, text, is_error = _parse_mcp_result(result)
    assert structured is None
    assert text == "one two"
    assert is_error is False


def test_history_keeps_both_sides_of_the_conversation():
    """The client used to label assistant turns `agent`, and they were dropped."""
    replayed = _history_messages([
        {"role": "user", "content": "revenue by region?"},
        {"role": "assistant", "content": "North leads at $4.0M."},
        {"role": "assistant", "content": "   "},
        {"role": "system", "content": "ignored"},
    ])
    assert replayed == [
        {"role": "user", "content": "revenue by region?"},
        {"role": "assistant", "content": "North leads at $4.0M."},
    ]


def test_replayed_history_is_declared_as_real_work():
    """Without this the agent re-reads its own answer and says it made the numbers up."""
    with_history = _system_prompt(None, "", None, has_history=True)
    assert "Earlier turns in this conversation" in with_history
    assert "not as something you made up" in with_history
    assert "Earlier turns in this conversation" not in _system_prompt(None, "", None)


if __name__ == "__main__":
    tests = [
        test_as_text_handles_structured_content_blocks,
        test_as_text_hides_object_reasoning_blocks,
        test_parse_mcp_result_handles_list_text,
        test_history_keeps_both_sides_of_the_conversation,
        test_replayed_history_is_declared_as_real_work,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
