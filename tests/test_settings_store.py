"""Standalone tests for the admin-settable deployment settings.

Covers the parts that need no database: precedence between a stored row, an env var
and the built-in default; what an admin is allowed to save; and the
model-name-to-base-path derivation that keeps AI Gateway names off the
serving-endpoints route (posting one there returns ENDPOINT_NOT_FOUND).
"""
import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import settings_store  # noqa: E402
from services.settings_store import (  # noqa: E402
    AI_GATEWAY_BASE_PATH,
    GENIE_ONE_SERVER,
    SERVING_BASE_PATH,
    SETTING_SPECS,
    base_path_for_model,
    get_host_list_setting,
    get_mcp_server_list,
    get_int_setting,
    get_setting,
    validate_value,
)

CHAT_MODEL_ENV = SETTING_SPECS["chat_model"].env


@contextmanager
def stored(rows, env=None):
    """Run with `rows` standing in for the settings table and `env` for the process
    environment, so these tests never need Lakebase or a real deployment."""
    original_reader = settings_store._read_rows
    original_env = {key: os.environ.get(key) for key in (env or {})}
    settings_store._read_rows = lambda: rows
    settings_store.invalidate()
    for key, value in (env or {}).items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        settings_store._read_rows = original_reader
        settings_store.invalidate()
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_falls_back_to_the_built_in_default():
    with stored({}, {CHAT_MODEL_ENV: None}):
        assert get_setting("chat_model") == SETTING_SPECS["chat_model"].default


def test_env_var_beats_the_default():
    with stored({}, {CHAT_MODEL_ENV: "databricks-gpt-5-mini"}):
        assert get_setting("chat_model") == "databricks-gpt-5-mini"


def test_stored_row_beats_the_env_var():
    with stored({"chat_model": "system.ai.claude-opus-5"}, {CHAT_MODEL_ENV: "databricks-gpt-5-mini"}):
        assert get_setting("chat_model") == "system.ai.claude-opus-5"


def test_a_blank_stored_row_does_not_shadow_the_env_var():
    # Clearing a setting in the UI deletes the row, but a row that somehow holds
    # whitespace must not pin the deployment to an empty model name.
    with stored({"chat_model": "   "}, {CHAT_MODEL_ENV: "databricks-gpt-5-mini"}):
        assert get_setting("chat_model") == "databricks-gpt-5-mini"


def test_a_failed_read_still_yields_a_usable_model():
    def boom():
        raise RuntimeError("lakebase asleep")

    original = settings_store._read_rows
    os_value = os.environ.pop(CHAT_MODEL_ENV, None)
    settings_store._read_rows = boom
    settings_store.invalidate()
    try:
        # A settings outage has to degrade to the old behavior, not break chat.
        assert get_setting("chat_model") == SETTING_SPECS["chat_model"].default
    finally:
        settings_store._read_rows = original
        settings_store.invalidate()
        if os_value is not None:
            os.environ[CHAT_MODEL_ENV] = os_value


def test_out_of_range_stored_limits_are_clamped():
    with stored({"chat_max_steps": "500"}):
        assert get_int_setting("chat_max_steps") == SETTING_SPECS["chat_max_steps"].maximum


def test_garbage_limit_falls_back_instead_of_raising():
    with stored({"chat_max_tokens": "lots"}):
        assert get_int_setting("chat_max_tokens") == int(SETTING_SPECS["chat_max_tokens"].default)


def test_rejects_unusable_endpoint_names():
    for raw in ("bad name", "a" * 201):
        assert validate_value("chat_model", raw)[1], raw


def test_accepts_both_naming_styles():
    for name in ("databricks-claude-sonnet-4-6", "system.ai.claude-opus-5"):
        assert validate_value("chat_model", name) == (name, None)


def test_blank_is_valid_and_means_clear_the_override():
    assert validate_value("chat_model", "  ") == ("", None)


def test_limits_are_bounded_and_coerced():
    assert validate_value("chat_max_steps", "12") == ("12", None)
    assert validate_value("chat_max_steps", 12.0) == ("12", None)
    assert validate_value("chat_max_steps", "0")[1]
    assert validate_value("chat_max_steps", "31")[1]


def test_unknown_key_is_refused():
    assert validate_value("chat_modle", "x")[1]


def test_model_parameters_must_be_an_object_per_model():
    cleaned, error = validate_value("model_params", '{"gpt-5.6-luna": {"reasoning_effort": "medium"}}')
    assert not error
    assert "reasoning_effort" in cleaned
    # A typo here would otherwise surface much later, as an agent failing.
    assert validate_value("model_params", "{not json")[1]
    assert validate_value("model_params", '{"a-model": "medium"}')[1]
    assert validate_value("model_params", '["a-model"]')[1]
    # Clearing it is how you go back to letting the app decide.
    assert validate_value("model_params", "  ") == ("", None)


def test_model_parameters_cannot_name_the_endpoint_or_the_credential():
    # This value is spread into the request next to `api_key` and `base_url`. An
    # entry naming either would send the app's own token, and every prompt, to
    # whatever host it pointed at — so the field takes tuning knobs and nothing else.
    for stray in ('{"a-model": {"base_url": "https://elsewhere/v1"}}',
                  '{"a-model": {"api_key": "sk-someone-elses"}}',
                  '{"a-model": {"model": "a-different-one"}}',
                  '{"a-model": {"messages": []}}'):
        cleaned, error = validate_value("model_params", stray)
        assert error and "Not a model parameter" in error, stray
        assert cleaned == ""


def test_base_path_follows_the_model_name():
    with stored({}, {"AGENT_RUNTIME_LLM_BASE_PATH": None}):
        assert base_path_for_model("system.ai.claude-opus-5", "AGENT_RUNTIME_LLM_BASE_PATH") == AI_GATEWAY_BASE_PATH
        assert base_path_for_model("databricks-claude-opus-5", "AGENT_RUNTIME_LLM_BASE_PATH") == SERVING_BASE_PATH


APP = "smart-system-prod-1526721948438476.aws.databricksapps.com"


def test_no_app_hosts_are_approved_by_default():
    with stored({}, {"WIDGET_APP_HOSTS": None}):
        assert get_host_list_setting("widget_app_hosts") == []


def test_app_hosts_accept_a_pasted_url_and_normalise_it():
    cleaned, error = validate_value("widget_app_hosts", f"https://{APP.upper()}/some/page?x=1\n{APP}, ")
    assert error is None and cleaned == APP


def test_a_whole_workspace_may_be_listed():
    for raw in ("*-1526721948438476.aws.databricksapps.com",
                "*-1526721948438476.7.azure.databricksapps.com"):
        assert validate_value("widget_app_hosts", raw) == (raw, None), raw


def test_a_dotted_workspace_wildcard_says_what_to_write_instead():
    # The ID is joined to the app name with a hyphen, so this form matches nothing.
    cleaned, error = validate_value("widget_app_hosts", "*.1526721948438476.aws.databricksapps.com")
    assert cleaned == "" and "*-1526721948438476.aws.databricksapps.com" in error


def test_app_hosts_refuse_anything_but_an_exact_databricks_app():
    for raw in ("*.databricksapps.com",          # every customer's apps
                "*.aws.databricksapps.com",
                "*-.aws.databricksapps.com",
                "*-abc.aws.databricksapps.com",
                "*-1526721948438476.*.databricksapps.com",
                "x*-1526721948438476.aws.databricksapps.com",
                "databricksapps.com",
                "evil.example",
                f"{APP}.evil.example",
                f"{APP}:8443",
                "a_b.aws.databricksapps.com"):
        assert validate_value("widget_app_hosts", raw)[1], raw


def test_a_stored_app_host_cannot_inject_into_the_csp_header():
    # Rows can arrive without passing validation (a data-migration import), and
    # each host is written into Content-Security-Policy.
    with stored({"widget_app_hosts": f"{APP}\nx.databricksapps.com;script-src\n*"}, {"WIDGET_APP_HOSTS": None}):
        assert get_host_list_setting("widget_app_hosts") == [APP]


MCP_ENV = SETTING_SPECS["mcp_servers"].env
WORKSPACE = "https://adb-123.11.azuredatabricks.net"


def test_the_default_mcp_servers_are_sql_and_genie_one():
    from services.agent_runtime import GENIE_ONE_PATH

    assert GENIE_ONE_SERVER == GENIE_ONE_PATH
    with stored({}, {MCP_ENV: None}):
        assert get_mcp_server_list() == ["/api/2.0/mcp/sql", GENIE_ONE_PATH]


def test_mcp_servers_accept_a_name_a_path_or_this_workspaces_url():
    with stored({}, {"DATABRICKS_HOST": WORKSPACE}):
        cleaned, error = validate_value(
            "mcp_servers",
            f"system.ai.atlassian\n/api/2.0/mcp/sql/, api/2.0/mcp/functions/main/sales\n"
            f"{WORKSPACE}/ai-gateway/mcp-services/system.ai.atlassian?x=1",
        )
    assert error is None
    assert cleaned == ("/ai-gateway/mcp-services/system.ai.atlassian\n/api/2.0/mcp/sql\n"
                       "/api/2.0/mcp/functions/main/sales")


def test_mcp_servers_refuse_anything_that_would_send_the_token_elsewhere():
    # Every listed server is opened with the signed-in user's token.
    with stored({}, {"DATABRICKS_HOST": WORKSPACE}):
        for raw in ("https://evil.example/api/2.0/mcp/sql",
                    "https://adb-999.11.azuredatabricks.net/api/2.0/mcp/sql",
                    "https://my-mcp-123.aws.databricksapps.com/mcp",
                    "atlassian",
                    "/api/2.0/sql",
                    "/api/2.0/mcp/",
                    "/api/2.0/mcp/../../oidc/token",
                    "/api/2.0/mcp/sql;x"):
            assert validate_value("mcp_servers", raw)[1], raw
    with stored({}, {"DATABRICKS_HOST": None}):
        # Without the workspace's address there is nothing to check a URL against.
        assert validate_value("mcp_servers", "https://host/api/2.0/mcp/sql")[1]


def test_a_stored_mcp_list_is_rechecked_and_an_unusable_one_falls_back():
    with stored({"mcp_servers": "system.ai.atlassian\nhttps://evil.example/x"}, {MCP_ENV: "/api/2.0/mcp/sql"}):
        assert get_mcp_server_list() == ["/ai-gateway/mcp-services/system.ai.atlassian"]
    with stored({"mcp_servers": "https://evil.example/x"}, {MCP_ENV: "/api/2.0/mcp/sql"}):
        assert get_mcp_server_list() == ["/api/2.0/mcp/sql"]


def test_the_deployments_mcp_list_may_still_name_an_app():
    app = "https://my-mcp-123.aws.databricksapps.com/mcp"
    with stored({}, {MCP_ENV: f"/api/2.0/mcp/sql,{app}"}):
        assert get_mcp_server_list() == ["/api/2.0/mcp/sql", app]


def test_explicit_base_path_env_var_wins():
    with stored({}, {"AGENT_RUNTIME_LLM_BASE_PATH": "custom/gateway"}):
        assert base_path_for_model("system.ai.claude-opus-5", "AGENT_RUNTIME_LLM_BASE_PATH") == "/custom/gateway"


if __name__ == "__main__":
    tests = [
        test_falls_back_to_the_built_in_default,
        test_env_var_beats_the_default,
        test_stored_row_beats_the_env_var,
        test_a_blank_stored_row_does_not_shadow_the_env_var,
        test_a_failed_read_still_yields_a_usable_model,
        test_out_of_range_stored_limits_are_clamped,
        test_garbage_limit_falls_back_instead_of_raising,
        test_rejects_unusable_endpoint_names,
        test_accepts_both_naming_styles,
        test_blank_is_valid_and_means_clear_the_override,
        test_limits_are_bounded_and_coerced,
        test_unknown_key_is_refused,
        test_model_parameters_must_be_an_object_per_model,
        test_model_parameters_cannot_name_the_endpoint_or_the_credential,
        test_base_path_follows_the_model_name,
        test_no_app_hosts_are_approved_by_default,
        test_app_hosts_accept_a_pasted_url_and_normalise_it,
        test_a_whole_workspace_may_be_listed,
        test_a_dotted_workspace_wildcard_says_what_to_write_instead,
        test_app_hosts_refuse_anything_but_an_exact_databricks_app,
        test_a_stored_app_host_cannot_inject_into_the_csp_header,
        test_the_default_mcp_servers_are_sql_and_genie_one,
        test_mcp_servers_accept_a_name_a_path_or_this_workspaces_url,
        test_mcp_servers_refuse_anything_that_would_send_the_token_elsewhere,
        test_a_stored_mcp_list_is_rechecked_and_an_unusable_one_falls_back,
        test_the_deployments_mcp_list_may_still_name_an_app,
        test_explicit_base_path_env_var_wins,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
