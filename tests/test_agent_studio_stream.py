"""Agent Studio's streamed authoring run, when the model refuses a parameter.

The stream used to be the one LLM caller in the app that didn't recover from a
refused parameter, so switching the authoring model to one that won't take, say,
`temperature` failed every draft. It now learns and retries — but only while
nothing has reached the browser, because a retry after that shows the user the
same prose twice. These drive the real route with a fake agent in place of
LangGraph and the model.

    PYTHONPATH=server server/venv/bin/python tests/test_agent_studio_stream.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import langgraph.prebuilt  # noqa: E402
from langchain_core.messages import AIMessageChunk  # noqa: E402

from routes import agent_studio_profiles as ap  # noqa: E402
from services import llm_params  # noqa: E402

MODEL = "fake-authoring-model"
REFUSED = "Error code: 400 - Unsupported parameter: 'temperature' is not supported with this model."


class FakeAgent:
    def __init__(self, script, params):
        self.script = script
        self.params = params

    async def astream(self, _inputs, stream_mode=None):
        for step in self.script(self.params):
            if isinstance(step, Exception):
                raise step
            yield step, {}


def run(script):
    """Stream one authoring run; returns (events, params each attempt was built with)."""
    built = []

    def create_react_agent(model, tools, prompt):
        built.append(model)
        return FakeAgent(script, model)

    llm_params.reset()
    llm_params._admin_overrides = lambda model: {"temperature": 0.2}
    langgraph.prebuilt.create_react_agent = create_react_agent
    ap._llm_credentials = lambda sp: ("key", "https://host/serving-endpoints")
    ap.get_agent_studio_store = lambda: type("S", (), {"_client": lambda self, t: None})()
    ap._make_tools = lambda ws, confirm: []
    ap._build_authoring_system_prompt = lambda req: "system"
    ap.get_setting = lambda key: MODEL
    ap._agent_studio_max_tokens = lambda: 1000
    ap._build_authoring_llm = lambda key, url, params: dict(params)

    async def consume():
        resp = await ap.stream_authoring(ap.AuthorRequest(prompt="draft me an agent"),
                                         obo_token=None, sp_client=None)
        frames = [f async for f in resp.body_iterator]
        events = []
        for frame in frames:
            text = frame.decode() if isinstance(frame, bytes) else frame
            if text.startswith("data: {"):
                events.append(json.loads(text[len("data: "):]))
        return events

    return asyncio.run(consume()), built


def reply(text):
    return AIMessageChunk(content=text, id="m1")


def test_refused_parameter_before_anything_streams_is_dropped_and_retried():
    def script(params):
        if "temperature" in params:
            return [Exception(REFUSED)]
        return [reply("Here is a draft. "), reply('```json\n{"name": "A"}\n```')]

    events, built = run(script)
    assert [("temperature" in p) for p in built] == [True, False]
    assert events[-1]["type"] == "final"
    assert events[-1]["draft"] == {"name": "A"}
    assert not any(e["type"] == "error" for e in events)
    # The prose streamed once, from the attempt that worked.
    assert "".join(e["content"] for e in events if e["type"] == "chunk").count("Here is a draft.") == 1


def test_failure_after_text_streamed_is_reported_not_retried():
    def script(params):
        return [reply("Here is a draft. "), Exception(REFUSED)]

    events, built = run(script)
    assert len(built) == 1
    assert events[-1]["type"] == "error"


def test_failure_after_a_tool_pill_is_reported_not_retried():
    def script(params):
        call = AIMessageChunk(content="", id="m1",
                              tool_call_chunks=[{"name": "run_sql", "args": "", "id": "t1", "index": 0}])
        return [call, Exception(REFUSED)]

    events, built = run(script)
    assert len(built) == 1
    assert events[-1]["type"] == "error"


def test_failure_that_is_not_about_parameters_is_not_retried():
    def script(params):
        return [Exception("Error code: 503 - the endpoint is scaling up")]

    events, built = run(script)
    assert len(built) == 1
    assert events[-1]["type"] == "error"
    assert "scaling up" in events[-1]["content"]


def test_a_refusal_that_keeps_coming_back_stops_after_one_retry():
    def script(params):
        return [Exception(REFUSED)]

    events, built = run(script)
    # Dropped once; the same lesson a second time means it didn't help.
    assert len(built) == 2
    assert events[-1]["type"] == "error"


if __name__ == "__main__":
    import traceback

    passed = failed = 0
    for _name, _fn in sorted(globals().items()):
        if not (_name.startswith("test_") and callable(_fn)):
            continue
        try:
            _fn()
            passed += 1
            print(f"PASS {_name}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {_name}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
