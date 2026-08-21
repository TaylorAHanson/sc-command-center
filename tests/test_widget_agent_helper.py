"""Standalone tests for the studio's cheap side-calls and size guidance.

Everything here is a step the agent is allowed to skip: refining a prompt,
compacting history, asking a question first. So the cases that matter most are
the ones where the helper model misbehaves — the turn has to carry on regardless.
No credentials needed: the helper is a plain callable the tests supply.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from services import upload_store
    from routes.widget_studio import (
        CLARIFY_MARKER,
        CLIENT_SIDE_ROW_CEILING,
        MAX_SUGGESTIONS,
        GenerateRequest,
        Message,
        _attachments,
        _extract_next,
        _clarify,
        _compact_history,
        _json_reply,
        _refine_prompt,
        _review_instruction,
        _size_guidance,
        _turn_message,
    )
except Exception as e:  # pragma: no cover - needs the backend venv (langchain, fastapi)
    print(f"SKIP test_widget_agent_helper: {e}")
    sys.exit(0)


def _req(**kwargs):
    kwargs.setdefault("prompt", "add a total row")
    return GenerateRequest(**kwargs)


def _says(payload):
    """A helper model that always answers with `payload`."""
    return lambda _messages: payload if isinstance(payload, str) else json.dumps(payload)


def _silent(_messages):
    """A helper model with no budget left, which is a supported outcome."""
    return ""


# A request long enough that `_wants_stages` calls it big, which is what gates
# the clarify pass.
BIG = (
    "Build an inventory ageing dashboard with a bucketed summary across sites, a "
    "drilldown table with search and paging, a CSV export, and a chart of the "
    "trend by month, plus the ability to click through from the chart into the "
    "table filtered to the month that was clicked and remember that selection."
)


def test_json_reply_reads_a_fenced_or_chatty_object():
    assert _json_reply('```json\n{"request": "x"}\n```', "t") == {"request": "x"}
    assert _json_reply('Sure! {"questions": []} — hope that helps.', "t") == {"questions": []}
    # Not an object, not readable, not there at all: all the same non-answer.
    assert _json_reply("[1, 2]", "t") == {}
    assert _json_reply("{nope", "t") == {}
    assert _json_reply("", "t") == {}


def test_refine_returns_empty_when_it_would_change_nothing():
    assert _refine_prompt(_says({"request": "add a total row"}), _req()) == ""
    assert _refine_prompt(_silent, _req()) == ""
    assert _refine_prompt(_says("not json"), _req()) == ""


def test_refine_rejects_a_restatement_that_stopped_being_one():
    long_ask = "make the table better in the ways we discussed earlier today please"
    # Dropped most of the request.
    assert _refine_prompt(_says({"request": "fix it"}), _req(prompt=long_ask)) == ""
    # Turned into a design document instead of a restatement.
    assert _refine_prompt(_says({"request": "x" * 5000}), _req(prompt=long_ask)) == ""
    good = "Add a footer row to the table totalling the quantity and value columns."
    assert _refine_prompt(_says({"request": good}), _req(prompt=long_ask)) == good


def test_a_compile_error_is_never_reworded():
    """The traceback is already precise, and rewriting it loses the detail."""
    called = []

    def helper(messages):
        called.append(messages)
        return json.dumps({"request": "something else"})

    assert _refine_prompt(helper, _req(error_log="Unexpected token (14:3)")) == ""
    assert not called


def test_clarify_holds_off_on_small_requests():
    """Asking about a one-line change is slower than doing it."""
    asked = _says({"questions": ["which column?"]})
    assert _clarify(asked, _req(prompt="make the header bold")) == []
    # Big enough to be worth planning is big enough to be worth asking about.
    assert _clarify(asked, _req(prompt=BIG)) == ["which column?"]


def test_clarify_cannot_ask_twice_in_a_conversation():
    asked = _says({"questions": ["which measure?"]})
    answered = _req(prompt=BIG, history=[
        Message(role="user", content="build me a dashboard"),
        Message(role="assistant", content=f"1. which measure?\n{CLARIFY_MARKER}"),
    ])
    assert _clarify(asked, answered) == []
    # And the client's own guard, for a turn that answers without the marker.
    assert _clarify(asked, _req(prompt=BIG, allow_clarify=False)) == []


def test_clarify_survives_an_unusable_answer():
    for reply in ("", "no questions!", {"questions": "which column?"}, {"questions": [1, "  "]}):
        assert _clarify(_says(reply), _req(prompt=BIG)) == []


def test_clarify_takes_at_most_three_questions():
    many = {"questions": [f"q{i}?" for i in range(9)]}
    assert _clarify(_says(many), _req(prompt=BIG)) == ["q0?", "q1?", "q2?"]


def _history(n: int, content: str = "x" * 400):
    return [Message(role="user" if i % 2 == 0 else "assistant", content=content) for i in range(n)]


def test_short_history_is_replayed_rather_than_summarised():
    called = []

    def helper(messages):
        called.append(messages)
        return "a summary"

    replayed = _compact_history(helper, _history(3, "short"))
    assert len(replayed) == 3
    assert not called  # not worth a round trip


def test_long_history_becomes_a_digest_plus_the_recent_turns():
    replayed = _compact_history(_says("They settled on POs by vendor."), _history(10))
    assert len(replayed) == 3  # digest + the last two turns verbatim
    assert "Earlier in this conversation" in replayed[0].content
    assert "They settled on POs by vendor." in replayed[0].content


def test_history_falls_back_to_the_raw_tail_when_the_summary_fails():
    replayed = _compact_history(_silent, _history(10))
    assert len(replayed) == 6
    assert all("Earlier in this conversation" not in m.content for m in replayed)


def test_size_guidance_only_speaks_about_sql():
    assert _size_guidance(_req(data_source_type="api", data_source_row_estimate=99999)) == ""
    assert _size_guidance(_req()) == ""


def test_a_big_result_set_is_told_to_work_in_the_database():
    guidance = _size_guidance(_req(data_source_type="sql", data_source_row_estimate=40000))
    assert "40,000" in guidance
    assert "LIMIT`/`OFFSET" in guidance
    # The actual reported failure: paging through everything to assemble it locally.
    assert "never the whole table in batches" in guidance


def test_a_small_result_set_is_left_to_the_browser():
    guidance = _size_guidance(_req(
        data_source_type="sql",
        data_source_row_estimate=CLIENT_SIDE_ROW_CEILING,
    ))
    assert "small enough to fetch" in guidance
    assert "round trip per keystroke" in guidance


def test_an_untested_source_is_treated_as_large():
    """Silence must not read as "small" — that is how whole tables get fetched."""
    guidance = _size_guidance(_req(data_source_type="sql"))
    assert "unknown" in guidance
    assert "potentially large" in guidance


READY = {"id": "u1", "kind": "image", "status": "ready", "filename": "shot.png",
         "mime": "image/png", "size_bytes": 512}


def test_an_attachment_is_looked_up_without_an_owner_filter():
    """A blank username is a filter that matches nobody, not a skipped check.

    The generation is a background task with no caller, so ownership is enforced
    where the id is minted. Passing `""` here found nothing and silently dropped
    every file the user attached.
    """
    seen = []

    def get_upload(env, upload_id, username=None):
        seen.append((env, upload_id, username))
        return dict(READY, id=upload_id)

    upload_store.get_upload = get_upload  # type: ignore[assignment]
    got = _attachments(_req(attachment_ids=["a", "b"], env="test"))
    assert [m["id"] for m in got] == ["a", "b"]
    assert seen == [("test", "a", None), ("test", "b", None)]


def test_a_file_still_being_read_or_missing_is_not_sent():
    def get_upload(env, upload_id, username=None):
        if upload_id == "gone":
            raise RuntimeError("no such row")
        return dict(READY, id=upload_id, status="parsing" if upload_id == "slow" else "ready")

    upload_store.get_upload = get_upload  # type: ignore[assignment]
    got = _attachments(_req(attachment_ids=["slow", "gone", "fine"]))
    assert [m["id"] for m in got] == ["fine"]


def test_a_turn_carries_its_files_and_stays_plain_without_them():
    upload_store.get_upload = lambda env, i, u=None: dict(READY, id=i)  # type: ignore[assignment]
    upload_store.load_raw = lambda env, i: b"bytes"  # type: ignore[assignment]

    plain = _turn_message("databricks-claude-sonnet-4", "dev", "make it blue", [])
    assert plain.content == "make it blue"

    with_file = _turn_message("databricks-claude-sonnet-4", "dev", "fix this", [READY])
    assert with_file.content[0] == {"type": "text", "text": "fix this"}
    assert with_file.content[1]["type"] == "image_url"


def _next_block(body):
    return f"Some prose about the widget.\n\n```widget-next\n{body}\n```"


def test_follow_ups_are_lifted_out_of_the_reply_and_the_block_disappears():
    items, prose = _extract_next(_next_block(json.dumps([
        {"kind": "idea", "label": "Sortable columns", "prompt": "Make the columns sortable."},
        {"kind": "fix", "label": "Placeholder contrast", "prompt": "Darken the placeholder."},
    ])))

    assert [i["label"] for i in items] == ["Sortable columns", "Placeholder contrast"]
    assert [i["kind"] for i in items] == ["idea", "fix"]
    # Whatever the model wrote, the user reads prose — never a JSON block.
    assert "widget-next" not in prose and prose == "Some prose about the widget."


def test_a_reply_with_no_block_is_left_exactly_as_it_was():
    items, prose = _extract_next("Nothing worth changing, and nothing worth adding.")
    assert items == []
    assert prose == "Nothing worth changing, and nothing worth adding."


def test_malformed_or_junk_follow_ups_cost_the_buttons_not_the_review():
    broken, prose = _extract_next(_next_block("{not json at all"))
    assert broken == [] and "widget-next" not in prose

    mixed, _ = _extract_next(_next_block(json.dumps([
        "a bare string",
        {"label": "No prompt"},
        {"prompt": "No label"},
        {"label": "Good", "prompt": "Do the thing.", "kind": "nonsense"},
    ])))
    # Only the usable one survives, and an unknown kind is an idea rather than a
    # fix: offering to "fix" something that isn't broken is the worse mistake.
    assert [(i["label"], i["kind"]) for i in mixed] == [("Good", "idea")]


def test_follow_ups_are_capped_and_trimmed_to_what_a_button_can_hold():
    items, _ = _extract_next(_next_block(json.dumps(
        [{"label": "L" * 200, "prompt": "P" * 900} for _ in range(9)]
    )))
    assert len(items) == MAX_SUGGESTIONS
    assert len(items[0]["label"]) == 70 and len(items[0]["prompt"]) == 400


def test_the_review_separates_defects_it_fixes_from_ideas_it_only_offers():
    text = _review_instruction(_req(prompt="supplier scorecard with a search box"))

    # The request is quoted, so "does it do what was asked" has something to check.
    assert "supplier scorecard with a search box" in text

    # Fixes stay narrow: the value of the pass is that it can be left switched on.
    assert "do not restyle, rename, reorganise or add features nobody asked for" in text

    # The product-owner half is explicitly not work, or a review starts growing
    # the widget behind the user's back.
    assert "## Worth considering" in text
    assert "do not implement them" in text

    # Both halves have to resist the same pull toward a comfortable clean pass:
    # the first by confirming each criterion it checked, the second by declining
    # to have an opinion. The observed review did both.
    assert "Do not walk back through those six confirming what is fine" in text
    assert "is this good at the job it exists to do" in text
    assert "say why you think so" in text

    # And it has to hand them over in a form the studio can put on a button,
    # otherwise the user's only way to act on a suggestion is to retype it.
    assert "```widget-next" in text
    assert "never for one you already fixed" in text

    # Legibility is enumerated rather than eyeballed. A pass that only checks the
    # colours the request drew attention to missed text-slate-400 sitting in an
    # empty state it had just called readable.
    assert "empty-state" in text and "400 or lighter" in text


if __name__ == "__main__":
    tests = [
        test_json_reply_reads_a_fenced_or_chatty_object,
        test_refine_returns_empty_when_it_would_change_nothing,
        test_refine_rejects_a_restatement_that_stopped_being_one,
        test_a_compile_error_is_never_reworded,
        test_clarify_holds_off_on_small_requests,
        test_clarify_cannot_ask_twice_in_a_conversation,
        test_clarify_survives_an_unusable_answer,
        test_clarify_takes_at_most_three_questions,
        test_short_history_is_replayed_rather_than_summarised,
        test_long_history_becomes_a_digest_plus_the_recent_turns,
        test_history_falls_back_to_the_raw_tail_when_the_summary_fails,
        test_size_guidance_only_speaks_about_sql,
        test_a_big_result_set_is_told_to_work_in_the_database,
        test_a_small_result_set_is_left_to_the_browser,
        test_an_untested_source_is_treated_as_large,
        test_an_attachment_is_looked_up_without_an_owner_filter,
        test_a_file_still_being_read_or_missing_is_not_sent,
        test_a_turn_carries_its_files_and_stays_plain_without_them,
        test_follow_ups_are_lifted_out_of_the_reply_and_the_block_disappears,
        test_a_reply_with_no_block_is_left_exactly_as_it_was,
        test_malformed_or_junk_follow_ups_cost_the_buttons_not_the_review,
        test_follow_ups_are_capped_and_trimmed_to_what_a_button_can_hold,
        test_the_review_separates_defects_it_fixes_from_ideas_it_only_offers,
    ]
    original = (upload_store.get_upload, upload_store.load_raw)
    try:
        for test in tests:
            test()
            print(f"PASS {test.__name__}")
    finally:
        upload_store.get_upload, upload_store.load_raw = original
