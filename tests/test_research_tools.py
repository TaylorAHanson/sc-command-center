"""Tests for the studios' research tools (read-only SQL and Genie, as the user).

Pinned: nothing that writes is ever sent, a query can't pull a whole table into
the prompt, a clipped result says it was clipped, an admin switch removes the tool
rather than leaving it to fail, and Widget Studio's planned runs only pay for a
research round when the request points at data.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from services import research_tools as rt
    from routes.widget_studio import GenerateRequest, _wants_research
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_research_tools: {e}")
    sys.exit(0)


class ExplodingClient:
    """A client that fails the test if anything reaches the warehouse."""

    class _Exec:
        def execute_statement(self, **_):
            raise AssertionError("a refused statement was sent")

    statement_execution = _Exec()


def test_writes_are_refused_before_anything_is_sent():
    for sql in ("DELETE FROM a.b.c", "select 1; drop table x", "MERGE INTO t USING s ON 1=1"):
        assert rt.run_sql(ExplodingClient(), sql).startswith("run_sql only reads"), sql


def test_an_empty_query_is_refused():
    assert rt.run_sql(ExplodingClient(), "  ") == "run_sql needs a query."


def test_selects_are_bounded():
    assert rt.bounded_query("SELECT * FROM a.b.c;", 50) == "SELECT * FROM (SELECT * FROM a.b.c) AS _research LIMIT 50"


def test_a_query_with_its_own_limit_is_left_alone():
    assert rt.bounded_query("select x from t limit 5", 50) == "select x from t limit 5"


def test_show_and_describe_are_not_wrapped():
    # They cannot sit in a subquery.
    assert rt.bounded_query("DESCRIBE TABLE a.b.c", 50) == "DESCRIBE TABLE a.b.c"
    assert rt.bounded_query("SHOW TABLES IN a.b", 50) == "SHOW TABLES IN a.b"


def test_row_counts_are_clamped():
    assert rt.clamp_rows(10_000) == rt.MAX_ROWS
    assert rt.clamp_rows(0) == 1
    assert rt.clamp_rows("lots") == rt.DEFAULT_ROWS


def test_results_render_as_a_table_with_safe_cells():
    out = rt.format_result(["a", "b"], [[1, "x|y"], [None, "line\nbreak"]], limit=50)
    assert "| a | b |" in out and "x\\|y" in out and "NULL" in out and "line break" in out


def test_hitting_the_row_limit_is_said_aloud():
    out = rt.format_result(["a"], [[i] for i in range(5)], limit=5)
    assert "may be more" in out


def test_a_clipped_result_says_how_much_is_missing():
    rows = [["x" * 70] for _ in range(200)]
    out = rt.format_result(["a"], rows, limit=200, max_chars=2000)
    assert "showing" in out and "of 200 rows" in out and len(out) < 2400


def test_no_rows_still_names_the_columns():
    assert rt.format_result(["a", "b"], [], limit=5) == "No rows. Columns: a, b"


def with_switches(sql, genie, fn):
    original = rt.enabled_tools
    rt.enabled_tools = lambda: {"run_sql": sql, "ask_genie": genie}
    try:
        return fn()
    finally:
        rt.enabled_tools = original


def test_admin_switches_remove_the_tools():
    names = lambda: [t.name for t in rt.langchain_tools(object())]
    assert with_switches(True, True, names) == ["run_sql", "ask_genie"]
    assert with_switches(False, True, names) == ["ask_genie"]
    assert with_switches(False, False, names) == []


def test_the_prompt_only_mentions_tools_that_are_bound():
    section = with_switches(True, False, lambda: rt.prompt_section(rt.langchain_tools(object())))
    assert "run_sql" in section and "ask_genie" not in section
    assert rt.prompt_section([]) == ""


def test_no_user_client_means_no_tools():
    # A caller that predates research tools passes nothing and gets nothing.
    assert rt.langchain_tools(None) == []


def test_a_tool_out_of_time_declines_instead_of_starting():
    tools = with_switches(True, False, lambda: rt.langchain_tools(ExplodingClient(), seconds_left=lambda: 3))
    assert tools[0].invoke({"query": "select 1"}).startswith("No time left")


def test_genie_gets_the_question_and_the_callers_clock():
    seen = {}

    class Client:
        def call_tool(self, name, args):
            seen.setdefault("calls", []).append((name, args))
            raise RuntimeError("stop here")

    original = rt._genie_client
    rt._genie_client = lambda ws: Client()
    try:
        out = rt.ask_genie(object(), "what counts as late?", timeout=30)
    finally:
        rt._genie_client = original
    assert seen["calls"][0] == ("genie_ask", {"question": "what counts as late?"})
    assert out.startswith("Genie is unavailable")


def wants(prompt, **kw):
    return _wants_research(GenerateRequest(prompt=prompt, **kw))


def test_a_named_table_triggers_research():
    assert wants("late shipments by week from main.supply.shipments, with a filter and an export")
    assert wants("use `my-cat`.sales.`order lines`")


def test_code_that_looks_like_a_table_does_not():
    # `props.data.username` is in half the requests people type.
    assert not wants("greet props.data.username and also show window.location.href")


def test_asking_for_genie_triggers_research():
    assert wants("ask Genie what late means and build a chart of it")


def test_styling_does_not():
    assert not wants("make the header blue and the table striped")


def test_fixing_a_compile_error_never_researches():
    assert not wants("fix main.supply.shipments usage", error_log="SyntaxError")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
