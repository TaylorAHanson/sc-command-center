"""Discover's view catalog: one searchable row per published, unarchived view.

The catalog is derived, never content. Each row is rebuilt from the view's
newest published version, its access list, its link name and `view_curation`,
so rebuilding writes no versions and Data Migration leaves it behind.

It is kept current three ways, all of which only queue the id:

* `touch(c, ...)` inside the publishing transaction (`drafts.publish`), so the
  mark commits together with the version it describes;
* `mark_dirty(...)` just after a commit elsewhere (sharing, archive, restore,
  delete), on its own connection;
* `reconcile`, every half hour, for anything a failed hook missed.

The catalog job (`sync_job`) rebuilds queued rows every few seconds, so no
request pays for reindexing.

Search runs in the best of three modes the database supports (`choose_mode`):
basic (weighted tsvector + GIN), keyword (Lakebase BM25) and hybrid (BM25,
name prefixes and vector distance, fused by RRF). Each mode fails open to the
one below it, per request.

Access: SQL filters `readers` by the caller's principal keys, and every page
is re-checked with `access.levels_for` before it is sent, so a stale row never
shows a view to someone who has just lost access.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

from services import access

logger = logging.getLogger(__name__)

#: Bump when what a row holds or how its tsvector is built changes; the catalog
#: job then rebuilds every row and reindexes the search indexes.
FORMAT_VERSION = 1

# Literals rather than access.APP and friends: access imports this module for
# its hooks, so nothing here may read access's attributes at import time.
APP = "app"
MANAGE, USE = "MANAGE", "USE"

MODES = ("basic", "keyword", "hybrid")
SCOPES = ("all", "mine", "shared", "favorites", "everything")
SORTS = ("relevance", "popular", "trending", "updated", "name", "favorites")
STATUSES = ("draft", "published")
OPENED = ("never", "90d")

MAX_LIMIT = 50
DEFAULT_LIMIT = 24
#: Relevance-sorted results stop here, like most search pages; other sorts page
#: through the whole filtered set.
RELEVANCE_CAP = 500
#: Per candidate list (BM25, name prefix, vector) before fusion.
CANDIDATES = 200
RRF_K = 60
#: A vector candidate further than this from the best one is dropped, so a query
#: with no near neighbours doesn't fill the page with the 200 least-far views.
VECTOR_SPREAD = 0.12
DESCRIPTION_CHARS = 240
SUGGEST_LIMIT = 8
RAIL_LIMIT = 12
MAX_WORDS = 8

BUILD_PAGE = 500
DRAIN_BATCH = 200
DRAIN_SECONDS = 5.0
RECONCILE_SECONDS = 30 * 60
ENSURE_SECONDS = 10 * 60

EMBED_BATCH = 100
EMBED_SECONDS = 20.0
EMBED_TIMEOUT = 30.0
QUERY_EMBED_TIMEOUT = 0.4
#: Share of rows that must be embedded before the vector index is built: the
#: index picks its lists from the table at build time.
ANN_MIN_COVERAGE = 0.9

#: Where the app installs the Lakebase Search extensions when it may. An
#: existing install, in whatever schema, is used as it is.
EXT_SCHEMA = "search_ext"
TEXT_EXT, VECTOR_EXT, PGVECTOR = "lakebase_text", "lakebase_vector", "vector"
BM25_INDEX, ANN_INDEX = "view_catalog_bm25", "view_catalog_ann"

#: Whether BM25 and vector scans apply the readers filter while scanning rather
#: than to the index's top matches afterwards. Off measured a few ms faster at
#: 50,000 views with the same pages, but only because every probe caller could
#: read a quarter of the views; someone who can read 1% would get short pages
#: for common words. Lakebase's own default is off (tools/discover_scale_probe.py).
BM25_PREFILTER = True
ANN_PREFILTER = True

_LOCK_KEY = 734_201_917  # pg advisory lock: full builds and reconciles

# --------------------------------------------------------------- process state

_ready = False
_hook_backoff_until = 0.0
_HOOK_BACKOFF_SECONDS = 30.0


def tables_ready() -> None:
    """Called by `database._create_discover_tables` once the tables exist.

    Hooks do nothing until then, so a worker whose startup couldn't reach the
    database (and every test that fakes one) never pays for them; the
    reconcile catches up on anything missed.
    """
    global _ready
    _ready = True


def enabled() -> bool:
    return _ready


def _content():
    from database import content_env, get_db_connection

    return get_db_connection(content_env())


def _settings():
    from database import get_db_connection
    from services.settings_store import settings_env

    return get_db_connection(settings_env(), physical=True)


def _unpooled():
    from database import content_env, get_db_connection

    return get_db_connection(content_env(), pooled=False)


def _ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_seconds(stamp: Any) -> float:
    """Seconds since an ISO time stored in the state table; infinite if unreadable."""
    try:
        then = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return float("inf")
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (_now() - then).total_seconds()


# ------------------------------------------------------------------ pure rules

def principal_keys(entries: Iterable[Dict[str, Any]], levels: Sequence[str] = (USE, MANAGE)) -> List[str]:
    """Access-list entries as the keys `readers` holds: `*`, `u:<lowercased user>`, `g:<group>`.

    Mirrors `access.matches`: users compare without case, groups exactly, and
    an unknown level grants nothing.
    """
    keys = set()
    for e in entries or []:
        if e.get("level") not in levels:
            continue
        principal = e.get("principal") or ""
        kind = e.get("principal_type")
        if kind == access.ALL or principal == access.EVERYONE:
            keys.add("*")
        elif kind == access.USER:
            if principal.strip():
                keys.add("u:" + principal.strip().lower())
        elif principal:
            keys.add("g:" + principal)
    return sorted(keys)


def caller_keys(who: access.Caller) -> List[str]:
    """The keys a caller matches in `readers`."""
    keys = ["*"]
    if (who.username or "").strip():
        keys.append("u:" + who.username.strip().lower())
    keys.extend("g:" + g for g in who.groups if g)
    return keys


def readers_match(readers: Iterable[str], keys: Iterable[str]) -> bool:
    """What `readers && keys` decides in SQL."""
    return bool(set(readers or ()) & set(keys or ()))


def acl_owner(entries: Iterable[Dict[str, Any]]) -> Optional[str]:
    """`access.owner_of`, over entries already read: the first user given Can manage."""
    users = [e for e in entries or [] if e.get("principal_type") == access.USER and e.get("level") == MANAGE]
    if not users:
        return None
    users.sort(key=lambda e: (e.get("granted_at") is None, e.get("granted_at") or datetime.min,
                              e.get("principal") or ""))
    return users[0]["principal"]


def fallback_ref(app_id: str, name: str) -> str:
    """A view's link part without a claimed name: `<name>-<id>`, as `appRoute.appRef` writes it."""
    from services import app_links

    if app_links.id_in(app_id or "") == (app_id or "").lower() and app_id:
        return f"{app_links.slugify(name)}-{app_id}"
    return app_id


def link_for(ref: str) -> str:
    return "#/app/" + quote(ref or "", safe="")


def owner_words(owner: Optional[str]) -> str:
    """`ana.lopez@example.com` as words, so a search for "ana" finds her views."""
    return re.sub(r"[@._+\-]+", " ", owner or "").strip()


def search_parts(row: Dict[str, Any]) -> Dict[str, str]:
    """The text behind each tsvector weight: A name, B description and tabs,
    C owner and domain, D widget names."""
    return {
        "ta": row.get("name") or "",
        "tb": " ".join([row.get("description") or ""] + list(row.get("tab_names") or [])).strip(),
        "tc": " ".join(p for p in (owner_words(row.get("owner")), row.get("domain") or "") if p),
        "td": " ".join(row.get("widget_names") or []),
    }


def embedding_text(row: Dict[str, Any]) -> str:
    """What is sent to the embedding model for a view: only its own words, never data or people."""
    parts = [row.get("name") or ""]
    if row.get("description"):
        parts.append(row["description"])
    if row.get("tab_names"):
        parts.append("Tabs: " + ", ".join(row["tab_names"]))
    if row.get("domain"):
        parts.append("Domain: " + row["domain"])
    if row.get("widget_names"):
        parts.append("Widgets: " + ", ".join(row["widget_names"]))
    return "\n".join(p.strip() for p in parts if p and p.strip())


def text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:32]


def catalog_row(head: Dict[str, Any], *, acl: Sequence[Dict[str, Any]] = (), slug: Optional[str] = None,
                widget_names: Optional[Dict[str, str]] = None, curation: Optional[Dict[str, Any]] = None,
                spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The catalog row for a view's newest published version. Never raises on a
    malformed spec: `read_spec` turns one into a single empty tab."""
    from services import app_spec, app_store

    app_id = head["id"]
    if spec is None:
        spec = app_spec.read_spec(app_id, head.get("spec_json"), head.get("widgets_json"))
    names = widget_names or {}
    tabs = [str(t.get("name") or "").strip() for t in spec.get("tabs") or []]
    widgets = app_store.custom_widget_ids(spec)
    presentation = spec.get("presentation")
    name = (head.get("name") or "").strip() or "Untitled view"
    creator = head.get("username")
    owner = acl_owner(acl) or (creator if creator and creator != "unknown" else None)
    cur = curation or {}
    updated = head.get("published_at") or head.get("timestamp")
    row = {
        "id": app_id,
        "name": name,
        "sort_name": name.lower(),
        "description": str(head.get("description") or spec.get("description") or "").strip(),
        "owner": owner,
        "owner_key": owner.strip().lower() if owner else None,
        "domain": head.get("domain") or None,
        "presentation": presentation if presentation in app_spec.PRESENTATIONS else "workspace",
        "ref": slug or fallback_ref(app_id, name),
        "tab_names": [t for t in tabs if t],
        "widget_ids": widgets,
        "widget_names": list(dict.fromkeys(names[w] for w in widgets if names.get(w))),
        "readers": principal_keys(acl),
        "managers": principal_keys(acl, (MANAGE,)),
        "published_version": head.get("version"),
        "published_at": head.get("first_at") or updated,
        "updated_at": updated or _now(),
        "featured_position": cur.get("featured_position"),
        "certified": bool(cur.get("certified")),
    }
    row.update(search_parts(row))
    row["embed_hash"] = text_hash(embedding_text(row))
    return row


def stale_ids(catalog: Dict[str, Dict[str, Any]], versions: Dict[str, int], archived: Iterable[str],
              slugs: Dict[str, str], curation: Dict[str, Dict[str, Any]], acls: Dict[str, List[Dict[str, Any]]],
              widget_names: Dict[str, str]) -> List[str]:
    """Which catalog rows disagree with their sources: the reconcile's diff."""
    archived = set(archived)
    expected = {i for i in versions if i not in archived}
    stale = (set(catalog) - expected) | (expected - set(catalog))
    for i in expected & set(catalog):
        row = catalog[i]
        entries = acls.get(i, [])
        cur = curation.get(i) or {}
        names = list(dict.fromkeys(widget_names[w] for w in row.get("widget_ids") or [] if widget_names.get(w)))
        owner = acl_owner(entries)
        if (row.get("published_version") != versions[i]
                or (slugs.get(i) and row.get("ref") != slugs[i])
                or row.get("featured_position") != cur.get("featured_position")
                or bool(row.get("certified")) != bool(cur.get("certified"))
                or sorted(row.get("readers") or []) != principal_keys(entries)
                or sorted(row.get("managers") or []) != principal_keys(entries, (MANAGE,))
                or (owner and row.get("owner") != owner)
                or list(row.get("widget_names") or []) != names):
            stale.add(i)
    return sorted(stale)


_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def query_words(q: Optional[str]) -> List[str]:
    """The words of a query, safe to put in a tsquery: letters and digits only."""
    return [w[:40] for w in _WORD.findall((q or "").lower())][:MAX_WORDS]


def prefix_query(words: Sequence[str], weight: str = "") -> str:
    """`to_tsquery` text matching every word as a prefix, optionally in one weight only."""
    return " & ".join(f"{w}:*{weight}" for w in words)


def rrf_fuse(lists: Sequence[Sequence[str]], k: int = RRF_K) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion: each list adds 1/(k + rank) to the ids it ranks.

    Ties break on id so a page never reshuffles between requests.
    """
    scores: Dict[str, float] = {}
    for ids in lists:
        for rank, item in enumerate(dict.fromkeys(ids), start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def boost(score: float, stats: Dict[str, Any]) -> float:
    """Relevance first: popularity, featured and certified only reorder near-ties.

    At most +7%, against the ~1.6% between RRF ranks one and two, so a popular
    view climbs a couple of places, never past a much better match.
    """
    viewers = max(0, int(stats.get("viewers_30d") or 0))
    popularity = min(1.0, math.log1p(viewers) / math.log1p(1000))
    featured = stats.get("featured_position") is not None
    return score * (1 + 0.03 * popularity + 0.02 * bool(stats.get("certified")) + 0.02 * featured)


def rank_candidates(lists: Sequence[Sequence[str]], stats: Dict[str, Dict[str, Any]],
                    k: int = RRF_K, cap: int = RELEVANCE_CAP) -> List[str]:
    fused = [(i, boost(s, stats.get(i) or {})) for i, s in rrf_fuse(lists, k)]
    fused.sort(key=lambda kv: (-kv[1], kv[0]))
    return [i for i, _ in fused[:cap]]


def vector_cutoff(scored: Sequence[Tuple[str, float]], spread: float = VECTOR_SPREAD) -> List[str]:
    """Ids from a nearest-first (id, distance) list within `spread` of the nearest."""
    if not scored:
        return []
    best = scored[0][1]
    return [i for i, d in scored if d is not None and d <= best + spread]


def encode_cursor(data: Dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":"), default=iso).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(text: str) -> Dict[str, Any]:
    """The cursor a previous page returned. ValueError for anything else."""
    try:
        padded = text + "=" * (-len(text) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Not a cursor this endpoint returned.") from exc
    if not isinstance(data, dict) or "s" not in data:
        raise ValueError("Not a cursor this endpoint returned.")
    return data


def available_modes(detected: Dict[str, Any], model: Optional[str]) -> List[str]:
    """Modes the database can run now, weakest first."""
    modes = ["basic"]
    if detected.get("text_schema") and detected.get("bm25"):
        modes.append("keyword")
        if (model and detected.get("vector_schema") and detected.get("ann")
                and detected.get("embedding_dims") and detected.get("embedded_model") == model):
            modes.append("hybrid")
    return modes


def choose_mode(detected: Dict[str, Any], setting: Optional[str], model: Optional[str]) -> Tuple[str, List[str]]:
    """The mode to search in, and notes for the Setup card when the setting can't be honoured."""
    modes = available_modes(detected, model)
    wanted = (setting or "auto").strip().lower()
    notes: List[str] = []
    if wanted not in ("auto",) + MODES:
        notes.append(f"Search mode '{setting}' isn't auto, basic, keyword or hybrid, so auto is used.")
        wanted = "auto"
    if wanted == "auto" or wanted in modes:
        return (modes[-1] if wanted == "auto" else wanted), notes
    notes.append(f"Search mode is set to {wanted}, which this database can't do yet, so {modes[-1]} is used.")
    return modes[-1], notes


def classify_install_error(text: str) -> str:
    """Why CREATE EXTENSION failed: `not_enabled`, `permission` or `error`."""
    lowered = (text or "").lower()
    if any(s in lowered for s in ("shared_preload_libraries", "could not open extension control file",
                                  "is not available", "not allowlisted", "not supported")):
        return "not_enabled"
    if any(s in lowered for s in ("permission denied", "must be owner", "must be superuser",
                                  "insufficient privilege", "must have create privilege")):
        return "permission"
    return "error"


def owner_sql(role: str, schema: str = "") -> str:
    """What a database owner runs when the app may not install the extensions itself."""
    schema = schema or EXT_SCHEMA
    return (f"CREATE SCHEMA IF NOT EXISTS {schema}; "
            f"CREATE EXTENSION IF NOT EXISTS {TEXT_EXT} SCHEMA {schema}; "
            f"CREATE EXTENSION IF NOT EXISTS {VECTOR_EXT} SCHEMA {schema} CASCADE; "
            f"GRANT USAGE ON SCHEMA {schema} TO {_ident(role) if role else '<app role>'};")


def capability_result(detected: Optional[Dict[str, Any]], setting: Optional[str], model: Optional[str]):
    """The Setup card's search row, from what `detect` found. Pure."""
    from services import capabilities

    if detected is None:
        return capabilities.result(False, missing=["The view catalog's tables haven't been created yet."],
                                   next_step="Restart the app: they are created at startup.")
    mode, notes = choose_mode(detected, setting, model)
    state = detected.get("state") or {}
    build = state.get("build") or {}
    ext = state.get("extensions") or {}
    emb = state.get("embeddings") or {}
    missing: List[str] = []
    steps: List[str] = []
    if not build.get("built_at"):
        missing.append("The view catalog is still being built.")
    if not detected.get("text_schema"):
        if ext.get("kind") == "permission":
            missing.append("Lakebase Search is enabled, but the app may not install its extensions.")
            steps.append("Ask a database owner to run: " + owner_sql(detected.get("role") or ""))
        else:
            missing.append("Lakebase Search isn't enabled for this database, so search uses basic word matching.")
            steps.append("Enable Lakebase Search in the Lakebase project's settings (Beta, PostgreSQL 16 or later). "
                         "It can't be turned off again and restarts the project's computes. The app installs "
                         "the extensions itself within about ten minutes.")
    elif not detected.get("text_usable") or not detected.get("vector_usable", True):
        missing.append("The app can't use the schema the Lakebase Search extensions are installed in.")
        steps.append(f"Ask a database owner to grant USAGE on schema {detected.get('text_schema')} to "
                     f"{detected.get('role') or 'the app role'}.")
    elif not detected.get("bm25"):
        missing.append("The keyword index is being built.")
    if not model:
        missing.append("Meaning-based search is off: Search embedding model is set to off.")
    elif detected.get("text_schema") and detected.get("vector_schema"):
        if emb.get("error"):
            missing.append(f"Embedding views failed: {emb['error']}")
            steps.append("Check that Settings → Search embedding model names an embedding endpoint the app's "
                         "service principal may query.")
        elif emb.get("model") != model or (emb.get("total") and emb.get("done", 0) < emb["total"]):
            missing.append(f"Embedding views: {emb.get('done', 0)} of {emb.get('total', '?')} done.")
        elif emb.get("total") == 0:
            missing.append("Meaning-based search starts once a view is published.")
        elif not detected.get("ann"):
            missing.append("The vector index is being built.")
    missing.extend(notes)
    return capabilities.result(bool(build.get("built_at")), mode=mode, missing=missing,
                               next_step=steps[0] if steps else "")


# ------------------------------------------------------------------ detection

_DETECT_SQL = """
SELECT
  (SELECT json_agg(json_build_array(e.extname, n.nspname, has_schema_privilege(n.oid, 'USAGE')))
     FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
    WHERE e.extname IN ('lakebase_text', 'lakebase_vector', 'vector')),
  (SELECT json_agg(name) FROM pg_available_extensions
    WHERE name IN ('lakebase_text', 'lakebase_vector', 'vector')),
  (SELECT json_agg(json_build_array(ic.relname, i.indisvalid))
     FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid
    WHERE i.indrelid = to_regclass('view_catalog') AND ic.relname IN ('view_catalog_bm25', 'view_catalog_ann')),
  (SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a
    WHERE a.attrelid = to_regclass('view_catalog') AND a.attname = 'embedding' AND NOT a.attisdropped),
  (SELECT json_object_agg(key, value) FROM view_catalog_state),
  current_user,
  current_schema()
"""


def detect(c) -> Dict[str, Any]:
    """What the database offers search right now, and the catalog's recorded state."""
    c.execute(_DETECT_SQL)
    exts, avail, indexes, emb_type, state, role, schema = c.fetchone()
    installed = {name: (schema, usable) for name, schema, usable in (exts or [])}
    valid = {name: ok for name, ok in (indexes or [])}
    dims = None
    match = re.search(r"\((\d+)\)", emb_type or "")
    if match:
        dims = int(match.group(1))
    state = state or {}
    return {
        "text_schema": (installed.get(TEXT_EXT) or (None,))[0],
        "text_usable": bool((installed.get(TEXT_EXT) or (None, False))[1]),
        "vector_schema": (installed.get(VECTOR_EXT) or (None,))[0],
        "vector_usable": bool((installed.get(VECTOR_EXT) or (None, True))[1]),
        "pgvector_schema": (installed.get(PGVECTOR) or (None,))[0],
        "available": sorted(avail or []),
        "bm25": bool(valid.get(BM25_INDEX)),
        "bm25_invalid": BM25_INDEX in valid and not valid[BM25_INDEX],
        "ann": bool(valid.get(ANN_INDEX)),
        "ann_invalid": ANN_INDEX in valid and not valid[ANN_INDEX],
        "embedding_dims": dims,
        "embedded_model": (state.get("embeddings") or {}).get("model"),
        "state": state,
        "role": role,
        "schema": schema,
    }


_detected: Dict[str, Any] = {"at": 0.0, "value": None}
_detect_lock = threading.Lock()
_DETECT_TTL = 30.0


def detected(max_age: float = _DETECT_TTL) -> Optional[Dict[str, Any]]:
    """`detect`, cached per process. None when the catalog can't be read."""
    now = time.monotonic()
    with _detect_lock:
        if _detected["value"] is not None and now - _detected["at"] < max_age:
            return _detected["value"]
    conn = None
    try:
        conn = _content()
        c = conn.cursor()
        value = detect(c)
        conn.commit()
    except Exception as e:  # noqa: BLE001
        logger.info("Could not read search capabilities: %s", e)
        return None
    finally:
        if conn is not None:
            conn.close()
    with _detect_lock:
        _detected.update(at=now, value=value)
    return value


def forget_detection() -> None:
    with _detect_lock:
        _detected.update(at=0.0, value=None)


def embedding_model() -> Optional[str]:
    """The model behind hybrid search, or None when an admin turned it off."""
    from services.settings_store import SETTING_SPECS, get_setting

    try:
        model = get_setting("search_embedding_model")
    except Exception:  # noqa: BLE001
        model = SETTING_SPECS["search_embedding_model"].default
    model = (model or "").strip()
    return None if model.lower() in ("", "off", "none", "-") else model


def search_setting() -> str:
    from services.settings_store import get_setting

    try:
        return get_setting("search_mode")
    except Exception:  # noqa: BLE001
        return "auto"


def current_mode() -> str:
    d = detected()
    if d is None:
        return "basic"
    return choose_mode(d, search_setting(), embedding_model())[0]


def capability_check():
    """Registered as the `search` capability in main.py."""
    d = detected(max_age=0) if _ready else None
    return capability_result(d, search_setting(), embedding_model())


def _search_path_sql(d: Dict[str, Any]) -> Tuple[str, str]:
    """Statement prefix putting the extension schemas after the content schema,
    for this transaction only.

    `to_bm25query` refers to `bm25query_tsvector` unqualified, and the `<@>`
    and `<=>` operators live in the extension schemas, so they must be on the
    path; the content schema stays first so every table still resolves to it.
    """
    extra = [s for s in dict.fromkeys((d.get("text_schema"), d.get("vector_schema"), d.get("pgvector_schema"))) if s]
    tail = "".join(", " + _ident(s) for s in extra)
    sql = ("SELECT set_config('search_path', current_setting('search_path') || %(sp_tail)s, true), "
           "set_config('lakebase_bm25.prefilter', %(sp_bpf)s, true), "
           "set_config('lakebase_ann.prefilter', %(sp_apf)s, true);\n")
    return sql, tail


# ---------------------------------------------------------------------- hooks

_QUEUE_SQL = ("INSERT INTO view_catalog_queue (app_id) VALUES (%s) "
              "ON CONFLICT (app_id) DO UPDATE SET queued_at = clock_timestamp()")


def touch(c, object_type: str, object_id: str) -> None:
    """Queue a view for reindexing inside the caller's transaction. Never raises.

    One round trip. A savepoint keeps a failure here (the queue table missing
    on an old schema) from aborting the publish it rides along with.
    """
    if not _ready or object_type != APP or not object_id:
        return
    try:
        c.execute(f"SAVEPOINT view_catalog_touch; {_QUEUE_SQL}; RELEASE SAVEPOINT view_catalog_touch", (object_id,))
    except Exception as e:  # noqa: BLE001
        try:
            c.execute("ROLLBACK TO SAVEPOINT view_catalog_touch")
        except Exception:  # noqa: BLE001
            pass
        logger.info("Could not queue view %s for the catalog: %s", object_id, e)


def mark_dirty(object_type: str, object_id: str) -> None:
    """Queue a view for reindexing after a change committed elsewhere. Never raises.

    One autocommitted statement on a pooled connection. After a failure the
    hook stands down for half a minute rather than add a timeout to every
    request while the database is unreachable; the reconcile catches up.
    """
    global _hook_backoff_until
    if not _ready or object_type != APP or not object_id or time.monotonic() < _hook_backoff_until:
        return
    conn = None
    try:
        conn = _content()
        # The pool's liveness ping can leave a transaction open, and autocommit
        # can't be switched on inside one.
        conn.rollback()
        conn.autocommit = True
        conn.cursor().execute(_QUEUE_SQL, (object_id,))
    except Exception as e:  # noqa: BLE001
        _hook_backoff_until = time.monotonic() + _HOOK_BACKOFF_SECONDS
        logger.info("Could not queue view %s for the catalog: %s", object_id, e)
    finally:
        if conn is not None:
            try:
                conn.autocommit = False
            except Exception:  # noqa: BLE001
                pass
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def queue(c, ids: Sequence[str]) -> None:
    ids = [i for i in dict.fromkeys(ids) if i]
    if ids:
        c.execute("INSERT INTO view_catalog_queue (app_id) SELECT unnest(%s::text[]) "
                  "ON CONFLICT (app_id) DO UPDATE SET queued_at = clock_timestamp()", (ids,))


# ---------------------------------------------------------------------- build

def _rows(c) -> List[Dict[str, Any]]:
    names = [d[0] for d in c.description]
    return [dict(zip(names, r)) for r in c.fetchall()]


def _heads_sql(where: str) -> str:
    from services.app_store import HEAD_COLUMNS

    cols = ", ".join(f"v.{col}" for col in HEAD_COLUMNS)
    return (f"SELECT {cols}, v.published_at, h.first_at FROM dashboard_views v "
            f"JOIN (SELECT id, MAX(version) AS version, MIN(COALESCE(published_at, timestamp)) AS first_at "
            f"FROM dashboard_views WHERE {where} GROUP BY id ORDER BY id LIMIT %s) h "
            f"ON v.id = h.id AND v.version = h.version ORDER BY v.id")


def _acls(ids: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    if not ids:
        return out
    conn = _settings()
    try:
        c = conn.cursor()
        c.execute("SELECT object_id, principal, principal_type, level, granted_at FROM object_permissions "
                  "WHERE object_type = %s AND object_id = ANY(%s) ORDER BY object_id, granted_at, principal",
                  (APP, list(ids)))
        for r in _rows(c):
            out.setdefault(r.pop("object_id"), []).append(r)
        conn.commit()
    finally:
        conn.close()
    return out


def build_rows(c, heads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Catalog rows for these published heads, leaving out archived views."""
    from services import app_links, app_spec, app_store

    if not heads:
        return []
    ids = [h["id"] for h in heads]
    c.execute("SELECT id FROM archived_views WHERE id = ANY(%s)", (ids,))
    archived = {r[0] for r in c.fetchall()}
    heads = [h for h in heads if h["id"] not in archived]
    if not heads:
        return []
    ids = [h["id"] for h in heads]
    slugs = app_links.current(c, ids)
    c.execute("SELECT app_id, featured_position, certified FROM view_curation WHERE app_id = ANY(%s)", (ids,))
    curation = {r["app_id"]: r for r in _rows(c)}
    specs = {h["id"]: app_spec.read_spec(h["id"], h.get("spec_json"), h.get("widgets_json")) for h in heads}
    wids = sorted({w for s in specs.values() for w in app_store.custom_widget_ids(s)})
    names = {w: (h.get("name") or "") for w, h in app_store.widget_heads(c, wids).items()}
    acls = _acls(ids)
    return [catalog_row(h, acl=acls.get(h["id"], []), slug=slugs.get(h["id"]), widget_names=names,
                        curation=curation.get(h["id"]), spec=specs[h["id"]]) for h in heads]


_COLUMNS = ("id", "name", "sort_name", "description", "owner", "owner_key", "domain", "presentation", "ref",
            "tab_names", "widget_ids", "widget_names", "readers", "managers", "published_version",
            "published_at", "updated_at", "tsv", "embed_hash", "featured_position", "certified")
_ARRAYS = ("tab_names", "widget_ids", "widget_names", "readers", "managers")
_TSV = ("setweight(to_tsvector('english', %(ta)s), 'A') || setweight(to_tsvector('simple', %(ta)s), 'A') || "
        "setweight(to_tsvector('english', %(tb)s), 'B') || setweight(to_tsvector('english', %(tc)s), 'C') || "
        "setweight(to_tsvector('english', %(td)s), 'D')")
_TEMPLATE = "(" + ", ".join(
    _TSV if col == "tsv" else f"%({col})s::text[]" if col in _ARRAYS else f"%({col})s" for col in _COLUMNS
) + ", now())"
_UPSERT = (
    f"INSERT INTO view_catalog ({', '.join(_COLUMNS)}, indexed_at) VALUES %s "
    f"ON CONFLICT (id) DO UPDATE SET {', '.join(f'{col} = EXCLUDED.{col}' for col in _COLUMNS[1:])}, "
    f"indexed_at = EXCLUDED.indexed_at "
    # An unchanged row isn't rewritten: every write touches the BM25, GIN and vector indexes.
    f"WHERE ({', '.join(f'view_catalog.{col}' for col in _COLUMNS[1:])}) IS DISTINCT FROM "
    f"({', '.join(f'EXCLUDED.{col}' for col in _COLUMNS[1:])})"
)


def upsert(c, rows: List[Dict[str, Any]]) -> None:
    if rows:
        from psycopg2.extras import execute_values

        execute_values(c, _UPSERT, rows, template=_TEMPLATE, page_size=200)


def rebuild_ids(conn, ids: Sequence[str]) -> int:
    """Rebuild these views' rows, dropping any no longer published or now archived."""
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return 0
    c = conn.cursor()
    c.execute(_heads_sql("id = ANY(%s)"), (ids, len(ids)))
    rows = build_rows(c, _rows(c))
    upsert(c, rows)
    built = {r["id"] for r in rows}
    gone = [i for i in ids if i not in built]
    if gone:
        c.execute("DELETE FROM view_catalog WHERE id = ANY(%s)", (gone,))
    conn.commit()
    return len(rows)


def _state(c, key: str) -> Dict[str, Any]:
    c.execute("SELECT value FROM view_catalog_state WHERE key = %s", (key,))
    row = c.fetchone()
    return dict(row[0]) if row and row[0] else {}


def set_state(c, key: str, value: Dict[str, Any], merge: bool = True) -> None:
    from psycopg2.extras import Json

    c.execute(
        "INSERT INTO view_catalog_state (key, value, updated_at) VALUES (%s, %s, now()) "
        "ON CONFLICT (key) DO UPDATE SET value = "
        + ("view_catalog_state.value || EXCLUDED.value" if merge else "EXCLUDED.value")
        + ", updated_at = now()",
        (key, Json(value, dumps=lambda v: json.dumps(v, default=iso))),
    )


def _autocommit(conn, sql: str) -> None:
    """Run a statement that can't be inside a transaction (VACUUM, … CONCURRENTLY)."""
    conn.commit()
    conn.autocommit = True
    try:
        conn.cursor().execute(sql)
    finally:
        conn.autocommit = False


def full_build(conn, page: int = BUILD_PAGE) -> int:
    """Rebuild every row. Search keeps answering from the old rows meanwhile."""
    c = conn.cursor()
    before = _state(c, "build")
    c.execute("SELECT COUNT(DISTINCT id) FROM dashboard_views "
              "WHERE id NOT IN (SELECT id FROM archived_views)")
    source_total = c.fetchone()[0]
    set_state(c, "build", {"status": "building", "started_at": _now(), "source_total": source_total,
                           "indexed": 0})
    conn.commit()
    after, done = "", 0
    while True:
        c.execute(_heads_sql("id > %s"), (after, page))
        heads = _rows(c)
        if not heads:
            break
        upsert(c, build_rows(c, heads))
        done += len(heads)
        after = heads[-1]["id"]
        set_state(c, "build", {"indexed": done})
        conn.commit()
    c.execute("DELETE FROM view_catalog vc WHERE NOT EXISTS (SELECT 1 FROM dashboard_views v WHERE v.id = vc.id) "
              "OR vc.id IN (SELECT id FROM archived_views)")
    c.execute("SELECT COUNT(*) FROM view_catalog")
    rows = c.fetchone()[0]
    set_state(c, "build", {"status": "ready", "format_version": FORMAT_VERSION, "built_at": _now(),
                           "rows": rows, "indexed": rows, "source_total": rows})
    set_state(c, "reconcile", {"at": _now()})
    conn.commit()
    # BM25 statistics come from index build and VACUUM only.
    try:
        _autocommit(conn, "VACUUM (ANALYZE) view_catalog")
    except Exception as e:  # noqa: BLE001
        logger.warning("VACUUM view_catalog failed: %s", e)
    if before.get("format_version") not in (None, FORMAT_VERSION):
        for index in (BM25_INDEX, ANN_INDEX):
            try:
                if _index_exists(c, index):
                    _autocommit(conn, f"REINDEX INDEX CONCURRENTLY {index}")
            except Exception as e:  # noqa: BLE001
                logger.warning("REINDEX %s failed: %s", index, e)
    forget_detection()
    return rows


def _index_exists(c, name: str) -> bool:
    c.execute("SELECT 1 FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid "
              "WHERE i.indrelid = to_regclass('view_catalog') AND ic.relname = %s", (name,))
    found = c.fetchone() is not None
    c.connection.commit()
    return found


def drain(conn, budget: float = DRAIN_SECONDS) -> int:
    """Rebuild queued rows. An id queued again while its row was rebuilding stays queued."""
    c = conn.cursor()
    started, done = time.monotonic(), 0
    while time.monotonic() - started < budget:
        c.execute("SELECT app_id, queued_at FROM view_catalog_queue ORDER BY queued_at LIMIT %s", (DRAIN_BATCH,))
        batch = c.fetchall()
        conn.commit()
        if not batch:
            break
        rebuild_ids(conn, [r[0] for r in batch])
        c.execute("DELETE FROM view_catalog_queue q USING unnest(%s::text[], %s::timestamptz[]) AS d(app_id, queued_at) "
                  "WHERE q.app_id = d.app_id AND q.queued_at = d.queued_at",
                  ([r[0] for r in batch], [r[1] for r in batch]))
        conn.commit()
        done += len(batch)
        if len(batch) < DRAIN_BATCH:
            break
    return done


def reconcile(conn) -> int:
    """Queue every row that disagrees with its sources. Returns how many."""
    c = conn.cursor()
    c.execute("SELECT id, MAX(version) FROM dashboard_views GROUP BY id")
    versions = dict(c.fetchall())
    c.execute("SELECT id FROM archived_views")
    archived = {r[0] for r in c.fetchall()}
    c.execute("SELECT DISTINCT ON (app_id) app_id, slug FROM app_links ORDER BY app_id, claimed_at DESC")
    slugs = dict(c.fetchall())
    c.execute("SELECT app_id, featured_position, certified FROM view_curation")
    curation = {r["app_id"]: r for r in _rows(c)}
    c.execute("SELECT w.id, w.name FROM widgets w JOIN (SELECT id, MAX(version) AS version FROM widgets "
              "WHERE is_deprecated = 0 GROUP BY id) l ON w.id = l.id AND w.version = l.version")
    widget_names = {i: n or "" for i, n in c.fetchall()}
    c.execute("SELECT id, published_version, ref, readers, managers, owner, featured_position, certified, "
              "widget_ids, widget_names FROM view_catalog")
    catalog = {r["id"]: r for r in _rows(c)}
    conn.commit()
    acls: Dict[str, List[Dict[str, Any]]] = {}
    sconn = _settings()
    try:
        sc = sconn.cursor()
        sc.execute("SELECT object_id, principal, principal_type, level, granted_at FROM object_permissions "
                   "WHERE object_type = %s ORDER BY object_id, granted_at, principal", (APP,))
        for r in _rows(sc):
            acls.setdefault(r.pop("object_id"), []).append(r)
        sconn.commit()
    finally:
        sconn.close()
    stale = stale_ids(catalog, versions, archived, slugs, curation, acls, widget_names)
    queue(c, stale)
    set_state(c, "reconcile", {"at": _now(), "queued": len(stale)})
    conn.commit()
    return len(stale)


def install_extensions(conn, d: Dict[str, Any]) -> Optional[str]:
    """Install whichever Lakebase Search extension is missing. The error text, or None."""
    c = conn.cursor()
    errors = []
    for ext, cascade in ((TEXT_EXT, ""), (VECTOR_EXT, " CASCADE")):
        if d.get("text_schema" if ext == TEXT_EXT else "vector_schema"):
            continue
        try:
            c.execute(f"CREATE SCHEMA IF NOT EXISTS {_ident(EXT_SCHEMA)}")
            c.execute(f"CREATE EXTENSION IF NOT EXISTS {ext} SCHEMA {_ident(EXT_SCHEMA)}{cascade}")
            conn.commit()
            logger.info("Installed %s in schema %s", ext, EXT_SCHEMA)
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            errors.append(f"{ext}: {str(e).strip().splitlines()[0] if str(e).strip() else e}")
    return "; ".join(errors) or None


_last_ensure = 0.0


def ensure_search(conn, force: bool = False) -> Dict[str, Any]:
    """Install the extensions if the database lets the app, and build the BM25
    index once the catalog has been filled. Never raises."""
    global _last_ensure
    c = conn.cursor()
    try:
        d = detect(c)
        conn.commit()
        built = bool((d["state"].get("build") or {}).get("built_at"))
        missing = not d["text_schema"] or not d["vector_schema"]
        if missing and (force or time.monotonic() - _last_ensure > ENSURE_SECONDS):
            _last_ensure = time.monotonic()
            error = install_extensions(conn, d)
            set_state(c, "extensions", {"checked_at": _now(), "error": error,
                                        "kind": classify_install_error(error) if error else None})
            conn.commit()
            d = detect(c)
            conn.commit()
        if d["text_schema"] and d["text_usable"] and built and not d["bm25"]:
            if d["bm25_invalid"]:
                c.execute(f"DROP INDEX IF EXISTS {BM25_INDEX}")
            c.execute(f"CREATE INDEX IF NOT EXISTS {BM25_INDEX} ON view_catalog USING lakebase_bm25 (tsv)")
            set_state(c, "indexes", {"bm25_built_at": _now()})
            conn.commit()
            logger.info("Built the view catalog's BM25 index")
            d = detect(c)
            conn.commit()
        forget_detection()
        return d
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        logger.warning("Could not set up Lakebase Search for the view catalog: %s", e)
        return {}


def _try_lock(c) -> bool:
    c.execute("SELECT pg_try_advisory_lock(%s)", (_LOCK_KEY,))
    return bool(c.fetchone()[0])


def sync_job() -> None:
    """The catalog job: first build or format rebuild, else drain the queue, and
    reconcile every half hour. Builds and reconciles hold the catalog lock."""
    if not _ready:
        return
    conn = _content()
    try:
        c = conn.cursor()
        build = _state(c, "build")
        last = _state(c, "reconcile").get("at")
        conn.commit()
        needs_build = build.get("format_version") != FORMAT_VERSION or build.get("status") == "building"
        due = _age_seconds(last) > RECONCILE_SECONDS
        if needs_build or due:
            locked = _unpooled()
            try:
                lc = locked.cursor()
                if _try_lock(lc):
                    try:
                        locked.commit()
                        if needs_build:
                            full_build(locked)
                            ensure_search(locked, force=True)
                        else:
                            reconcile(locked)
                    finally:
                        lc.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
                        locked.commit()
            finally:
                locked.close()
        drain(conn)
        ensure_search(conn)
    finally:
        conn.close()


# ------------------------------------------------------------------ embedding

_auth_override: Optional[Callable[[], Tuple[str, str]]] = None
_http = None
_http_lock = threading.Lock()


def set_embedding_auth(fn: Optional[Callable[[], Tuple[str, str]]]) -> None:
    """(host, token) for embedding calls, for tools that run outside the app."""
    global _auth_override
    _auth_override = fn


def _embedding_auth() -> Tuple[str, str]:
    """Signed by the app's service principal, like LLM inference.

    The catalog is embedded in the background with nobody signed in, and only
    a view's own name, description, tab, domain and widget names are sent.
    """
    if _auth_override is not None:
        return _auth_override()
    from services.agent_runtime import _bearer, _sp_ws

    ws = _sp_ws()
    token = _bearer(ws) or ws.config.token
    if not token:
        raise RuntimeError("The app's service principal has no token for the embedding endpoint")
    return ws.config.host.rstrip("/"), token


def _session():
    global _http
    with _http_lock:
        if _http is None:
            import requests

            _http = requests.Session()
        return _http


def embed_texts(texts: Sequence[str], model: str, timeout: float = EMBED_TIMEOUT) -> List[List[float]]:
    from services.settings_store import base_path_for_model

    host, token = _embedding_auth()
    response = _session().post(
        f"{host}{base_path_for_model(model)}/embeddings",
        json={"model": model, "input": list(texts)},
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"{model} answered {response.status_code}: {response.text[:200]}")
    data = sorted(response.json().get("data") or [], key=lambda d: d.get("index", 0))
    vectors = [d.get("embedding") for d in data]
    if len(vectors) != len(texts) or not all(isinstance(v, list) and v for v in vectors):
        raise RuntimeError(f"{model} returned {len(vectors)} embeddings for {len(texts)} texts")
    return vectors


_query_cache: "OrderedDict[Tuple[str, str], List[float]]" = OrderedDict()
_query_lock = threading.Lock()
_QUERY_CACHE_SIZE = 256
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="search-embed")


def _remember(key: Tuple[str, str], vector: List[float]) -> None:
    with _query_lock:
        _query_cache[key] = vector
        _query_cache.move_to_end(key)
        while len(_query_cache) > _QUERY_CACHE_SIZE:
            _query_cache.popitem(last=False)


def embed_query(text: str, model: str, timeout: float = QUERY_EMBED_TIMEOUT) -> Optional[List[float]]:
    """The query's embedding, or None if the model doesn't answer in time.

    A slow answer still lands in the cache, so the same search a moment later
    gets hybrid results.
    """
    key = (model, (text or "").strip().lower()[:200])
    with _query_lock:
        if key in _query_cache:
            _query_cache.move_to_end(key)
            return _query_cache[key]
    started = time.monotonic()
    future = _executor.submit(lambda: embed_texts([key[1]], model, timeout=max(2.0, timeout * 5))[0])
    try:
        vector = future.result(timeout=timeout)
    except FutureTimeout:
        # Logged because the search itself just answers as keyword: without this
        # nobody can tell a budget that is too tight from an endpoint that is down.
        def late(f) -> None:
            took = time.monotonic() - started
            if f.exception() is None:
                _remember(key, f.result())
                logger.info("Search query embedding took %.2fs, past the %.2fs budget", took, timeout)
            else:
                logger.info("Search query embedding failed after %.2fs: %s", took, f.exception())

        future.add_done_callback(late)
        return None
    except Exception as e:  # noqa: BLE001
        logger.info("Embedding the search query failed: %s", e)
        return None
    _remember(key, vector)
    return vector


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def _ensure_embedding_column(conn, d: Dict[str, Any], dims: int) -> None:
    c = conn.cursor()
    if d.get("embedding_dims") == dims:
        return
    if d.get("embedding_dims"):
        c.execute(f"DROP INDEX IF EXISTS {ANN_INDEX}")
        c.execute("ALTER TABLE view_catalog DROP COLUMN IF EXISTS embedding")
        c.execute("UPDATE view_catalog SET embedded_hash = NULL WHERE embedded_hash IS NOT NULL")
    vs = d.get("pgvector_schema") or d.get("vector_schema")
    c.execute(f"ALTER TABLE view_catalog ADD COLUMN IF NOT EXISTS embedding {_ident(vs)}.vector({int(dims)})")
    conn.commit()
    d["embedding_dims"] = dims


def embed_job(budget: float = EMBED_SECONDS, batch: int = EMBED_BATCH) -> None:
    """Embed rows whose text changed, then build the vector index once most are done."""
    if not _ready:
        return
    model = embedding_model()
    if not model:
        return
    conn = _content()
    c = conn.cursor()
    try:
        d = detect(c)
        conn.commit()
        if not d["vector_schema"] or not d["vector_usable"] or not d["text_schema"]:
            return
        emb = (d["state"].get("embeddings") or {})
        if emb.get("model") and emb["model"] != model:
            c.execute(f"DROP INDEX IF EXISTS {ANN_INDEX}")
            c.execute("UPDATE view_catalog SET embedded_hash = NULL WHERE embedded_hash IS NOT NULL")
            set_state(c, "embeddings", {"model": model, "error": None, "done": 0}, merge=False)
            conn.commit()
            d["ann"] = False
        started, error = time.monotonic(), None
        while time.monotonic() - started < budget:
            c.execute("SELECT id, name, description, tab_names, domain, widget_names, embed_hash FROM view_catalog "
                      "WHERE embed_hash IS DISTINCT FROM embedded_hash ORDER BY viewers_30d DESC, id LIMIT %s",
                      (batch,))
            rows = _rows(c)
            conn.commit()
            if not rows:
                break
            try:
                vectors = embed_texts([embedding_text(r) for r in rows], model)
            except Exception as e:  # noqa: BLE001
                error = str(e)[:300]
                break
            _ensure_embedding_column(conn, d, len(vectors[0]))
            vs = d.get("pgvector_schema") or d.get("vector_schema")
            c.execute(f"UPDATE view_catalog vc SET embedding = d.v::{_ident(vs)}.vector, embedded_hash = d.h "
                      "FROM unnest(%s::text[], %s::text[], %s::text[]) AS d(id, v, h) "
                      "WHERE vc.id = d.id AND vc.embed_hash = d.h",
                      ([r["id"] for r in rows], [_vector_literal(v) for v in vectors], [r["embed_hash"] for r in rows]))
            conn.commit()
        c.execute("SELECT COUNT(*) FILTER (WHERE embedded_hash = embed_hash), COUNT(*) FROM view_catalog")
        done, total = c.fetchone()
        set_state(c, "embeddings", {"model": model, "dims": d.get("embedding_dims"), "done": done, "total": total,
                                    "error": error, "at": _now()})
        conn.commit()
        if error:
            logger.warning("Embedding views for search failed: %s", error)
        elif d.get("embedding_dims") and total and done >= ANN_MIN_COVERAGE * total:
            indexes = _state(c, "indexes")
            conn.commit()
            if not d["ann"]:
                path_sql, tail = _search_path_sql(d)
                c.execute(path_sql, {"sp_tail": tail, "sp_bpf": "off", "sp_apf": "off"})
                if d.get("ann_invalid"):
                    c.execute(f"DROP INDEX IF EXISTS {ANN_INDEX}")
                c.execute(f"CREATE INDEX IF NOT EXISTS {ANN_INDEX} ON view_catalog "
                          "USING lakebase_ann (embedding vector_cosine_ops)")
                set_state(c, "indexes", {"ann_built_at": _now(), "ann_rows": total})
                conn.commit()
                logger.info("Built the view catalog's vector index over %s rows", total)
            elif total > 2 * int(indexes.get("ann_rows") or total):
                # The index chose its lists for the table it was built on.
                _autocommit(conn, f"REINDEX INDEX CONCURRENTLY {ANN_INDEX}")
                set_state(c, "indexes", {"ann_built_at": _now(), "ann_rows": total})
                conn.commit()
        forget_detection()
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        logger.warning("The view embedding job failed: %s", e)
        try:
            set_state(c, "embeddings", {"error": str(e)[:300], "at": _now()})
            conn.commit()
        except Exception:  # noqa: BLE001
            conn.rollback()
    finally:
        conn.close()


# --------------------------------------------------------------------- search

@dataclass
class SearchParams:
    q: str = ""
    scope: str = "all"
    sort: str = "relevance"
    domain: List[str] = field(default_factory=list)
    owner: List[str] = field(default_factory=list)
    certified: Optional[bool] = None
    standalone: Optional[bool] = None
    status: Optional[str] = None
    opened: Optional[str] = None
    cursor: Optional[str] = None
    limit: int = DEFAULT_LIMIT
    facets: bool = False


class Refused(Exception):
    """A request the caller isn't allowed to make (`scope=everything` without being an admin)."""


def validate(p: SearchParams, who: access.Caller) -> SearchParams:
    """ValueError for a bad parameter, Refused for a forbidden one."""
    if p.scope not in SCOPES:
        raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
    if p.sort not in SORTS:
        raise ValueError(f"sort must be one of {', '.join(SORTS)}")
    if p.status and p.status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    if p.opened and p.opened not in OPENED:
        raise ValueError(f"opened must be one of {', '.join(OPENED)}")
    if p.scope == "everything" and not who.is_admin:
        raise Refused("Only app administrators can search every view.")
    p.limit = max(1, min(MAX_LIMIT, int(p.limit or DEFAULT_LIMIT)))
    p.domain = [d for d in p.domain if d]
    p.owner = [o.strip().lower() for o in p.owner if o and o.strip()]
    return p


_LIGHT = (
    "vc.id, vc.ref, vc.name, LEFT(vc.description, %d) AS description, vc.owner, vc.domain, vc.presentation, "
    "vc.updated_at, vc.published_at, vc.viewers_30d, vc.trend, vc.favorites, vc.featured_position, vc.certified, "
    "(f.app_id IS NOT NULL) AS favorite, (h.app_id IS NOT NULL) AS hidden, "
    "(SELECT MAX(v.last_opened_at) FROM view_visits v WHERE v.username = %%(me)s AND v.app_id = vc.id) AS my_opened, "
    "EXISTS (SELECT 1 FROM object_drafts d WHERE d.object_type = 'app' AND d.object_id = vc.id) AS has_draft, "
    "(vc.readers && %%(keys)s::text[]) AS listed"
) % DESCRIPTION_CHARS
_JOINS = ("LEFT JOIN user_favorites f ON f.username = %(me)s AND f.app_id = vc.id "
          "LEFT JOIN view_hidden h ON h.username = %(me)s AND h.app_id = vc.id")

_KEYSET = {
    "popular": ("vc.viewers_30d", "int", "DESC"),
    "trending": ("vc.trend", "real", "DESC"),
    "updated": ("vc.updated_at", "timestamptz", "DESC"),
    "favorites": ("vc.favorites", "int", "DESC"),
    "name": ("vc.sort_name", "text", "ASC"),
}


def _me(who: access.Caller) -> str:
    return (who.username or "").strip().lower()


def filters(who: access.Caller, p: SearchParams, *, skip: Sequence[str] = ()) -> Tuple[List[str], Dict[str, Any]]:
    """WHERE clauses (over `vc`) and their parameters for a search's scope and filters."""
    where: List[str] = []
    args: Dict[str, Any] = {"keys": caller_keys(who), "me": _me(who)}
    if p.scope != "everything":
        where.append("vc.readers && %(keys)s::text[]")
    if p.scope == "mine":
        where.append("vc.owner_key = %(me)s")
    elif p.scope == "shared":
        where.append("vc.owner_key IS DISTINCT FROM %(me)s")
    elif p.scope == "favorites":
        where.append("EXISTS (SELECT 1 FROM user_favorites uf WHERE uf.username = %(me)s AND uf.app_id = vc.id)")
    if p.domain and "domain" not in skip:
        where.append("vc.domain = ANY(%(domain)s)")
        args["domain"] = list(p.domain)
    if p.owner and "owner" not in skip:
        where.append("vc.owner_key = ANY(%(owner)s)")
        args["owner"] = list(p.owner)
    if p.certified is not None:
        where.append("vc.certified" if p.certified else "NOT vc.certified")
    if p.standalone is not None:
        where.append("vc.presentation " + ("=" if p.standalone else "<>") + " 'standalone'")
    if p.status:
        if not who.is_admin:
            where.append("vc.managers && %(keys)s::text[]")
        drafted = "EXISTS (SELECT 1 FROM object_drafts od WHERE od.object_type = 'app' AND od.object_id = vc.id)"
        where.append(drafted if p.status == "draft" else f"NOT {drafted}")
    if p.opened == "never":
        where.append("vc.last_opened_at IS NULL")
    elif p.opened == "90d":
        where.append("(vc.last_opened_at IS NULL OR vc.last_opened_at < now() - interval '90 days')")
    return where, args


def text_match(words: Sequence[str]) -> Tuple[str, Dict[str, Any]]:
    """Basic mode's match: every word as a prefix anywhere (stemmed), or in the
    name exactly as typed, which keeps a stop word like "a" findable in names."""
    return ("vc.tsv @@ (to_tsquery('english', %(tq)s) || to_tsquery('simple', %(nq)s))",
            {"tq": prefix_query(words), "nq": prefix_query(words, "A")})


def _where(clauses: Sequence[str]) -> str:
    return " AND ".join(clauses) if clauses else "TRUE"


def light(row: Dict[str, Any], level: str) -> Dict[str, Any]:
    """The shape every Discover list returns."""
    from services import drafts

    out = {
        "id": row["id"],
        "link": link_for(row.get("ref") or row["id"]),
        "ref": row.get("ref") or row["id"],
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "owner": row.get("owner"),
        "domain": row.get("domain"),
        "presentation": row.get("presentation") or "workspace",
        "updated_at": iso(row.get("updated_at")),
        "published_at": iso(row.get("published_at")),
        "viewers_30d": int(row.get("viewers_30d") or 0),
        "trend": round(float(row.get("trend") or 0), 3),
        "favorites": int(row.get("favorites") or 0),
        "featured": row.get("featured_position") is not None,
        "featured_position": row.get("featured_position"),
        "certified": bool(row.get("certified")),
        "access": level,
        "favorite": bool(row.get("favorite")),
        "hidden": bool(row.get("hidden")),
        "last_opened_at": iso(row.get("my_opened")),
    }
    if level == MANAGE:
        out["state"] = row.get("state") or (drafts.PUBLISHED_WITH_DRAFT if row.get("has_draft") else drafts.PUBLISHED)
    return out


def recheck(who: access.Caller, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Light rows for those the caller still holds a level on, in order.

    A row whose readers let the caller through but whose access list doesn't
    is queued, so the catalog corrects itself. Rows fetched by id (favorites,
    recent opens) can name views the caller has since lost; those are just
    dropped, since their catalog row is already right.
    """
    if not rows:
        return []
    levels = access.levels_for(who, APP, [r["id"] for r in rows])
    out, stale = [], []
    for r in rows:
        level = levels.get(r["id"])
        if level:
            out.append(light(r, level))
        elif r.get("listed"):
            stale.append(r["id"])
    for i in stale[:10]:
        mark_dirty(APP, i)
    return out


def light_rows(c, who: access.Caller, ids: Sequence[str]) -> List[Dict[str, Any]]:
    """Catalog rows for these ids, in the order given; ids not in the catalog are left out."""
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return []
    c.execute(f"SELECT {_LIGHT} FROM view_catalog vc {_JOINS} WHERE vc.id = ANY(%(ids)s)",
              {"me": _me(who), "keys": caller_keys(who), "ids": ids})
    found = {r["id"]: r for r in _rows(c)}
    return [found[i] for i in ids if i in found]


def _candidates(c, d: Dict[str, Any], mode: str, words: Sequence[str], where: List[str], args: Dict[str, Any],
                vector: Optional[List[float]], bm25_prefilter: bool, ann_prefilter: bool):
    """(lists, stats) for keyword or hybrid ranking, in one round trip."""
    path_sql, tail = _search_path_sql(d)
    w = _where(where)
    ctes = [
        f"bm AS (SELECT id, score FROM (SELECT vc.id, vc.tsv <@> to_bm25query(to_tsvector('english', %(bq)s), %(bm25)s) "
        f"AS score FROM view_catalog vc WHERE {w} ORDER BY score LIMIT {CANDIDATES}) s WHERE score < 0)",
        f"np AS (SELECT vc.id, ts_rank_cd(vc.tsv, to_tsquery('simple', %(nq)s)) AS score FROM view_catalog vc "
        f"WHERE vc.tsv @@ to_tsquery('simple', %(nq)s) AND {w} ORDER BY score DESC, vc.id LIMIT {CANDIDATES})",
    ]
    union = ["SELECT 'bm' AS src, row_number() OVER (ORDER BY score, id) AS rn, id, score FROM bm",
             "SELECT 'np', row_number() OVER (ORDER BY score DESC, id), id, score FROM np"]
    params = dict(args, bq=" ".join(words), nq=prefix_query(words, "A"),
                  bm25=f"{_ident(d['schema'])}.{BM25_INDEX}" if d.get("schema") else BM25_INDEX,
                  sp_tail=tail, sp_bpf="on" if bm25_prefilter else "off", sp_apf="on" if ann_prefilter else "off")
    if mode == "hybrid" and vector is not None:
        vs = _ident(d.get("pgvector_schema") or d.get("vector_schema"))
        ctes.append(f"vec AS (SELECT id, score FROM (SELECT vc.id, vc.embedding <=> %(qv)s::{vs}.vector AS score "
                    f"FROM view_catalog vc WHERE {w} ORDER BY score LIMIT {CANDIDATES}) s WHERE score IS NOT NULL)")
        union.append("SELECT 'vec', row_number() OVER (ORDER BY score, id), id, score FROM vec")
        params["qv"] = _vector_literal(vector)
    sql = (path_sql + "WITH " + ", ".join(ctes) + ", c AS (" + " UNION ALL ".join(union) + ") "
           "SELECT c.src, c.rn, c.id, c.score, vc.viewers_30d, vc.certified, vc.featured_position "
           "FROM c JOIN view_catalog vc ON vc.id = c.id ORDER BY c.src, c.rn")
    c.execute(sql, params)
    lists: Dict[str, List[Tuple[str, float]]] = {"bm": [], "np": [], "vec": []}
    stats: Dict[str, Dict[str, Any]] = {}
    for src, _rn, i, score, viewers, certified, featured in c.fetchall():
        lists[src].append((i, score))
        stats[i] = {"viewers_30d": viewers, "certified": certified, "featured_position": featured}
    ranked = [[i for i, _ in lists["bm"]], [i for i, _ in lists["np"]]]
    if lists["vec"]:
        ranked.append(vector_cutoff(lists["vec"]))
    return ranked, stats


def _basic_candidates(c, words: Sequence[str], where: List[str], args: Dict[str, Any]):
    match, margs = text_match(words)
    c.execute(
        "SELECT vc.id, ts_rank_cd(vc.tsv, to_tsquery('english', %(tq)s) || to_tsquery('simple', %(nq)s)) AS score, "
        f"vc.viewers_30d, vc.certified, vc.featured_position FROM view_catalog vc WHERE {match} AND {_where(where)} "
        f"ORDER BY score DESC, vc.id LIMIT {RELEVANCE_CAP}",
        dict(args, **margs),
    )
    rows = c.fetchall()
    stats = {r[0]: {"viewers_30d": r[2], "certified": r[3], "featured_position": r[4]} for r in rows}
    return [[r[0] for r in rows]], stats


def ranked_ids(conn, d: Optional[Dict[str, Any]], mode: str, q: str, words: Sequence[str], where: List[str],
               args: Dict[str, Any], bm25_prefilter: bool = BM25_PREFILTER,
               ann_prefilter: bool = ANN_PREFILTER) -> Tuple[List[str], str]:
    """Relevance order for a query, and the mode that produced it.

    Hybrid falls back to keyword when the query can't be embedded in time, and
    keyword to basic when the extension query fails: search never errors for
    want of an optional feature.
    """
    c = conn.cursor()
    vector = None
    if mode == "hybrid":
        model = embedding_model()
        vector = embed_query(q, model) if model else None
        if vector is None:
            mode = "keyword"
    if mode in ("keyword", "hybrid") and d:
        try:
            lists, stats = _candidates(c, d, mode, words, where, args, vector, bm25_prefilter, ann_prefilter)
            return rank_candidates(lists, stats), mode
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            forget_detection()
            logger.warning("%s search failed, answering in basic mode: %s", mode, e)
    lists, stats = _basic_candidates(c, words, where, args)
    return rank_candidates(lists, stats), "basic"


def _keyset(c, sort: str, where: List[str], args: Dict[str, Any], cursor: Optional[Dict[str, Any]], limit: int):
    col, kind, direction = _KEYSET[sort]
    clauses = list(where)
    params = dict(args, lim=limit + 1)
    if cursor:
        clauses.append(f"({col}, vc.id) {'<' if direction == 'DESC' else '>'} (%(cv)s::{kind}, %(ci)s)")
        params.update(cv=cursor.get("v"), ci=cursor.get("i"))
    c.execute(f"SELECT {_LIGHT}, {col} AS sort_value FROM view_catalog vc {_JOINS} WHERE {_where(clauses)} "
              f"ORDER BY {col} {direction}, vc.id {direction} LIMIT %(lim)s", params)
    rows = _rows(c)
    more = len(rows) > limit
    rows = rows[:limit]
    last = rows[-1] if rows and more else None
    return rows, ({"s": sort, "v": iso(last["sort_value"]) if isinstance(last["sort_value"], datetime)
                   else last["sort_value"], "i": last["id"]} if last else None)


def facets(c, who: access.Caller, p: SearchParams, words: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Domain and owner counts (top 20), each ignoring its own filter so the
    other choices stay visible."""
    match, margs = text_match(words) if words else ("TRUE", {})
    dw, dargs = filters(who, p, skip=("domain",))
    ow, oargs = filters(who, p, skip=("owner",))
    c.execute(
        f"(SELECT 'domain' AS facet, COALESCE(vc.domain, '') AS value, '' AS label, COUNT(*) AS n "
        f"FROM view_catalog vc WHERE {match} AND {_where(dw)} GROUP BY 2 ORDER BY 4 DESC, 2 LIMIT 20) "
        f"UNION ALL (SELECT 'owner', COALESCE(vc.owner_key, ''), MIN(vc.owner), COUNT(*) "
        f"FROM view_catalog vc WHERE {match} AND {_where(ow)} GROUP BY 2 ORDER BY 4 DESC, 2 LIMIT 20)",
        {**dargs, **oargs, **margs},
    )
    out: Dict[str, List[Dict[str, Any]]] = {"domain": [], "owner": []}
    for facet, value, label, n in c.fetchall():
        item = {"value": value, "count": int(n)}
        if facet == "owner":
            item["label"] = label or value
        out[facet].append(item)
    return out


def search(who: access.Caller, p: SearchParams, *, mode: Optional[str] = None,
           bm25_prefilter: bool = BM25_PREFILTER, ann_prefilter: bool = ANN_PREFILTER) -> Dict[str, Any]:
    """`GET /api/discover/search`."""
    p = validate(p, who)
    words = query_words(p.q)
    sort = "popular" if p.sort == "relevance" and not words else p.sort
    cursor = decode_cursor(p.cursor) if p.cursor else None
    if cursor and cursor.get("s") != sort:
        raise ValueError("That cursor belongs to a different sort.")
    d = detected()
    if mode is None:
        mode = choose_mode(d, search_setting(), embedding_model())[0] if d else "basic"
    where, args = filters(who, p)
    conn = _content()
    try:
        c = conn.cursor()
        capped = False
        if sort == "relevance":
            ordered, used = ranked_ids(conn, d, mode, p.q, words, where, args, bm25_prefilter, ann_prefilter)
            c = conn.cursor()
            offset = max(0, int(cursor.get("o") or 0)) if cursor else 0
            total = len(ordered)
            capped = total >= RELEVANCE_CAP
            rows = light_rows(c, who, ordered[offset:offset + p.limit])
            nxt = {"s": sort, "o": offset + p.limit} if offset + p.limit < total else None
        else:
            used = "basic" if words else mode
            if words:
                match, margs = text_match(words)
                where, args = where + [match], dict(args, **margs)
            rows, nxt = _keyset(c, sort, where, args, cursor, p.limit)
            if cursor and "t" in cursor:
                total = int(cursor["t"])
            else:
                c.execute(f"SELECT COUNT(*) FROM view_catalog vc WHERE {_where(where)}", args)
                total = int(c.fetchone()[0])
            if nxt:
                nxt["t"] = total
        facet_counts = facets(c, who, p, words) if p.facets else None
        conn.commit()
    finally:
        conn.close()
    body = {"results": recheck(who, rows), "next_cursor": encode_cursor(nxt) if nxt else None,
            "total": total, "mode": used, "capped": capped}
    if facet_counts is not None:
        body["facets"] = facet_counts
    return body


def suggest(who: access.Caller, q: str) -> Dict[str, Any]:
    """Search-as-you-type: name prefixes first, basic mode always."""
    words = query_words(q)
    if not words:
        return {"results": [], "mode": "basic"}
    match, margs = text_match(words)
    conn = _content()
    try:
        c = conn.cursor()
        c.execute(
            f"SELECT {_LIGHT} FROM view_catalog vc {_JOINS} "
            f"WHERE {match} AND vc.readers && %(keys)s::text[] "
            "ORDER BY ts_rank_cd(vc.tsv, to_tsquery('simple', %(nq)s)) DESC, "
            "ts_rank_cd(vc.tsv, to_tsquery('english', %(tq)s)) DESC, vc.viewers_30d DESC, vc.id "
            f"LIMIT {SUGGEST_LIMIT}",
            dict(margs, me=_me(who), keys=caller_keys(who)),
        )
        rows = _rows(c)
        conn.commit()
    finally:
        conn.close()
    return {"results": recheck(who, rows), "mode": "basic"}


_RAILS = (
    ("featured", "vc.featured_position IS NOT NULL", "vc.featured_position, vc.id"),
    ("certified", "vc.certified", "vc.viewers_30d DESC, vc.id DESC"),
    ("popular", "vc.viewers_30d > 0", "vc.viewers_30d DESC, vc.id DESC"),
    ("trending", "vc.trend > 0 AND vc.viewers_7d >= 3", "vc.trend DESC, vc.id DESC"),
    ("updated", "TRUE", "vc.updated_at DESC, vc.id DESC"),
)


def rails(who: access.Caller) -> Dict[str, List[Dict[str, Any]]]:
    """`GET /api/discover/rails`: five rails in one query, plus New for you."""
    from services import view_signals

    fresh = view_signals.new_for_you_ids(who, limit=RAIL_LIMIT)
    conn = _content()
    try:
        c = conn.cursor()
        parts = [f"(SELECT '{name}' AS rail, {_LIGHT} FROM view_catalog vc {_JOINS} "
                 f"WHERE vc.readers && %(keys)s::text[] AND h.app_id IS NULL AND {cond} "
                 f"ORDER BY {order} LIMIT {RAIL_LIMIT})" for name, cond, order in _RAILS]
        c.execute(" UNION ALL ".join(parts), {"me": _me(who), "keys": caller_keys(who)})
        rows = _rows(c)
        new_rows = light_rows(c, who, fresh)
        conn.commit()
    finally:
        conn.close()
    unique = {r["id"]: r for r in rows + new_rows}
    allowed = {r["id"]: r for r in recheck(who, list(unique.values()))}
    out: Dict[str, List[Dict[str, Any]]] = {name: [] for name, _, _ in _RAILS}
    for r in rows:
        if r["id"] in allowed:
            out[r["rail"]].append(allowed[r["id"]])
    out["new_for_you"] = [allowed[r["id"]] for r in new_rows if r["id"] in allowed and not r.get("hidden")]
    return out


def status() -> Dict[str, Any]:
    """`GET /api/discover/status`: whether the catalog has finished its first build."""
    conn = _content()
    try:
        c = conn.cursor()
        build = _state(c, "build")
        c.execute("SELECT COUNT(*) FROM view_catalog")
        indexed = int(c.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    building = build.get("status") == "building"
    return {
        "ready": bool(build.get("built_at")),
        "mode": current_mode(),
        "indexed": int(build.get("indexed") or 0) if building else indexed,
        "total": int(build.get("source_total") or indexed) if building else indexed,
        "building": building,
    }
