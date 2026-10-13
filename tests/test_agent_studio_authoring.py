"""Agent Studio's authoring run, as the job the studio polls.

The run used to be a stream held open for its whole length, and a run with Genie
research outlasted something between the browser and the app: the connection was
cut, the studio said "network error", and the draft was lost. It is now a job in
the shared store (`services/generation_jobs.py`) that the studio polls.

Two behaviours carried over and are pinned here. A refused parameter is learned
and the run retried, but only while nothing is on the job yet, because a poll may
already have shown it and a retry would show the same prose twice. And a draft
that can't be read says why instead of ending like a good one. These drive the
real routes with a fake agent in place of LangGraph and the model.

    PYTHONPATH=server .venv/bin/python tests/test_agent_studio_authoring.py
"""
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
            if callable(step):
                step()
                continue
            yield step, {}


class Background:
    """Stands in for FastAPI's BackgroundTasks: records what the route queues."""

    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args):
        self.tasks.append((fn, args))


def start():
    """Start a run through the route, without running it yet. Returns (job_id, background)."""
    ap.authoring_jobs.persist = False
    background = Background()
    job_id = ap.start_authoring(ap.AuthorRequest(prompt="draft me an agent"), background,
                                obo_token=None, sp_client=None)["job_id"]
    return job_id, background


def run(script):
    """Run one authoring turn; returns (the settled job, params each attempt was built with)."""
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

    job_id, background = start()
    run.job_id = job_id
    for fn, args in background.tasks:
        fn(*args)
    return ap.get_authoring(job_id), built


def reply(text):
    return AIMessageChunk(content=text, id="m1")


def test_starting_a_run_answers_at_once_with_a_job_to_poll():
    job_id, background = start()
    assert len(background.tasks) == 1
    assert ap.get_authoring(job_id) == {"status": "running", "text": "", "tool_calls": []}


def test_prose_is_on_the_job_while_the_run_is_still_going():
    seen = []
    job, _ = run(lambda p: [reply("Here is a draft. "),
                            lambda: seen.append(ap.get_authoring(run.job_id)),
                            reply('```json\n{"name": "A"}\n```')])
    assert seen[0]["status"] == "running"
    assert seen[0]["text"] == "Here is a draft. "
    assert job["status"] == "completed"
    # The JSON payload is the draft, never part of the prose.
    assert "```" not in job["text"]


def test_tool_pills_are_on_the_job():
    call = AIMessageChunk(content="", id="m1",
                          tool_call_chunks=[{"name": "run_sql", "args": "", "id": "t1", "index": 0}])
    job, _ = run(lambda p: [call, reply("Done.")])
    assert [tc["status"] for tc in job["tool_calls"]] == ["running"]


def test_stop_settles_the_run_as_cancelled_without_a_draft():
    job, _ = run(lambda p: [reply("Looking at the tables. "),
                            lambda: ap.stop_authoring(run.job_id),
                            reply('```json\n{"name": "A"}\n```')])
    assert job["status"] == "cancelled"
    assert job.get("draft") is None
    assert job["text"] == "Looking at the tables. "


def test_stopping_an_unknown_run_is_a_404():
    try:
        ap.stop_authoring("no-such-job")
    except ap.HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected a 404")


def test_refused_parameter_before_anything_is_shown_is_dropped_and_retried():
    def script(params):
        if "temperature" in params:
            return [Exception(REFUSED)]
        return [reply("Here is a draft. "), reply('```json\n{"name": "A"}\n```')]

    job, built = run(script)
    assert [("temperature" in p) for p in built] == [True, False]
    assert job["status"] == "completed"
    assert job["draft"] == {"name": "A"}
    # The prose appears once, from the attempt that worked.
    assert job["text"].count("Here is a draft.") == 1


def test_failure_after_text_was_shown_is_reported_not_retried():
    job, built = run(lambda p: [reply("Here is a draft. "), Exception(REFUSED)])
    assert len(built) == 1
    assert job["status"] == "failed"


def test_failure_after_a_tool_pill_is_reported_not_retried():
    def script(params):
        call = AIMessageChunk(content="", id="m1",
                              tool_call_chunks=[{"name": "run_sql", "args": "", "id": "t1", "index": 0}])
        return [call, Exception(REFUSED)]

    job, built = run(script)
    assert len(built) == 1
    assert job["status"] == "failed"


def test_failure_that_is_not_about_parameters_is_not_retried():
    job, built = run(lambda p: [Exception("Error code: 503 - the endpoint is scaling up")])
    assert len(built) == 1
    assert job["status"] == "failed"
    assert "scaling up" in job["error"]


def test_a_refusal_that_keeps_coming_back_stops_after_one_retry():
    job, built = run(lambda p: [Exception(REFUSED)])
    # Dropped once; the same lesson a second time means it didn't help.
    assert len(built) == 2
    assert job["status"] == "failed"


# A draft that can't be read used to end the run like a good one: the prose said
# the agent was built, the form stayed empty, and only the server log knew.

DRAFT_START = 'I built a demo agent.\n\n```json\n{"name": "Taxi", "prompt": "You answer questions about '


def final_of(script):
    job, _ = run(script)
    assert job["status"] == "completed", job
    return job


def test_a_draft_cut_off_at_the_length_limit_says_so():
    final = final_of(lambda p: [reply(DRAFT_START),
                                AIMessageChunk(content="taxi", id="m1", response_metadata={"finish_reason": "length"})])
    assert final["draft"] is None
    assert "length limit" in final["draft_error"], final["draft_error"]


def test_a_draft_that_stops_short_without_a_reason_says_it_was_cut_off():
    final = final_of(lambda p: [reply(DRAFT_START + "taxi trips")])
    assert final["draft"] is None
    assert "cut off" in final["draft_error"], final["draft_error"]


def test_a_draft_that_is_not_valid_json_says_where():
    final = final_of(lambda p: [reply('Done.\n\n```json\n{"name": "Taxi", "prompt": "Use "trips" only",}\n```')])
    assert final["draft"] is None
    assert "not valid JSON" in final["draft_error"] and "line" in final["draft_error"], final["draft_error"]


def test_a_reply_with_no_draft_in_it_is_not_an_error():
    final = final_of(lambda p: [reply("Which data should it reach: the {sales} tables or Genie?")])
    assert final["draft"] is None
    assert not final.get("draft_error")


def test_a_good_draft_has_no_error():
    final = final_of(lambda p: [reply(DRAFT_START + 'taxi trips."}\n```')])
    assert final["draft"] == {"name": "Taxi", "prompt": "You answer questions about taxi trips."}
    assert not final.get("draft_error")


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
