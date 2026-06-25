"""Agent Studio storage — OBO-scoped CRUD over AGENT.md / SKILL.md folders.

The Command Center's Agent Studio authors **agent profiles** and **skills** as
plain files on Unity Catalog Volumes (and, optionally, the user's personal
Workspace folder). There is intentionally **no database** for these artifacts:
Unity Catalog governs who can see/edit/run them, and the consolidated agent
runtime loads the same files under the caller's token. This keeps one
governance model (UC grants) and makes profiles portable, inspectable files.

Layout
------
A *profile* is a folder that contains an ``AGENT.md`` and an optional
``skills/`` subfolder of ``*.md`` skill files::

    <base>/.agents/<slug>/AGENT.md
    <base>/.agents/<slug>/skills/<skill-slug>.md

``AGENT.md`` is markdown with a leading YAML frontmatter block carrying the
profile metadata (``name``, ``description``, ``model``, ``tools``); the body is
the main system prompt. Each ``skills/*.md`` is a single-file skill (its own
``name``/``description`` frontmatter + markdown instructions).

Two scopes, both addressed under a ``.agents`` directory:

  1. **Personal** — the user's Workspace folder
     (``/Workspace/Users/<email>/.agents``), read/written via the Workspace API
     (``RAW`` format).
  2. **Shared** — any ``.agents`` directory on a UC Volume the user can
     read/write, discovered by a bounded OBO walk of catalogs -> schemas ->
     volumes. Read/written via the Files API.

Every method builds the WorkspaceClient from the caller's OBO token, so a user
only ever sees/edits what Unity Catalog already permits — governance is not
re-implemented here.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

AGENT_FILE = "AGENT.md"
SKILL_FILE = "SKILL.md"
SKILLS_SUBDIR = "skills"
VERSIONS_SUBDIR = ".versions"      # per-profile AGENT.md history snapshots
PROMOTIONS_FILE = "PROMOTIONS.jsonl"  # append-only promotion audit (per target dir)

STORE_WORKSPACE = "workspace"
STORE_VOLUME = "volume"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _dir_name() -> str:
    return (os.environ.get("AGENT_STUDIO_DIR_NAME") or ".agents").strip() or ".agents"


def _max_bytes() -> int:
    try:
        return int(os.environ.get("AGENT_STUDIO_MAX_BYTES", str(256 * 1024)))
    except ValueError:
        return 256 * 1024


def _max_versions() -> int:
    """How many AGENT.md history snapshots to keep per profile (0 disables)."""
    try:
        return int(os.environ.get("AGENT_STUDIO_MAX_VERSIONS", "20"))
    except ValueError:
        return 20


def _discovery_ttl() -> float:
    """Seconds to cache the shared-volume discovery walk (0 disables)."""
    try:
        return float(os.environ.get("AGENT_STUDIO_DISCOVERY_TTL", "45"))
    except ValueError:
        return 45.0


def _configured_shared_locations() -> List[str]:
    """Pinned ``.agents`` directories to use INSTEAD of the metastore walk.

    Comma-separated absolute paths (UC Volume ``/Volumes/.../.agents`` or
    Workspace ``/Workspace/.../.agents``). When set, shared discovery lists only
    these — turning an O(catalogs×schemas×volumes) crawl into a handful of
    directory listings. Unset = fall back to the bounded crawl.
    """
    raw = (os.environ.get("AGENT_STUDIO_PROFILE_LOCATIONS") or "").strip()
    if not raw:
        return []
    return [p.strip().rstrip("/") for p in raw.split(",") if p.strip()]


def _scan_caps() -> Tuple[int, int, int]:
    def _cap(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, str(default)))
        except ValueError:
            return default

    return (
        _cap("AGENT_STUDIO_SCAN_MAX_CATALOGS", 25),
        _cap("AGENT_STUDIO_SCAN_MAX_SCHEMAS", 50),
        _cap("AGENT_STUDIO_SCAN_MAX_VOLUMES", 50),
    )


def _scan_catalogs() -> List[str]:
    return [c.strip() for c in (os.environ.get("AGENT_STUDIO_SCAN_CATALOGS") or "").split(",") if c.strip()]


class AgentStudioError(Exception):
    """A user-facing storage failure (permission denied, not found, etc.)."""


class ProfileConflictError(AgentStudioError):
    """The profile changed since the caller loaded it (optimistic-concurrency)."""


# --------------------------------------------------------------------- models

@dataclass
class SkillFile:
    """A single-file skill inside a profile's ``skills/`` folder."""

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
class ProfileRef:
    """An agent profile (folder + parsed metadata).

    ``id`` is an opaque, URL-safe handle (``store|dir_path``) the frontend and
    the runtime round-trip to address the profile.
    """

    store: str
    dir_path: str  # the folder that contains AGENT.md
    name: str
    description: str = ""
    model: str = ""
    tools: List[str] = field(default_factory=list)
    location_label: str = ""
    writable: bool = True
    # Provenance: the email of whoever last saved the profile, and whether that
    # is the current caller. Surfaced as a badge so users can judge trust before
    # running an other-authored shared profile.
    author: str = ""
    owned_by_me: bool = False
    # Version marker for optimistic concurrency. The frontend echoes this back
    # on save; if it no longer matches the stored value, someone else edited the
    # profile in between and we refuse the (clobbering) write.
    updated_at: str = ""
    # Populated only when a single profile is fetched (list views omit these).
    prompt: Optional[str] = None
    skills: Optional[List[SkillFile]] = None

    @property
    def agent_md_path(self) -> str:
        return f"{self.dir_path.rstrip('/')}/{AGENT_FILE}"

    @property
    def id(self) -> str:
        return encode_id(self.store, self.dir_path)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "store": self.store,
            "dir_path": self.dir_path,
            "name": self.name,
            "description": self.description,
            "model": self.model,
            "tools": list(self.tools),
            "location_label": self.location_label,
            "writable": self.writable,
            "author": self.author,
            "owned_by_me": self.owned_by_me,
            "updated_at": self.updated_at,
        }
        if self.prompt is not None:
            d["prompt"] = self.prompt
        if self.skills is not None:
            d["skills"] = [s.to_dict() for s in self.skills]
        return d


@dataclass
class StudioLocation:
    """A place a new profile can be created."""

    store: str
    base_path: str  # the .agents dir
    label: str
    is_personal: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "store": self.store,
            "base_path": self.base_path,
            "label": self.label,
            "is_personal": self.is_personal,
        }


# ----------------------------------------------------------------- id + parse

def encode_id(store: str, dir_path: str) -> str:
    raw = f"{store}|{dir_path}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_id(profile_id: str) -> Tuple[str, str]:
    pad = "=" * (-len(profile_id) % 4)
    try:
        raw = base64.urlsafe_b64decode(profile_id + pad).decode("utf-8")
        store, dir_path = raw.split("|", 1)
    except Exception as exc:  # noqa: BLE001
        raise AgentStudioError(f"Invalid profile id: {profile_id}") from exc
    if store not in (STORE_WORKSPACE, STORE_VOLUME):
        raise AgentStudioError(f"Invalid store: {store}")
    return store, dir_path


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug or "agent"


def parse_frontmatter(content: str) -> Dict[str, Any]:
    """Tolerant scan of a leading ``---`` YAML block.

    Returns a dict of the simple ``key: value`` pairs plus the remaining
    ``body`` (markdown after the frontmatter). ``tools`` is parsed from either a
    flow list (``[a, b]``) or a YAML block list (``- a``). Avoids a YAML
    dependency so a malformed block never blocks listing.
    """
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
    """Compose an AGENT.md from metadata + the main prompt body."""
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


def _ws_path_variants(path: str) -> List[str]:
    """Both namespaces the Workspace API might honor (with/without /Workspace)."""
    p = (path or "").rstrip("/")
    variants = [p]
    if p.startswith("/Workspace/"):
        alt = p[len("/Workspace"):]
    elif p.startswith("/"):
        alt = "/Workspace" + p
    else:
        alt = p
    if alt and alt not in variants:
        variants.append(alt)
    return variants


def _basename(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def _volume_label(volume_path: str) -> str:
    parts = [p for p in volume_path.split("/") if p]
    if len(parts) >= 4 and parts[0] == "Volumes":
        return f"{parts[1]}.{parts[2]}.{parts[3]}"
    return volume_path


class AgentStudioStore:
    """OBO CRUD for agent profiles + their skills across Workspace + UC Volumes."""

    def __init__(self) -> None:
        self._dir = _dir_name()
        # Per-user TTL cache for the (expensive) shared-volume discovery walk.
        # Keyed by an OBO-token fingerprint so each caller only ever sees what
        # their own grants permit. Bounded + time-expired below.
        self._shared_cache: Dict[str, Tuple[float, List["ProfileRef"]]] = {}

    # ---- client -----------------------------------------------------------
    def _client(self, obo_token: Optional[str]):
        from databricks.sdk import WorkspaceClient

        if not os.environ.get("HOME"):
            os.environ["HOME"] = "/tmp"
        host = os.environ.get("DATABRICKS_HOST")
        dev_mode = os.environ.get("DEV_MODE", "").lower() == "true"
        if obo_token and host:
            # auth_type="pat" forces token auth, so any SP OAuth env vars present
            # in the App runtime are ignored without us having to mutate
            # os.environ — which would race across concurrent threadpool requests.
            return WorkspaceClient(host=host, token=obo_token, auth_type="pat")
        if dev_mode:
            return WorkspaceClient()
        if host:
            return WorkspaceClient(host=host)
        return WorkspaceClient()

    def _whoami(self, client, fallback: str = "") -> str:
        try:
            uname = getattr(client.current_user.me(), "user_name", None)
            if uname:
                return uname
        except Exception as exc:  # noqa: BLE001
            logger.debug("current_user.me() failed; using '%s': %s", fallback, exc)
        return fallback

    def _effective_personal_dir(self, client, user_email: str) -> str:
        configured = (os.environ.get("AGENT_STUDIO_PERSONAL_WORKSPACE_DIR") or "").strip()
        if configured:
            return configured.rstrip("/")
        return f"/Workspace/Users/{self._whoami(client, user_email)}/{self._dir}"

    # ---- listing ----------------------------------------------------------
    def list_profiles(
        self,
        obo_token: Optional[str],
        user_email: str,
        include_shared: bool = True,
    ) -> List[ProfileRef]:
        client = self._client(obo_token)
        out: List[ProfileRef] = []
        personal = self._list_personal(client, user_email)
        for ref in personal:
            ref.owned_by_me = True  # in the caller's own workspace folder
        out.extend(personal)
        if include_shared:
            me = self._whoami(client, user_email)
            shared = self._discover_shared_cached(client, obo_token)
            for ref in shared:
                ref.owned_by_me = bool(ref.author) and ref.author == me
            out.extend(shared)
        out.sort(key=lambda p: (p.store != STORE_WORKSPACE, p.location_label, p.name.lower()))
        return out

    def _discover_shared_cached(self, client, obo_token: Optional[str]) -> List["ProfileRef"]:
        ttl = _discovery_ttl()
        if ttl <= 0:
            return self._discover_shared(client)
        key = hashlib.sha256((obo_token or "anon").encode("utf-8")).hexdigest()
        now = time.monotonic()
        hit = self._shared_cache.get(key)
        if hit and (now - hit[0]) < ttl:
            return hit[1]
        refs = self._discover_shared(client)
        if len(self._shared_cache) > 100:
            self._shared_cache.clear()
        self._shared_cache[key] = (now, refs)
        return refs

    def _list_personal(self, client, user_email: str) -> List[ProfileRef]:
        from databricks.sdk.service.workspace import ObjectType

        base = self._effective_personal_dir(client, user_email)
        objs: List[Any] = []
        for cand in _ws_path_variants(base):
            try:
                listed = list(client.workspace.list(cand))
            except Exception as exc:  # noqa: BLE001
                logger.debug("personal list(%s) failed: %s", cand, exc)
                continue
            if listed:
                objs = listed
                break
        out: List[ProfileRef] = []
        for obj in objs:
            if obj.object_type != ObjectType.DIRECTORY:
                continue
            text = self._read_workspace_text(client, f"{obj.path}/{AGENT_FILE}")
            if text is None:
                continue
            meta = parse_frontmatter(text)
            out.append(self._ref_from_meta(STORE_WORKSPACE, obj.path, meta, "Personal"))
        return out

    def _discover_shared(self, client) -> List[ProfileRef]:
        out: List[ProfileRef] = []

        # Fast path: an admin-pinned index of shared ``.agents`` dirs avoids the
        # expensive metastore crawl entirely.
        configured = _configured_shared_locations()
        if configured:
            for agents_dir in configured:
                if agents_dir.startswith("/Volumes"):
                    out.extend(self._list_volume_profiles_dir(client, agents_dir))
                else:
                    out.extend(self._list_workspace_profiles_dir(client, agents_dir, "Shared"))
            return out

        only = _scan_catalogs()
        max_cat, max_sch, max_vol = _scan_caps()
        try:
            catalogs = list(client.catalogs.list())
        except Exception as exc:  # noqa: BLE001
            logger.debug("scan: catalogs.list failed: %s", exc)
            return out
        cat_count = 0
        for cat in catalogs:
            cat_name = getattr(cat, "name", None)
            if not cat_name or (only and cat_name not in only):
                continue
            if cat_count >= max_cat:
                break
            cat_count += 1
            try:
                schemas = list(client.schemas.list(catalog_name=cat_name))
            except Exception as exc:  # noqa: BLE001
                logger.debug("scan: schemas.list(%s) failed: %s", cat_name, exc)
                continue
            sch_count = 0
            for sch in schemas:
                sch_name = getattr(sch, "name", None)
                if not sch_name or sch_name == "information_schema":
                    continue
                if sch_count >= max_sch:
                    break
                sch_count += 1
                try:
                    volumes = list(client.volumes.list(catalog_name=cat_name, schema_name=sch_name))
                except Exception as exc:  # noqa: BLE001
                    logger.debug("scan: volumes.list(%s.%s) failed: %s", cat_name, sch_name, exc)
                    continue
                vol_count = 0
                for vol in volumes:
                    vol_name = getattr(vol, "name", None)
                    if not vol_name:
                        continue
                    if vol_count >= max_vol:
                        break
                    vol_count += 1
                    agents_dir = f"/Volumes/{cat_name}/{sch_name}/{vol_name}/{self._dir}"
                    out.extend(self._list_volume_profiles_dir(client, agents_dir))
        return out

    def _list_volume_profiles_dir(self, client, agents_dir: str) -> List[ProfileRef]:
        out: List[ProfileRef] = []
        try:
            entries = list(client.files.list_directory_contents(agents_dir))
        except Exception:  # noqa: BLE001
            return out
        label = _volume_label(agents_dir)
        for entry in entries:
            if not getattr(entry, "is_directory", False):
                continue
            dir_path = getattr(entry, "path", None)
            if not dir_path:
                continue
            text = self._read_volume_text(client, f"{dir_path.rstrip('/')}/{AGENT_FILE}")
            if text is None:
                continue
            meta = parse_frontmatter(text)
            out.append(self._ref_from_meta(STORE_VOLUME, dir_path.rstrip("/"), meta, label))
        return out

    def _list_workspace_profiles_dir(self, client, agents_dir: str, label: str) -> List[ProfileRef]:
        from databricks.sdk.service.workspace import ObjectType

        objs: List[Any] = []
        for cand in _ws_path_variants(agents_dir):
            try:
                listed = list(client.workspace.list(cand))
            except Exception:  # noqa: BLE001
                continue
            if listed:
                objs = listed
                break
        out: List[ProfileRef] = []
        for obj in objs:
            if obj.object_type != ObjectType.DIRECTORY:
                continue
            text = self._read_workspace_text(client, f"{obj.path}/{AGENT_FILE}")
            if text is None:
                continue
            meta = parse_frontmatter(text)
            out.append(self._ref_from_meta(STORE_WORKSPACE, obj.path, meta, label))
        return out

    def _ref_from_meta(self, store: str, dir_path: str, meta: Dict[str, Any], label: str) -> ProfileRef:
        return ProfileRef(
            store=store,
            dir_path=dir_path,
            name=meta.get("name") or _basename(dir_path),
            description=meta.get("description") or "",
            model=meta.get("model") or "",
            tools=meta.get("tools") or [],
            location_label=label,
            writable=True,
            author=meta.get("author") or "",
            updated_at=meta.get("updated_at") or "",
        )

    # ---- read -------------------------------------------------------------
    def get_profile(self, obo_token: Optional[str], profile_id: str) -> ProfileRef:
        store, dir_path = decode_id(profile_id)
        client = self._client(obo_token)
        agent_path = f"{dir_path.rstrip('/')}/{AGENT_FILE}"
        if store == STORE_WORKSPACE:
            text = self._read_workspace_text(client, agent_path)
            label = "Personal"
        else:
            text = self._read_volume_text(client, agent_path)
            label = _volume_label(dir_path)
        if text is None:
            raise AgentStudioError("Profile not found or not readable.")
        meta = parse_frontmatter(text)
        ref = self._ref_from_meta(store, dir_path.rstrip("/"), meta, label)
        ref.owned_by_me = store == STORE_WORKSPACE or (
            bool(ref.author) and ref.author == self._whoami(client)
        )
        ref.prompt = meta.get("body", "")
        ref.skills = self._read_skills(client, store, dir_path.rstrip("/"))
        return ref

    def _read_skills(self, client, store: str, dir_path: str) -> List[SkillFile]:
        skills_dir = f"{dir_path}/{SKILLS_SUBDIR}"
        out: List[SkillFile] = []
        if store == STORE_WORKSPACE:
            from databricks.sdk.service.workspace import ObjectType

            entries: List[Any] = []
            for cand in _ws_path_variants(skills_dir):
                try:
                    listed = list(client.workspace.list(cand))
                except Exception:  # noqa: BLE001
                    continue
                if listed:
                    entries = listed
                    break
            for obj in entries:
                if obj.object_type == ObjectType.DIRECTORY:
                    continue
                path = getattr(obj, "path", "")
                text = self._read_workspace_text(client, path)
                if text is None:
                    continue
                out.append(self._skill_from_text(path, text))
        else:
            try:
                vol_entries = list(client.files.list_directory_contents(skills_dir))
            except Exception:  # noqa: BLE001
                vol_entries = []
            for entry in vol_entries:
                if getattr(entry, "is_directory", False):
                    continue
                path = getattr(entry, "path", "")
                if not path.endswith(".md"):
                    continue
                text = self._read_volume_text(client, path)
                if text is None:
                    continue
                out.append(self._skill_from_text(path, text))
        out.sort(key=lambda s: s.name.lower())
        return out

    def _skill_from_text(self, path: str, text: str) -> SkillFile:
        meta = parse_frontmatter(text)
        slug = _basename(path)
        if slug.endswith(".md"):
            slug = slug[:-3]
        # Return the body only (not the raw file). The editor binds ``content``
        # to the body textarea and edits ``name``/``description`` separately, and
        # the writer rebuilds the frontmatter from those fields — so carrying the
        # frontmatter inside ``content`` would both show it in the editor and (via
        # build_skill_markdown's "already has frontmatter" guard) silently ignore
        # any metadata edits on the next save.
        return SkillFile(
            slug=slug,
            name=meta.get("name") or slug,
            description=meta.get("description") or "",
            content=meta.get("body", text),
        )

    # ---- write ------------------------------------------------------------
    def save_profile(
        self,
        obo_token: Optional[str],
        user_email: str,
        name: str,
        prompt: str,
        description: str = "",
        model: str = "",
        tools: Optional[List[str]] = None,
        skills: Optional[List[Dict[str, Any]]] = None,
        store: str = STORE_VOLUME,
        base_path: Optional[str] = None,
        profile_id: Optional[str] = None,
        expected_updated_at: Optional[str] = None,
    ) -> ProfileRef:
        if not name or not name.strip():
            raise AgentStudioError("Profile name is required.")
        tools = tools or []

        client = self._client(obo_token)

        if profile_id:
            store, dir_path = decode_id(profile_id)
        else:
            slug = slugify(name)
            if store == STORE_WORKSPACE:
                base = (base_path or self._effective_personal_dir(client, user_email)).rstrip("/")
            else:
                if not base_path:
                    raise AgentStudioError("A target .agents volume path is required.")
                base = base_path.rstrip("/")
            dir_path = f"{base}/{slug}"

        agent_path = f"{dir_path}/{AGENT_FILE}"

        # Optimistic concurrency: when updating, refuse to clobber a profile that
        # someone else changed since the caller loaded it. We compare the stored
        # ``updated_at`` against the value the client echoed back from its load.
        if profile_id and expected_updated_at is not None:
            current = (
                self._read_workspace_text(client, agent_path)
                if store == STORE_WORKSPACE
                else self._read_volume_text(client, agent_path)
            )
            if current is not None:
                cur_ver = parse_frontmatter(current).get("updated_at") or ""
                if expected_updated_at and cur_ver and cur_ver != expected_updated_at:
                    raise ProfileConflictError(
                        "This profile was changed by someone else since you opened "
                        "it. Reload to get the latest version, then re-apply your edits."
                    )

        updated_at = datetime.now(timezone.utc).isoformat()
        author = (user_email or "").strip()
        document = build_agent_markdown(
            name, description, model, tools, prompt, updated_at, author,
        )
        data = document.encode("utf-8")
        if len(data) > _max_bytes():
            raise AgentStudioError(f"Profile exceeds max size ({_max_bytes() // 1024} KB).")

        label = "Personal" if store == STORE_WORKSPACE else _volume_label(dir_path)

        # Write order gives create/update near-atomic semantics: write the skills
        # (and prune orphans) FIRST, then AGENT.md LAST as the commit marker.
        # Listing/loading key on AGENT.md, so a partial failure leaves the profile
        # invisible/old rather than half-written.
        if skills is not None:
            self._write_skills(client, store, dir_path, skills)
        if store == STORE_WORKSPACE:
            self._write_workspace(client, dir_path, agent_path, data)
        else:
            self._write_volume(client, agent_path, data)

        self._snapshot_version(client, store, dir_path, data, updated_at)

        meta = parse_frontmatter(document)
        ref = self._ref_from_meta(store, dir_path, meta, label)
        ref.owned_by_me = True  # the caller just saved it
        ref.prompt = meta.get("body", "")
        ref.skills = self._read_skills(client, store, dir_path)
        self._shared_cache.clear()
        return ref

    def _write_skills(self, client, store: str, dir_path: str, skills: List[Dict[str, Any]]) -> None:
        skills_dir = f"{dir_path}/{SKILLS_SUBDIR}"
        keep_slugs: set = set()
        for sk in skills:
            sk_name = (sk.get("name") or "").strip()
            if not sk_name:
                continue
            slug = sk.get("slug") or slugify(sk_name)
            keep_slugs.add(slug)
            document = build_skill_markdown(sk_name, sk.get("description") or "", sk.get("content") or "")
            data = document.encode("utf-8")
            md_path = f"{skills_dir}/{slug}.md"
            if store == STORE_WORKSPACE:
                self._write_workspace(client, skills_dir, md_path, data)
            else:
                self._write_volume(client, md_path, data)
        # Reconcile: drop skill files that were removed in the editor so they no
        # longer get inlined into the agent's prompt. An empty skill list prunes
        # them all (the caller passed skills=[] on purpose).
        self._prune_skills(client, store, skills_dir, keep_slugs)

    def _prune_skills(self, client, store: str, skills_dir: str, keep_slugs: set) -> None:
        try:
            if store == STORE_WORKSPACE:
                from databricks.sdk.service.workspace import ObjectType

                entries: List[Any] = []
                for cand in _ws_path_variants(skills_dir):
                    try:
                        listed = list(client.workspace.list(cand))
                    except Exception:  # noqa: BLE001
                        continue
                    if listed:
                        entries = listed
                        break
                for obj in entries:
                    if getattr(obj, "object_type", None) == ObjectType.DIRECTORY:
                        continue
                    path = getattr(obj, "path", "") or ""
                    base = _basename(path)
                    if not base.endswith(".md"):
                        continue
                    if base[:-3] not in keep_slugs:
                        try:
                            client.workspace.delete(path)
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("prune skill %s failed: %s", path, exc)
            else:
                try:
                    entries = list(client.files.list_directory_contents(skills_dir))
                except Exception:  # noqa: BLE001
                    entries = []
                for entry in entries:
                    if getattr(entry, "is_directory", False):
                        continue
                    path = getattr(entry, "path", "") or ""
                    base = _basename(path)
                    if not base.endswith(".md"):
                        continue
                    if base[:-3] not in keep_slugs:
                        try:
                            client.files.delete(path)
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("prune skill %s failed: %s", path, exc)
        except Exception as exc:  # noqa: BLE001
            logger.debug("prune skills in %s failed: %s", skills_dir, exc)

    def delete_profile(self, obo_token: Optional[str], profile_id: str) -> None:
        store, dir_path = decode_id(profile_id)
        self._shared_cache.clear()
        client = self._client(obo_token)
        if store == STORE_WORKSPACE:
            last_exc: Optional[Exception] = None
            for cand in _ws_path_variants(dir_path):
                try:
                    client.workspace.delete(cand, recursive=True)
                    return
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
            raise AgentStudioError(f"Could not delete profile: {last_exc}") from last_exc
        try:
            client.files.delete_directory(dir_path)
        except Exception as exc:  # noqa: BLE001
            raise AgentStudioError(f"Could not delete profile: {exc}") from exc

    # ---- locations --------------------------------------------------------
    def list_locations(
        self,
        obo_token: Optional[str],
        user_email: str,
        include_shared: bool = True,
    ) -> List[StudioLocation]:
        client = self._client(obo_token)
        locations: List[StudioLocation] = [
            StudioLocation(
                store=STORE_WORKSPACE,
                base_path=self._effective_personal_dir(client, user_email),
                label="Personal workspace",
                is_personal=True,
            )
        ]
        if include_shared:
            seen = set()
            for ref in self._discover_shared_cached(client, obo_token):
                base = ref.dir_path.rsplit("/", 1)[0]
                if base in seen:
                    continue
                seen.add(base)
                # Preserve the discovered ref's store: AGENT_STUDIO_PROFILE_LOCATIONS
                # can pin a /Workspace/.../.agents path, which yields STORE_WORKSPACE
                # refs. Hardcoding STORE_VOLUME here would route a later save/promote
                # into that location through the Files (volume) IO path against a
                # Workspace path and fail.
                locations.append(
                    StudioLocation(
                        store=ref.store,
                        base_path=base,
                        label=_volume_label(base),
                    )
                )
        return locations

    # ---- low-level workspace IO ------------------------------------------
    def _read_workspace_text(self, client, path: str) -> Optional[str]:
        from databricks.sdk.service.workspace import ExportFormat

        # Our AGENT.md / SKILL.md are imported as RAW *files* (ObjectType.FILE).
        # Reading them back with ExportFormat.RAW is rejected by the Workspace API
        # ("Invalid export request: format=RAW, directDownload=false") because the
        # SDK does not set directDownload — so a saved profile would read back as
        # None and silently disappear from listings. SOURCE returns the file bytes
        # for these objects; keep RAW as a fallback for older workspaces.
        for cand in _ws_path_variants(path):
            for fmt in (ExportFormat.SOURCE, ExportFormat.RAW):
                try:
                    resp = client.workspace.export(path=cand, format=fmt)
                    if resp and getattr(resp, "content", None):
                        return base64.b64decode(resp.content).decode("utf-8", errors="replace")
                except Exception as exc:  # noqa: BLE001
                    logger.debug("workspace export (%s) failed for %s: %s", fmt, cand, exc)
        return None

    def _write_workspace(self, client, dir_path: str, md_path: str, data: bytes) -> None:
        from databricks.sdk.service.workspace import ImportFormat

        try:
            client.workspace.mkdirs(dir_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mkdirs(%s) failed: %s", dir_path, exc)
            raise AgentStudioError(f"Could not create folder '{dir_path}': {exc}") from exc
        try:
            client.workspace.import_(
                path=md_path,
                format=ImportFormat.RAW,
                content=base64.b64encode(data).decode("ascii"),
                overwrite=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise AgentStudioError(f"Could not write '{md_path}': {exc}") from exc

    # ---- low-level volume IO ---------------------------------------------
    def _read_volume_text(self, client, md_path: str) -> Optional[str]:
        try:
            resp = client.files.download(md_path)
            raw = resp.contents.read()
            if isinstance(raw, str):
                return raw
            return raw.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.debug("volume download failed for %s: %s", md_path, exc)
            return None

    def _write_volume(self, client, md_path: str, data: bytes) -> None:
        try:
            client.files.upload(file_path=md_path, contents=BytesIO(data), overwrite=True)
        except Exception as exc:  # noqa: BLE001
            raise AgentStudioError(f"Could not save to volume: {exc}") from exc

    # ---- versioning + audit (best-effort; never fail the primary write) ----
    def _list_dir_paths(self, client, store: str, dir_path: str) -> List[str]:
        try:
            if store == STORE_WORKSPACE:
                for cand in _ws_path_variants(dir_path):
                    objs = list(client.workspace.list(cand))
                    if objs:
                        return [o.path for o in objs if getattr(o, "path", None)]
                return []
            return [
                e.path for e in client.files.list_directory_contents(dir_path)
                if getattr(e, "path", None)
            ]
        except Exception as exc:  # noqa: BLE001
            logger.debug("list_dir(%s) failed: %s", dir_path, exc)
            return []

    def _delete_path(self, client, store: str, path: str) -> None:
        try:
            if store == STORE_WORKSPACE:
                client.workspace.delete(path)
            else:
                client.files.delete(path)
        except Exception as exc:  # noqa: BLE001
            logger.debug("delete(%s) failed: %s", path, exc)

    def _snapshot_version(self, client, store: str, dir_path: str, data: bytes, updated_at: str) -> None:
        """Append a timestamped AGENT.md snapshot under ``.versions`` and prune."""
        keep = _max_versions()
        if keep <= 0:
            return
        versions_dir = f"{dir_path}/{VERSIONS_SUBDIR}"
        stamp = re.sub(r"[^0-9A-Za-z]", "-", updated_at or "") or str(int(time.time()))
        snap_path = f"{versions_dir}/AGENT-{stamp}.md"
        try:
            if store == STORE_WORKSPACE:
                self._write_workspace(client, versions_dir, snap_path, data)
            else:
                self._write_volume(client, snap_path, data)
        except Exception as exc:  # noqa: BLE001
            logger.debug("version snapshot failed for %s: %s", snap_path, exc)
            return
        # Prune oldest beyond `keep` (ISO stamps sort lexicographically).
        snaps = sorted(
            p for p in self._list_dir_paths(client, store, versions_dir)
            if _basename(p).startswith("AGENT-")
        )
        for stale in snaps[:-keep]:
            self._delete_path(client, store, stale)

    def record_promotion(
        self,
        obo_token: Optional[str],
        target_store: str,
        target_dir: str,
        entry: Dict[str, Any],
    ) -> None:
        """Append an audit line to ``<target_dir>/PROMOTIONS.jsonl`` (best-effort)."""
        import json as _json

        audit_path = f"{target_dir.rstrip('/')}/{PROMOTIONS_FILE}"
        try:
            client = self._client(obo_token)
            existing = (
                self._read_workspace_text(client, audit_path)
                if target_store == STORE_WORKSPACE
                else self._read_volume_text(client, audit_path)
            ) or ""
            lines = [ln for ln in existing.splitlines() if ln.strip()]
            lines.append(_json.dumps(entry, separators=(",", ":")))
            lines = lines[-500:]  # bound the log
            data = ("\n".join(lines) + "\n").encode("utf-8")
            if target_store == STORE_WORKSPACE:
                self._write_workspace(client, target_dir.rstrip("/"), audit_path, data)
            else:
                self._write_volume(client, audit_path, data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record promotion audit at %s: %s", audit_path, exc)


_store: Optional[AgentStudioStore] = None


def get_agent_studio_store() -> AgentStudioStore:
    global _store
    if _store is None:
        _store = AgentStudioStore()
    return _store
