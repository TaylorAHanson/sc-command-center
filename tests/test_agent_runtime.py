"""Standalone tests for agent runtime response normalization and stopping."""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import agent_runtime  # noqa: E402
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


# --------------------------------------------------------------- stopping a turn

class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False
        self.yielded = 0

    def __iter__(self):
        for chunk in self._chunks:
            if self.closed:
                return
            self.yielded += 1
            yield chunk

    def close(self):
        self.closed = True


def _text_chunk(text):
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=None)])


def _tool_chunk(name):
    call = SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name=name, arguments="{}"))
    delta = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason="tool_calls")])


def _run_turn(streams, should_stop):
    """Drive _run_loop offline; returns (frames, settled texts, tools run, streams)."""
    ran_tools = []
    queued = list(streams)
    patches = {
        "_obo_ws": lambda token: object(),
        "_openai_client": lambda ws, token, model: object(),
        "_model_default": lambda: "test-model",
        "_build_tools": lambda ws, profile, attachments, env: (
            [{"type": "function", "function": {"name": "lookup"}}],
            {"lookup": {"friendly": "Lookup"}},
        ),
        "_system_prompt": lambda *a, **k: "system",
        "_max_steps": lambda: 4,
        "_max_tokens": lambda: 100,
        "_stream_completion": lambda client, kwargs, request_id="": queued.pop(0),
        "_run_tool": lambda ws, desc, args: ran_tools.append(desc["friendly"]) or "42",
        "native_files": SimpleNamespace(parts=lambda model, env, attachments: []),
    }
    saved = {name: getattr(agent_runtime, name) for name in patches}
    frames, settled = [], []
    try:
        for name, value in patches.items():
            setattr(agent_runtime, name, value)
        agent_runtime._run_loop(
            lambda item: frames.append(json.loads(item[6:]) if item else None),
            obo_token=None, query="q", ui_context="", profile=None, history=None,
            on_finish=lambda text, tools, error: settled.append(text),
            should_stop=should_stop,
        )
    finally:
        for name, value in saved.items():
            setattr(agent_runtime, name, value)
    return frames, settled, ran_tools


def test_stop_mid_answer_keeps_the_partial_text_and_closes_the_stream():
    stream = _FakeStream([_text_chunk("North "), _text_chunk("leads"), _text_chunk(" by far.")])
    frames, settled, _ = _run_turn([stream], lambda: stream.yielded >= 2)
    expected = f"North leads\n\n{agent_runtime.STOPPED_MARKER}"
    assert settled == [expected]
    assert frames[-2] == {"type": "final", "content": expected}
    assert frames[-1] is None
    assert stream.closed
    assert " by far." not in json.dumps(frames)


class _StopWhenDrained(_FakeStream):
    """Presses Stop the moment the model has finished asking for a tool."""

    def __init__(self, chunks, stop):
        super().__init__(chunks)
        self._stop = stop

    def __iter__(self):
        yield from super().__iter__()
        self._stop["pressed"] = True


def test_stop_before_a_tool_runs_spends_nothing_more():
    stop = {"pressed": False}
    tool_step = _StopWhenDrained([_text_chunk("Checking."), _tool_chunk("lookup")], stop)
    _, settled, ran_tools = _run_turn([tool_step], lambda: stop["pressed"])
    assert ran_tools == []
    assert settled == [agent_runtime.STOPPED_MARKER]


def test_no_stop_means_the_turn_finishes_normally():
    frames, settled, ran_tools = _run_turn(
        [_FakeStream([_tool_chunk("lookup")]), _FakeStream([_text_chunk("It is 42.")])],
        lambda: False,
    )
    assert ran_tools == ["Lookup"]
    assert settled == ["It is 42."]


def _disconnect_outcome(stop_requested):
    """Open stream_chat, drop the client after one frame; did the loop stop?"""
    import asyncio
    import threading
    import time

    outcome = {}
    done = threading.Event()

    def fake_loop(put, *, should_stop, **_):
        put(b"data: {}\n\n")
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if should_stop():
                outcome["stopped"] = True
                break
            time.sleep(0.01)
        outcome.setdefault("stopped", False)
        put(None)
        done.set()

    async def drive():
        gen = agent_runtime.stream_chat(obo_token=None, query="q", stop_requested=stop_requested)
        await gen.__anext__()
        try:
            await gen.aclose()
        except RuntimeError:
            pass  # the trailing [DONE] yield in `finally`; the client is gone anyway

    saved = agent_runtime._run_loop
    agent_runtime._run_loop = fake_loop
    try:
        asyncio.run(drive())
        done.wait(3)
    finally:
        agent_runtime._run_loop = saved
    return outcome["stopped"]


def test_a_dropped_connection_stops_only_when_nothing_would_keep_the_answer():
    """A reload also drops the stream; a saved turn must still land unless Stop was pressed."""
    assert _disconnect_outcome(None) is True
    assert _disconnect_outcome(lambda: False) is False
    assert _disconnect_outcome(lambda: True) is True


if __name__ == "__main__":
    tests = [
        test_as_text_handles_structured_content_blocks,
        test_as_text_hides_object_reasoning_blocks,
        test_parse_mcp_result_handles_list_text,
        test_history_keeps_both_sides_of_the_conversation,
        test_replayed_history_is_declared_as_real_work,
        test_stop_mid_answer_keeps_the_partial_text_and_closes_the_stream,
        test_stop_before_a_tool_runs_spends_nothing_more,
        test_no_stop_means_the_turn_finishes_normally,
        test_a_dropped_connection_stops_only_when_nothing_would_keep_the_answer,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
