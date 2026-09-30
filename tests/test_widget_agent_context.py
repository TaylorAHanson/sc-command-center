"""Standalone tests for what Widget Studio's agent is shown about the running widget.

The agent writes code it never sees run: the browser compiles it, mounts it and
calls the data source. These cover the channel back — sample rows from the tested
source, what happened when the widget last ran, the studio's pattern checks, and
a screenshot — and that each arrives bounded, only when it applies, and pointed
at the right action. Also the data-source test, which runs as the user and must
never execute a write or fetch an arbitrary URL on the server, and the helper
model's no-reasoning default with its fallbacks.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from fastapi import HTTPException
    from routes import widget_studio
    from routes.widget_studio import (
        DataSourceTestRequest,
        GenerateRequest,
        MAX_RUNTIME_LINES,
        _build_system_prompt,
        _column_names,
        _column_types,
        _endpoint_missing,
        _helper_params,
        _probe_statement,
        _review_instruction,
        _sample_rows,
        _sql_check_hint,
        test_datasource as run_datasource_test,
    )
    from services import llm_params, native_files
except Exception as e:  # pragma: no cover - needs the backend venv (langchain, fastapi)
    print(f"SKIP test_widget_agent_context: {e}")
    sys.exit(0)

WIDGET = "export default function Widget(props) {\n  return <div className=\"p-4\" />;\n}"
PNG = "data:image/png;base64," + "iVBORw0KGgo" * 10


def req(**fields):
    fields.setdefault("prompt", "make it better")
    return GenerateRequest(**fields)


# --------------------------------------------------------------- the prompt

def test_sample_rows_reach_the_prompt_clipped():
    long = "x" * 500
    prompt = _build_system_prompt(req(data_source_sample=[{"id": 1, "note": long}] * 9))
    assert "These rows came back when the data source was tested" in prompt
    assert prompt.count('"id": 1') == 5
    assert long not in prompt and "…" in prompt


def test_runtime_and_lint_only_ride_along_with_code_they_describe():
    extra = {"runtime_log": ["/api/sql/execute-raw returned HTTP 400"], "lint_findings": ["line 3: error [x] y"]}
    without_code = _build_system_prompt(req(**extra))
    assert "last time it ran" not in without_code
    assert "automated checks flag" not in without_code

    with_code = _build_system_prompt(req(current_code=WIDGET, **extra))
    assert "last time it ran in the studio's preview" in with_code
    assert "returned HTTP 400" in with_code
    assert "automated checks flag" in with_code and "line 3: error [x] y" in with_code


def test_the_runtime_log_is_bounded_even_if_the_browser_sends_more():
    lines = [f"entry {i} " + "y" * 2000 for i in range(100)]
    prompt = _build_system_prompt(req(current_code=WIDGET, runtime_log=lines))
    assert "entry 99" in prompt and f"entry {99 - MAX_RUNTIME_LINES}" not in prompt
    assert "y" * 700 not in prompt


def test_only_an_agent_that_can_run_sql_is_told_to_check_its_sql():
    assert _sql_check_hint([]) == ""
    assert _sql_check_hint([SimpleNamespace(name="ask_genie")]) == ""
    hint = _sql_check_hint([SimpleNamespace(name="run_sql")])
    assert "run_sql" in hint and "never run an INSERT" in hint


def test_the_review_points_at_evidence_only_when_there_is_some():
    plain = _review_instruction(req(current_code=WIDGET))
    assert "screenshot" not in plain and "automated checks" not in plain

    full = _review_instruction(
        req(current_code=WIDGET, runtime_log=["HTTP 400"], lint_findings=["line 1: warning [x] y"]),
        screenshot=True,
    )
    assert "screenshot of the widget as it rendered" in full
    assert "last ran in the preview" in full
    assert "automated checks flagged" in full
    # The two-part structure it had is intact.
    assert "## What's wrong" in full and "## Worth considering" in full


# --------------------------------------------------------- the screenshot

def test_a_screenshot_goes_only_to_a_model_that_reads_images_and_only_as_an_image():
    assert native_files.image_part("databricks-claude-sonnet-4-6", PNG) == {
        "type": "image_url", "image_url": {"url": PNG},
    }
    assert native_files.image_part("databricks-meta-llama-3-3-70b", PNG) is None
    assert native_files.image_part("databricks-claude-sonnet-4-6", None) is None
    assert native_files.image_part("databricks-claude-sonnet-4-6", "data:text/html;base64,PGgxPg==") is None
    assert native_files.image_part("databricks-claude-sonnet-4-6", "https://example.com/x.png") is None


def test_an_oversized_screenshot_is_left_off():
    os.environ["AGENT_RUNTIME_NATIVE_FILE_MB"] = "1"
    try:
        huge = "data:image/png;base64," + "A" * (2 * 1024 * 1024)
        assert native_files.image_part("databricks-claude-sonnet-4-6", huge) is None
    finally:
        del os.environ["AGENT_RUNTIME_NATIVE_FILE_MB"]


def test_the_turn_message_carries_the_screenshot():
    message = widget_studio._turn_message("databricks-claude-sonnet-4-6", "dev", "fix it", [], PNG)
    assert isinstance(message.content, list)
    assert message.content[0] == {"type": "text", "text": "fix it"}
    assert message.content[-1]["image_url"]["url"] == PNG
    assert widget_studio._turn_message("databricks-claude-sonnet-4-6", "dev", "fix it", []).content == "fix it"


# ------------------------------------------------------- the data-source test

def test_column_types_come_from_the_manifest_not_the_values():
    manifest = SimpleNamespace(schema=SimpleNamespace(columns=[
        SimpleNamespace(name="qty", type_text="int", type_name=None),
        SimpleNamespace(name="price", type_text="decimal(10,2)", type_name=None),
        SimpleNamespace(name="shipped", type_text=None, type_name=SimpleNamespace(value="DATE")),
        SimpleNamespace(name="mystery", type_text=None, type_name=None),
    ]))
    assert _column_types(manifest) == {
        "qty": "INT", "price": "DECIMAL(10,2)", "shipped": "DATE", "mystery": "STRING",
    }
    assert _column_types(None) == {}


def test_sample_rows_are_few_and_cut():
    rows = _sample_rows(["a", "b"], [["1", "z" * 500]] * 20 + [["short"]])
    assert len(rows) == 5
    assert rows[0]["a"] == "1" and len(rows[0]["b"]) == 200 and rows[0]["b"].endswith("…")
    assert _sample_rows(["a"], None) == []


def test_a_repeated_column_name_does_not_shift_the_values_after_it():
    # SELECT o.id, c.id, o.qty ... — the type map has two keys, the row has three values.
    manifest = SimpleNamespace(schema=SimpleNamespace(columns=[
        SimpleNamespace(name="id", type_text="int", type_name=None),
        SimpleNamespace(name="id", type_text="int", type_name=None),
        SimpleNamespace(name="qty", type_text="int", type_name=None),
    ]))
    assert _column_names(manifest) == ["id", "id", "qty"]
    rows = _sample_rows(_column_names(manifest), [["1", "77", "5"]])
    assert rows[0]["qty"] == "5"


def test_a_poll_gets_a_copy_it_can_encode_while_the_job_keeps_changing():
    from services.generation_jobs import JobStore

    store = JobStore()
    store.persist = False
    store.create("j", {"status": "running", "trace": []})
    seen = store.snapshot("j")
    store.update("j", stages=[{"title": "a"}])
    assert "stages" not in seen
    assert store.snapshot("j")["stages"] == [{"title": "a"}]


def test_the_probe_bounds_a_query_and_survives_a_trailing_comment():
    probe = _probe_statement("SELECT * FROM t -- newest first")
    assert probe.startswith("SELECT * FROM (\n") and probe.endswith(") AS _schema_probe LIMIT 5")
    assert "\n) AS" in probe
    assert _probe_statement("WITH x AS (SELECT 1) SELECT * FROM x").endswith("LIMIT 5")
    assert _probe_statement("SHOW TABLES IN main.default") == "SHOW TABLES IN main.default"


def test_a_write_is_never_run_to_test_it():
    # No client at all: reaching the warehouse would raise.
    out = run_datasource_test(DataSourceTestRequest(data_source_type="sql",
                                                    data_source="MERGE INTO t USING s ON t.id = s.id"),
                              db_client=None)
    assert out["schema"] is None and out["sample"] == []
    assert "MERGE" in out["note"] and "not run" in out["note"]


def test_an_empty_statement_is_refused():
    try:
        run_datasource_test(DataSourceTestRequest(data_source_type="sql", data_source="  ;  "), db_client=None)
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("an empty statement must be refused")


def test_an_external_api_is_not_fetched_by_the_server():
    try:
        run_datasource_test(DataSourceTestRequest(data_source_type="api",
                                                  data_source="http://169.254.169.254/latest/meta-data"),
                            db_client=None)
    except HTTPException as exc:
        assert exc.status_code == 400 and "browser" in exc.detail
    else:
        raise AssertionError("the server must not fetch an arbitrary URL")


# ------------------------------------------------------------ the helper

def test_the_helper_asks_an_openai_model_not_to_reason():
    llm_params.reset()
    assert _helper_params("system.ai.gpt-6-luna", 700).get("reasoning_effort") == "none"
    assert "reasoning_effort" not in _helper_params("databricks-claude-sonnet-4-6", 700)


def test_anything_with_a_say_about_the_effort_wins_over_the_default():
    model = "system.ai.gpt-6-luna"
    llm_params.reset()

    # The endpoint refused the parameter: never sent again.
    llm_params.adapt(model, "Unsupported parameter: 'reasoning_effort'")
    assert "reasoning_effort" not in _helper_params(model, 700)
    llm_params.reset()

    # An admin named it, including "never send it".
    original = llm_params.configured
    try:
        llm_params.configured = lambda m: {"reasoning_effort": None}
        assert "reasoning_effort" not in _helper_params(model, 700)
        llm_params.configured = lambda m: {"reasoning_effort": "low"}
        assert _helper_params(model, 700).get("reasoning_effort") != "none"
    finally:
        llm_params.configured = original

    # The model refused the value "none" earlier in this process.
    widget_studio._helper_no_effort.add(model)
    try:
        assert "reasoning_effort" not in _helper_params(model, 700)
    finally:
        widget_studio._helper_no_effort.discard(model)


def test_a_helper_the_workspace_does_not_serve_falls_back_to_the_generation_model():
    original = widget_studio.get_setting
    settings = {"widget_helper_model": "system.ai.gpt-6-luna", "widget_model": "databricks-claude-sonnet-4-6"}
    widget_studio.get_setting = lambda key: settings.get(key, "")
    try:
        assert widget_studio._helper_model() == "system.ai.gpt-6-luna"
        widget_studio._helper_missing["system.ai.gpt-6-luna"] = widget_studio.time.monotonic() + 60
        assert widget_studio._helper_model() == "databricks-claude-sonnet-4-6"
        widget_studio._helper_missing["system.ai.gpt-6-luna"] = widget_studio.time.monotonic() - 1
        assert widget_studio._helper_model() == "system.ai.gpt-6-luna"
    finally:
        widget_studio.get_setting = original
        widget_studio._helper_missing.clear()


def test_a_missing_endpoint_is_told_apart_from_other_failures():
    assert _endpoint_missing(RuntimeError("ENDPOINT_NOT_FOUND: system.ai.gpt-6-luna"))
    assert _endpoint_missing(type("NotFoundError", (Exception,), {})("404"))
    assert not _endpoint_missing(RuntimeError("Read timed out."))
    assert not _endpoint_missing(RuntimeError("reasoning_effort: 'none' is not one of low, medium, high"))


if __name__ == "__main__":
    tests = [
        test_sample_rows_reach_the_prompt_clipped,
        test_runtime_and_lint_only_ride_along_with_code_they_describe,
        test_the_runtime_log_is_bounded_even_if_the_browser_sends_more,
        test_only_an_agent_that_can_run_sql_is_told_to_check_its_sql,
        test_the_review_points_at_evidence_only_when_there_is_some,
        test_a_screenshot_goes_only_to_a_model_that_reads_images_and_only_as_an_image,
        test_an_oversized_screenshot_is_left_off,
        test_the_turn_message_carries_the_screenshot,
        test_column_types_come_from_the_manifest_not_the_values,
        test_sample_rows_are_few_and_cut,
        test_a_repeated_column_name_does_not_shift_the_values_after_it,
        test_a_poll_gets_a_copy_it_can_encode_while_the_job_keeps_changing,
        test_the_probe_bounds_a_query_and_survives_a_trailing_comment,
        test_a_write_is_never_run_to_test_it,
        test_an_empty_statement_is_refused,
        test_an_external_api_is_not_fetched_by_the_server,
        test_the_helper_asks_an_openai_model_not_to_reason,
        test_anything_with_a_say_about_the_effort_wins_over_the_default,
        test_a_helper_the_workspace_does_not_serve_falls_back_to_the_generation_model,
        test_a_missing_endpoint_is_told_apart_from_other_failures,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
