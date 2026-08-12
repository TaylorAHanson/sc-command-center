"""Tests for the shape of the messages we send a model.

The bug these exist for: Agent Studio on Claude Opus 5 answered every prompt with

    INVALID_PARAMETER_VALUE: Content in ChatMessage must have type in
    String or List[ContentItem]

because that model replies in content blocks and LangChain hands the text back as
a list of bare strings — `["I'll start by..."]` — which is neither of the two
things a ChatMessage accepts. Opus 4.8 replies with a plain string and was fine,
so the difference looked like a broken model rather than a broken shape.

`tools/authoring_repro.py` reproduces the original failure end to end (`RAW=1`);
these cover the repair without needing an endpoint.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services.llm_client import normalise_content, reply_text  # noqa: E402


# ------------------------------------------------- what already worked, still does

def test_a_plain_string_is_left_alone():
    assert normalise_content("hello", "assistant") == "hello"


def test_a_null_assistant_turn_stays_null():
    # An assistant that only calls tools says nothing, and the endpoint accepts
    # that; rewriting it to "" would be a change with nothing to gain.
    assert normalise_content(None, "assistant") is None


# ------------------------------------------------------------------ the failure

def test_the_list_of_bare_strings_that_broke_opus_5_becomes_a_string():
    assert normalise_content(["I'll start by discovering what's available."], "assistant") == (
        "I'll start by discovering what's available."
    )


def test_several_text_blocks_keep_their_order_and_read_as_prose():
    assert normalise_content(["First.", {"type": "text", "text": "Second."}], "assistant") == (
        "First.\n\nSecond."
    )


def test_a_models_private_reasoning_is_not_sent_back():
    # Reasoning blocks aren't a ContentItem and can't be replayed; the answer is
    # the text beside them.
    content = [
        {"type": "reasoning", "summary": [], "signature": "abc123"},
        {"type": "text", "text": "Here's the plan."},
    ]
    assert normalise_content(content, "assistant") == "Here's the plan."


def test_a_turn_that_was_only_reasoning_says_nothing_rather_than_something_invalid():
    content = [{"type": "reasoning", "summary": [], "signature": "abc123"}]
    assert normalise_content(content, "assistant") is None
    # Only an assistant may say nothing — a tool result has to be a string.
    assert normalise_content(content, "tool") == ""


def test_images_survive_and_keep_the_message_a_list():
    content = ["Look at this:", {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    assert normalise_content(content, "user") == [
        {"type": "text", "text": "Look at this:"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]


def test_anything_unexpected_is_still_sent_as_something_sendable():
    # Better a stringified oddity than a 400 nobody can read.
    assert normalise_content({"unexpected": True}, "assistant") == "{'unexpected': True}"


# ------------------------------------------------------- the client that uses it

def test_the_client_repairs_every_message_on_its_way_out():
    from services.llm_client import DatabricksChatOpenAI

    client = DatabricksChatOpenAI(api_key="x", base_url="https://example.invalid/v1", model="m")

    payload = {
        "messages": [
            {"role": "system", "content": "You help."},
            {"role": "user", "content": "test"},
            {"role": "assistant", "content": ["thinking out loud"], "tool_calls": [{"id": "1"}]},
            {"role": "tool", "tool_call_id": "1", "content": "done"},
        ]
    }
    real = type(client).__mro__[1]._get_request_payload
    type(client).__mro__[1]._get_request_payload = lambda *a, **k: payload
    try:
        out = client._get_request_payload([])
    finally:
        type(client).__mro__[1]._get_request_payload = real

    kinds = [type(m["content"]).__name__ for m in out["messages"]]
    assert kinds == ["str", "str", "str", "str"], "no message may leave as a list of strings"
    assert out["messages"][2]["content"] == "thinking out loud"


# ------------------------------------------------------- reading what comes back

class _Reply:
    """Stands in for an AIMessage, which is all `reply_text` looks at."""

    def __init__(self, content):
        self.content = content


def test_a_string_reply_reads_as_itself():
    assert reply_text(_Reply("Here is your widget.")) == "Here is your widget."


def test_a_reply_of_reasoning_then_text_reads_as_the_text():
    # What Claude Sonnet 5 sends for every Widget Studio generation. The summary
    # is empty and signed, so there is nothing to show even if we wanted to.
    reply = _Reply([
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "", "signature": "Es0F"}]},
        {"type": "text", "text": "```tsx\nexport default function W() {}\n```"},
    ])
    assert reply_text(reply) == "```tsx\nexport default function W() {}\n```"


def test_a_reply_of_bare_strings_is_not_silently_empty():
    # The shape that returned "" and left a studio to run its whole allowance and
    # display nothing at the end of it.
    assert reply_text(_Reply(["I'll add the chart ", "and wire up the data."])) == (
        "I'll add the chart and wire up the data."
    )


def test_the_pieces_of_a_split_code_block_are_joined_without_gaps():
    # Joined bare, not with blank lines: these arrive mid-token and a separator
    # would land inside the widget's source.
    reply = _Reply([{"type": "text", "text": "```tsx\nconst a"},
                    {"type": "text", "text": " = 1;\n```"}])
    assert reply_text(reply) == "```tsx\nconst a = 1;\n```"


def test_a_reply_that_says_nothing_reads_as_empty_rather_than_none():
    # Callers hand this straight to `parse_edits` and `looks_truncated`, which
    # want a string. None was never a valid answer here.
    assert reply_text(_Reply(None)) == ""
    assert reply_text(_Reply([])) == ""


def test_a_content_list_never_escapes_as_python_syntax():
    # The failure this is really guarding: `str(content)` on a list puts
    # "[{'type': 'text'..." into a widget file, and handing the list itself to
    # parse_edits raises "expected string or bytes-like object, got 'list'".
    for content in ([{"type": "text", "text": "ok"}], ["ok"], None, "ok"):
        assert isinstance(reply_text(_Reply(content)), str)
        assert not reply_text(_Reply(content)).startswith("[")


def test_the_reader_accepts_a_bare_content_value_as_well_as_a_message():
    assert reply_text(["already unwrapped"]) == "already unwrapped"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
