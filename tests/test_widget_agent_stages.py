"""Tests for planning a big widget request and applying it a step at a time.

What staging is for: one reply cannot cover "build a table, add filters, add export"
inside a token budget or a timeout, and when it failed the user lost the whole turn.
So the cases that matter here are about what survives — a step that fails, a plan
that can't be read, time running out, and a stop — because in every one of those the
steps that already landed must still be in the editor.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from routes import agent_studio
    from routes.agent_studio import (
        GenerateRequest,
        _Budget,
        _plan_stages,
        _run_stages,
        _wants_stages,
    )
except Exception as e:  # pragma: no cover - needs the backend venv (langchain, fastapi)
    print(f"SKIP test_widget_agent_stages: {e}")
    sys.exit(0)

WIDGET = ("export default function Widget(props) {\n"
          "  const rows = props.data.rows || [];\n"
          "  return <div className=\"p-4\">{rows.length}</div>;\n"
          "}")

PLAN = ('{"steps": [{"title": "Table", "detail": "render the rows"},'
        ' {"title": "Filters", "detail": "add a filter bar"},'
        ' {"title": "Export", "detail": "add a CSV button"}]}')


def edit(search: str, replace: str) -> str:
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"


class Model:
    """Replies from a script, one per call, and records how often it was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        self.limits = []

    def __call__(self, messages, limit=None):
        self.calls += 1
        # Planning passes a cap; a step takes whatever the budget has left.
        self.limits.append(limit)
        return self.replies.pop(0) if self.replies else ""


def run(replies, current_code=WIDGET, stages=None, seconds=600, job_id="job"):
    """Drive a staged run against a scripted model, returning (job, model)."""
    model = Model(replies)
    agent_studio.generation_jobs[job_id] = {"status": "pending", "result": None, "error": None}
    plan = stages if stages is not None else [
        {"title": "Filters", "detail": "add a filter bar"},
        {"title": "Export", "detail": "add a CSV button"},
    ]
    req = GenerateRequest(prompt="add filters and an export button", current_code=current_code)
    _run_stages(job_id, req, plan, model, lambda: None, _Budget(seconds))
    return agent_studio.generation_jobs[job_id], model


# ------------------------------------------------------------------- planning

def test_only_requests_that_ask_for_several_things_are_planned():
    assert not _wants_stages(GenerateRequest(prompt="make the header blue"))
    assert _wants_stages(GenerateRequest(prompt="add a filter bar and also a totals row; then export"))
    assert _wants_stages(GenerateRequest(prompt="Build me a dashboard. " * 12))
    # A compile-error retry is one job however long the error text is.
    assert not _wants_stages(GenerateRequest(prompt="Build me a dashboard. " * 12, error_log="SyntaxError"))


def test_a_plan_is_read_out_of_the_reply():
    stages = _plan_stages(Model([f"Here is the plan:\n```json\n{PLAN}\n```"]), "system", "do things")
    assert [s["title"] for s in stages] == ["Table", "Filters", "Export"]


def test_an_unreadable_or_single_step_plan_means_no_staging():
    # Falling back to one pass is always safe; refusing to answer is not.
    assert _plan_stages(Model(["I'll just get on with it."]), "system", "do things") == []
    assert _plan_stages(Model(['{"steps": [{"title": "Just do it"}]}']), "system", "do things") == []
    assert _plan_stages(Model(['{"steps": "nonsense"}']), "system", "do things") == []


def test_planning_cannot_spend_the_whole_allowance():
    # Uncapped, a slow plan came back with nothing left to build with: every step
    # would be skipped and the user would wait out the full timeout for no code.
    model = Model([PLAN])
    _plan_stages(model, "system", "do things")
    assert model.limits == [agent_studio.PLAN_SECONDS]


# ------------------------------------------------------------------- applying

def test_each_step_builds_on_the_last_and_lands_separately():
    job, model = run([
        edit("  const rows = props.data.rows || [];",
             "  const rows = props.data.rows || [];\n  const [q, setQ] = React.useState('');"),
        edit("  return <div className=\"p-4\">{rows.length}</div>;",
             "  return <div className=\"p-4\"><button>CSV</button>{rows.length}</div>;"),
    ])
    code = job["result"]["code"]
    assert "setQ" in code and "CSV" in code, "both steps are in the final code"
    assert [s["status"] for s in job["stages"]] == ["done", "done"]
    assert job["stage_index"] == 2
    assert model.calls == 2, "one call per step, no whole-file rewrites"


def test_progress_carries_the_code_so_the_studio_can_apply_it_as_it_goes():
    # Each step's code has to reach the client while the run is still going: that is
    # what puts every step in History and what keeps earlier work if a later step
    # fails. `stage_code` is that channel.
    seen = []
    original = agent_studio._publish

    def spy(job_id, **fields):
        if "stage_code" in fields:
            seen.append((fields.get("stage_index"), fields["stage_code"]))
        original(job_id, **fields)

    agent_studio._publish = spy
    try:
        run([
            edit("  const rows = props.data.rows || [];",
                 "  const rows = props.data.rows || [];\n  const [q, setQ] = React.useState('');"),
            edit("  return <div className=\"p-4\">{rows.length}</div>;",
                 "  return <div className=\"p-4\"><button>CSV</button>{rows.length}</div>;"),
        ])
    finally:
        agent_studio._publish = original

    assert [index for index, _ in seen] == [1, 2]
    assert "setQ" in seen[0][1] and "CSV" not in seen[0][1], "step 1 published its own code"
    assert "CSV" in seen[1][1], "step 2 published the code including its change"


def test_a_step_that_explains_itself_is_quoted_in_the_summary():
    job, _ = run([
        "Added a search box above the table.\n" +
        edit("  const rows = props.data.rows || [];",
             "  const rows = props.data.rows || [];\n  const [q, setQ] = React.useState('');"),
        "Added a CSV download button.\n" +
        edit("  return <div className=\"p-4\">{rows.length}</div>;",
             "  return <div className=\"p-4\"><button>CSV</button>{rows.length}</div>;"),
    ])
    assert "Added a search box above the table." in job["result"]["explanation"]
    assert "Added a CSV download button." in job["result"]["explanation"]


def test_a_step_that_says_nothing_is_still_accounted_for():
    # Models that reason privately answer with bare code, and the run used to
    # come back as "Worked through 2 of 2 steps" and nothing else — the plan
    # carried out invisibly. What the step was asked to do stands in for it.
    job, _ = run([
        edit("  const rows = props.data.rows || [];",
             "  const rows = props.data.rows || [];\n  const [q, setQ] = React.useState('');"),
        edit("  return <div className=\"p-4\">{rows.length}</div>;",
             "  return <div className=\"p-4\"><button>CSV</button>{rows.length}</div>;"),
    ])
    explanation = job["result"]["explanation"]
    assert "Filters" in explanation and "add a filter bar" in explanation
    assert "Export" in explanation and "add a CSV button" in explanation


def test_a_step_that_did_nothing_is_not_described_as_though_it_had():
    # The fallback speaks for steps that landed. A failed step is already named
    # in the "did not land" line, and repeating its plan as if it were done
    # would be the summary lying about the widget.
    job, _ = run([
        "",  # nothing at all: no prose, no edits
        edit("  return <div className=\"p-4\">{rows.length}</div>;",
             "  return <div className=\"p-4\"><button>CSV</button>{rows.length}</div>;"),
    ])
    explanation = job["result"]["explanation"]
    assert "add a filter bar" not in explanation
    assert "did not land" in explanation and "Filters" in explanation


def test_a_step_that_fails_does_not_take_the_rest_with_it():
    job, _ = run([
        "I could not work out how to do that.",  # no edits: nothing to apply
        edit("  return <div className=\"p-4\">{rows.length}</div>;",
             "  return <div className=\"p-4\"><button>CSV</button>{rows.length}</div>;"),
    ])
    assert [s["status"] for s in job["stages"]] == ["failed", "done"]
    assert "CSV" in job["result"]["code"], "the step that worked is still applied"
    assert "did not land" in job["result"]["explanation"]
    assert "Filters" in job["result"]["explanation"], "and the failure is named"


def test_a_step_that_raises_is_reported_rather_than_ending_the_run():
    class Angry(Model):
        def __call__(self, messages):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("upstream connect error")
            return edit("  const rows = props.data.rows || [];",
                        "  const rows = props.data.rows || [];\n  const done = true;")

    model = Angry([])
    agent_studio.generation_jobs["raise"] = {"status": "pending"}
    _run_stages("raise", GenerateRequest(prompt="two things", current_code=WIDGET),
                [{"title": "One", "detail": "a"}, {"title": "Two", "detail": "b"}],
                model, lambda: None, _Budget(600))
    job = agent_studio.generation_jobs["raise"]
    assert job["status"] == "completed"
    assert job["stages"][0]["status"] == "failed"
    assert "const done = true;" in job["result"]["code"]


def test_running_out_of_time_keeps_what_landed_and_says_what_to_do():
    budget = _Budget(600)
    model = Model([edit("  const rows = props.data.rows || [];",
                        "  const rows = props.data.rows || [];\n  const [q, setQ] = React.useState('');")])
    agent_studio.generation_jobs["slow"] = {"status": "pending"}

    # Spend the allowance during the first step, as a slow model would.
    original = agent_studio._publish

    def burn(job_id, **fields):
        if fields.get("stage_index") == 1:
            budget.deadline = budget.deadline - 600
        original(job_id, **fields)

    agent_studio._publish = burn
    try:
        _run_stages("slow", GenerateRequest(prompt="two things", current_code=WIDGET),
                    [{"title": "Filters", "detail": "a"}, {"title": "Export", "detail": "b"}],
                    model, lambda: None, budget)
    finally:
        agent_studio._publish = original

    job = agent_studio.generation_jobs["slow"]
    assert "setQ" in job["result"]["code"], "the finished step is kept"
    assert job["stages"][1]["status"] == "skipped"
    assert "Ran out of time" in job["result"]["explanation"]
    assert "timeout in Admin Panel" in job["result"]["explanation"]
    assert model.calls == 1, "no step is started that cannot finish"


def test_stopping_leaves_the_finished_steps_in_place():
    model = Model([edit("  const rows = props.data.rows || [];",
                        "  const rows = props.data.rows || [];\n  const [q, setQ] = React.useState('');")])
    agent_studio.generation_jobs["stop"] = {"status": "pending"}
    original = agent_studio._publish

    def cancel_after_first(job_id, **fields):
        if fields.get("stage_index") == 1:
            agent_studio.generation_jobs[job_id]["cancelled"] = True
        original(job_id, **fields)

    agent_studio._publish = cancel_after_first
    try:
        _run_stages("stop", GenerateRequest(prompt="two things", current_code=WIDGET),
                    [{"title": "Filters", "detail": "a"}, {"title": "Export", "detail": "b"}],
                    model, lambda: None, _Budget(600))
    finally:
        agent_studio._publish = original

    job = agent_studio.generation_jobs["stop"]
    assert "setQ" in job["result"]["code"]
    assert job["stages"][1]["status"] == "skipped"
    assert "Stopped after 1 of 2 steps" in job["result"]["explanation"]


def test_a_run_where_nothing_applied_returns_no_code_at_all():
    # The studio must keep what the user has rather than be handed the code back
    # unchanged, which would put a pointless entry in History.
    job, _ = run(["nope", "still nope"])
    assert job["result"]["code"] is None
    assert [s["status"] for s in job["stages"]] == ["failed", "failed"]


def test_a_widget_can_be_built_from_nothing_in_steps():
    whole = "```tsx\n" + WIDGET + "\n```"
    job, _ = run([whole, edit("  return <div className=\"p-4\">{rows.length}</div>;",
                              "  return <div className=\"p-4\"><button>CSV</button>{rows.length}</div>;")],
                 current_code="")
    assert "export default function Widget" in job["result"]["code"]
    assert "CSV" in job["result"]["code"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
