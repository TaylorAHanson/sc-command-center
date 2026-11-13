"""Tests for the chat agent's email tool (services/email_tool.py) and its switch.

No network and no database. Pinned here:

- the switch: `builtin/send_email` among an agent's tools adds the tool, it is
  not a curated MCP list (the default catalog still comes), it is never looked
  up as an MCP server, and the external runtime is never sent it;
- that the tool only drafts: content problems go back to the model to fix, a
  To line outside the policy still drafts (the person fixes it in the dialog),
  and email being off or no signed-in sender drafts nothing;
- that the draft rides on the turn's tool entry through the loop;
- that a sent draft is found on its turn and the replay tells the agent so.
"""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    import agent_studio_store as store
    from routes import agent_studio_profiles
    from services import agent_runtime, conversation_store, email_service, email_tool, settings_store
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_email_tool: {e}")
    sys.exit(0)

# Built-in defaults for every setting, rather than a database this test hasn't got.
settings_store._read_rows = lambda: {}
settings_store.invalidate()

ME = "ana@example.com"


class Patched:
    def __init__(self, target, **values):
        self.target, self.values, self.saved = target, values, {}

    def __enter__(self):
        for name, value in self.values.items():
            self.saved[name] = getattr(self.target, name)
            setattr(self.target, name, value)
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(self.target, name, value)


def email_ready(transport="ses", allowed=()):
    settings = email_service.Settings(True, "cc@example.com", list(allowed), 10, 50)
    return Patched(email_service, current_transport=lambda: transport, current_settings=lambda: settings)


# --- the switch -----------------------------------------------------------------

def test_built_in_ids_are_split_from_mcp_ids():
    assert store.split_builtin_tools(["sql/execute_sql", "builtin/send_email", "genie/genie_ask"]) == (
        ["sql/execute_sql", "genie/genie_one"], ["builtin/send_email"])
    assert store.upstream_tool_ids(["builtin/send_email", "genie/genie_one"]) == ["genie/genie_ask"]


def build(tools):
    asked = []

    def discover(ws, servers=None, **kw):
        asked.append(list(servers or []))
        return [{"id": "sql/execute_sql", "name": "execute_sql", "server": "/api/2.0/mcp/sql",
                 "description": "Run SQL", "input_schema": {"type": "object", "properties": {}}}]

    with Patched(agent_studio_profiles, discover_mcp_tools=discover):
        specs, dispatch = agent_runtime._build_tools(object(), {"tools": tools})
    return [s["function"]["name"] for s in specs], dispatch, asked


def test_switched_on_the_tool_is_offered_and_the_catalog_stays():
    names, dispatch, asked = build(["builtin/send_email"])
    assert "send_email" in names and dispatch["send_email"]["kind"] == "email"
    # Still the default catalog, and no MCP server named `builtin` looked up.
    assert any("execute_sql" in n for n in names)
    assert asked == [[]]


def test_switched_off_there_is_no_email_tool():
    for tools in ([], ["sql/execute_sql"]):
        names, dispatch, _ = build(tools)
        assert "send_email" not in names and "send_email" not in dispatch


def test_with_a_curated_list_it_rides_alongside():
    names, _, _ = build(["sql/execute_sql", "builtin/send_email"])
    assert "send_email" in names and any("execute_sql" in n for n in names)


# --- drafting -------------------------------------------------------------------

def test_a_draft_is_checked_and_handed_over_unsent():
    with email_ready():
        text, draft = email_tool.draft(ME, {
            "to": ["bob@example.com"], "subject": "Q3", "message": "Up **4%**",
            "tables": [{"title": "West", "columns": ["a"], "rows": [[1]]}], "attach_csv": True,
            "attachments": [{"filename": "n.txt", "content": "hi", "data": "ignored"}]})
    assert draft["to"] == ["bob@example.com"] and draft["subject"] == "Q3" and draft["attach_csv"] is True
    # Only text, whatever else the model sent along.
    assert draft["attachments"] == [{"filename": "n.txt", "content": "hi"}]
    assert len(draft["id"]) == 32
    assert "NOT been sent" in text and "never say it was sent" in text


def test_the_model_can_attach_text_files_only():
    with email_ready():
        text, draft = email_tool.draft(ME, {"subject": "x", "message": "y",
                                            "attachments": [{"filename": "chart.png", "data": "AAAA"}]})
    assert draft is None and "only text files can be attached" in text and "chart.png" in text


def test_content_problems_go_back_to_the_model():
    with email_ready():
        text, draft = email_tool.draft(ME, {"subject": "", "message": "hi"})
        assert draft is None and "Add a subject." in text and "call send_email again" in text
        text, draft = email_tool.draft(ME, {"subject": "x", "attachments": [{"filename": "a.pdf", "content": "x"}]})
        assert draft is None and "only .csv" in text


def test_a_recipient_problem_still_drafts():
    with email_ready():
        text, draft = email_tool.draft(ME, {"to": ["eve@other.com"], "subject": "x", "message": "y"})
    assert draft is not None and "fix the To line" in text and "your own domain (example.com)" in text
    with email_ready():
        text, draft = email_tool.draft(ME, {"subject": "x", "message": "y"})
    assert draft is not None and "no recipients yet" in text


def test_nothing_is_drafted_when_email_is_off_or_nobody_is_signed_in():
    with email_ready(transport="off"):
        text, draft = email_tool.draft(ME, {"subject": "x", "message": "y"})
    assert draft is None and text.startswith(email_service.UNAVAILABLE)
    with email_ready():
        text, draft = email_tool.draft("unknown", {"subject": "x", "message": "y"})
    assert draft is None and "signed-in person" in text


def test_draft_never_raises():
    def broken():
        raise RuntimeError("settings unreadable")

    with Patched(email_service, current_transport=broken):
        text, draft = email_tool.draft(ME, {"subject": "x"})
    assert draft is None and "couldn't be drafted" in text


# --- through the loop -----------------------------------------------------------

def test_the_draft_rides_on_the_turns_tool_entry():
    call = SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="send_email", arguments="{}"))
    tool_step = [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=[call]),
                                                          finish_reason="tool_calls")])]
    answer = [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Ready to review.",
                                                                             tool_calls=None),
                                                       finish_reason="stop")])]
    queued = [tool_step, answer]
    draft = {"id": "d" * 32, "subject": "Q3"}
    frames, finished = [], []
    with Patched(agent_runtime,
                 _obo_ws=lambda token: object(), _openai_client=lambda ws, token, model: object(),
                 _model_default=lambda: "m", _system_prompt=lambda *a, **k: "s", _max_steps=lambda: 3,
                 _max_tokens=lambda: 10, _stream_completion=lambda client, kwargs, request_id="": queued.pop(0),
                 _build_tools=lambda ws, profile, attachments, env: (
                     [email_tool.tool_spec()], {"send_email": {"kind": "email", "friendly": email_tool.FRIENDLY}}),
                 native_files=SimpleNamespace(parts=lambda model, env, attachments: [])), \
            Patched(email_tool, draft=lambda sender, args: ("handed over", draft)):
        agent_runtime._run_loop(lambda item: frames.append(json.loads(item[6:]) if item else None),
                                obo_token=None, query="email it", ui_context="", profile=None, history=None,
                                on_finish=lambda text, tools, error: finished.append(tools))
    tool_frames = [f for f in frames if f and f["type"] == "tool_calls"]
    assert tool_frames[0]["content"] == [{"tool_name": "Drafting an email", "status": "done", "email_draft": draft}]
    assert finished == [[{"tool_name": "Drafting an email", "status": "done", "email_draft": draft}]]


# --- after the person sends -----------------------------------------------------

def test_a_sent_draft_is_found_on_its_turn():
    calls = json.dumps([{"tool_name": "Lookup"}, {"tool_name": "Drafting an email", "email_draft": {"id": "abc12345"}}])
    marked = conversation_store.mark_draft_entries(calls, "abc12345", {"status": "sent", "recipients": ["b@x.com"]})
    assert marked[1]["email_sent"] == {"status": "sent", "recipients": ["b@x.com"]} and "email_sent" not in marked[0]
    assert conversation_store.mark_draft_entries(calls, "nope0000", {}) is None
    assert conversation_store.mark_draft_entries("not json", "abc12345", {}) is None
    # Nothing that isn't a draft id reaches the query.
    assert conversation_store.mark_email_draft("prod", ME, "c1", "%' OR '1'='1", "sent", []) is False


def test_the_replay_tells_the_agent_what_became_of_it():
    pending = json.dumps([{"tool_name": "Drafting an email", "email_draft": {"id": "a"}}])
    sent = json.dumps([{"tool_name": "Drafting an email", "email_draft": {"id": "a"},
                        "email_sent": {"status": "sent", "recipients": ["b@x.com"]}}])
    assert conversation_store.with_tool_evidence("assistant", "Done.", pending).endswith(
        "[tools used: Drafting an email (not sent yet: the person hasn't sent it)]")
    assert conversation_store.with_tool_evidence("assistant", "Done.", sent).endswith(
        "[tools used: Drafting an email (the person sent it to b@x.com)]")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
