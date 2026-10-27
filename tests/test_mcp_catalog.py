"""The AI Gateway tool catalog Agent Studio and the chat runtime both read.

Discovery used to ask only the configured servers (SQL and the general Genie
server), so no Genie space ever showed up in the picker, and it dropped Genie's
poll tool outright. It now also asks each Genie space the caller can see, marks
plumbing tools `internal` rather than removing them, and caches per credential
because the chat runtime builds its tool list on every turn. These drive
`discover_mcp_tools` with a fake MCP client and a fake Genie API.

    PYTHONPATH=server .venv/bin/python tests/test_mcp_catalog.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from routes import agent_studio_profiles as ap  # noqa: E402
from services import settings_store  # noqa: E402

# No settings table here: the server list resolves to AGENT_STUDIO_MCP_SERVERS.
settings_store._read_rows = lambda: {}

ASK = "Ask Databricks Genie a question. Returns a handle; poll genie_poll_response for the answer."

GENIE_ONE = "/ai-gateway/mcp-services/system.ai.genie_one_mcp"

SERVERS = {
    GENIE_ONE: [
        ("genie_ask", ASK),
        ("genie_poll_response", "Fetch the latest state of an in-flight response."),
        ("genie_get_query_result", "Fetch the full SQL result."),
        ("genie_cancel_response", "Stop a Genie response."),
    ],
    "/api/2.0/mcp/sql": [
        ("execute_sql", "Execute a SQL query."),
        ("poll_sql_result", "Poll a DBSQL statement that is still pending."),
    ],
    "/api/2.0/mcp/genie/s1": [
        ("query_space_s1", "Ask the Supply space."),
        ("poll_response_s1", "Poll a Supply space response."),
    ],
    "/api/2.0/mcp/genie/s2": [
        ("query_space_s2", "Ask the Finance space."),
        ("poll_response_s2", "Poll a Finance space response."),
    ],
    "/api/2.0/mcp/functions/main/sales": [("lookup_order", "Look up an order.")],
    "/api/2.0/mcp/vector-search/main/docs": [("docs_index", "Search the docs index.")],
    "/api/2.0/mcp/external/jira": [("search_issues", "Search Jira.")],
}
SPACES = [("s1", "Supply"), ("s2", "Finance")]

listed = []
ap._retry_sleep = lambda seconds: None  # a failing server is retried; don't wait for it here


class FakeClient:
    def __init__(self, server_url, workspace_client):
        self.path = server_url.replace("https://host", "")

    def list_tools(self):
        listed.append(self.path)
        return [types.SimpleNamespace(name=n, description=d, inputSchema={}) for n, d in SERVERS[self.path]]


class FakeGenie:
    def list_spaces(self, page_size=None, page_token=None):
        spaces = [types.SimpleNamespace(space_id=i, title=t) for i, t in SPACES]
        return types.SimpleNamespace(spaces=spaces, next_page_token=None)


class FakeStatements:
    """Answers the information_schema read that finds schemas holding functions."""
    state = "SUCCEEDED"
    rows = [["main", "sales"], ["a b", "odd name"]]
    statements = []

    def execute_statement(self, **kwargs):
        from databricks.sdk.service.sql import StatementState

        FakeStatements.statements.append(kwargs["statement"])
        return types.SimpleNamespace(
            status=types.SimpleNamespace(state=getattr(StatementState, FakeStatements.state)),
            result=types.SimpleNamespace(data_array=FakeStatements.rows), statement_id="st1")

    def cancel_execution(self, statement_id):
        pass


class FakeVectorEndpoints:
    def list_endpoints(self):
        return [types.SimpleNamespace(name="ep1")]


class FakeVectorIndexes:
    def list_indexes(self, endpoint_name):
        return [types.SimpleNamespace(name="main.docs.handbook"), types.SimpleNamespace(name="main.docs.faq")]


class FakeConnections:
    def list(self):
        from databricks.sdk.service.catalog import ConnectionType

        mcp = {"is_mcp_connection": "true"}
        return [
            types.SimpleNamespace(name="jira", connection_type=ConnectionType.HTTP, options=mcp),
            types.SimpleNamespace(name="plain_http", connection_type=ConnectionType.HTTP, options={}),
            types.SimpleNamespace(name="warehouse", connection_type=ConnectionType.MYSQL, options=mcp),
        ]


def workspace(token="tok-a"):
    return types.SimpleNamespace(config=types.SimpleNamespace(host="https://host", token=token, auth_type="pat"),
                                 genie=FakeGenie(), statement_execution=FakeStatements(),
                                 vector_search_endpoints=FakeVectorEndpoints(),
                                 vector_search_indexes=FakeVectorIndexes(), connections=FakeConnections())


def catalog(ws=None, configured=f"{GENIE_ONE},/api/2.0/mcp/sql", **kwargs):
    sys.modules["databricks_mcp"] = types.SimpleNamespace(DatabricksMCPClient=FakeClient)
    os.environ["AGENT_STUDIO_MCP_SERVERS"] = configured
    return {t["id"]: t for t in ap.discover_mcp_tools(ws or workspace(), **kwargs)}


def fresh_start():
    ap._mcp_cache.clear()
    listed.clear()


def test_configured_servers_only_by_default():
    fresh_start()
    assert {t["source"] for t in catalog().values()} == {"genie", "sql"}


def test_every_genie_space_is_listed_with_its_title():
    fresh_start()
    tools = catalog(genie_spaces=True)
    space = tools["genie.s1/query_space_s1"]
    assert space["source"] == "genie_space" and space["server_title"] == "Supply"
    assert tools["genie.s2/query_space_s2"]["server_title"] == "Finance"


def test_genie_poll_tools_are_listed_but_internal():
    fresh_start()
    tools = catalog(genie_spaces=True)
    assert tools["genie/genie_poll_response"]["internal"] is True
    assert tools["genie.s1/poll_response_s1"]["internal"] is True
    assert tools["genie/genie_one"]["internal"] is False
    assert tools["genie/genie_cancel_response"]["internal"] is False


def test_each_ask_tool_knows_its_own_servers_poll_tool():
    fresh_start()
    tools = catalog(genie_spaces=True)
    assert tools["genie/genie_one"]["poll_tool"] == "genie_poll_response"
    assert tools["genie.s1/query_space_s1"]["poll_tool"] == "poll_response_s1"
    assert "poll_tool" not in tools["sql/execute_sql"]


def test_genie_ones_ask_tool_is_listed_as_genie_one_and_called_by_its_server_name():
    fresh_start()
    tools = catalog(genie_spaces=True)
    one = tools["genie/genie_one"]
    assert one["name"] == "genie_one" and one["upstream_name"] == "genie_ask"
    assert "genie/genie_ask" not in tools
    assert "upstream_name" not in tools["genie.s1/query_space_s1"], "a space's tools keep their own names"
    assert "upstream_name" not in tools["genie/genie_poll_response"]


def test_genie_ask_tools_say_the_app_polls_for_them():
    fresh_start()
    tools = catalog(genie_spaces=True)
    description = tools["genie/genie_one"]["description"]
    assert description == ap.GENIE_ONE_DESCRIPTION and "genie_ask" not in description
    assert "poll" in description and len(description) <= 1024, "the runtime truncates at 1024"
    assert tools["genie.s1/query_space_s1"]["description"].startswith(ap.GENIE_POLLED_NOTE)


def test_sql_poll_stays_model_facing_and_unannotated():
    fresh_start()
    tools = catalog()
    assert tools["sql/poll_sql_result"]["internal"] is False
    assert tools["sql/poll_sql_result"]["description"] == "Poll a DBSQL statement that is still pending."


def test_tool_lists_are_cached_per_credential():
    fresh_start()
    catalog()
    catalog()
    assert sorted(listed) == [GENIE_ONE, "/api/2.0/mcp/sql"]
    catalog(workspace(token="tok-b"))
    assert len(listed) == 4, "another person's token must not read the first person's cache"


def test_refresh_skips_the_cache():
    fresh_start()
    catalog()
    catalog(fresh=True)
    assert len(listed) == 4


def test_a_named_server_is_asked_without_listing_every_space():
    fresh_start()
    tools = catalog(servers=[ap.server_for_tool_id("genie.s2/query_space_s2")])
    assert "genie.s2/query_space_s2" in tools
    assert "genie.s1/query_space_s1" not in tools


def test_tool_ids_map_back_to_their_server():
    assert ap.server_for_tool_id("genie.s1/query_space_s1") == "/api/2.0/mcp/genie/s1"
    assert ap.server_for_tool_id("sql/execute_sql") == "/api/2.0/mcp/sql"
    assert ap.server_for_tool_id("functions.main.sales/lookup") == "/api/2.0/mcp/functions/main/sales"
    assert ap.server_for_tool_id("genie_one") is None


def test_genie_one_keeps_the_genie_label_so_saved_tool_ids_still_match():
    assert ap.server_for_tool_id("genie/genie_one") == GENIE_ONE
    assert ap.server_for_tool_id("genie/genie_ask") == GENIE_ONE
    url = f"https://host{GENIE_ONE}"
    assert ap._server_label(url) == "genie" and ap._source_of(url) == "genie"
    assert ap._is_genie_server(url) and ap._is_genie_server("https://host/api/2.0/mcp/genie/s1")
    assert not ap._is_genie_server("https://host/ai-gateway/mcp-services/system.ai.dbsql")


def test_a_setting_that_still_names_the_old_genie_server_reads_as_genie_one():
    fresh_start()
    tools = catalog(configured="/api/2.0/mcp/genie,/api/2.0/mcp/sql")
    assert "/api/2.0/mcp/genie" not in listed, "the sunset server must not be asked"
    assert listed.count(GENIE_ONE) == 1
    assert tools["genie/genie_one"]["source"] == "genie"
    assert tools["genie/genie_one"]["poll_tool"] == "genie_poll_response"


def test_naming_both_genie_servers_asks_genie_one_once():
    fresh_start()
    catalog(configured=f"/api/2.0/mcp/genie,{GENIE_ONE},https://host/api/2.0/mcp/genie")
    assert listed == [GENIE_ONE]


def test_the_default_servers_are_sql_and_genie_one():
    os.environ.pop("AGENT_STUDIO_MCP_SERVERS", None)
    assert ap._mcp_server_urls("https://host") == ["https://host/api/2.0/mcp/sql", f"https://host{GENIE_ONE}"]


def test_the_research_tools_ask_genie_one():
    from services import research_tools as rts

    sys.modules["databricks_mcp"] = types.SimpleNamespace(DatabricksMCPClient=FakeClient)
    client = rts._genie_client(types.SimpleNamespace(config=types.SimpleNamespace(host="https://host/")))
    assert client.path == GENIE_ONE


def test_an_incomplete_genie_response_ends_the_wait_with_what_it_has():
    import json
    from services import agent_runtime as rt

    class Genie:
        def call_tool(self, name, args):
            body = ({"conversation_id": "c1", "response_id": "r1"} if name == "genie_ask"
                    else {"status": "incomplete", "final_answer": "Top two regions only."})
            return types.SimpleNamespace(content=[types.SimpleNamespace(text=json.dumps(body))],
                                         structuredContent=body, isError=False)

    interval, rt._genie_poll_interval = rt._genie_poll_interval, lambda: 0.0
    try:
        out = rt._exec_genie(Genie(), "genie_ask", {"question": "q"}, timeout=5)
    finally:
        rt._genie_poll_interval = interval
    assert out.startswith("Top two regions only.") and "may be partial" in out


def test_other_kinds_of_server_are_off_unless_asked_for():
    fresh_start()
    FakeStatements.statements.clear()
    os.environ["SQL_WAREHOUSE_ID"] = "wh"
    tools = catalog(genie_spaces=True)
    assert not {"functions", "vector-search", "external"} & {t["source"] for t in tools.values()}
    assert FakeStatements.statements == [], "nothing should touch the warehouse unless the picker asked"


def test_every_other_kind_is_listed_with_its_own_source():
    fresh_start()
    os.environ["SQL_WAREHOUSE_ID"] = "wh"
    tools = catalog(genie_spaces=True, extra_kinds=True)
    assert tools["functions.main.sales/lookup_order"]["source"] == "functions"
    assert tools["functions.main.sales/lookup_order"]["server_title"] == "main.sales"
    assert tools["vector-search.main.docs/docs_index"]["source"] == "vector-search"
    assert tools["external.jira/search_issues"]["source"] == "external"
    assert not any(t.startswith("external.plain_http") or t.startswith("external.warehouse") for t in tools), \
        "only HTTP connections flagged as MCP are servers"
    assert not any("odd name" in t["server"] for t in tools.values()), "unaddressable names are skipped"


def test_a_vector_schema_with_two_indexes_is_one_server():
    fresh_start()
    listed_vs = [p for p in ap.extra_mcp_servers(workspace(), "https://host") if "vector-search" in p]
    assert listed_vs == ["https://host/api/2.0/mcp/vector-search/main/docs"]


def test_a_kind_the_caller_cannot_list_contributes_nothing():
    fresh_start()
    os.environ["SQL_WAREHOUSE_ID"] = "wh"
    ws = workspace()

    def refused():
        raise PermissionError("OAuth token does not have required scopes: catalog.connections")

    ws.connections = types.SimpleNamespace(list=refused)
    tools = catalog(ws, extra_kinds=True)
    assert "functions.main.sales/lookup_order" in tools
    assert not any(t["source"] == "external" for t in tools.values())


def test_functions_are_skipped_without_a_warehouse_or_when_the_listing_does_not_finish():
    fresh_start()
    os.environ.pop("SQL_WAREHOUSE_ID", None)
    assert not any(t["source"] == "functions" for t in catalog(extra_kinds=True).values())
    fresh_start()
    os.environ["SQL_WAREHOUSE_ID"] = "wh"
    FakeStatements.state = "FAILED"
    try:
        assert not any(t["source"] == "functions" for t in catalog(extra_kinds=True).values())
    finally:
        FakeStatements.state = "SUCCEEDED"


def test_gateway_services_and_custom_apps_get_their_own_source_and_distinct_labels():
    gateway = "https://host/ai-gateway/mcp-services/system.ai.dbsql"
    app_a, app_b = "https://mcp-orders-123.databricksapps.com/mcp", "https://mcp-stock-456.cloud.databricksapps.com/mcp"
    assert ap._source_of(gateway) == "gateway" and ap._server_label(gateway) == "gateway.system.ai.dbsql"
    assert ap._source_of(app_a) == "app" and ap._source_of(app_b) == "app"
    assert ap._server_label(app_a) == "app.mcp-orders-123" and ap._server_label(app_b) == "app.mcp-stock-456"
    assert ap._source_of("https://host/api/2.0/mcp/ai-search/main/docs/idx") == "vector-search"
    assert ap.server_for_tool_id("gateway.system.ai.dbsql/execute") == "/ai-gateway/mcp-services/system.ai.dbsql"
    assert ap.server_for_tool_id("app.mcp-orders-123/lookup") is None


def test_a_kind_with_many_servers_cannot_crowd_out_the_others():
    many = {f"https://host/api/2.0/mcp/functions/c/s{i}": f"c.s{i}" for i in range(ap._MAX_EXTRA_SERVERS)}
    saved = (ap._uc_function_servers, ap._external_servers, ap._vector_search_servers)
    ap._uc_function_servers = lambda ws, host, fresh: many
    ap._vector_search_servers = lambda ws, host, fresh: {}
    ap._external_servers = lambda ws, host, fresh: {"https://host/api/2.0/mcp/external/jira": "jira"}
    try:
        found = ap.extra_mcp_servers(workspace(), "https://host")
    finally:
        ap._uc_function_servers, ap._external_servers, ap._vector_search_servers = saved
    assert "https://host/api/2.0/mcp/external/jira" in found and len(found) == len(many) + 1


def test_a_server_that_refuses_once_is_listed_on_the_retry():
    fresh_start()
    attempts = []

    class Flaky(FakeClient):
        def list_tools(self):
            attempts.append(self.path)
            if self.path == "/api/2.0/mcp/sql" and attempts.count(self.path) == 1:
                raise RuntimeError("Server returned an error response")
            return super().list_tools()

    sys.modules["databricks_mcp"] = types.SimpleNamespace(DatabricksMCPClient=Flaky)
    os.environ["AGENT_STUDIO_MCP_SERVERS"] = "/api/2.0/mcp/sql"
    tools = {t["id"] for t in ap.discover_mcp_tools(workspace())}
    assert "sql/execute_sql" in tools and attempts.count("/api/2.0/mcp/sql") == 2


def test_a_server_that_keeps_failing_is_given_up_on_after_a_few_tries():
    fresh_start()
    attempts = []

    class Broken:
        def __init__(self, server_url, workspace_client):
            pass

        def list_tools(self):
            attempts.append(1)
            raise RuntimeError("Server returned an error response")

    sys.modules["databricks_mcp"] = types.SimpleNamespace(DatabricksMCPClient=Broken)
    os.environ["AGENT_STUDIO_MCP_SERVERS"] = "/api/2.0/mcp/sql"
    assert ap.discover_mcp_tools(workspace()) == [] and len(attempts) == ap._LIST_ATTEMPTS


def test_an_unreachable_server_lists_nothing_and_the_rest_still_arrive():
    fresh_start()
    SERVERS_BACKUP = dict(SERVERS)
    del SERVERS["/api/2.0/mcp/genie/s1"]
    try:
        tools = catalog(genie_spaces=True)
    finally:
        SERVERS.update(SERVERS_BACKUP)
    assert "genie.s2/query_space_s2" in tools
    assert not any(t.startswith("genie.s1/") for t in tools)


def test_a_space_ask_is_polled_with_that_spaces_poll_tool():
    import json
    from services import agent_runtime as rt

    calls = []

    class Space:
        def call_tool(self, name, args):
            calls.append(name)
            body = ({"conversation_id": "c1", "response_id": "r1"} if name == "query_space_s1"
                    else {"status": "completed", "final_answer": "42"})
            return types.SimpleNamespace(content=[types.SimpleNamespace(text=json.dumps(body))],
                                         structuredContent=body, isError=False)

    interval, rt._genie_poll_interval = rt._genie_poll_interval, lambda: 0.0
    try:
        assert rt._is_genie_ask_tool("query_space_s1")
        out = rt._exec_genie(Space(), "query_space_s1", {"query": "q"}, timeout=5, poll_tool="poll_response_s1")
    finally:
        rt._genie_poll_interval = interval
    assert out == "42" and calls == ["query_space_s1", "poll_response_s1"]


def test_an_agent_saved_with_the_old_genie_ask_id_gets_genie_one():
    from services import agent_runtime as rt

    fresh_start()
    entries = list(catalog().values())
    saved = (ap.discover_mcp_tools, rt._tool_is_disabled)
    ap.discover_mcp_tools = lambda ws, **kwargs: entries
    rt._tool_is_disabled = lambda url: False
    try:
        for tools in (["genie/genie_ask"], ["genie_ask"], ["genie/genie_one"]):
            specs, dispatch = rt._build_tools(workspace(), {"tools": tools})
            names = [s["function"]["name"] for s in specs if s["function"]["name"] != "app_help"]
            assert names == ["genie_genie_one"], tools
            assert dispatch["genie_genie_one"]["real_name"] == "genie_ask", "the server only answers to genie_ask"
            assert dispatch["genie_genie_one"]["friendly"] == "Asking Genie One"
    finally:
        ap.discover_mcp_tools, rt._tool_is_disabled = saved


def test_saved_agents_read_the_old_genie_id_as_genie_one():
    import json
    import agent_studio_store as store

    old = ["genie/genie_ask", "sql/execute_sql", "genie/genie_one", "genie_ask"]
    assert store.canonical_tool_ids(old) == ["genie/genie_one", "sql/execute_sql", "genie_one"]
    ref = store.AgentStudioStore()._row_to_ref({"id": "a1", "tools_json": json.dumps(old)}, "me")
    assert ref.tools == ["genie/genie_one", "sql/execute_sql", "genie_one"]
    # The external agent (AGENT_LOCAL_RUNTIME=false) is sent the servers' own names.
    assert store.upstream_tool_ids(["genie/genie_one", "sql/execute_sql"]) == ["genie/genie_ask", "sql/execute_sql"]


ATLASSIAN = "/ai-gateway/mcp-services/system.ai.atlassian"
NOT_SIGNED_IN = ("Credential for user identity 123 is not found for the connection 'atlassian'. "
                 "Please login first at https://host/explore/conn")


def test_a_server_waiting_for_sign_in_is_reported_and_not_retried():
    fresh_start()
    attempts = []

    class NeedsSignIn(FakeClient):
        def list_tools(self):
            if self.path == ATLASSIAN:
                attempts.append(1)
                raise RuntimeError(NOT_SIGNED_IN)
            return super().list_tools()

    sys.modules["databricks_mcp"] = types.SimpleNamespace(DatabricksMCPClient=NeedsSignIn)
    os.environ["AGENT_STUDIO_MCP_SERVERS"] = f"/api/2.0/mcp/sql,{ATLASSIAN}"
    problems = []
    tools = {t["id"] for t in ap.discover_mcp_tools(workspace(), problems=problems)}
    assert "sql/execute_sql" in tools
    # Asking again can't sign anyone in, so it costs one round trip, not three.
    assert len(attempts) == 1
    assert problems == [{"server": f"https://host{ATLASSIAN}", "name": "system.ai.atlassian", "sign_in": True}]


def test_a_configured_server_that_fails_is_reported_but_a_discovered_one_is_not():
    fresh_start()

    class SomeFail(FakeClient):
        def list_tools(self):
            if self.path in ("/api/2.0/mcp/sql", "/api/2.0/mcp/genie/s1"):
                raise RuntimeError("Server returned an error response")
            return super().list_tools()

    sys.modules["databricks_mcp"] = types.SimpleNamespace(DatabricksMCPClient=SomeFail)
    os.environ["AGENT_STUDIO_MCP_SERVERS"] = "/api/2.0/mcp/sql"
    problems = []
    ap.discover_mcp_tools(workspace(), genie_spaces=True, problems=problems)
    # An admin named the SQL server, so its silence must be visible; a Genie
    # space failing is one of possibly hundreds and stays in the log.
    assert [(p["name"], p["sign_in"]) for p in problems] == [("sql", False)]


def test_the_server_list_saved_in_settings_replaces_the_deployments():
    fresh_start()
    sys.modules["databricks_mcp"] = types.SimpleNamespace(DatabricksMCPClient=FakeClient)
    os.environ["AGENT_STUDIO_MCP_SERVERS"] = "/api/2.0/mcp/sql"
    settings_store._read_rows = lambda: {"mcp_servers": f"{GENIE_ONE}\nhttps://elsewhere.example/mcp"}
    settings_store.invalidate()
    try:
        urls = ap._mcp_server_urls("https://host")
    finally:
        settings_store._read_rows = lambda: {}
        settings_store.invalidate()
    # The off-workspace entry can't have been saved through the form; dropped on read.
    assert urls == [f"https://host{GENIE_ONE}"]


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
