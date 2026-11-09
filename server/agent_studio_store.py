"""Agent Studio storage — agents as versioned Postgres rows, with drafts and sharing.

Agents authored in the Command Center's Agent Studio used to live as **files** on
Unity Catalog Volumes / the user's Workspace folder, governed by UC grants. That
broke for users who have *app* access ("anyone in my organization can access")
but no *workspace* access: they can't write to Volumes/Workspace folders, so they
could never save an agent.

Agents are now **database rows**, exactly like widgets and dashboard views, and
work the way they do:

  * **Who** may reach an agent is its access list (``services.access``): Can
    manage or Can use, for a user, a group or everyone. ``domain`` is only a label
    for filtering; it grants nothing. Anyone may create an agent, and the creator
    is given Can manage.
  * **What** they see is a draft or a published version (``services.drafts``).
    Managers edit a draft saved in place; Publish makes it the next row of
    ``agent_profiles``. People who can only use an agent — and every chat, for
    everyone — read the newest published version, so an agent that has never been
    published doesn't exist for them.

Authorization is enforced here rather than in the routes, so the chat proxy and
the Studio's CRUD resolve an agent through the same checks.

Each agent is one logical record: its skills, tool ids, and author-written Python
tools are stored inline as JSON. A handful of pure helpers (frontmatter parsing,
slug + markdown composition) are retained because they're still handy for
import/export and are covered by tests.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException

from services import access, drafts
from services.creator_stats import same_person

logger = logging.getLogger(__name__)

AGENT_FILE = "AGENT.md"
SKILL_FILE = "SKILL.md"

DEFAULT_DOMAIN = "General"
NOT_FOUND = "Agent not found."

# The `visibility` column predates access lists. Nothing here reads it, but the
# previous release does, so a published row keeps a value that makes a rollback
# list the agent no wider than its access list does now.
_LEGACY_PERSONAL = "personal"
_LEGACY_GLOBAL = "global"

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Tool ids an agent may have been saved with -> the id the catalog lists today.
# Genie One's ask tool is `genie_ask` on the server and `genie_one` in this app;
# agents saved before the rename hold the server's name. Mapping on read, rather
# than migrating, leaves versioned rows alone and also covers rows that arrive
# later by snapshot import.
TOOL_ID_ALIASES = {"genie/genie_ask": "genie/genie_one", "genie_ask": "genie_one"}
_UPSTREAM_TOOL_IDS = {new: old for old, new in TOOL_ID_ALIASES.items()}


def canonical_tool_ids(tools: List[Any]) -> List[str]:
    """An agent's tool ids under their current names, deduplicated, order kept."""
    ids = (TOOL_ID_ALIASES.get(t, t) for t in tools or [] if isinstance(t, str))
    return list(dict.fromkeys(ids))


def upstream_tool_ids(tools: List[Any]) -> List[str]:
    """The reverse, for a runtime that only knows the servers' own names."""
    return [_UPSTREAM_TOOL_IDS.get(t, t) for t in tools or [] if isinstance(t, str)]


def _max_bytes() -> int:
    try:
        return int(os.environ.get("AGENT_STUDIO_MAX_BYTES", str(256 * 1024)))
    except ValueError:
        return 256 * 1024


class AgentStudioError(Exception):
    """A user-facing storage failure (invalid input, etc.); maps to HTTP 400."""


class ProfileConflictError(AgentStudioError):
    """The profile changed since the caller loaded it (optimistic-concurrency)."""


# --------------------------------------------------------------------- models

@dataclass
class SkillFile:
    """A single skill attached to a profile."""

    slug: str
    name: str
    description: str = ""
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "content": self.content,
        }


@dataclass
class PythonToolFile:
    """An author-written Python tool the runtime can call via its sandbox.

    A tool is a small, self-contained Python function; ``code`` is the pristine
    function body (no metadata header — that only exists for the legacy file
    format, rebuilt on demand by ``build_python_tool_file``).
    """

    slug: str
    name: str
    description: str = ""
    code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "code": self.code,
        }


@dataclass
class ProfileRef:
    """An agent as one caller sees it (metadata; body populated on single fetch).

    ``id`` is the stable, opaque handle (a UUID) the frontend and chat runtime
    round-trip to address the profile across versions.
    """

    id: str
    name: str
    description: str = ""
    model: str = ""
    tools: List[str] = field(default_factory=list)
    # How the profile body combines with the runtime's structural prompt:
    # "full" (default) layers the persona on top of the runtime scaffold;
    # "none"/"standalone" makes the body the entire system prompt.
    base: str = "full"
    # The published version this row is (or, for a draft, was started from); 0
    # when the agent has never been published.
    version: int = 0
    domain: str = DEFAULT_DOMAIN
    # Email of whoever created the profile. Surfaced as a badge so users can
    # judge trust before running someone else's agent.
    username: str = ""
    owned_by_me: bool = False
    # Optimistic-concurrency marker. The frontend echoes this back on save; a
    # mismatch means someone edited in between and we refuse the clobbering write.
    updated_at: str = ""
    access: Optional[str] = None
    state: Optional[str] = None
    published_version: Optional[int] = None
    is_draft: bool = False
    published_by: str = ""
    published_at: str = ""
    # Populated only when a single profile is fetched (list views omit these).
    prompt: Optional[str] = None
    skills: Optional[List[SkillFile]] = None
    python_tools: Optional[List[PythonToolFile]] = None

    @property
    def author(self) -> str:
        return self.username

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "model": self.model,
            "tools": list(self.tools),
            "base": self.base,
            "domain": self.domain,
            "username": self.username,
            "author": self.author,
            "owned_by_me": self.owned_by_me,
            "access": self.access,
            "state": self.state,
            "published_version": self.published_version,
            "has_draft": self.state in (drafts.DRAFT_ONLY, drafts.PUBLISHED_WITH_DRAFT),
            "is_draft": self.is_draft,
            "writable": self.access == access.MANAGE,
            "updated_at": self.updated_at,
            "published_by": self.published_by,
            "published_at": self.published_at,
        }
        if self.prompt is not None:
            d["prompt"] = self.prompt
        if self.skills is not None:
            d["skills"] = [s.to_dict() for s in self.skills]
        if self.python_tools is not None:
            d["python_tools"] = [t.to_dict() for t in self.python_tools]
        return d


# --------------------------------------------------------- pure text helpers
# Retained for import/export + covered by tests; not used by the DB path itself.

def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug or "agent"


def parse_frontmatter(content: str) -> Dict[str, Any]:
    """Tolerant scan of a leading ``---`` YAML block (no YAML dependency)."""
    meta: Dict[str, Any] = {"body": content, "tools": []}
    text = content.lstrip()
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    block = text[3:end]
    after = text[end + 4:]
    meta["body"] = after.lstrip("\n")

    tools: List[str] = []
    current_list_key: Optional[str] = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_list_key == "tools":
            tools.append(stripped[2:].strip().strip('"').strip("'"))
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip().lower()
        val = val.strip()
        current_list_key = None
        if key == "tools":
            current_list_key = "tools"
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                if inner:
                    tools.extend(t.strip().strip('"').strip("'") for t in inner.split(",") if t.strip())
            continue
        meta[key] = val.strip('"').strip("'")
    meta["tools"] = [t for t in tools if t]
    return meta


def build_agent_markdown(
    name: str,
    description: str,
    model: str,
    tools: List[str],
    prompt: str,
    updated_at: str = "",
    author: str = "",
) -> str:
    """Compose an AGENT.md from metadata + the main prompt body (export/import)."""
    safe_desc = (description or "").replace("\n", " ").strip()
    tools_inline = ", ".join(t.strip() for t in (tools or []) if t.strip())
    body = (prompt or "").strip() or f"# {name.strip()}\n\nDescribe how this agent should behave."
    lines = [
        "---",
        f"name: {name.strip()}",
        f"description: {safe_desc}",
        f"model: {(model or '').strip()}",
        f"tools: [{tools_inline}]",
    ]
    if author:
        lines.append(f"author: {author.strip()}")
    if updated_at:
        lines.append(f"updated_at: {updated_at}")
    lines += ["---", "", body]
    return "\n".join(lines) + "\n"


def build_skill_markdown(name: str, description: str, body: str = "") -> str:
    body = (body or "").strip()
    if body.lstrip().startswith("---"):
        return body if body.endswith("\n") else body + "\n"
    safe_desc = (description or "").replace("\n", " ").strip()
    lines = ["---", f"name: {name.strip()}", f"description: {safe_desc}", "---", ""]
    if body:
        lines.append(body)
    else:
        lines.append(f"# {name.strip()}\n\nStep-by-step instructions for the agent.")
    return "\n".join(lines) + "\n"


_PY_TOOL_BANNER = "# Agent Studio Python tool (generated — edit in Agent Studio)"


def build_python_tool_file(name: str, description: str, code: str = "") -> str:
    """Compose a ``tools/<slug>.py`` file: a metadata header + the tool code."""
    safe_name = (name or "").strip()
    safe_desc = (description or "").replace("\n", " ").strip()
    body = (code or "").strip("\n")
    header = "\n".join([
        _PY_TOOL_BANNER,
        f"# @name: {safe_name}",
        f"# @description: {safe_desc}",
    ])
    if not body:
        body = (
            "def my_tool(value: str) -> str:\n"
            '    """Describe what this tool does and its arguments."""\n'
            "    return value"
        )
    return f"{header}\n\n{body}\n"


def _basename(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def parse_python_tool(path: str, text: str) -> "PythonToolFile":
    """Parse a ``tools/<slug>.py`` file back into name/description/code."""
    slug = _basename(path)
    if slug.endswith(".py"):
        slug = slug[:-3]
    name, description = slug, ""
    lines = text.split("\n")
    i = 0
    saw_meta = False
    while i < len(lines) and lines[i].lstrip().startswith("#"):
        s = lines[i].strip()
        if s.startswith("# @name:"):
            name = s[len("# @name:"):].strip() or slug
            saw_meta = True
        elif s.startswith("# @description:"):
            description = s[len("# @description:"):].strip()
            saw_meta = True
        i += 1
    if not saw_meta:
        return PythonToolFile(slug=slug, name=name, description=description, code=text.strip("\n"))
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    code = "\n".join(lines[i:]).strip("\n")
    return PythonToolFile(slug=slug, name=name, description=description, code=code)


# --------------------------------------------------------------- normalization

def _norm_domain(value: Optional[str]) -> str:
    d = (value or "").strip()
    return d or DEFAULT_DOMAIN


def _skill_dicts(skills: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for sk in skills or []:
        name = (sk.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "slug": (sk.get("slug") or slugify(name)),
            "name": name,
            "description": (sk.get("description") or ""),
            "content": (sk.get("content") or ""),
        })
    return out


def _pytool_dicts(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for pt in tools or []:
        name = (pt.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "slug": (pt.get("slug") or slugify(name)),
            "name": name,
            "description": (pt.get("description") or ""),
            "code": (pt.get("code") or ""),
        })
    return out


# ------------------------------------------------------- pure access/draft rules

def profile_payload(
    *,
    name: str,
    prompt: str,
    description: str = "",
    model: str = "",
    tools: Optional[List[str]] = None,
    skills: Optional[List[Dict[str, Any]]] = None,
    python_tools: Optional[List[Dict[str, Any]]] = None,
    domain: str = DEFAULT_DOMAIN,
    base: str = "full",
    owner: str = "",
    visibility: str = _LEGACY_PERSONAL,
    updated_at: str = "",
) -> Dict[str, Any]:
    """The ``agent_profiles`` columns a draft holds, validated."""
    if not name or not name.strip():
        raise AgentStudioError("Profile name is required.")
    prompt = prompt or ""
    skills_json = json.dumps(_skill_dicts(skills))
    pytools_json = json.dumps(_pytool_dicts(python_tools))
    size = len(prompt.encode("utf-8")) + len(skills_json.encode("utf-8")) + len(pytools_json.encode("utf-8"))
    if size > _max_bytes():
        raise AgentStudioError(f"Profile exceeds max size ({_max_bytes() // 1024} KB).")
    return {
        "name": name.strip(),
        "description": (description or "").strip(),
        "model": (model or "").strip(),
        "base": (base or "full").strip() or "full",
        "prompt": prompt,
        "tools_json": json.dumps(canonical_tool_ids([t for t in (tools or []) if isinstance(t, str) and t.strip()])),
        "skills_json": skills_json,
        "python_tools_json": pytools_json,
        "domain": _norm_domain(domain),
        "visibility": visibility or _LEGACY_PERSONAL,
        "username": owner or "",
        "is_deprecated": 0,
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
    }


def check_unchanged(current: Optional[Dict[str, Any]], expected_updated_at: Optional[str]) -> None:
    """Refuse to clobber an edit made since the caller loaded the agent."""
    held = (current or {}).get("updated_at") or ""
    if expected_updated_at and held and held != expected_updated_at:
        raise ProfileConflictError(
            "This profile was changed by someone else since you opened "
            "it. Reload to get the latest version, then re-apply your edits."
        )


def legacy_visibility(entries: Iterable[Dict[str, Any]], current: Optional[str]) -> str:
    """The ``visibility`` a published row should carry for the previous release.

    Everyone on the access list is the old "global". Anything narrower can't be
    expressed (a group isn't a domain), so a row that was global falls back to
    personal: after a rollback it is reachable by fewer people, never more.
    """
    if any((e.get("principal") or "") == access.EVERYONE for e in entries or []):
        return _LEGACY_GLOBAL
    if not current or current == _LEGACY_GLOBAL:
        return _LEGACY_PERSONAL
    return current


def pick_view(level: Optional[str], mode: Optional[str], published: Optional[Dict[str, Any]],
              draft: Optional[Dict[str, Any]], object_id: str) -> Optional[Dict[str, Any]]:
    """The row this caller gets for ``mode``: the merged draft only for a manager asking for it.

    Without a mode a manager gets the draft and anyone else the published version.
    Someone who can only use an agent is served the published version whatever
    they ask for, so a draft never reaches them.
    """
    if level is None:
        return None
    if level == access.MANAGE and (mode or "draft") == "draft":
        return drafts.merge(published, draft, object_id)
    return dict(published) if published else None


def listing(published: Dict[str, Dict[str, Any]], pending: Dict[str, Dict[str, Any]],
            levels: Optional[Dict[str, str]], me: str, usable_only: bool = False) -> List["ProfileRef"]:
    """What ``GET /profiles`` returns, from rows already fetched.

    ``levels`` is the caller's level per id, or None for an admin (MANAGE on
    everything). A manager sees the draft merged over the newest published row;
    anyone else, and every caller when ``usable_only`` (the chat picker, which
    runs published versions), sees published rows only — so an agent that has
    never been published is listed only for its managers.
    """
    ids = set(published) | set(pending)
    out: List[ProfileRef] = []
    for object_id in ids:
        level = access.MANAGE if levels is None else levels.get(object_id)
        if level is None:
            continue
        pub = published.get(object_id)
        manager = level == access.MANAGE and not usable_only
        draft = pending.get(object_id) if manager else None
        row = drafts.merge(pub, draft, object_id) if manager else (dict(pub) if pub else None)
        if row is None:
            continue
        ref = _row_to_ref(row, me)
        ref.access = level
        ref.published_version = int(pub["version"]) if pub else None
        ref.state = drafts.state_of(draft is not None, ref.published_version)
        out.append(ref)
    out.sort(key=lambda p: (not p.owned_by_me, p.name.lower()))
    return out


def _parse_skills(raw: Optional[str]) -> List[SkillFile]:
    out: List[SkillFile] = []
    try:
        for s in json.loads(raw or "[]"):
            name = (s.get("name") or "").strip()
            if not name:
                continue
            out.append(SkillFile(
                slug=s.get("slug") or slugify(name),
                name=name,
                description=s.get("description") or "",
                content=s.get("content") or "",
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("skills_json parse failed: %s", exc)
    out.sort(key=lambda s: s.name.lower())
    return out


def _parse_pytools(raw: Optional[str]) -> List[PythonToolFile]:
    out: List[PythonToolFile] = []
    try:
        for t in json.loads(raw or "[]"):
            name = (t.get("name") or "").strip()
            if not name:
                continue
            out.append(PythonToolFile(
                slug=t.get("slug") or slugify(name),
                name=name,
                description=t.get("description") or "",
                code=t.get("code") or "",
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("python_tools_json parse failed: %s", exc)
    out.sort(key=lambda t: t.name.lower())
    return out


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _row_to_ref(row: Dict[str, Any], me: str, with_body: bool = False) -> ProfileRef:
    try:
        tools = json.loads(row.get("tools_json") or "[]")
    except Exception:  # noqa: BLE001
        tools = []
    ref = ProfileRef(
        id=row["id"],
        name=row.get("name") or "",
        description=row.get("description") or "",
        model=row.get("model") or "",
        tools=canonical_tool_ids(tools),
        base=row.get("base") or "full",
        version=int(row.get("version") or 0),
        domain=row.get("domain") or DEFAULT_DOMAIN,
        username=row.get("username") or "",
        updated_at=row.get("updated_at") or "",
        is_draft=bool(row.get("is_draft")),
        published_by=row.get("published_by") or "",
        published_at=_text(row.get("published_at")),
    )
    ref.owned_by_me = same_person(ref.username, me)
    if with_body:
        ref.prompt = row.get("prompt") or ""
        ref.skills = _parse_skills(row.get("skills_json"))
        ref.python_tools = _parse_pytools(row.get("python_tools_json"))
    return ref


# ---------------------------------------------------------------------- store

def _rows(c) -> List[Dict[str, Any]]:
    cols = [d[0] for d in c.description]
    return [dict(r) if hasattr(r, "keys") else dict(zip(cols, r)) for r in c.fetchall()]


class AgentStudioStore:
    """CRUD, publishing and sharing checks for agent profiles.

    Methods take the caller (``access.Caller``, or a WorkspaceClient to resolve
    one) and raise ``HTTPException`` for access (404 when the agent isn't shared
    with them, 403 when they can use but must manage) and ``AgentStudioError``
    for bad input.
    """

    # ---- OBO client (still needed for MCP tool discovery + schema probes) ----
    def _client(self, obo_token: Optional[str]):
        from databricks.sdk import WorkspaceClient
        from middleware.auth import _cached_client, _token_key

        if not os.environ.get("HOME"):
            os.environ["HOME"] = "/tmp"
        host = os.environ.get("DATABRICKS_HOST")
        dev_mode = os.environ.get("DEV_MODE", "").lower() == "true"
        # Cached per credential: the agent runtime builds a client for every turn
        # and every tool call, and the constructor is expensive enough to show up
        # in request latency. See middleware.auth for the caching rationale.
        if obo_token and host:
            # auth_type="pat" forces token auth, so any SP OAuth env vars present
            # in the App runtime are ignored without us mutating os.environ (which
            # would race across concurrent threadpool requests).
            return _cached_client(
                _token_key("obo", obo_token),
                lambda: WorkspaceClient(host=host, token=obo_token, auth_type="pat"),
            )
        if dev_mode:
            return _cached_client("dev-mode", WorkspaceClient)
        if host:
            return _cached_client(f"host:{host}", lambda: WorkspaceClient(host=host))
        return _cached_client("default", WorkspaceClient)

    def _row_to_ref(self, row: Dict[str, Any], me: str, with_body: bool = False) -> ProfileRef:
        return _row_to_ref(row, me, with_body)

    # ---- low-level DB -----------------------------------------------------
    def _latest_rows(self, c, ids: Optional[Iterable[str]]) -> Dict[str, Dict[str, Any]]:
        """Newest published, non-retired row per agent; ``ids`` None means all."""
        sql = """
            SELECT ap.* FROM agent_profiles ap
            INNER JOIN (
                SELECT id, MAX(version) AS mv
                FROM agent_profiles
                WHERE COALESCE(is_deprecated, 0) = 0
                GROUP BY id
            ) latest ON ap.id = latest.id AND ap.version = latest.mv
            WHERE COALESCE(ap.is_deprecated, 0) = 0
        """
        params: list = []
        if ids is not None:
            ids = [i for i in ids if i]
            if not ids:
                return {}
            sql += " AND ap.id = ANY(%s)"
            params.append(ids)
        c.execute(sql, params or None)
        return {r["id"]: r for r in _rows(c)}

    def _levels(self, who: access.Caller) -> Optional[Dict[str, str]]:
        return None if who.is_admin else access.grants_for(who, access.AGENT)

    def _as_ref(self, row: Dict[str, Any], who: access.Caller, level: str,
                published: Optional[Dict[str, Any]], has_draft: bool) -> ProfileRef:
        ref = _row_to_ref(row, who.username, with_body=True)
        ref.access = level
        ref.published_version = int(published["version"]) if published else None
        ref.state = drafts.state_of(has_draft and level == access.MANAGE, ref.published_version)
        return ref

    # ---- listing ----------------------------------------------------------
    def list_profiles(self, who: Any, usable_only: bool = False) -> List[ProfileRef]:
        """Agents the caller can reach; ``usable_only`` limits it to what chat can run."""
        from database import get_db_connection

        who = access.caller(who)
        levels = self._levels(who)
        if levels is not None and not levels:
            return []
        ids = None if levels is None else list(levels)
        managed = None if levels is None else [i for i, lv in levels.items() if lv == access.MANAGE]
        conn = get_db_connection()
        try:
            c = conn.cursor()
            published = self._latest_rows(c, ids)
            pending = {} if usable_only else drafts.drafts(c, access.AGENT, managed)
            conn.commit()
        finally:
            conn.close()
        return listing(published, pending, levels, who.username, usable_only)

    # ---- read -------------------------------------------------------------
    def get_profile(self, who: Any, profile_id: str, mode: Optional[str] = None) -> ProfileRef:
        """One agent with its body: the draft for a manager (unless ``mode='published'``)."""
        from database import get_db_connection

        who = access.caller(who)
        level = access.require(who, access.AGENT, profile_id, access.USE, not_found=NOT_FOUND)
        conn = get_db_connection()
        try:
            c = conn.cursor()
            published = drafts.latest(c, access.AGENT, profile_id)
            draft = drafts.read(c, access.AGENT, profile_id) if level == access.MANAGE else None
            conn.commit()
        finally:
            conn.close()
        row = pick_view(level, mode, published, draft, profile_id)
        if row is None:
            if published is None and draft is not None:
                raise HTTPException(status_code=404, detail="This agent hasn't been published yet.")
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return self._as_ref(row, who, level, published, draft is not None)

    def resolve_published(self, who: Any, profile_id: str) -> Optional[ProfileRef]:
        """The published agent chat should run, or None if the caller can't use one.

        Chat always runs the published version, managers included: the Studio's
        Try it sends its draft inline, so this is never how a draft is tried.
        """
        who = access.caller(who)
        try:
            return self.get_profile(who, profile_id, mode="published")
        except HTTPException as exc:
            if exc.status_code == 404:
                return None
            raise

    # ---- write ------------------------------------------------------------
    def save_draft(
        self,
        who: Any,
        *,
        name: str,
        prompt: str,
        description: str = "",
        model: str = "",
        tools: Optional[List[str]] = None,
        skills: Optional[List[Dict[str, Any]]] = None,
        python_tools: Optional[List[Dict[str, Any]]] = None,
        domain: str = DEFAULT_DOMAIN,
        base: str = "full",
        profile_id: Optional[str] = None,
        expected_updated_at: Optional[str] = None,
    ) -> ProfileRef:
        """Create an agent (as a draft only its creator can reach) or save over its draft."""
        from database import get_db_connection

        who = access.caller(who)
        creating = not profile_id
        if creating:
            if not who.is_admin and who.username in ("", "unknown"):
                # grant_owner can't record an owner it can't name, and an agent
                # with no manager is one only an admin could ever open again.
                raise HTTPException(status_code=401, detail="Couldn't tell who you are. Reload the page and try again.")
            profile_id = str(uuid.uuid4())
        else:
            access.require(who, access.AGENT, profile_id, access.MANAGE, not_found=NOT_FOUND)

        conn = get_db_connection()
        try:
            c = conn.cursor()
            published = None if creating else drafts.latest(c, access.AGENT, profile_id)
            draft = None if creating else drafts.read(c, access.AGENT, profile_id)
            current = drafts.merge(published, draft, profile_id)
            if not creating and current is None:
                raise HTTPException(status_code=404, detail=NOT_FOUND)
            check_unchanged(current, expected_updated_at)
            payload = profile_payload(
                name=name, prompt=prompt, description=description, model=model, tools=tools,
                skills=skills, python_tools=python_tools, domain=domain, base=base,
                owner=(current or {}).get("username") or who.username,
                visibility=(current or {}).get("visibility") or _LEGACY_PERSONAL,
            )
            if creating:
                drafts.save(c, access.AGENT, profile_id, payload, who.username, base_version=None)
            else:
                drafts.save(c, access.AGENT, profile_id, payload, who.username)
            saved = drafts.merge(published, drafts.read(c, access.AGENT, profile_id), profile_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if creating:
            access.grant_owner(access.AGENT, profile_id, who.username)
        return self._as_ref(saved, who, access.MANAGE, published, True)

    def publish(self, who: Any, profile_id: str) -> int:
        """Make the draft the next published version; returns that version."""
        from database import get_db_connection

        who = access.caller(who)
        access.require(who, access.AGENT, profile_id, access.MANAGE, not_found=NOT_FOUND)
        try:
            entries = access.get_acl(access.AGENT, profile_id)
        except Exception as exc:  # noqa: BLE001 - only the rollback label depends on it
            logger.warning("Could not read the access list of agent %s: %s", profile_id, exc)
            entries = []
        conn = get_db_connection()
        try:
            c = conn.cursor()
            draft = drafts.read(c, access.AGENT, profile_id)
            version = drafts.publish(c, access.AGENT, profile_id, who.username)
            c.execute(
                "UPDATE agent_profiles SET visibility = %s WHERE id = %s AND version = %s",
                (legacy_visibility(entries, ((draft or {}).get("payload") or {}).get("visibility")), profile_id, version),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return version

    def discard(self, who: Any, profile_id: str) -> None:
        """Throw the draft away, back to the published version."""
        from database import get_db_connection

        who = access.caller(who)
        access.require(who, access.AGENT, profile_id, access.MANAGE, not_found=NOT_FOUND)
        conn = get_db_connection()
        try:
            c = conn.cursor()
            if drafts.latest(c, access.AGENT, profile_id) is None:
                raise HTTPException(
                    status_code=409,
                    detail="This agent has never been published, so there is nothing to go back to. Delete it instead.",
                )
            drafts.discard(c, access.AGENT, profile_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def revert(self, who: Any, profile_id: str, version: int) -> ProfileRef:
        """Make an earlier published version the draft, to publish again or not."""
        from database import get_db_connection

        who = access.caller(who)
        access.require(who, access.AGENT, profile_id, access.MANAGE, not_found=NOT_FOUND)
        conn = get_db_connection()
        try:
            c = conn.cursor()
            drafts.revert(c, access.AGENT, profile_id, int(version), who.username)
            published = drafts.latest(c, access.AGENT, profile_id)
            saved = drafts.merge(published, drafts.read(c, access.AGENT, profile_id), profile_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self._as_ref(saved, who, access.MANAGE, published, True)

    def delete_profile(self, who: Any, profile_id: str) -> None:
        """Retire every version and drop the draft.

        Published versions are kept (flagged), like widgets, so the access list is
        kept with them; an agent that was only ever a draft leaves nothing behind,
        so its access list goes too.
        """
        from database import get_db_connection

        who = access.caller(who)
        access.require(who, access.AGENT, profile_id, access.MANAGE, not_found=NOT_FOUND)
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute("UPDATE agent_profiles SET is_deprecated = 1 WHERE id = %s", (profile_id,))
            had_versions = c.rowcount > 0
            drafts.discard(c, access.AGENT, profile_id)
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            raise AgentStudioError(f"Could not delete profile: {exc}") from exc
        finally:
            conn.close()
        if not had_versions:
            access.delete_acl(access.AGENT, profile_id)

    def history(self, who: Any, profile_id: str) -> List[Dict[str, Any]]:
        """Published versions, newest first, for a manager choosing one to revert to."""
        from database import get_db_connection

        who = access.caller(who)
        access.require(who, access.AGENT, profile_id, access.MANAGE, not_found=NOT_FOUND)
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT version, name, username, published_by, published_at, updated_at, timestamp "
                "FROM agent_profiles WHERE id = %s AND COALESCE(is_deprecated, 0) = 0 ORDER BY version DESC",
                (profile_id,),
            )
            rows = _rows(c)
            conn.commit()
        finally:
            conn.close()
        return [{k: (_text(v) if k in ("published_at", "timestamp") else v) for k, v in r.items()} for r in rows]


_store: Optional[AgentStudioStore] = None


def get_agent_studio_store() -> AgentStudioStore:
    global _store
    if _store is None:
        _store = AgentStudioStore()
    return _store
