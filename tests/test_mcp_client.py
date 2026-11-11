"""The MCP client every call goes through (services/mcp_client.py).

It exists because `databricks_mcp` 0.9.2 on mcp 2.x left httpx's five-second
read timeout in place, which failed every call to a Genie space. These pin the
timeout it uses instead, that a failure arrives as itself rather than as
"unhandled errors in a TaskGroup", and that the public pieces it is built from
are still where it expects them, so an upgrade that moves one fails here.

    PYTHONPATH=server .venv/bin/python tests/test_mcp_client.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import mcp_client as mc  # noqa: E402
from services import settings_store  # noqa: E402

settings_store._read_rows = lambda: {}


def test_the_read_timeout_is_the_tool_call_timeout():
    os.environ["AGENT_RUNTIME_TOOL_TIMEOUT"] = "120"
    settings_store.invalidate()
    try:
        assert mc.read_timeout() == 120.0
    finally:
        os.environ.pop("AGENT_RUNTIME_TOOL_TIMEOUT", None)
        settings_store.invalidate()
    assert mc.read_timeout() == 90.0, "the setting's default"


def test_the_read_timeout_never_drops_to_where_a_genie_space_fails():
    # A space holds its ask open ten to fifteen seconds; five is what broke it.
    os.environ["AGENT_RUNTIME_TOOL_TIMEOUT"] = "5"
    settings_store.invalidate()
    try:
        assert mc.read_timeout() == 30.0
    finally:
        os.environ.pop("AGENT_RUNTIME_TOOL_TIMEOUT", None)
        settings_store.invalidate()


def test_a_failure_arrives_as_itself_not_as_its_task_group():
    class ReadTimeout(Exception):
        pass

    async def fails():
        raise ExceptionGroup("unhandled errors in a TaskGroup", [ExceptionGroup("inner", [ReadTimeout("slow")])])

    try:
        mc._run(fails())
    except ReadTimeout as exc:
        assert str(exc) == "slow"
    else:
        raise AssertionError("expected the ReadTimeout")


def test_several_failures_stay_grouped():
    async def fails():
        raise ExceptionGroup("two", [ValueError("a"), KeyError("b")])

    try:
        mc._run(fails())
    except ExceptionGroup as group:
        assert len(group.exceptions) == 2
    else:
        raise AssertionError("expected the group")


def test_the_session_is_built_from_public_pieces_with_a_real_read_timeout():
    import asyncio
    import types

    import httpx2

    seen = {}
    real_client = httpx2.AsyncClient

    class Recording(real_client):
        def __init__(self, **kwargs):
            seen.update(kwargs)
            super().__init__(**kwargs)

    class Session:
        def __init__(self, transport):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def list_tools(self):
            return types.SimpleNamespace(tools=["t"])

    import mcp

    saved = (httpx2.AsyncClient, mcp.Client)
    httpx2.AsyncClient, mcp.Client = Recording, Session
    try:
        ws = types.SimpleNamespace(config=types.SimpleNamespace(authenticate=lambda: {"Authorization": "Bearer x"}))
        tools = asyncio.run(mc.mcp_client("https://host/api/2.0/mcp/genie/s1", ws)._list_tools())
    finally:
        httpx2.AsyncClient, mcp.Client = saved
    assert tools == ["t"]
    assert seen["timeout"].read == mc.read_timeout() and seen["timeout"].read >= 30
    assert seen["follow_redirects"] is True and seen["auth"] is not None


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
