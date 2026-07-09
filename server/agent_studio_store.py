"""Agent Studio storage — domain-scoped CRUD over Postgres rows.

Agents authored in the Command Center's Agent Studio used to live as **files** on
Unity Catalog Volumes / the user's Workspace folder, governed by UC grants. That
broke for users who have *app* access ("anyone in my organization can access")
but no *workspace* access: they can't write to Volumes/Workspace folders, so they
could never save an agent.

Agents are now **database rows**, exactly like widgets and dashboard views, and
visibility follows the same ``role_mappings`` (domain) model instead of UC file
grants:

  * ``visibility='personal'`` — only the creator (``username``) sees it. No domain
    role is required to save one, so anyone can keep private drafts.
  * ``visibility='domain'`` — visible to anyone with access to ``domain``; domain
    editors (or global admins) can edit.
  * ``visibility='global'`` — visible to every authenticated user; only global
    admins can create/edit.

Each agent is one logical record (versioned like widgets/views): its skills,
tool ids, and author-written Python tools are stored inline as JSON. Write
authorization (editor/admin checks) is enforced at the route layer with the same
``require_domain_editor`` / ``require_global_admin`` helpers used by widgets and
views; this module enforces *read* visibility so the chat proxy can safely
resolve a saved agent under the caller's own token.

A handful of pure helpers (frontmatter parsing, slug + markdown composition) are
retained because they're still handy for import/export and are covered by tests.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

AGENT_FILE = "AGENT.md"
SKILL_FILE = "SKILL.md"

# Visibility tiers (mirrors widgets' domain scoping + views' global flag, plus a
# private "personal" tier so users can keep drafts without any domain role).
VIS_PERSONAL = "personal"
VIS_DOMAIN = "domain"
VIS_GLOBAL = "global"
VALID_VISIBILITIES = {VIS_PERSONAL, VIS_DOMAIN, VIS_GLOBAL}
DEFAULT_DOMAIN = "General"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _max_bytes() -> int:
    try:
        return int(os.environ.get("AGENT_STUDIO_MAX_BYTES", str(256 * 1024)))
    except ValueError:
        return 256 * 1024


class AgentStudioError(Exception):
    """A user-facing storage failure (not found, invalid input, etc.)."""


class ProfileConflictError(AgentStudioError):
    """The profile changed since the caller loaded it (optimistic-concurrency)."""


class ProfileAccessError(AgentStudioError):
    """The caller may not read/write this profile (maps to HTTP 403)."""


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
    """An agent profile row (metadata; body populated on single fetch).

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
    version: int = 0
    domain: str = DEFAULT_DOMAIN
    visibility: str = VIS_PERSONAL
    # Email of whoever authored/last-saved the profile. Surfaced as a badge so
    # users can judge trust before running an other-authored shared profile.
    username: str = ""
    owned_by_me: bool = False
    # Optimistic-concurrency marker. The frontend echoes this back on save; a
    # mismatch means someone edited in between and we refuse the clobbering write.
    updated_at: str = ""
    # Populated only when a single profile is fetched (list views omit these).
    prompt: Optional[str] = None
    skills: Optional[List[SkillFile]] = None
    python_tools: Optional[List[PythonToolFile]] = None

    @property
    def author(self) -> str:
        return self.username

    @property
    def location_label(self) -> str:
        if self.visibility == VIS_GLOBAL:
            return "Global"
        if self.visibility == VIS_DOMAIN:
            return self.domain or DEFAULT_DOMAIN
        return "Personal"

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
            "visibility": self.visibility,
            "username": self.username,
            "author": self.author,
            "owned_by_me": self.owned_by_me,
            "location_label": self.location_label,
            "writable": True,
            "updated_at": self.updated_at,
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

def _norm_visibility(value: Optional[str]) -> str:
    v = (value or "").strip().lower()
    return v if v in VALID_VISIBILITIES else VIS_PERSONAL


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


# ---------------------------------------------------------------------- store

class AgentStudioStore:
    """Domain-scoped CRUD for agent profiles, backed by Postgres rows.

    Read visibility is enforced here (so the chat proxy can resolve a saved
    profile under the caller's own token). *Write* authorization (editor/admin)
    is enforced at the route layer with the shared ``require_*`` helpers, mirroring
    the widget/view convention; this class exposes ``get_meta`` so a route can
    read the existing row's visibility/owner before authorizing an edit.
    """

    # ---- OBO client (still needed for MCP tool discovery + schema probes) ----
    def _client(self, obo_token: Optional[str]):
        from databricks.sdk import WorkspaceClient

        if not os.environ.get("HOME"):
            os.environ["HOME"] = "/tmp"
        host = os.environ.get("DATABRICKS_HOST")
        dev_mode = os.environ.get("DEV_MODE", "").lower() == "true"
        if obo_token and host:
            # auth_type="pat" forces token auth, so any SP OAuth env vars present
            # in the App runtime are ignored without us mutating os.environ (which
            # would race across concurrent threadpool requests).
            return WorkspaceClient(host=host, token=obo_token, auth_type="pat")
        if dev_mode:
            return WorkspaceClient()
        if host:
            return WorkspaceClient(host=host)
        return WorkspaceClient()

    def _permissions(self, obo_token: Optional[str], env: str) -> Tuple[str, bool, Dict[str, str]]:
        """(username, is_global_admin, {domain: level}) for the caller.

        Reuses the exact role/permission logic widgets and views use — including
        the DEV_MODE / DISABLE_PERMISSION_CHECKS shortcuts — so agents share one
        access model with the rest of the app.
        """
        from routes.roles import _get_current_username, _get_user_permissions

        client = self._client(obo_token)
        try:
            username = _get_current_username(client)
        except Exception:  # noqa: BLE001
            username = "unknown"
        try:
            perms = _get_user_permissions(client, env)
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent perms lookup failed: %s", exc)
            perms = {"is_admin": False, "domain_permissions": {}}
        return username, bool(perms.get("is_admin")), dict(perms.get("domain_permissions") or {})

    def _can_read(self, row: Dict[str, Any], me: str, is_admin: bool, domains: Dict[str, str]) -> bool:
        if is_admin:
            return True
        vis = row.get("visibility") or VIS_PERSONAL
        if (row.get("username") or "") == me:
            return True
        if vis == VIS_GLOBAL:
            return True
        if vis == VIS_DOMAIN and (row.get("domain") or DEFAULT_DOMAIN) in domains:
            return True
        return False

    # ---- row <-> ref ------------------------------------------------------
    def _row_to_ref(self, row: Dict[str, Any], me: str, with_body: bool = False) -> ProfileRef:
        try:
            tools = json.loads(row.get("tools_json") or "[]")
        except Exception:  # noqa: BLE001
            tools = []
        ref = ProfileRef(
            id=row["id"],
            name=row.get("name") or "",
            description=row.get("description") or "",
            model=row.get("model") or "",
            tools=[t for t in tools if isinstance(t, str)],
            base=row.get("base") or "full",
            version=int(row.get("version") or 0),
            domain=row.get("domain") or DEFAULT_DOMAIN,
            visibility=row.get("visibility") or VIS_PERSONAL,
            username=row.get("username") or "",
            updated_at=row.get("updated_at") or "",
        )
        ref.owned_by_me = bool(ref.username) and ref.username == me
        if with_body:
            ref.prompt = row.get("prompt") or ""
            ref.skills = self._parse_skills(row.get("skills_json"))
            ref.python_tools = self._parse_pytools(row.get("python_tools_json"))
        return ref

    def _parse_skills(self, raw: Optional[str]) -> List[SkillFile]:
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

    def _parse_pytools(self, raw: Optional[str]) -> List[PythonToolFile]:
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

    # ---- low-level DB -----------------------------------------------------
    def _latest_rows(self, c) -> List[Dict[str, Any]]:
        c.execute(
            """
            SELECT ap.* FROM agent_profiles ap
            INNER JOIN (
                SELECT id, MAX(version) AS mv
                FROM agent_profiles
                WHERE is_deprecated = 0
                GROUP BY id
            ) latest ON ap.id = latest.id AND ap.version = latest.mv
            WHERE ap.is_deprecated = 0
            """
        )
        cols = [d[0] for d in c.description]
        return [dict(zip(cols, row)) for row in c.fetchall()]

    def _latest_row(self, c, profile_id: str) -> Optional[Dict[str, Any]]:
        c.execute(
            "SELECT * FROM agent_profiles WHERE id = %s AND is_deprecated = 0 ORDER BY version DESC LIMIT 1",
            (profile_id,),
        )
        row = c.fetchone()
        if not row:
            return None
        cols = [d[0] for d in c.description]
        return dict(zip(cols, row))

    # ---- listing ----------------------------------------------------------
    def list_profiles(
        self,
        obo_token: Optional[str],
        user_email: str,
        env: str = "dev",
        include_shared: bool = True,
    ) -> List[ProfileRef]:
        from database import get_db_connection

        me, is_admin, domains = self._permissions(obo_token, env)
        conn = get_db_connection(env)
        try:
            c = conn.cursor()
            rows = self._latest_rows(c)
        finally:
            conn.close()

        out: List[ProfileRef] = []
        for row in rows:
            if not self._can_read(row, me, is_admin, domains):
                continue
            ref = self._row_to_ref(row, me)
            if not include_shared and not ref.owned_by_me:
                continue
            out.append(ref)
        # Your own first, then by location tier + name.
        out.sort(key=lambda p: (not p.owned_by_me, p.location_label, p.name.lower()))
        return out

    # ---- read -------------------------------------------------------------
    def get_profile(self, obo_token: Optional[str], profile_id: str, env: str = "dev") -> ProfileRef:
        from database import get_db_connection

        me, is_admin, domains = self._permissions(obo_token, env)
        conn = get_db_connection(env)
        try:
            c = conn.cursor()
            row = self._latest_row(c, profile_id)
        finally:
            conn.close()
        if row is None:
            raise AgentStudioError("Profile not found.")
        if not self._can_read(row, me, is_admin, domains):
            raise ProfileAccessError("You do not have access to this profile.")
        return self._row_to_ref(row, me, with_body=True)

    def get_meta(self, profile_id: str, env: str = "dev") -> Optional[Dict[str, Any]]:
        """Latest row for a profile ignoring access (route-side authorization)."""
        from database import get_db_connection

        conn = get_db_connection(env)
        try:
            c = conn.cursor()
            return self._latest_row(c, profile_id)
        finally:
            conn.close()

    # ---- write ------------------------------------------------------------
    def save_profile(
        self,
        user_email: str,
        name: str,
        prompt: str,
        description: str = "",
        model: str = "",
        tools: Optional[List[str]] = None,
        skills: Optional[List[Dict[str, Any]]] = None,
        python_tools: Optional[List[Dict[str, Any]]] = None,
        visibility: str = VIS_PERSONAL,
        domain: str = DEFAULT_DOMAIN,
        base: str = "full",
        profile_id: Optional[str] = None,
        owner: Optional[str] = None,
        expected_updated_at: Optional[str] = None,
        env: str = "dev",
    ) -> ProfileRef:
        """Insert a new version row for a profile.

        The caller (route) is responsible for authorizing the write against the
        target visibility/domain BEFORE calling this. ``owner`` is the author to
        persist (the current user on create; the original author preserved on
        update). Optimistic concurrency is enforced against ``expected_updated_at``.
        """
        from database import get_db_connection

        if not name or not name.strip():
            raise AgentStudioError("Profile name is required.")

        tools = [t for t in (tools or []) if isinstance(t, str) and t.strip()]
        visibility = _norm_visibility(visibility)
        domain = _norm_domain(domain)
        base = (base or "full").strip() or "full"
        me = (user_email or "").strip()
        owner = (owner or me or "").strip()

        skills_dicts = _skill_dicts(skills) if skills is not None else []
        pytool_dicts = _pytool_dicts(python_tools) if python_tools is not None else []

        tools_json = json.dumps(tools)
        skills_json = json.dumps(skills_dicts)
        pytools_json = json.dumps(pytool_dicts)
        prompt = prompt or ""

        payload_size = len(prompt.encode("utf-8")) + len(skills_json.encode("utf-8")) + len(pytools_json.encode("utf-8"))
        if payload_size > _max_bytes():
            raise AgentStudioError(f"Profile exceeds max size ({_max_bytes() // 1024} KB).")

        updated_at = datetime.now(timezone.utc).isoformat()

        conn = get_db_connection(env)
        try:
            c = conn.cursor()
            if profile_id:
                existing = self._latest_row(c, profile_id)
                if existing is None:
                    raise AgentStudioError("Profile not found.")
                # Optimistic concurrency: refuse to clobber a newer edit.
                cur_ver = existing.get("updated_at") or ""
                if expected_updated_at and cur_ver and cur_ver != expected_updated_at:
                    raise ProfileConflictError(
                        "This profile was changed by someone else since you opened "
                        "it. Reload to get the latest version, then re-apply your edits."
                    )
                # Preserve the original author unless one was explicitly supplied.
                if not owner:
                    owner = existing.get("username") or me
                c.execute("SELECT MAX(version) FROM agent_profiles WHERE id = %s", (profile_id,))
                row = c.fetchone()
                new_version = (row[0] or 0) + 1 if row else 1
            else:
                profile_id = str(uuid.uuid4())
                new_version = 1

            c.execute(
                """
                INSERT INTO agent_profiles
                (id, version, name, description, model, base, prompt, tools_json,
                 skills_json, python_tools_json, domain, visibility, username,
                 is_deprecated, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s)
                """,
                (
                    profile_id, new_version, name.strip(), (description or "").strip(),
                    (model or "").strip(), base, prompt, tools_json, skills_json,
                    pytools_json, domain, visibility, owner, updated_at,
                ),
            )
            conn.commit()
            row = self._latest_row(c, profile_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        ref = self._row_to_ref(row, me, with_body=True)
        return ref

    def delete_profile(self, profile_id: str, env: str = "dev") -> None:
        """Soft-delete every version of a profile (mirrors widgets)."""
        from database import get_db_connection

        conn = get_db_connection(env)
        try:
            c = conn.cursor()
            c.execute("UPDATE agent_profiles SET is_deprecated = 1 WHERE id = %s", (profile_id,))
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            raise AgentStudioError(f"Could not delete profile: {exc}") from exc
        finally:
            conn.close()

    def history(self, profile_id: str, env: str = "dev") -> List[Dict[str, Any]]:
        from database import get_db_connection

        conn = get_db_connection(env)
        try:
            c = conn.cursor()
            c.execute(
                "SELECT version, name, username, visibility, domain, updated_at, timestamp "
                "FROM agent_profiles WHERE id = %s ORDER BY version DESC",
                (profile_id,),
            )
            cols = [d[0] for d in c.description]
            return [dict(zip(cols, row)) for row in c.fetchall()]
        finally:
            conn.close()


_store: Optional[AgentStudioStore] = None


def get_agent_studio_store() -> AgentStudioStore:
    global _store
    if _store is None:
        _store = AgentStudioStore()
    return _store
