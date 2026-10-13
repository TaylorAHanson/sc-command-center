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

ASK = "Ask Databricks Genie a question. Returns a handle; poll genie_poll_response for the answer."

SERVERS = {
    "/api/2.0/mcp/genie": [
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
}
SPACES = [("s1", "Supply"), ("s2", "Finance")]

listed = []


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


def workspace(token="tok-a"):
    return types.SimpleNamespace(config=types.SimpleNamespace(host="https://host", token=token, auth_type="pat"),
                                 genie=FakeGenie())


def catalog(ws=None, **kwargs):
    sys.modules["databricks_mcp"] = types.SimpleNamespace(DatabricksMCPClient=FakeClient)
    os.environ["AGENT_STUDIO_MCP_SERVERS"] = "/api/2.0/mcp/genie,/api/2.0/mcp/sql"
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
    assert tools["genie/genie_ask"]["internal"] is False
    assert tools["genie/genie_cancel_response"]["internal"] is False


def test_each_ask_tool_knows_its_own_servers_poll_tool():
    fresh_start()
    tools = catalog(genie_spaces=True)
    assert tools["genie/genie_ask"]["poll_tool"] == "genie_poll_response"
    assert tools["genie.s1/query_space_s1"]["poll_tool"] == "poll_response_s1"
    assert "poll_tool" not in tools["sql/execute_sql"]


def test_genie_ask_tools_say_the_app_polls_for_them():
    fresh_start()
    tools = catalog(genie_spaces=True)
    assert tools["genie/genie_ask"]["description"] == ap.GENIE_POLLED_NOTE + ASK
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
    assert sorted(listed) == ["/api/2.0/mcp/genie", "/api/2.0/mcp/sql"]
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
    assert ap.server_for_tool_id("genie_ask") is None


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
