"""Standalone tests for agent runtime response normalization."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services.agent_runtime import _as_text, _parse_mcp_result  # noqa: E402


def test_as_text_handles_structured_content_blocks():
    value = [
        {"type": "text", "text": "Available "},
        {"type": "text", "text": ["tools", ":"]},
        {"content": " SQL"},
    ]
    assert _as_text(value) == "Available tools: SQL"


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


if __name__ == "__main__":
    tests = [test_as_text_handles_structured_content_blocks, test_parse_mcp_result_handles_list_text]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
