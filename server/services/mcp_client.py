"""The MCP client every call in this app goes through.

Not `databricks_mcp.DatabricksMCPClient`, because of its timeouts: on mcp 2.x,
0.9.2 (the newest release) opens each session on an `httpx2.AsyncClient` built
with none, so httpx's five-second default applies to every read. A Genie space's
ask tool holds the request open while Genie works, ten to fifteen seconds before
it answers or hands back a handle, so every call to one failed with a
`ReadTimeout`, which arrived as "unhandled errors in a TaskGroup". A slow SQL
statement hit the same wall.

This is the same session built on public pieces only (mcp's `Client` and
transport, `databricks_mcp`'s OAuth provider), with the timeouts mcp recommends
and the read bounded by the admin's tool-call timeout. The app needs two calls,
so that is all it has. Tests replace `mcp_client`; patch it here, where the
call sites look it up.
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional


class MCPClient:
    """`list_tools` / `call_tool` against one server, as `ws`'s credential."""

    def __init__(self, server_url: str, ws):
        self.server_url = server_url
        self.ws = ws

    def list_tools(self) -> List[Any]:
        return _run(self._list_tools())

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None):
        return _run(self._call_tool(name, arguments or {}))

    async def _list_tools(self):
        async with self._session() as session:
            return (await session.list_tools()).tools

    async def _call_tool(self, name: str, arguments: Dict[str, Any]):
        async with self._session() as session:
            return await session.call_tool(name, arguments)

    @asynccontextmanager
    async def _session(self):
        import httpx2
        from databricks_mcp.oauth_provider import DatabricksOAuthClientProvider
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import MCP_DEFAULT_TIMEOUT

        timeout = httpx2.Timeout(MCP_DEFAULT_TIMEOUT, read=read_timeout())
        auth = DatabricksOAuthClientProvider(self.ws)
        async with httpx2.AsyncClient(auth=auth, follow_redirects=True, timeout=timeout) as http_client:
            async with Client(streamable_http_client(self.server_url, http_client=http_client)) as session:
                yield session


def mcp_client(server_url: str, ws) -> MCPClient:
    return MCPClient(server_url, ws)


def read_timeout() -> float:
    """Seconds one MCP read may wait: the chat's tool-call timeout. Never raises."""
    try:
        from services.settings_store import get_int_setting

        return float(max(30, get_int_setting("chat_tool_timeout")))
    except Exception:  # noqa: BLE001 — a settings outage must not break tools
        return 90.0


def _run(coro):
    """Run one session to completion, raising what went wrong rather than its wrapper.

    The transport runs in a task group, so any failure arrives as "unhandled
    errors in a TaskGroup (1 sub-exception)", and that is what a user was shown.
    """
    try:
        return asyncio.run(coro)
    except BaseExceptionGroup as group:
        leaf: BaseException = group
        while isinstance(leaf, BaseExceptionGroup) and len(leaf.exceptions) == 1:
            leaf = leaf.exceptions[0]
        if leaf is group or not isinstance(leaf, Exception):
            raise
        raise leaf from group
