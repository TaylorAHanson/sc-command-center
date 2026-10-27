"""Agent Studio — profile/skill CRUD + AI-assisted authoring.

This router powers the Command Center's Agent Studio: a place to author **agent
profiles** (an ``AGENT.md`` + ``skills/*.md``) that the consolidated agent
runtime later loads and runs. Storage lives entirely on Unity Catalog Volumes /
the user's Workspace folder (see ``agent_studio_store``) — Unity Catalog governs
visibility and edit rights, so every storage call is made under the caller's OBO
token.

Two surfaces:

  * **CRUD** (``/profiles*``, ``/locations``) — list/read/save/delete profiles,
    delegated to :class:`AgentStudioStore`, scoped by OBO.
  * **Authoring** (``/tools``, ``/generate``) — an AI-assisted draft
    loop. A Claude (sonnet) agent proposes an ``AGENT.md`` +
    skills, *grounded* in (a) the tools actually exposed by the Unity Catalog AI
    Gateway MCP and (b) live schema probes against SQL/Genie. It returns a draft
    plus a structured **Review** so the author can see suggested tools, missing
    capabilities, ambiguities, and schema confirmations before saving.

The LLM call uses the app Service Principal (it must reach the serving
endpoint), while tool discovery and schema probes use the user's OBO token so
the Review reflects what *this user* can actually see and run.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from databricks.sdk import WorkspaceClient

from middleware.auth import get_db_client, get_db_client_sp, get_user_token, require_auth
from agent_studio_store import (
    AgentStudioError,
    ProfileAccessError,
    ProfileConflictError,
    VIS_DOMAIN,
    VIS_GLOBAL,
    VIS_PERSONAL,
    DEFAULT_DOMAIN,
    get_agent_studio_store,
)
from routes.roles import (
    _get_current_username,
    require_domain_editor,
    require_global_admin,
)
from services import llm_params, research_tools
from services.generation_jobs import JobStore
from services.llm_client import reply_text
from services.settings_store import base_path_for_model, get_int_setting, get_setting

logger = logging.getLogger(__name__)

router = APIRouter()


# --------------------------------------------------------------------- models

class SkillPayload(BaseModel):
    slug: Optional[str] = None
    name: str
    description: str = ""
    content: str = ""


class PythonToolPayload(BaseModel):
    slug: Optional[str] = None
    name: str
    description: str = ""
    code: str = ""


class SaveProfileRequest(BaseModel):
    name: str
    prompt: str
    description: str = ""
    model: str = ""
    tools: List[str] = []
    skills: Optional[List[SkillPayload]] = None
    python_tools: Optional[List[PythonToolPayload]] = None
    # Domain-scoped sharing (mirrors widgets/views):
    #   visibility="personal" -> private to the creator (no domain role needed)
    #   visibility="domain"   -> shared to `domain` (domain editors can edit)
    #   visibility="global"   -> visible to everyone (global admins only)
    visibility: str = VIS_PERSONAL
    domain: str = DEFAULT_DOMAIN
    base: str = "full"
    profile_id: Optional[str] = None
    # Optimistic-concurrency token: the ``updated_at`` the client last loaded.
    # When present on an update, the save is refused (409) if the stored profile
    # has since changed.
    expected_updated_at: Optional[str] = None


class AuthorMessage(BaseModel):
    role: str
    content: str


class AuthorRequest(BaseModel):
    prompt: str
    history: List[AuthorMessage] = []
    current_prompt: Optional[str] = None        # existing AGENT.md body, if editing
    current_skills: Optional[List[SkillPayload]] = None
    current_python_tools: Optional[List[PythonToolPayload]] = None
    confirm_schema: bool = True                 # run live SQL/Genie probes


# ------------------------------------------------------------------ MCP tools

def _mcp_server_urls(host: str) -> List[str]:
    """Resolve the AI Gateway MCP server URLs to introspect.

    The ``mcp_servers`` setting (Admin Panel → Settings), falling back to
    ``AGENT_STUDIO_MCP_SERVERS`` (comma-separated). Entries are workspace-relative
    paths (joined to ``host``), or from the env var also absolute URLs. Defaults
    to the managed SQL MCP server **and** the general Genie server (Genie One,
    ``system.ai.genie_one_mcp``), which searches across the caller's accessible
    Genie data.

    The old general server (``/api/2.0/mcp/genie``) is sunset on 2026-10-31, and
    a deployment's setting names it explicitly (the bundle variable's old
    default), so an entry for it is read as Genie One rather than left to stop
    working: same tools, same arguments, same tool ids.
    """
    from services.agent_runtime import GENIE_ONE_PATH, LEGACY_GENIE_PATH
    from services.settings_store import get_mcp_server_list

    urls: List[str] = []
    for entry in get_mcp_server_list():
        url = _absolute_url(host, entry)
        if url and _mcp_path(url) == LEGACY_GENIE_PATH:
            url = _absolute_url(host, GENIE_ONE_PATH)
        if url and url not in urls:
            urls.append(url)
    return urls


def _absolute_url(host: str, entry: str) -> str:
    entry = (entry or "").strip()
    if entry.startswith("http://") or entry.startswith("https://"):
        return entry.rstrip("/")
    if entry and host:
        return f"{host.rstrip('/')}/{entry.lstrip('/')}".rstrip("/")
    return ""


def _mcp_path(server_url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(server_url or "").path or "").rstrip("/")


def _source_of(server_url: str) -> str:
    """Which kind of MCP server a URL is, for the picker's source filters.

    ``genie`` is the general server that searches every space the caller can see
    (Genie One, or the old ``/api/2.0/mcp/genie``); ``genie_space`` is one
    space's own server (``/api/2.0/mcp/genie/<space_id>``).
    """
    from urllib.parse import urlparse
    from services.agent_runtime import GENIE_ONE_PATH

    path = _mcp_path(server_url)
    if path == GENIE_ONE_PATH:
        return "genie"
    # Neither of these sits under /api/2.0/mcp, so they'd otherwise all read "other".
    if path.startswith("/ai-gateway/mcp-services/"):
        return "gateway"
    if (urlparse(server_url or "").hostname or "").endswith(".databricksapps.com"):
        return "app"
    parts = [p for p in path.split("/") if p]
    if "mcp" not in parts or parts.index("mcp") + 1 >= len(parts):
        return "other"
    tail = parts[parts.index("mcp") + 1:]
    if tail[0] == "genie":
        return "genie_space" if len(tail) > 1 else "genie"
    if tail[0] in ("sql", "functions", "vector-search", "external"):
        return tail[0]
    # Databricks renamed Vector Search "AI Search" and moved its URL; same thing.
    if tail[0] == "ai-search":
        return "vector-search"
    return "other"


def _is_genie_server(server_url: str) -> bool:
    from services.agent_runtime import _is_genie_server as is_genie

    return is_genie(server_url)


def _is_internal_mcp_tool(server_url: str, name: str) -> bool:
    """True for tools that are an INTERNAL transport mechanism, not an
    agent-facing capability. They are still listed, marked ``internal``, so the
    picker can show them on request; the authoring assistant's catalog and the
    runtime leave them out.

    A Genie MCP server (the general one and each space's own) exposes a poll
    tool purely to drain an async query started by its ask tool. The runtime
    drives that poll loop itself (``services.agent_runtime._exec_genie``, told the
    poll tool's name by discovery), so it is never a capability an agent picks.
    """
    return _is_genie_server(server_url) and "poll" in (name or "").lower()


GENIE_POLLED_NOTE = (
    "In this app the call waits for Genie and returns the finished answer: the"
    " runtime polls for it itself, which is why the poll tool is not offered. "
)

# Genie One's ask tool, under the name people know it by. The server lists it as
# `genie_ask` (agent_runtime.GENIE_ONE_ASK_TOOL); the entry keeps that as
# `upstream_name`, which is what the runtime calls.
GENIE_ONE_TOOL = "genie_one"
GENIE_ONE_DESCRIPTION = (
    "Genie One: ask a question in plain language about the data you can access in"
    " Unity Catalog, and get Genie's answer back. It runs as the signed-in user, so"
    " it sees only the tables and rows their permissions allow. Put the whole"
    " question in `question`; to follow up on an earlier answer, pass the"
    " `conversation_id` that came with it. The call waits for the finished answer"
    " itself (often 30 seconds to a couple of minutes), so there is nothing to"
    " poll; if Genie stops early, the answer says it may be partial."
)


def _shown_name(server_url: str, name: str) -> str:
    """The name the catalog lists a server's tool under."""
    from services.agent_runtime import GENIE_ONE_ASK_TOOL

    # Only the general server's: a Genie space's own server is not Genie One.
    if name == GENIE_ONE_ASK_TOOL and _server_label(server_url) == "genie":
        return GENIE_ONE_TOOL
    return name


def _tool_description(server_url: str, name: str, description: str) -> str:
    """The description an author and a model read for one discovered tool.

    Genie's own text for its ask tool says to poll the poll tool, which
    :func:`_is_internal_mcp_tool` keeps from agents. Left as it was, the authoring
    assistant reported the poll tool as a missing capability and wrote agents told
    to poll by hand, so the description is corrected where the catalog is built.
    The note goes first because the runtime truncates descriptions. Genie One's
    text is replaced outright: it names the tool by its server name, which the
    catalog doesn't use.
    """
    from services.agent_runtime import _is_genie_ask_tool

    if _shown_name(server_url, name) == GENIE_ONE_TOOL:
        return GENIE_ONE_DESCRIPTION
    if _is_genie_server(server_url) and _is_genie_ask_tool(name):
        return GENIE_POLLED_NOTE + description
    return description


def _readable(exc: BaseException, depth: int = 0) -> str:
    """The error inside the error.

    The MCP client runs its transport in a task group, so a failure arrives as an
    exception group and logs as "unhandled errors in a TaskGroup (1
    sub-exception)" — accurate, and no use to whoever is reading the log. What
    they need is the one underneath, which says whether the server is
    unreachable, the token is wrong, or the endpoint isn't there at all.
    """
    inner = getattr(exc, "exceptions", None)
    if inner and depth < 3:
        return "; ".join(_readable(e, depth + 1) for e in inner)
    return f"{type(exc).__name__}: {str(exc).strip() or 'no message'}"


# Discovery opens an MCP session per server, and with every Genie space included
# that is dozens of round trips; the chat runtime also builds its tool list on
# every turn. So each server's tools (and the list of Genie spaces) are cached per
# credential, and servers are asked in parallel.
_MCP_CACHE_SECONDS = float(os.environ.get("AGENT_STUDIO_MCP_CACHE_SECONDS", "300") or "300")
_MAX_GENIE_SPACES = int(os.environ.get("AGENT_STUDIO_MAX_GENIE_SPACES", "200") or "200")
_DISCOVERY_WORKERS = 8
_mcp_cache: Dict[Tuple[str, str], Tuple[float, Any]] = {}
_mcp_cache_lock = threading.Lock()


def _credential_key(ws: WorkspaceClient) -> str:
    """Whose view of the catalog this is: a hash of the token, never a name."""
    from middleware.auth import _token_key

    try:
        token = ws.config.token
        if token:
            return _token_key("mcp", token)
        return f"mcp:{ws.config.host}:{ws.config.auth_type}"
    except Exception:  # noqa: BLE001
        return f"mcp:{id(ws)}"


def _cached(ws: WorkspaceClient, what: str, fresh: bool, build):
    """`build()`, remembered per credential for `_MCP_CACHE_SECONDS`. Failures aren't kept."""
    key = (_credential_key(ws), what)
    now = time.monotonic()
    if not fresh:
        with _mcp_cache_lock:
            hit = _mcp_cache.get(key)
        if hit and now - hit[0] < _MCP_CACHE_SECONDS:
            return hit[1]
    value = build()
    with _mcp_cache_lock:
        if len(_mcp_cache) > 5000:
            _mcp_cache.clear()
        _mcp_cache[key] = (now, value)
    return value


def _genie_space_servers(ws: WorkspaceClient, host: str, fresh: bool = False) -> Dict[str, str]:
    """{server url: space title} for each Genie space the caller can see."""
    def build() -> Dict[str, str]:
        spaces: Dict[str, str] = {}
        token = None
        while len(spaces) < _MAX_GENIE_SPACES:
            page = ws.genie.list_spaces(page_size=100, page_token=token)
            for space in page.spaces or []:
                if space.space_id:
                    spaces[_absolute_url(host, f"/api/2.0/mcp/genie/{space.space_id}")] = space.title or space.space_id
            token = page.next_page_token
            if not token:
                break
        return dict(list(spaces.items())[:_MAX_GENIE_SPACES])

    try:
        return _cached(ws, "genie-spaces", fresh, build)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Listing Genie spaces failed: %s", _readable(exc))
        return {}


_MAX_EXTRA_SERVERS = int(os.environ.get("AGENT_STUDIO_MAX_EXTRA_SERVERS", "100") or "100")
_PLAIN_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def _extra_kind(ws: WorkspaceClient, what: str, fresh: bool, build) -> Dict[str, str]:
    """One kind of extra server, cached like the rest. A kind the caller can't
    list (a user scope the App wasn't granted, a feature the workspace lacks)
    simply contributes nothing; the picker still works without it."""
    try:
        return _cached(ws, what, fresh, build)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Listing %s MCP servers failed: %s", what, _readable(exc))
        return {}


def _schema_servers(host: str, kind: str, pairs) -> Dict[str, str]:
    """{server url: "catalog.schema"} for UC-scoped managed servers."""
    out: Dict[str, str] = {}
    for catalog, schema in pairs:
        if len(out) >= _MAX_EXTRA_SERVERS:
            break
        # A backtick-quoted name with odd characters can't be put in a URL path
        # or recovered from a tool id's label; skip it rather than guess.
        if _PLAIN_NAME.match(catalog or "") and _PLAIN_NAME.match(schema or ""):
            out[_absolute_url(host, f"/api/2.0/mcp/{kind}/{catalog}/{schema}")] = f"{catalog}.{schema}"
    return out


def _uc_function_servers(ws: WorkspaceClient, host: str, fresh: bool) -> Dict[str, str]:
    """Schemas holding functions the caller can see, each a managed MCP server.

    Read from information_schema as the caller rather than walking catalogs and
    schemas through the SDK: one statement instead of a call per schema, and it
    needs only the SQL scopes the App already has. It does use the app's
    warehouse, which may start it.
    """
    def build() -> Dict[str, str]:
        from databricks.sdk.service.sql import StatementState

        warehouse_id = os.environ.get("SQL_WAREHOUSE_ID", "")
        if not warehouse_id:
            return {}
        result = ws.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=(
                "SELECT DISTINCT routine_catalog, routine_schema FROM system.information_schema.routines "
                "WHERE routine_schema <> 'information_schema' "
                f"ORDER BY 1, 2 LIMIT {_MAX_EXTRA_SERVERS}"
            ),
            wait_timeout="20s",
        )
        state = getattr(getattr(result, "status", None), "state", None)
        if state != StatementState.SUCCEEDED:
            try:
                ws.statement_execution.cancel_execution(result.statement_id)
            except Exception:  # noqa: BLE001 — the warehouse times it out anyway
                pass
            raise RuntimeError(f"function listing ended {state}")
        rows = (result.result.data_array if getattr(result, "result", None) else None) or []
        return _schema_servers(host, "functions", [(r[0], r[1]) for r in rows])

    return _extra_kind(ws, "uc-functions", fresh, build)


def _vector_search_servers(ws: WorkspaceClient, host: str, fresh: bool) -> Dict[str, str]:
    """Schemas holding vector indexes, from the endpoints the caller can list."""
    def build() -> Dict[str, str]:
        pairs: List[Tuple[str, str]] = []
        for endpoint in ws.vector_search_endpoints.list_endpoints():
            for index in ws.vector_search_indexes.list_indexes(endpoint.name):
                parts = (index.name or "").split(".")
                if len(parts) == 3 and (parts[0], parts[1]) not in pairs:
                    pairs.append((parts[0], parts[1]))
                if len(pairs) >= _MAX_EXTRA_SERVERS:
                    return _schema_servers(host, "vector-search", pairs)
        return _schema_servers(host, "vector-search", pairs)

    return _extra_kind(ws, "vector-search", fresh, build)


def _external_servers(ws: WorkspaceClient, host: str, fresh: bool) -> Dict[str, str]:
    """External MCP servers: Unity Catalog HTTP connections flagged as MCP."""
    def build() -> Dict[str, str]:
        from databricks.sdk.service.catalog import ConnectionType

        out: Dict[str, str] = {}
        for conn in ws.connections.list():
            if len(out) >= _MAX_EXTRA_SERVERS:
                break
            if conn.connection_type != ConnectionType.HTTP:
                continue
            if str((conn.options or {}).get("is_mcp_connection", "")).lower() != "true":
                continue
            if conn.name and _PLAIN_NAME.match(conn.name):
                out[_absolute_url(host, f"/api/2.0/mcp/external/{conn.name}")] = conn.name
        return out

    return _extra_kind(ws, "external", fresh, build)


def extra_mcp_servers(ws: WorkspaceClient, host: str, fresh: bool = False) -> Dict[str, str]:
    """{server url: title} for every other kind of managed MCP server the caller
    can reach, in parallel. Only the picker asks for this: the chat runtime and
    the authoring assistant stay on the configured servers (plus an agent's own)."""
    from concurrent.futures import ThreadPoolExecutor

    finders = (_uc_function_servers, _vector_search_servers, _external_servers)
    with ThreadPoolExecutor(max_workers=len(finders)) as pool:
        found = list(pool.map(lambda find: find(ws, host, fresh), finders))
    # Each kind is already capped on its own. A cap on the merged total once let a
    # workspace with 100 function schemas push every external connection out of
    # the picker, since functions come first.
    merged: Dict[str, str] = {}
    for servers in found:
        merged.update(servers)
    return merged


_LIST_ATTEMPTS = 3

# What an AI Gateway server that holds a per-user credential (Atlassian, for one)
# answers until that person has signed in: "Credential for user identity … is not
# found for the connection 'atlassian'. Please login first…". The sign-in link in
# it arrives cut short, so the picker gives directions instead of the link.
_SIGN_IN_MARKERS = ("please login first", "please log in first", "credential for user identity")


def needs_sign_in(reason: str) -> bool:
    text = (reason or "").lower()
    return any(marker in text for marker in _SIGN_IN_MARKERS)


def _server_name(server_url: str) -> str:
    """What to call a server when telling a person about it."""
    path = _mcp_path(server_url)
    prefix = "/ai-gateway/mcp-services/"
    return path[len(prefix):] if path.startswith(prefix) else _server_label(server_url)


def _retry_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def _list_tools_with_retry(client) -> list:
    """list_tools, tried again when the server refuses.

    Opening the picker lists up to a couple of hundred servers at once, and the
    workspace answers the overflow with 429. The MCP client reports that only as
    "Server returned an error response", so a rate limit can't be told from a
    server that is simply broken; both get a short, jittered wait and another
    go, and a broken one costs about a second before it is given up on.
    """
    import random

    for attempt in range(_LIST_ATTEMPTS):
        try:
            return client.list_tools()
        except Exception as exc:  # noqa: BLE001
            # Asking again won't sign anyone in.
            if attempt == _LIST_ATTEMPTS - 1 or needs_sign_in(_readable(exc)):
                raise
            _retry_sleep(0.4 * (2 ** attempt) + random.random() * 0.4)
    return []


def _server_tools(ws: WorkspaceClient, server_url: str, title: str, fresh: bool,
                  problems: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """One server's tools, as catalog entries. An unreachable server lists none,
    and is recorded in ``problems`` when the caller passes a list."""
    from databricks_mcp import DatabricksMCPClient
    from services.agent_runtime import _is_genie_ask_tool

    def build() -> List[Dict[str, Any]]:
        client = DatabricksMCPClient(server_url=server_url, workspace_client=ws)
        tools = [t for t in _list_tools_with_retry(client) if getattr(t, "name", None)]
        label = _server_label(server_url)
        source = _source_of(server_url)
        genie = _is_genie_server(server_url)
        poll_tool = next((t.name for t in tools if genie and "poll" in t.name.lower()), None)
        entries = []
        for tool in tools:
            name = tool.name
            shown = _shown_name(server_url, name)
            entry = {
                # Canonical, server-qualified identifier authored profiles store
                # (``<server>/<tool>``). Unambiguous when two servers expose the
                # same tool name, which every Genie space does; the runtime
                # matches on this id or, as a fallback, the bare ``name``.
                "id": f"{label}/{shown}",
                "name": shown,
                "server_label": label,
                "server_title": title,
                "source": source,
                "internal": _is_internal_mcp_tool(server_url, name),
                "description": _tool_description(server_url, name, getattr(tool, "description", "") or ""),
                "server": server_url,
                "input_schema": getattr(tool, "inputSchema", None)
                or getattr(tool, "input_schema", None)
                or {},
            }
            if shown != name:
                entry["upstream_name"] = name
            if genie and poll_tool and _is_genie_ask_tool(name):
                entry["poll_tool"] = poll_tool
            entries.append(entry)
        return entries

    try:
        return _cached(ws, f"tools:{server_url}", fresh, build)
    except Exception as exc:  # noqa: BLE001
        reason = _readable(exc)
        logger.warning("MCP list_tools failed for %s: %s", server_url, reason)
        if problems is not None:
            problems.append({
                "server": server_url,
                "name": title or _server_name(server_url),
                "sign_in": needs_sign_in(reason),
            })
        return []


def server_for_tool_id(tool_id: str) -> Optional[str]:
    """The workspace-relative MCP path a ``<server label>/<tool>`` id came from.

    The inverse of :func:`_server_label` for the managed URL shapes, so the chat
    runtime can open only the servers an agent's tools live on rather than
    listing every Genie space on every turn. None for a bare tool name.
    """
    label, sep, _name = (tool_id or "").rpartition("/")
    if not sep or not label:
        return None
    if label.startswith("gateway."):
        return "/ai-gateway/mcp-services/" + label[len("gateway."):]
    # Saved agents hold `genie/<tool>`, which named the old general server; it is
    # Genie One now, under the same label, so those agents need no edit.
    if label == "genie":
        from services.agent_runtime import GENIE_ONE_PATH

        return GENIE_ONE_PATH
    # A custom app's host can't be recovered from its label, so an agent that
    # uses one has to find it through the configured servers.
    if label.startswith("app."):
        return None
    return "/api/2.0/mcp/" + "/".join(label.split("."))


def discover_mcp_tools(ws: WorkspaceClient, *, genie_spaces: bool = False, extra_kinds: bool = False,
                       servers: Optional[List[str]] = None, fresh: bool = False,
                       problems: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """List tools exposed by AI Gateway MCP servers under the caller's OBO token.

    Always the configured servers (the ``mcp_servers`` setting); with
    ``genie_spaces``, also every Genie space the caller can see, each its own
    server; with ``extra_kinds``, also the Unity Catalog function schemas, vector
    search schemas and external MCP connections the caller can reach; plus any
    ``servers`` named (absolute or workspace-relative). Nothing
    is dropped: plumbing tools come back marked ``internal`` and it is each
    caller's choice whether to show them. ``fresh`` skips the cache.

    ``problems``, when given, collects the servers that listed nothing because
    they failed: every configured one (an admin named it, so silence would look
    like a typo nobody can see) and any that wants the caller to sign in. Other
    discovered servers failing stays a log line; there can be hundreds.

    Degrades gracefully: a missing ``databricks-mcp`` package or an unreachable
    server yields a partial/empty catalog rather than failing the request.
    """
    from concurrent.futures import ThreadPoolExecutor

    host = ""
    try:
        host = ws.config.host or ""
    except Exception:  # noqa: BLE001
        host = os.environ.get("DATABRICKS_HOST", "")

    try:
        import databricks_mcp  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        logger.warning("databricks-mcp not installed; tool discovery disabled: %s", exc)
        return []

    titles: Dict[str, str] = {}
    for url in _mcp_server_urls(host):
        titles.setdefault(url, "")
    # A configured server with an unusual URL can't be recovered from its label,
    # so a named server whose label is already configured is that one.
    configured = {_server_label(url) for url in titles}
    for entry in servers or []:
        url = _absolute_url(host, entry)
        if url and _server_label(url) not in configured:
            titles.setdefault(url, "")
    if genie_spaces:
        for url, title in _genie_space_servers(ws, host, fresh).items():
            titles[url] = title
    if extra_kinds:
        for url, title in extra_mcp_servers(ws, host, fresh).items():
            # A configured server of the same label keeps its place.
            if _server_label(url) not in configured:
                titles.setdefault(url, title)

    if not titles:
        return []
    failed: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(_DISCOVERY_WORKERS, len(titles))) as pool:
        lists = list(pool.map(lambda item: _server_tools(ws, item[0], item[1], fresh, failed), titles.items()))
    if problems is not None:
        problems.extend(p for p in failed if p["sign_in"] or _server_label(p["server"]) in configured)
    return [entry for tools in lists for entry in tools]


def _server_label(server_url: str) -> str:
    """Short, stable label for an MCP server URL, used to qualify tool ids.

    Mirrors the managed MCP URL shapes (``/api/2.0/mcp/<kind>[/...]``): we take
    the path segments after ``mcp`` and join them, so
    ``/api/2.0/mcp/functions/main/sales`` -> ``functions.main.sales`` and
    ``/api/2.0/mcp/sql`` -> ``sql``. Falls back to the host for odd URLs.
    """
    s = (server_url or "").rstrip("/")
    # Every custom app serves at /mcp, so the host is the only thing telling two
    # of them apart; without it their tool ids collide.
    app = re.match(r"^https?://([^/.]+)\.[^/]*databricksapps\.com(?:/|$)", s)
    if app:
        return f"app.{app.group(1)}"
    s = re.sub(r"^https?://[^/]+", "", s)  # strip scheme+host
    # Keeps the label the old general server had, so tool ids already saved on an
    # agent (`genie/...`) still match after the move to Genie One.
    if s == "/ai-gateway/mcp-services/system.ai.genie_one_mcp":
        return "genie"
    parts = [p for p in s.split("/") if p]
    if len(parts) >= 3 and parts[:2] == ["ai-gateway", "mcp-services"]:
        return f"gateway.{parts[2]}"
    if "mcp" in parts:
        tail = parts[parts.index("mcp") + 1:]
        if tail:
            return ".".join(tail)
    return parts[-1] if parts else "mcp"


def _python_sandbox_timeout() -> int:
    try:
        return int(os.environ.get("AGENT_STUDIO_PY_SANDBOX_TIMEOUT", "6"))
    except ValueError:
        return 6


def _run_python_sandbox(code: str, timeout_s: int = 6) -> Dict[str, Any]:
    """Execute a short Python snippet in an isolated subprocess.

    This is a *validation* sandbox for authoring, not a hardened jail. It runs
    a fresh interpreter in isolated mode (``-I``: ignores PYTHON* env vars and
    user site-packages) with a **credential-free environment** (no DATABRICKS_*,
    PG*, tokens, secrets — only a minimal PATH/HOME), a wall-clock timeout, and
    (on POSIX) CPU + address-space rlimits. It lets the authoring assistant
    confirm an author's Python tool imports, runs, and returns sane output
    without exposing the app's credentials or hanging the request.
    """
    import subprocess
    import sys
    import tempfile

    if not (code or "").strip():
        return {"exit_code": -1, "stdout": "", "stderr": "No code provided."}

    safe_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    preexec = None
    if os.name == "posix":
        def _apply_limits() -> None:  # pragma: no cover - child process
            try:
                import resource
                resource.setrlimit(resource.RLIMIT_CPU, (timeout_s, timeout_s + 1))
                mem = 512 * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
                resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))  # no file writes
            except Exception:
                pass
        preexec = _apply_limits

    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=safe_env,
            cwd=tempfile.gettempdir(),
            preexec_fn=preexec,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": f"Timed out after {timeout_s}s."}
    except Exception as exc:  # noqa: BLE001
        return {"exit_code": -1, "stdout": "", "stderr": f"Sandbox error: {exc}"}


def _run_probe_sql(ws: WorkspaceClient, sql: str, max_rows: int = 1) -> Dict[str, Any]:
    """Run a bounded, read-only probe under OBO, returning columns AND rows.

    Wraps arbitrary queries in ``SELECT * FROM (...) LIMIT N`` when they lack a
    ``LIMIT`` so a probe can never scan a whole table. Returns
    ``{"columns": [...], "rows": [[...], ...]}`` or ``{"error": ...}``.
    """
    from databricks.sdk.service.sql import Disposition, StatementExecutionAPI

    warehouse_id = os.environ.get("SQL_WAREHOUSE_ID", "")
    if not warehouse_id:
        return {"error": "No SQL_WAREHOUSE_ID configured."}
    query = (sql or "").strip().rstrip(";")
    if not query:
        return {"error": "Empty query."}
    limit = max(1, min(int(max_rows or 1), 50))
    if not re.search(r"\bLIMIT\b", query, re.IGNORECASE):
        query = f"SELECT * FROM ({query}) AS _schema_probe LIMIT {limit}"
    try:
        sql_api = StatementExecutionAPI(ws.api_client)
        stmt = sql_api.execute_statement(
            warehouse_id=warehouse_id,
            statement=query,
            wait_timeout="50s",
            disposition=Disposition.INLINE,
        )
        columns: List[str] = []
        if stmt.manifest and stmt.manifest.schema and stmt.manifest.schema.columns:
            columns = [c.name for c in stmt.manifest.schema.columns]
        rows: List[List[Any]] = []
        if stmt.result and stmt.result.data_array:
            rows = stmt.result.data_array
        return {"columns": columns, "rows": rows}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _probe_sql_schema(ws: WorkspaceClient, sql: str) -> Dict[str, Any]:
    """Confirm a query/table shape under OBO (columns only, backward-compat)."""
    return _run_probe_sql(ws, sql, max_rows=1)


# UC identifiers we interpolate into information_schema queries. Restricting to
# word chars keeps the discovery helpers injection-safe (they already run under
# the caller's OBO token, but defense-in-depth is cheap).
_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _valid_ident(name: str) -> bool:
    return bool(name and _IDENT_RE.match(name))


def _list_tables(ws: WorkspaceClient, catalog: str, schema: str) -> Dict[str, Any]:
    """List table names in ``catalog.schema`` via information_schema (read-only)."""
    catalog = (catalog or "").strip()
    schema = (schema or "").strip()
    if not _valid_ident(catalog) or not _valid_ident(schema):
        return {"error": "catalog and schema must be simple identifiers (letters, digits, underscore)."}
    q = (
        f"SELECT table_name FROM {catalog}.information_schema.tables "
        f"WHERE table_schema = '{schema}' ORDER BY table_name LIMIT 500"
    )
    result = _run_probe_sql(ws, q, max_rows=500)
    if result.get("error"):
        return result
    tables = [r[0] for r in (result.get("rows") or []) if r and r[0] is not None]
    return {"tables": tables}


def _describe_table(ws: WorkspaceClient, catalog: str, schema: str, table: str) -> Dict[str, Any]:
    """List a table's columns/types via information_schema (read-only)."""
    catalog = (catalog or "").strip()
    schema = (schema or "").strip()
    table = (table or "").strip()
    if not (_valid_ident(catalog) and _valid_ident(schema) and _valid_ident(table)):
        return {"error": "catalog, schema, and table must be simple identifiers (letters, digits, underscore)."}
    q = (
        f"SELECT column_name, data_type FROM {catalog}.information_schema.columns "
        f"WHERE table_schema = '{schema}' AND table_name = '{table}' "
        f"ORDER BY ordinal_position LIMIT 1000"
    )
    result = _run_probe_sql(ws, q, max_rows=1000)
    if result.get("error"):
        return result
    cols = [
        {"name": r[0], "type": r[1] if len(r) > 1 else ""}
        for r in (result.get("rows") or [])
        if r and r[0] is not None
    ]
    return {"columns": cols}


def _fmt_cell(value: Any, limit: int = 40) -> str:
    """Render one probe cell for display: NULL-safe and length-capped."""
    if value is None:
        return "NULL"
    s = str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


# ------------------------------------------------------------ authoring agent

AUTHORING_SYSTEM_PROMPT = """\
You are the Agent Studio authoring assistant for an enterprise data platform.
Your job is to help an author design ONE agent profile: a system prompt
(AGENT.md body) plus a small set of single-file markdown skills.

Hard rules:
- Agents can ONLY use tools exposed by the Unity Catalog AI Gateway MCP. Before
  recommending any tool, call `list_available_tools` and choose ONLY from the
  returned names. Never invent tool names. If a needed capability is missing,
  record it under `review.missing` instead of pretending it exists.
- When the agent will query data, DISCOVER and CONFIRM the real schema before
  writing any SQL — never guess table or column names:
  - `list_tables(catalog, schema)` to enumerate the actual table names.
  - `describe_table(catalog, schema, table)` to get a table's real columns/types.
  - `probe_sql_schema(sql)` to validate a specific query and preview a few rows.
  Reflect the confirmed columns in the prompt/skills and record each check under
  `review.schema_checks`. If a table/schema cannot be confirmed with these tools,
  record it under `review.ambiguities` rather than inventing names.
- When they are available, RESEARCH the data the agent will answer about, so the
  prompt and skills describe it accurately rather than generically:
  - `run_sql(query)` runs a read-only query as the author (up to 200 rows): the
    distinct values of a status column, date coverage, typical volumes, how two
    tables join. Put what you learn into the prompt (for example "status is one
    of OPEN, HELD, SHIPPED") and record the query under `review.schema_checks`.
  - `ask_genie(question)` asks Databricks Genie, which knows the business
    definitions curated in the author's Genie spaces (what counts as "late", which
    table is authoritative). Slow; use it for meaning, not for rows.
  These are authoring-time research tools only. They are NOT tools the authored
  agent gets — its `tools` list still comes only from `list_available_tools`.
- Skills are SINGLE markdown files. Keep each focused; do not invent folders or
  multi-file skills.
- Prefer reusing/clarifying the author's existing prompt and skills when editing.
- Never use emojis, emoticons, or decorative Unicode symbols — neither in your
  own replies to the author nor in the AGENT.md body, skills, or any text you
  generate. Plain, professional text only.

Handling ambiguity:
- Do NOT block on missing detail. Make a reasonable, explicitly-stated
  assumption, build the draft anyway, and list the open question under
  `review.ambiguities` so the author can correct it. Only refuse to produce a
  draft if the request is impossible with the available tools.

How to write a good AGENT.md body (the `prompt` field):
- Write it as instructions TO the agent (second person), in markdown, no
  frontmatter. Aim for ~150-400 words. Include these sections, in order:
  - **Role**: one or two sentences on who the agent is and its scope.
  - **Capabilities & tools**: which tools it has and when to use each (reference
    the exact tool ids you selected).
  - **How to answer**: querying/data rules, when to use which skill, how to cite
    or show data, and the expected response format/tone.
  - **Boundaries**: what it must NOT do, how to handle out-of-scope requests,
    and how to behave when a tool errors, returns nothing, or the question is
    ambiguous (ask a brief clarifying question rather than guessing at data).
- Ground every data claim in a confirmed schema. Never reference columns or
  tables you have not seen via `probe_sql_schema`.

Skill quality and length budget:
- Add a skill only when it captures a reusable, multi-step procedure that would
  bloat the main prompt. Otherwise keep guidance in the AGENT.md body.
- Keep each skill content under ~250 words. Keep the whole draft compact to
  avoid truncation; prefer fewer, tighter skills over many long ones.

Authoring Python tools (custom code tools):
- When a needed capability is NOT available as an MCP tool, you may define a
  small Python function as a tool under `python_tools`. Each entry is a single,
  self-contained function with a typed signature and a docstring stating what it
  does and its arguments. The runtime exposes these to the agent through a
  sandboxed `execute_python`.
- ALWAYS validate a Python tool before proposing it: call the `execute_python`
  tool with the function plus a tiny test call that `print()`s a sample result.
  Iterate until it runs cleanly. Record the check under `review.schema_checks`
  (use the test snippet as the `query`) and note any remaining concerns under
  `review.safety`.
- Safety rules for Python tools (NON-NEGOTIABLE — this is the evaluation gate):
  - NEVER hardcode credentials, tokens, API keys, passwords, or connection
    strings. NEVER read secrets from environment variables, files, or args.
  - Keep tools pure and deterministic: inputs in, value out. No destructive
    filesystem writes, no shelling out / subprocess, no network calls, no
    unbounded loops.
  - Prefer the Python standard library. If a tool needs governed data, it must
    accept that data as an argument (fetched via an MCP/SQL tool upstream), not
    fetch it itself with embedded credentials.
  - If the author asks for something unsafe (e.g. "just paste my token in the
    code"), REFUSE that part, implement it the safe way, and explain why under
    `review.safety`.
- Use Python tools sparingly. Good ones are deterministic transforms or
  calculations (date math, unit conversion, parsing, formatting, scoring), NOT
  data fetchers. Prefer MCP tools for anything touching governed data.

`review.schema_checks[].ok` semantics: set `ok` to true ONLY if the probe
returned and the columns the agent relies on are present; set it to false if the
probe errored or an expected column is missing. Do not mark `ok: true` for
queries you did not actually probe.

Output contract (STRICT):
- Write a short human-readable explanation FIRST, then end your reply with a
  SINGLE fenced ```json block and nothing after it.
- The JSON must be valid: escape newlines inside string values as \\n and escape
  any double quotes. Do not include comments or trailing commas. Markdown bodies
  (`prompt`, skill `content`) go inside JSON strings — they must be properly
  escaped.
- Match this shape exactly:
```json
{
  "name": "short profile name",
  "description": "one-line description",
  "model": "serving endpoint name or empty",
  "tools": ["<exact AI Gateway MCP tool ids>"],
  "prompt": "the AGENT.md body (markdown, no frontmatter)",
  "skills": [{"name": "Skill name", "description": "one line", "content": "markdown body"}],
  "python_tools": [{"name": "Tool name", "description": "one line", "code": "def tool(x: int) -> int:\\n    \\"\\"\\"docstring\\"\\"\\"\\n    return x"}],
  "review": {
    "suggested_tools": [{"name": "tool", "why": "reason"}],
    "missing": ["capabilities requested but not available as MCP tools"],
    "ambiguities": ["questions the author should resolve"],
    "schema_checks": [{"query": "...", "columns": ["..."], "ok": true}],
    "safety": ["Python-tool safety notes: anything refused/changed, or 'No issues — no hardcoded secrets, pure functions'"]
  }
}
```
- `python_tools` is OPTIONAL — include it only when you actually defined custom
  code tools; otherwise use `[]`. The `code` value is a JSON string, so escape
  newlines as \\n and quotes as needed.

Worked example (abbreviated — your `prompt` should be fuller than this):
```json
{
  "name": "Orders Analyst",
  "description": "Answers supply-chain questions from the orders table.",
  "model": "",
  "tools": ["sql/execute_sql"],
  "prompt": "# Orders Analyst\\n\\n## Role\\nYou answer supply-chain questions about customer orders for internal ops staff.\\n\\n## Capabilities & tools\\nUse `sql/execute_sql` to query the `orders` table. Confirmed columns: order_id, status, region, total_amount, created_at.\\n\\n## How to answer\\nWrite a single SQL query scoped to the user's question, then summarize the result in plain language and show the key numbers. Default to the last 90 days unless the user gives a range.\\n\\n## Boundaries\\nOnly answer from the orders data. If a question needs data you cannot reach, say so. If a query returns no rows, say the result was empty rather than inventing numbers.",
  "skills": [],
  "python_tools": [],
  "review": {
    "suggested_tools": [{"name": "sql/execute_sql", "why": "Needed to read the orders table."}],
    "missing": [],
    "ambiguities": ["Should 'recent' default to 90 days?"],
    "schema_checks": [{"query": "SELECT * FROM orders", "columns": ["order_id", "status", "region", "total_amount", "created_at"], "ok": true}],
    "safety": []
  }
}
```
"""


def _make_tools(ws: WorkspaceClient, confirm_schema: bool):
    from langchain_core.tools import tool

    # MCP discovery is a network round-trip per server; the agent often calls
    # `list_available_tools` more than once per run, so memoize the catalog for
    # the lifetime of this tool set (one authoring run).
    _catalog_cache: Dict[str, List[Dict[str, Any]]] = {}

    def _catalog() -> List[Dict[str, Any]]:
        if "tools" not in _catalog_cache:
            _catalog_cache["tools"] = [t for t in discover_mcp_tools(ws, genie_spaces=True) if not t.get("internal")]
        return _catalog_cache["tools"]

    @tool
    def list_available_tools(query: str = "") -> str:
        """List agent tools available via the Unity Catalog AI Gateway MCP.

        Optionally filter by a substring `query`. Returns tool name + description.
        Only names returned here may be referenced in the profile.
        """
        catalog = _catalog()
        if query:
            q = query.lower()
            catalog = [t for t in catalog if q in t["name"].lower() or q in t["description"].lower()]
        if not catalog:
            return "No MCP tools discovered. Do not reference any tools; record needs under review.missing."
        lines = [
            f"- {t['id']}: " + (f"[Genie space: {t['server_title']}] " if t.get("source") == "genie_space" else "")
            + t["description"]
            for t in catalog[:100]
        ]
        return (
            "Available AI Gateway MCP tools. Reference tools by their exact id "
            "(the server-qualified value before the colon) in the profile's "
            "`tools` list:\n" + "\n".join(lines)
        )

    @tool
    def list_tables(catalog: str, schema: str) -> str:
        """List the real table names in a Unity Catalog schema.

        Call this to DISCOVER actual table names before referencing them — never
        guess. Runs a read-only information_schema query under your access.
        `catalog` and `schema` are the two-level names (e.g. catalog="main",
        schema="sales").
        """
        if not confirm_schema:
            return "Schema confirmation is disabled for this run."
        result = _list_tables(ws, catalog, schema)
        if result.get("error"):
            return f"list_tables failed: {result['error']}"
        names = result.get("tables") or []
        if not names:
            return f"No tables found in {catalog}.{schema} (empty schema or no access)."
        return f"Tables in {catalog}.{schema} ({len(names)}):\n" + "\n".join(f"- {n}" for n in names)

    @tool
    def describe_table(catalog: str, schema: str, table: str) -> str:
        """List a table's real columns and types (read-only).

        Call this to CONFIRM column names/types for a known table before writing
        SQL or documenting the schema. Runs a read-only information_schema query.
        """
        if not confirm_schema:
            return "Schema confirmation is disabled for this run."
        result = _describe_table(ws, catalog, schema, table)
        if result.get("error"):
            return f"describe_table failed: {result['error']}"
        cols = result.get("columns") or []
        if not cols:
            return f"No columns found for {catalog}.{schema}.{table} (missing table or no access)."
        body = "\n".join(f"- {c['name']}: {c['type']}" for c in cols)
        return f"Columns of {catalog}.{schema}.{table} ({len(cols)}):\n{body}"

    @tool
    def probe_sql_schema(sql: str) -> str:
        """Confirm a SQL query/table's columns AND preview up to 5 sample rows.

        Runs a bounded, read-only probe (auto-wrapped in LIMIT). Use this to
        validate a specific query and see example VALUES. To enumerate table or
        column names, use `list_tables` / `describe_table` instead — this returns
        the result-set columns, not the catalog's table list.
        """
        if not confirm_schema:
            return "Schema confirmation is disabled for this run."
        result = _run_probe_sql(ws, sql, max_rows=5)
        if result.get("error"):
            return f"Schema probe failed: {result['error']}"
        cols = result.get("columns") or []
        rows = result.get("rows") or []
        out = ["Confirmed columns: " + (", ".join(cols) if cols else "(none returned)")]
        if rows:
            out.append(f"Sample rows ({len(rows)}):")
            out.extend("  " + " | ".join(_fmt_cell(v) for v in row) for row in rows[:5])
        return "\n".join(out)

    @tool
    def execute_python(code: str) -> str:
        """Run a short Python snippet in an isolated, credential-free sandbox.

        Use this to VALIDATE an author's Python tool before proposing it: paste
        the tool function plus a tiny test call that `print()`s a sample result,
        and confirm it runs cleanly. The sandbox has no credentials and a strict
        timeout, so never rely on secrets, network, or the filesystem here.
        Returns the exit code, stdout, and stderr.
        """
        result = _run_python_sandbox(code, _python_sandbox_timeout())
        parts = [f"exit_code={result['exit_code']}"]
        if result.get("stdout"):
            parts.append("stdout:\n" + result["stdout"])
        if result.get("stderr"):
            parts.append("stderr:\n" + result["stderr"])
        return "\n".join(parts)

    # Research, not just confirmation: `probe_sql_schema` proves a query parses and
    # shows five rows, which is not enough to write "statuses are OPEN, HELD and
    # SHIPPED" into an agent's prompt. Gated by the same `confirm_schema` switch as
    # the probes — both are the author saying whether this run may touch live data —
    # and by the admin switches, inside `langchain_tools`.
    research = research_tools.langchain_tools(ws) if confirm_schema else []
    return [list_available_tools, list_tables, describe_table, probe_sql_schema, execute_python, *research]


def _build_authoring_system_prompt(req: AuthorRequest) -> str:
    """Compose the authoring system prompt, grounding it in the current draft."""
    system_prompt = AUTHORING_SYSTEM_PROMPT
    if req.current_prompt:
        system_prompt += f"\n\nThe author's CURRENT AGENT.md body:\n```markdown\n{req.current_prompt}\n```"
    if req.current_skills:
        existing = "\n".join(f"- {s.name}: {s.description}" for s in req.current_skills)
        system_prompt += f"\n\nExisting skills:\n{existing}"
    if req.current_python_tools:
        existing_pt = "\n".join(
            f"- {t.name}: {t.description}" for t in req.current_python_tools
        )
        system_prompt += f"\n\nExisting Python tools:\n{existing_pt}"
    return system_prompt


def _agent_studio_max_tokens() -> int:
    """Output budget for the Agent Studio LLM (Admin Panel → Settings).

    The draft is a single JSON object holding the system prompt PLUS every skill
    body and Python tool. A too-small cap truncates that JSON mid-string, which
    surfaces as "The draft was cut off at the response length limit".
    A multi-skill agent easily exceeds 6k output tokens, so the default is generous.
    """
    return get_int_setting("authoring_max_tokens")


def _build_authoring_llm(api_key: str, base_url: str, params: Optional[Dict[str, Any]] = None):
    """The authoring client, with whatever parameters this model accepts.

    Which parameters those are is `services/llm_params.py`'s business — it drops
    what an endpoint refuses and adds what one demands, so every studio in the app
    behaves the same way when the model changes. `AGENT_STUDIO_LLM_TEMPERATURE`
    still works for deployments that set it, and is overridden by the `model_params`
    setting if that names a temperature too.
    """
    from services.llm_client import chat_client

    # Admin-settable (Admin Panel → Settings), falling back to AGENT_STUDIO_LLM_MODEL.
    model_name = get_setting("authoring_model")
    if params is None:
        params = llm_params.langchain_params(model_name, _agent_studio_max_tokens())
    kwargs: Dict[str, Any] = {
        **params,
        # Last, so nothing arriving in `params` can displace them: this dict is the
        # one place an admin-supplied value sits next to the credential and the host
        # it is sent to, and spreading `params` over the top would let a `base_url`
        # entry mail the app's token somewhere else. `llm_params.CONFIGURABLE` keeps
        # such a key out of `params` to begin with; this is the order that makes it
        # not matter.
        "api_key": api_key,
        "base_url": base_url,
        "model": model_name,
    }
    temp = (os.environ.get("AGENT_STUDIO_LLM_TEMPERATURE") or "").strip()
    if temp and "temperature" not in kwargs and "temperature" not in llm_params.describe(model_name)["omitted"]:
        try:
            kwargs["temperature"] = float(temp)
        except ValueError:
            pass
    return chat_client(**kwargs)


def _llm_credentials(sp_client: WorkspaceClient) -> tuple[str, str]:
    """Resolve (api_key, base_url) for the authoring LLM from the SP client.

    The base path follows the configured model name (see
    ``settings_store.base_path_for_model``), because the two routes accept
    different naming:
      - ``/serving-endpoints``: addresses models by *serving endpoint name*, e.g.
        ``databricks-claude-sonnet-4-6``.
      - ``/ai-gateway/mlflow/v1``: the UC-governed AI Gateway, which addresses
        models by their catalog name, e.g. ``system.ai.claude-opus-4-8`` (the
        non-deprecated path; workspace endpoints are being retired).
    ``AGENT_STUDIO_LLM_BASE_PATH`` overrides the derivation. Either way langchain
    appends ``/chat/completions``.
    """
    host = sp_client.config.host
    auth_headers_fn = sp_client.config.authenticate()
    auth_headers = auth_headers_fn() if callable(auth_headers_fn) else auth_headers_fn
    api_key = auth_headers.get("Authorization", "").replace("Bearer ", "") if auth_headers else ""
    api_key = (
        api_key
        or sp_client.config.token
        or os.environ.get("DATABRICKS_TOKEN")
        or "dummy"
    )
    base_path = base_path_for_model(get_setting("authoring_model"), "AGENT_STUDIO_LLM_BASE_PATH")
    base_url = f"{host}{base_path}" if host else os.environ.get("OPENAI_BASE_URL", "")
    return api_key, base_url


# Authoring runs, readable from either worker; see `start_authoring`. Same table
# as Widget Studio's jobs, which is safe because job ids are UUIDs.
authoring_jobs = JobStore()

#: The shortest gap between two writes of a run's prose to the job table.
_AUTHORING_SAVE_SECS = 1.0


_FRIENDLY_TOOL = {
    "list_available_tools": "Listing available tools",
    "list_tables": "Listing tables",
    "describe_table": "Describing table",
    "probe_sql_schema": "Confirming schema",
    "execute_python": "Testing Python tool",
    **research_tools.TOOL_LABELS,
}


def _prose_cut(content: str) -> int:
    """Index where the human prose ends and the JSON payload begins (or -1).

    The model is asked to write a short explanation, then the profile as JSON.
    The JSON is not always fenced, and its skill bodies can themselves contain
    ``` code fences — so we cut at the EARLIEST of the first ``` fence or the
    first ``{`` (JSON object start), never merely the first fence.
    """
    candidates = [i for i in (content.find("```"), content.find("{")) if i != -1]
    return min(candidates) if candidates else -1


def _split_explanation(content: str) -> str:
    """Return only the human-readable prose, dropping the JSON payload."""
    cut = _prose_cut(content)
    explanation = content if cut == -1 else content[:cut]
    return re.sub(r"\n{3,}", "\n\n", explanation).strip()


def _scan_balanced_object(text: str, start: int) -> Optional[str]:
    """Return the first balanced ``{...}`` object at/after ``start``.

    Brace counting is string-aware (ignores braces inside JSON string literals
    and respects backslash escapes), so it is robust to skill bodies that embed
    ``` code fences, ``{`` / ``}`` characters, or stray punctuation. Returns
    ``None`` if no opening brace is found or the object never closes (truncated).
    """
    i = text.find("{", start)
    if i == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return None


def _read_draft(content: str, finish_reason: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """The profile JSON the model appended after its prose, or why it can't be used.

    The model often does NOT fence the JSON, and when it does the body can
    contain inner ``` fences that defeat a naive non-greedy regex. We therefore
    extract the JSON by balanced-brace scanning (string-aware), trying the
    fenced region first, then the whole message, then a greedy regex as a final
    fallback. The first candidate that parses wins.

    The reason is for the author: without it a draft that failed to arrive ends
    the run exactly like one that did, under prose saying the agent was built.
    A reply with no draft in it (a clarifying question) has no reason; only a
    ```json fence or a "prompt" key counts as an attempt at one.
    """
    candidates: List[str] = []
    fence = re.search(r"```json\s*\n", content, re.IGNORECASE)
    primary = _scan_balanced_object(content, fence.end() if fence else 0)
    if primary:
        candidates.append(primary)
    if fence:
        obj = _scan_balanced_object(content, 0)
        if obj:
            candidates.append(obj)
    greedy = re.search(r"\{.*\}", content, re.DOTALL)
    if greedy:
        candidates.append(greedy.group(0))

    error: Optional[ValueError] = None
    for raw in candidates:
        try:
            return json.loads(raw), None
        except ValueError as exc:
            error = error or exc

    if not (fence or '"prompt"' in content):
        return None, None
    if finish_reason == "length":
        problem = "The draft was cut off at the response length limit (Admin Panel → Settings)."
    elif primary is None:
        problem = "The draft was cut off before it finished."
    elif isinstance(error, json.JSONDecodeError):
        problem = f"The draft is not valid JSON ({error.msg} at line {error.lineno}, column {error.colno})."
    else:
        problem = "The draft is not valid JSON."
    logger.warning("Agent Studio: unusable draft: %s finish_reason=%s len=%d tail=%r",
                   problem, finish_reason, len(content), content[-160:])
    return None, problem


# --------------------------------------------------------------------- routes

@router.get("/tools")
def list_tools(refresh: bool = False, obo_token: Optional[str] = Depends(get_user_token)):
    """Every tool the current user can reach through the AI Gateway MCP.

    Unfiltered on purpose, Genie spaces, every other kind of managed server and
    internal tools included: the picker decides what to show by default
    (`source`, `internal`), and the author can widen it. ``refresh`` re-asks
    every server instead of using the cache. ``problems`` names servers that
    listed nothing, and whether signing in to them would fix it.
    """
    store = get_agent_studio_store()
    ws = store._client(obo_token)
    problems: List[Dict[str, Any]] = []
    tools = discover_mcp_tools(ws, genie_spaces=True, extra_kinds=True, fresh=refresh, problems=problems)
    return {"tools": tools, "problems": problems}


def _authorize_write(w: WorkspaceClient, visibility: str, domain: str, env: str) -> None:
    """Gate a write to a target visibility/domain (mirrors widgets/views).

    - personal: anyone may save their own private agent.
    - domain:   must be an editor (or admin) of that domain.
    - global:   must be a global admin.
    """
    vis = (visibility or VIS_PERSONAL).strip().lower()
    if vis == VIS_GLOBAL:
        require_global_admin(w)
    elif vis == VIS_DOMAIN:
        require_domain_editor(w, domain or DEFAULT_DOMAIN)
    # personal -> no domain role required


@router.get("/profiles")
def list_profiles(
    include_shared: bool = True,
    env: str = "dev",
    _: str = Depends(require_auth),
    obo_token: Optional[str] = Depends(get_user_token),
):
    store = get_agent_studio_store()
    email = _user_email(obo_token)
    try:
        profiles = store.list_profiles(obo_token, email, env=env, include_shared=include_shared)
    except AgentStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"profiles": [p.to_dict() for p in profiles]}


@router.get("/profiles/{profile_id}")
def get_profile(
    profile_id: str,
    env: str = "dev",
    _: str = Depends(require_auth),
    obo_token: Optional[str] = Depends(get_user_token),
):
    store = get_agent_studio_store()
    try:
        profile = store.get_profile(obo_token, profile_id, env=env)
    except ProfileAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except AgentStudioError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return profile.to_dict()


@router.post("/profiles")
def save_profile(
    req: SaveProfileRequest,
    env: str = "dev",
    w: WorkspaceClient = Depends(get_db_client),
    obo_token: Optional[str] = Depends(get_user_token),
):
    store = get_agent_studio_store()
    me = _get_current_username(w)
    skills = [s.dict() for s in req.skills] if req.skills is not None else None
    python_tools = (
        [t.dict() for t in req.python_tools] if req.python_tools is not None else None
    )

    # Determine the author to persist. On update, preserve the original author
    # (so the "shared by" badge stays accurate even when a domain editor edits
    # someone else's agent); on create, the author is the current user.
    owner = me
    if req.profile_id:
        existing = store.get_meta(req.profile_id, env=env)
        if existing is None:
            raise HTTPException(status_code=404, detail="Profile not found.")
        owner = existing.get("username") or me
        # Authorize editing the EXISTING record based on its current visibility.
        _authorize_write(w, existing.get("visibility") or VIS_PERSONAL, existing.get("domain") or DEFAULT_DOMAIN, env)
        # A personal agent can only be edited by its owner (unless global admin).
        if (existing.get("visibility") or VIS_PERSONAL) == VIS_PERSONAL and owner != me:
            require_global_admin(w)

    # Authorize writing to the TARGET visibility/domain.
    _authorize_write(w, req.visibility, req.domain, env)

    try:
        profile = store.save_profile(
            me,
            name=req.name,
            prompt=req.prompt,
            description=req.description,
            model=req.model,
            tools=req.tools,
            skills=skills,
            python_tools=python_tools,
            visibility=req.visibility,
            domain=req.domain,
            base=req.base,
            profile_id=req.profile_id,
            owner=owner,
            expected_updated_at=req.expected_updated_at,
            env=env,
        )
    except ProfileConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except AgentStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return profile.to_dict()


@router.delete("/profiles/{profile_id}")
def delete_profile(
    profile_id: str,
    env: str = "dev",
    w: WorkspaceClient = Depends(get_db_client),
    obo_token: Optional[str] = Depends(get_user_token),
):
    store = get_agent_studio_store()
    me = _get_current_username(w)
    existing = store.get_meta(profile_id, env=env)
    if existing is None:
        raise HTTPException(status_code=404, detail="Profile not found.")
    vis = existing.get("visibility") or VIS_PERSONAL
    # Same authorization as editing: owner for personal, domain editor for
    # domain, global admin for global.
    _authorize_write(w, vis, existing.get("domain") or DEFAULT_DOMAIN, env)
    if vis == VIS_PERSONAL and (existing.get("username") or "") != me:
        require_global_admin(w)
    try:
        store.delete_profile(profile_id, env=env)
    except AgentStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "deleted"}


class _Stopped(Exception):
    """Stop was pressed (on either worker); the run ends with what it has."""


async def _run_authoring(job_id: str, req: AuthorRequest, api_key: str, base_url: str,
                         obo_token: Optional[str]) -> None:
    """Run one authoring turn, writing its progress onto ``authoring_jobs[job_id]``.

    ``text`` is the prose so far, before the JSON payload, and ``tool_calls`` the
    tool pills; both are replaced rather than appended to, because a poll copies
    the job from a request thread while this one is writing it. Prose is written
    through to the table (which a poll on the other worker reads) at most every
    ``_AUTHORING_SAVE_SECS``; tool pills and the settled state go at once.
    The run settles as ``completed`` (with ``draft``, ``draft_error`` and
    ``explanation``), ``failed`` (``error``) or ``cancelled``.
    """
    job = authoring_jobs.get(job_id)
    last_save = 0.0

    def progress(force: bool = False, **fields: Any) -> None:
        nonlocal last_save
        job.update(fields)
        now = time.monotonic()
        if force or now - last_save >= _AUTHORING_SAVE_SECS:
            last_save = now
            authoring_jobs.save(job_id)

    def settle(**fields: Any) -> None:
        authoring_jobs.replace(job_id, {**job, **fields}, final=True)

    full = ""
    try:
        from langchain_core.messages import AIMessage, HumanMessage
        from langgraph.prebuilt import create_react_agent

        store = get_agent_studio_store()
        ws = store._client(obo_token)

        history = req.history[-6:] if len(req.history) > 6 else req.history
        lc_history: List[Any] = []
        for m in history:
            if m.role == "user":
                lc_history.append(HumanMessage(content=m.content))
            else:
                lc_history.append(AIMessage(content=m.content))

        # A parameter the endpoint refuses fails the first request, before
        # anything is shown, so that failure is learned from (`llm_params.adapt`)
        # and the run started again — the same recovery `with_adaptation` gives
        # the other callers. Once prose or a tool pill is on the job a poll may
        # already have shown it, and a retry would show it twice, so from then on
        # a failure is reported.
        model_name = get_setting("authoring_model")
        last_note = ""
        for remaining in range(2, -1, -1):
            params = llm_params.langchain_params(model_name, _agent_studio_max_tokens())
            agent = create_react_agent(
                model=_build_authoring_llm(api_key, base_url, params),
                tools=_make_tools(ws, req.confirm_schema),
                prompt=_build_authoring_system_prompt(req),
            )
            full = ""
            finish_reason: Optional[str] = None
            tool_calls: List[Dict[str, str]] = []
            tool_seen: set[str] = set()
            # Track which message produced the last prose so we can insert a
            # paragraph break between separate AI messages (the ReAct loop emits
            # one per step); otherwise their text runs together with no space.
            last_content_id: Optional[str] = None
            try:
                async for msg, _meta in agent.astream(
                    {"messages": lc_history + [HumanMessage(content=req.prompt)]},
                    stream_mode="messages",
                ):
                    # A tool call already running (Genie can take minutes) can't be
                    # interrupted, so Stop lands at the next message.
                    if authoring_jobs.is_cancelled(job_id):
                        raise _Stopped()

                    # A tool finished -> flip its pill to done.
                    if getattr(msg, "type", None) == "tool":
                        name = getattr(msg, "name", None)
                        if name:
                            label = _FRIENDLY_TOOL.get(name, name)
                            tool_calls = [{**tc, "status": "done"} if tc["tool_name"] == label else tc
                                          for tc in tool_calls]
                            progress(force=True, tool_calls=tool_calls)
                        continue

                    # New tool call requested by the model.
                    for tcc in getattr(msg, "tool_call_chunks", None) or []:
                        nm = tcc.get("name")
                        if nm and nm not in tool_seen:
                            tool_seen.add(nm)
                            tool_calls = [*tool_calls, {"tool_name": _FRIENDLY_TOOL.get(nm, nm), "status": "running"}]
                            progress(force=True, tool_calls=tool_calls)

                    finish_reason = (getattr(msg, "response_metadata", None) or {}).get("finish_reason") or finish_reason
                    content = reply_text(msg)
                    if not content:
                        continue
                    msg_id = getattr(msg, "id", None)
                    if last_content_id is not None and msg_id != last_content_id:
                        full += "\n\n"
                    last_content_id = msg_id
                    full += content
                    # Show only the prose before the JSON payload. The boundary
                    # (`{` or a ``` fence) is detected by _prose_cut and never
                    # shown. The only thing that could leak is the START of a
                    # fence, so hold back ONLY a trailing run of 1-2 backticks (a
                    # partial ```); everything else is shown verbatim.
                    cut = _prose_cut(full)
                    if cut != -1:
                        shown = full[:cut]
                    else:
                        stripped = full.rstrip("`")
                        trailing_ticks = len(full) - len(stripped)
                        shown = stripped if 0 < trailing_ticks < 3 else full
                    if len(shown) > len(job.get("text") or ""):
                        progress(text=shown)
                break
            except _Stopped:
                raise
            except Exception as exc:  # noqa: BLE001 — re-raised unless it taught us something
                sent = bool(job.get("text") or job.get("tool_calls"))
                note = None if sent else llm_params.adapt(
                    model_name, str(exc), llm_params.requested_tokens(params))
                if not note or not remaining or note == last_note:
                    raise
                last_note = note
                logger.info("Agent Studio authoring retrying: %s.", note)

        draft, draft_error = _read_draft(full, finish_reason)
        explanation = _split_explanation(full) or "Draft updated."
        settle(status="completed", draft=draft, draft_error=draft_error, explanation=explanation)
    except _Stopped:
        settle(status="cancelled")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Authoring run failed")
        settle(status="failed", error=str(exc))


def _authoring_task(job_id: str, req: AuthorRequest, api_key: str, base_url: str,
                    obo_token: Optional[str]) -> None:
    # A plain function, so FastAPI runs it on its thread pool: the run blocks on
    # the job table and on sync tools, and must not hold up the worker's loop.
    asyncio.run(_run_authoring(job_id, req, api_key, base_url, obo_token))


@router.post("/generate")
def start_authoring(
    req: AuthorRequest,
    background_tasks: BackgroundTasks,
    obo_token: Optional[str] = Depends(get_user_token),
    sp_client: WorkspaceClient = Depends(get_db_client_sp),
):
    """Start an AI-assisted authoring run; poll ``GET /generate/{job_id}``.

    A job rather than a stream held open for the whole run: a run with Genie
    research takes minutes, and somewhere between the browser and the app a
    connection held that long was being cut ("network error"), which lost the
    draft even though the run was still going. A poll that fails is just tried
    again. LLM uses the SP credential; tools/probes use the caller's OBO.

    Jobs live in the store Widget Studio uses (``services/generation_jobs.py``),
    because with two workers half the polls and Stops reach the one that isn't
    running the job.
    """
    try:
        api_key, base_url = _llm_credentials(sp_client)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"LLM client init failed: {exc}")
    job_id = str(uuid.uuid4())
    authoring_jobs.create(job_id, {"status": "running", "text": "", "tool_calls": []})
    background_tasks.add_task(_authoring_task, job_id, req, api_key, base_url, obo_token)
    return {"job_id": job_id}


@router.get("/generate/{job_id}")
def get_authoring(job_id: str):
    job = authoring_jobs.snapshot(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/generate/{job_id}")
def stop_authoring(job_id: str):
    """Stop a run. Recorded on the job's row, so it reaches the other worker too."""
    job = authoring_jobs.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": job.get("status", "running"), "cancelled": True}


# --------------------------------------------------------------------- helper

def _user_email(obo_token: Optional[str]) -> str:
    """Best-effort caller email for the personal workspace path.

    The store re-resolves this via ``current_user.me()`` when possible, so this
    is only a fallback used to compose ``/Workspace/Users/<email>/.agents``.
    """
    return os.environ.get("AGENT_STUDIO_FALLBACK_EMAIL", "me")
