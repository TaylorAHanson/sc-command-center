"""Standalone tests for the guard between a model's reply and the user's widget.

`assess_rewrite` decides whether a whole-file reply is a whole widget (see
test_code_patch.py). These tests cover what the route does with that verdict: a
fragment must never be written, and the follow-up ask for edits must be able to
rescue the turn.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from routes.agent_studio import _Budget, _failure_text, _vet_rewrite, _widget_llm
except Exception as e:  # pragma: no cover - needs the backend venv (langchain, fastapi)
    print(f"SKIP test_widget_agent_rewrite: {e}")
    sys.exit(0)

WIDGET = "export default function Widget(props) {\n" + "".join(
    f"  const v{i} = {i};\n" for i in range(40)
) + '  return <div className="p-4">{v1}</div>;\n}'

# What the model sent instead of an edit: the one function it touched.
FRAGMENT = "function formatRow(row) {\n  return row.name;\n}"


class FakeLLM:
    """Records what it was asked and replies with a canned answer."""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts = []

    def invoke(self, messages):
        self.prompts.append(messages[-1].content)
        return type("Reply", (), {"content": self.reply})()


def _vet(new_code, reply="", time_left=True):
    """Run the guard. `time_left=False` stands in for a spent time budget, where the
    route hands back no client at all rather than starting another round."""
    llm = FakeLLM(reply)
    code, notes = _vet_rewrite(lambda: llm if time_left else None,
                               "system", "add sorting", "assistant reply", WIDGET, new_code)
    return code, notes, llm


def test_a_clean_rewrite_is_written_without_a_second_call():
    rewrite = WIDGET.replace("const v1 = 1;", "const v1 = 1;\n  const sorted = true;")
    code, notes, llm = _vet(rewrite)
    assert code == rewrite
    assert notes == []
    # No verdict to act on means no extra round trip.
    assert llm.prompts == []


def test_a_fragment_becomes_an_edit_when_the_model_can_supply_one():
    edit = ("<<<<<<< SEARCH\n  const v0 = 0;\n=======\n"
            "  const v0 = 0;\n  const sortKey = 'name';\n>>>>>>> REPLACE")
    code, notes, llm = _vet(FRAGMENT, reply=edit)
    # The whole widget survived and the change landed inside it.
    assert "const v39 = 39;" in code
    assert "const sortKey = 'name';" in code
    assert "targeted edit instead" in notes[0]
    # The follow-up handed the model the current code to edit against.
    assert "const v39 = 39;" in llm.prompts[0]


def test_a_fragment_the_model_will_not_fix_leaves_the_code_alone():
    code, notes, _ = _vet(FRAGMENT, reply="Sorry, here it is again:\n```tsx\n" + FRAGMENT + "\n```")
    assert code is None
    assert "unchanged" in notes[0]
    assert "exports nothing" in notes[0]


def test_a_drastic_shrink_is_written_but_says_how_to_undo_it():
    smaller = "export default function Widget() {\n  return <div>tiny</div>;\n}"
    code, notes, llm = _vet(smaller, reply="no edits here")
    assert code == smaller
    assert "History" in notes[0]
    # A complete widget, so there is nothing to ask about — "simplify this" and
    # "start over" are requests, not mistakes.
    assert llm.prompts == []


def test_failed_edits_from_the_follow_up_are_reported_not_silent():
    edit = ("<<<<<<< SEARCH\n  const nothingLikeThis = 1;\n=======\n"
            "  const other = 2;\n>>>>>>> REPLACE")
    code, notes, _ = _vet(FRAGMENT, reply=edit)
    # Nothing applied, so the fragment verdict stands and the code is kept.
    assert code is None
    assert "unchanged" in notes[0]


def test_a_spent_time_budget_still_protects_the_widget():
    edit = ("<<<<<<< SEARCH\n  const v0 = 0;\n=======\n"
            "  const v0 = 0;\n  const sortKey = 'name';\n>>>>>>> REPLACE")
    code, notes, llm = _vet(FRAGMENT, reply=edit, time_left=False)
    # There was no time to ask for edits, but the fragment must not be written
    # either — running out of time may cost the change, never the widget.
    assert code is None
    assert "unchanged" in notes[0]
    assert llm.prompts == []


def test_the_budget_stops_starting_rounds_it_cannot_finish():
    generous = _Budget(600)
    assert generous.has(15)
    # A budget with seconds left is not worth another model call.
    nearly_gone = _Budget(600)
    nearly_gone.deadline = nearly_gone.deadline - 597
    assert not nearly_gone.has(15)
    assert nearly_gone.left > 0  # still positive, just not enough to be useful
    assert nearly_gone.spent >= 597


def test_one_call_cannot_outlive_the_budget_by_retrying():
    # `timeout` is per attempt, and both langchain and the OpenAI client retry twice
    # by default — so an uncapped client could spend three times the whole allowance
    # on a single call and sail past the deadline the budget exists to hold.
    llm = _widget_llm("key", "https://example.invalid", "some-model", _Budget(600))
    assert llm.max_retries == 0
    assert llm.request_timeout > 45

    # Planning asks for less than is left, because it must leave room for the work.
    capped = _widget_llm("key", "https://example.invalid", "some-model", _Budget(600), limit=45)
    assert capped.request_timeout == 45


def test_a_timeout_says_what_to_change_and_a_normal_failure_does_not():
    spent = _Budget(300)
    spent.deadline = spent.deadline - 300

    timed_out = _failure_text(RuntimeError("Read timed out."), spent)
    assert "300s" in timed_out and "Settings" in timed_out

    # An unrelated failure is passed through, not dressed up as a timeout.
    plain = _failure_text(RuntimeError("ENDPOINT_NOT_FOUND"), _Budget(300))
    assert plain == "ENDPOINT_NOT_FOUND"


if __name__ == "__main__":
    tests = [
        test_a_clean_rewrite_is_written_without_a_second_call,
        test_a_fragment_becomes_an_edit_when_the_model_can_supply_one,
        test_a_fragment_the_model_will_not_fix_leaves_the_code_alone,
        test_a_drastic_shrink_is_written_but_says_how_to_undo_it,
        test_failed_edits_from_the_follow_up_are_reported_not_silent,
        test_a_spent_time_budget_still_protects_the_widget,
        test_the_budget_stops_starting_rounds_it_cannot_finish,
        test_one_call_cannot_outlive_the_budget_by_retrying,
        test_a_timeout_says_what_to_change_and_a_normal_failure_does_not,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
