"""Turns the retired role mappings into access lists, once per deployment.

Access used to follow a label: a role mapping gave a group or user `viewer`,
`editor` or `admin` on a domain, and every widget, global view and domain agent
filed under that domain followed it. Sharing replaced that with a list on each
object (`services/access.py`), so this writes, once, the list each object's
domain used to imply — the same people keep the same access on the day of the
cutover. The rules are what the old checks *did*, as the release before sharing
made them (its `roles._get_user_permissions`, `custom_widgets._visible`,
`app_spec.can_read` and the agent studio's `_authorize_write`, none of which
exist any more):

  * A mapping on a global alias (`GLOBAL_DOMAINS`) at `admin` made a global
    admin; that principal goes into `app_admins`.
  * Any other mapping applied to objects whose domain is exactly its domain (an
    unset domain reads as `General`): `viewer` becomes USE, `editor` and `admin`
    MANAGE. That covers every widget, *global* views and *domain* agents —
    personal views and agents never followed a domain.
  * A global alias at `viewer` or `editor` granted nothing outside objects filed
    under that literal name, because only `admin` was read as global. It still
    grants exactly that, and the report names each such mapping.
  * Owners get MANAGE: a widget's `created_by` and a personal view's or a
    personal or domain agent's `username`, where that is a person.
  * `shared_views` subscribers get USE on the view: that is who had a link open.
  * Global agents get Everyone USE, and nobody but admins manages them, as before.

Objects are read from the content store, its drafts, and the old Dev and Test
stores too, so work that only ever existed there is covered even if folding it
in (`consolidation`) failed; an id filed differently in different stores gets
the grants of each. Only rows are added: `role_mappings` is read and left as it
was, so redeploying the previous version finds access exactly as it left it.
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple

from routes.roles import GLOBAL_DOMAINS
from services import access, consolidation
from services.access import AGENT, ALL, APP, EVERYONE, GROUP, MANAGE, USE, USER, WIDGET

logger = logging.getLogger(__name__)

STEP = "access"
STEPS = (consolidation.STEP, STEP)
GRANTED_BY = "migration"
DEFAULT_DOMAIN = "General"
#: What init_db seeded as the first global admin; the same lockout prevention.
FALLBACK_ADMIN = ("users", GROUP)

LEVELS = {"viewer": USE, "editor": MANAGE, "admin": MANAGE}
_RANK = {USE: 1, MANAGE: 2}
_NOT_A_PERSON = {"", "unknown", "dev", "none", "null", "system", "n/a"}


class Mapping(NamedTuple):
    principal: str
    domain: str
    level: str


# ------------------------------------------------------------------ pure rules

def level_of(permission_level: Any) -> Optional[str]:
    return LEVELS.get(str(permission_level or "").strip().lower())


def is_global_domain(domain: Any) -> bool:
    return str(domain or "").strip().lower() in GLOBAL_DOMAINS


def mappings_from(rows: Iterable[Any]) -> List[Mapping]:
    """Role mapping rows (external_role, domain, permission_level) as `Mapping`s, unusable ones dropped."""
    out: List[Mapping] = []
    for r in rows:
        role, domain, level = (r["external_role"], r["domain"], r["permission_level"]) if hasattr(r, "keys") else tuple(r)[:3]
        role = str(role or "").strip()
        level = str(level or "").strip().lower()
        if role and domain and level in LEVELS:
            out.append(Mapping(role, str(domain).strip(), level))
    return out


def admins_from(mappings: Iterable[Mapping]) -> List[Tuple[str, str]]:
    """Who becomes an app admin: every global-alias `admin` mapping, as (principal, type)."""
    seen: Dict[str, Tuple[str, str]] = {}
    for m in mappings:
        if is_global_domain(m.domain) and m.level == "admin":
            ptype = access.infer_type(m.principal)
            seen.setdefault(_key(m.principal, ptype), (m.principal, ptype))
    return list(seen.values())


def by_domain(mappings: Iterable[Mapping]) -> Dict[str, List[Mapping]]:
    """Mappings keyed by the exact domain the old checks compared object domains with.

    Global admins are left out: they manage everything anyway, and listing them
    on every object labelled "Global" would only clutter those lists.
    """
    out: Dict[str, List[Mapping]] = defaultdict(list)
    for m in mappings:
        if is_global_domain(m.domain) and m.level == "admin":
            continue
        out[m.domain].append(m)
    return out


def is_person(name: Any) -> bool:
    try:
        from services.creator_stats import is_person as _is_person
    except Exception:  # noqa: BLE001
        return bool(name) and str(name).strip().lower() not in _NOT_A_PERSON
    return _is_person(name)


def is_subscriber(name: Any) -> bool:
    """A subscription's username names someone signed in: a person or an application id, not a placeholder."""
    return bool(name) and str(name).strip().lower() not in _NOT_A_PERSON


def _key(principal: str, ptype: str) -> str:
    return principal.lower() if ptype == USER else principal


def _give(into: Dict[str, Dict[str, str]], principal: str, level: Optional[str], ptype: Optional[str] = None) -> None:
    if not principal or level not in _RANK:
        return
    ptype = ptype or access.infer_type(principal)
    k = _key(principal, ptype)
    held = into.get(k)
    if held is None or _RANK[level] > _RANK[held["level"]]:
        into[k] = {"principal": principal, "principal_type": ptype, "level": level}


def _flag(value: Any) -> bool:
    try:
        return bool(int(value or 0))
    except (TypeError, ValueError):
        return str(value).strip().lower() in ("true", "t", "yes")


def follows_domain(obj: Dict[str, Any]) -> bool:
    """Whether the old checks gave this object's domain mappings any say over it."""
    t = obj.get("object_type")
    if t == WIDGET:
        return True
    if t == APP:
        return _flag(obj.get("is_global"))
    if t == AGENT:
        return (obj.get("visibility") or "personal").strip().lower() == "domain"
    return False


def owner_of(obj: Dict[str, Any]) -> Optional[str]:
    """Who gets MANAGE as its creator, or None. Global views record 'system'; global agents' authors never managed them."""
    t = obj.get("object_type")
    if t == WIDGET:
        name = obj.get("created_by")
    elif t == APP:
        name = None if _flag(obj.get("is_global")) else obj.get("username")
    elif t == AGENT:
        vis = (obj.get("visibility") or "personal").strip().lower()
        name = None if vis == "global" else obj.get("username")
    else:
        name = None
    return name if is_person(name) else None


def domain_of(obj: Dict[str, Any]) -> str:
    return (obj.get("domain") or "").strip() or DEFAULT_DOMAIN


def grants_for(obj: Dict[str, Any], domains: Dict[str, List[Mapping]]) -> Dict[str, Dict[str, str]]:
    """The access list one object description implies, keyed by principal."""
    out: Dict[str, Dict[str, str]] = {}
    if obj.get("object_type") == AGENT and (obj.get("visibility") or "").strip().lower() == "global":
        _give(out, EVERYONE, USE, ALL)
    if follows_domain(obj):
        for m in domains.get(domain_of(obj), []):
            _give(out, m.principal, level_of(m.level))
    owner = owner_of(obj)
    if owner:
        _give(out, owner, MANAGE, USER)
    return out


def all_grants(objects: Iterable[Dict[str, Any]], mappings: Sequence[Mapping],
               subscriptions: Iterable[Tuple[str, str]]) -> Dict[Tuple[str, str], Dict[str, Dict[str, str]]]:
    """Every object's access list. An object described more than once (by several stores) gets the union."""
    domains = by_domain(mappings)
    out: Dict[Tuple[str, str], Dict[str, Dict[str, str]]] = defaultdict(dict)
    for obj in objects:
        target = out[(obj["object_type"], str(obj["object_id"]))]
        for entry in grants_for(obj, domains).values():
            _give(target, entry["principal"], entry["level"], entry["principal_type"])
    for username, view_id in subscriptions:
        if is_subscriber(username) and view_id:
            _give(out[(APP, str(view_id))], username, USE, USER)
    return {k: v for k, v in out.items() if v}


def grant_rows(grants: Dict[Tuple[str, str], Dict[str, Dict[str, str]]]) -> List[Tuple[str, str, str, str, str]]:
    """(object_type, object_id, principal, principal_type, level) rows, in a stable order."""
    rows = []
    for (object_type, object_id), entries in sorted(grants.items()):
        for e in access.sort_entries(entries.values()):
            rows.append((object_type, object_id, e["principal"], e["principal_type"], e["level"]))
    return rows


def descriptor(object_type: str, row: Dict[str, Any], source: str = "") -> Dict[str, Any]:
    """The fields the rules read, from a versioned row or a draft payload."""
    return {
        "object_type": object_type,
        "object_id": str(row.get("id") if row.get("id") is not None else row.get("object_id")),
        "name": row.get("name") or "",
        "domain": row.get("domain"),
        "created_by": row.get("created_by"),
        "username": row.get("username"),
        "is_global": row.get("is_global"),
        "visibility": row.get("visibility"),
        "source": source,
    }


# ------------------------------------------------------------------ the report

def _counts_phrase(counts: Dict[str, int]) -> str:
    return consolidation.counts_phrase(counts)


def _distinct(objects: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One description per (type, id) per domain-relevant shape, so counts aren't doubled across stores."""
    seen: Set[Tuple] = set()
    out = []
    for o in objects:
        k = (o["object_type"], o["object_id"], domain_of(o), follows_domain(o), owner_of(o))
        if k not in seen:
            seen.add(k)
            out.append(o)
    return out


def principal_changes(mappings: Sequence[Mapping], objects: Iterable[Dict[str, Any]],
                      admins: Sequence[Tuple[str, str]]) -> List[Dict[str, Any]]:
    """Per principal, what they can do now that they couldn't, and what they no longer get.

    Only differences are listed. A viewer's USE is what being a viewer gave, so it
    isn't news; what is news is that MANAGE is more than editing, that a domain no
    longer reaches new work, and that a domain admin isn't an app admin.
    """
    objects = _distinct(objects)
    admin_keys = {_key(p, t) for p, t in admins}
    covered: Dict[str, Counter] = defaultdict(Counter)
    owned: Dict[str, Counter] = defaultdict(Counter)
    owner_names: Dict[str, str] = {}
    seen_ids: Set[Tuple[str, str, str]] = set()
    for o in objects:
        ident = (o["object_type"], o["object_id"])
        if follows_domain(o) and (domain_of(o),) + ident not in seen_ids:
            seen_ids.add((domain_of(o),) + ident)
            covered[domain_of(o)][o["object_type"]] += 1
        owner = owner_of(o)
        # Personal views and agents were always their owner's to edit; widgets and
        # domain agents were their domain editors'.
        if owner and (o["object_type"] == WIDGET or follows_domain(o)):
            k = _key(owner, USER)
            owner_names.setdefault(k, owner)
            owned[k][o["object_type"]] += 1

    people: Dict[str, Dict[str, Any]] = {}

    def entry(principal: str, ptype: str) -> Dict[str, Any]:
        k = _key(principal, ptype)
        if k not in people:
            people[k] = {"principal": principal, "principal_type": ptype, "gained": [], "lost": []}
        return people[k]

    for m in sorted(set(mappings)):
        ptype = access.infer_type(m.principal)
        if _key(m.principal, ptype) in admin_keys or is_global_domain(m.domain):
            continue
        e = entry(m.principal, ptype)
        counts = dict(covered.get(m.domain, {}))
        if level_of(m.level) == MANAGE and counts:
            label = (f"Can manage {_counts_phrase(counts)} in {m.domain}: share, publish, archive and delete them, "
                     "not only edit")
            if label not in e["gained"]:
                e["gained"].append(label)
        label = f"New work filed under {m.domain} reaches them only when it is shared (domains are labels now)"
        if label not in e["lost"]:
            e["lost"].append(label)
        if m.level == "admin":
            e["lost"].append(f"The Admin Panel, which being admin of {m.domain} opened; only app administrators have it now")

    for k, counts in owned.items():
        if k in admin_keys:
            continue
        entry(owner_names[k], USER)["gained"].append(
            f"Can manage the {_counts_phrase(dict(counts))} they created, whatever their domain role")

    return sorted((p for p in people.values() if p["gained"] or p["lost"]),
                  key=lambda p: (p["principal_type"] != GROUP, p["principal"].lower()))


def mapping_notes(mappings: Sequence[Mapping], *, seeded: bool, personal_views: int,
                  subscribed_views: int, permissions_off: bool) -> List[str]:
    notes: List[str] = []
    for m in sorted(set(mappings)):
        if is_global_domain(m.domain) and m.level != "admin":
            notes.append(f"'{m.principal}' was mapped to {m.domain} as {m.level}, which only ever covered items filed "
                         f"under the domain '{m.domain}' (only admin meant every domain). That is still all it covers; "
                         "make them an administrator or share with them if they need more.")
    if seeded:
        notes.append("No role mapping made anyone a global admin, so the group 'users' — essentially everyone — was made "
                     "an administrator, as the old default was. Replace it under Administrators with your admin group.")
    elif any(p == FALLBACK_ADMIN[0] and t == FALLBACK_ADMIN[1] for p, t in admins_from(mappings)):
        notes.append("The group 'users' — essentially everyone — was a global admin (the app made it one when nobody "
                     "else was), so it is an administrator now. Replace it under Administrators with your admin group.")
    if personal_views:
        notes.append(f"Links to personal views used to open for anyone holding them. They now open for the owner and "
                     f"for the people who had added them ({subscribed_views} of {personal_views} personal views had "
                     "someone); share a view to give anyone else access.")
    notes.append("Widgets placed on a view now show to everyone who can use the view, whatever the widget's domain.")
    notes.append("Anyone signed in can now build widgets, views and agents; what they build is theirs until they share it.")
    if permissions_off:
        notes.append("Permission checks are switched off (DISABLE_PERMISSION_CHECKS), so everyone is still an "
                     "administrator. These access lists take effect when it is turned off.")
    return notes


def build_report(logs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """GET /api/sharing/migration/report: both steps' logs as one answer."""
    steps = [logs.get(s) for s in STEPS]
    failed = any(s is not None and s.get("status") == consolidation.FAILED for s in steps)
    ran = all(s is not None and s.get("status") in (consolidation.DONE, consolidation.SKIPPED) for s in steps)
    stamps = [s.get("ran_at") for s in steps if s and s.get("ran_at")]
    cons = (logs.get(consolidation.STEP) or {}).get("report") or {}
    acc = (logs.get(STEP) or {}).get("report") or {}
    cs, as_ = cons.get("summary") or {}, acc.get("summary") or {}
    notes: List[str] = []
    labels = {consolidation.STEP: "Bringing Dev and Test work over as drafts", STEP: "Turning role mappings into access lists"}
    for step, s in zip(STEPS, steps):
        if s is not None and s.get("status") == consolidation.FAILED:
            notes.append(f"{labels[step]} failed: {s.get('error') or 'unknown error'}. Nothing from that step was "
                         "saved; fix the cause and press Retry.")
    notes.extend(cons.get("notes") or [])
    notes.extend(acc.get("notes") or [])
    return {
        "ran": ran,
        "failed": failed,
        "ran_at": max(stamps) if stamps else None,
        "summary": {
            "admins": int(as_.get("admins") or 0),
            "grants": int(as_.get("grants") or 0),
            "drafts_created": int(cs.get("drafts_created") or 0),
            "pins_dropped": int(cs.get("pins_dropped") or 0),
            "objects": int(as_.get("objects") or 0),
        },
        "principals": acc.get("principals") or [],
        "notes": notes,
        "steps": [{"step": step, "status": (s or {}).get("status"), "ran_at": (s or {}).get("ran_at"),
                   "error": (s or {}).get("error")} for step, s in zip(STEPS, steps)],
    }


# ------------------------------------------------------------------ snapshots from before sharing

def _body_rows(body: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not body:
        return []
    columns = body.get("columns") or []
    return [dict(zip(columns, r)) for r in body.get("rows") or []]


def _newest(rows: Iterable[Dict[str, Any]], deprecates: bool) -> List[Dict[str, Any]]:
    best: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if deprecates and _flag(r.get("is_deprecated")):
            continue
        k = str(r.get("id"))
        if k not in best or int(r.get("version") or 0) > int(best[k].get("version") or 0):
            best[k] = r
    return list(best.values())


def tables_from_legacy_snapshot(tables: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """`object_permissions` and `app_admins` bodies for a snapshot written before sharing.

    Such a file carries `role_mappings` and no access lists, so importing only its
    content would leave everything in it reachable by admins alone. These are the
    rows this module would have written for that content.
    """
    mappings = mappings_from((r.get("external_role"), r.get("domain"), r.get("permission_level"))
                             for r in _body_rows(tables.get("role_mappings")))
    objects = []
    for object_type, table in consolidation.VERSIONED:
        for row in _newest(_body_rows(tables.get(table)), object_type != APP):
            objects.append(descriptor(object_type, row, "snapshot"))
    subs = [(r.get("username"), r.get("view_id")) for r in _body_rows(tables.get("shared_views"))]
    rows = grant_rows(all_grants(objects, mappings, subs))
    admins = admins_from(mappings)
    return {
        "object_permissions": {
            "columns": ["object_type", "object_id", "principal", "principal_type", "level", "granted_by"],
            "rows": [list(r) + [GRANTED_BY] for r in rows],
        },
        "app_admins": {
            "columns": ["principal", "principal_type", "added_by"],
            "rows": [[p, t, GRANTED_BY] for p, t in admins],
        },
    }


# ------------------------------------------------------------------ database

_DESCRIBE = {
    WIDGET: "SELECT DISTINCT ON (id) id, name, domain, created_by FROM widgets "
            "WHERE COALESCE(is_deprecated, 0) = 0 ORDER BY id, version DESC",
    APP: "SELECT DISTINCT ON (id) id, name, domain, username, is_global FROM dashboard_views ORDER BY id, version DESC",
    AGENT: "SELECT DISTINCT ON (id) id, name, domain, username, visibility FROM agent_profiles "
           "WHERE COALESCE(is_deprecated, 0) = 0 ORDER BY id, version DESC",
}


def _rows(c) -> List[Dict[str, Any]]:
    names = [d[0] for d in c.description]
    return [dict(r) if hasattr(r, "keys") else dict(zip(names, r)) for r in c.fetchall()]


def read_store(conn, source: str, drafts_too: bool = False) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]], List[str]]:
    """(object descriptions, subscriptions, problems) from one store. A missing table is a problem, not a failure."""
    objects: List[Dict[str, Any]] = []
    subs: List[Tuple[str, str]] = []
    problems: List[str] = []
    c = conn.cursor()
    present = consolidation.present_tables(c, ["widgets", "dashboard_views", "agent_profiles", "shared_views", "object_drafts"])
    conn.rollback()
    for object_type, sql in _DESCRIBE.items():
        table = dict(consolidation.VERSIONED)[object_type]
        if table not in present:
            continue
        try:
            c.execute(sql)
            objects.extend(descriptor(object_type, r, source) for r in _rows(c))
        except Exception as e:  # noqa: BLE001 - an older schema lacking a column
            conn.rollback()
            problems.append(f"Could not read {table} in {source}: {e}")
    if "shared_views" in present:
        try:
            c.execute("SELECT username, view_id FROM shared_views")
            subs.extend((r["username"], r["view_id"]) for r in _rows(c))
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            problems.append(f"Could not read shared_views in {source}: {e}")
    if drafts_too and "object_drafts" in present:
        try:
            c.execute("SELECT object_type, object_id, payload FROM object_drafts")
            for r in _rows(c):
                payload = r.get("payload")
                if isinstance(payload, str):
                    payload = json.loads(payload)
                objects.append(descriptor(r["object_type"], {**(payload or {}), "id": r["object_id"]}, f"{source} draft"))
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            problems.append(f"Could not read drafts in {source}: {e}")
    conn.rollback()
    return objects, subs, problems


def _read_mappings(c) -> List[Mapping]:
    c.execute("SELECT to_regclass('role_mappings')")
    if consolidation._first(c.fetchone()) is None:
        return []
    c.execute("SELECT external_role, domain, permission_level FROM role_mappings")
    return mappings_from(c.fetchall())


def _write_admins(c, admins: Sequence[Tuple[str, str]]) -> bool:
    """Add the admins; seed the fallback if that leaves none. Returns whether it seeded."""
    for principal, ptype in admins:
        c.execute(
            "INSERT INTO app_admins (principal, principal_type, added_by) VALUES (%s, %s, %s) "
            "ON CONFLICT (principal) DO NOTHING",
            (principal, ptype, GRANTED_BY),
        )
    c.execute("SELECT COUNT(*) FROM app_admins")
    if int(consolidation._first(c.fetchone()) or 0) > 0:
        return False
    # Lockout prevention, as init_db's seed was: with nobody an admin, nobody can
    # add the first one, and checks switched on would leave the Admin Panel shut.
    logger.warning(
        "No global admin mapping to migrate - making the 'users' group an app administrator so the deployment "
        "is administrable. That is EVERY member of 'users'. Replace it in Admin Panel -> Administrators."
    )
    c.execute(
        "INSERT INTO app_admins (principal, principal_type, added_by) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (*FALLBACK_ADMIN, GRANTED_BY),
    )
    return True


def _write_grants(c, rows: Sequence[Tuple[str, str, str, str, str]], batch: int = 500) -> int:
    from psycopg2.extras import execute_values

    # Never lowers a level: an owner given MANAGE by a create since startup keeps it.
    sql = (
        "INSERT INTO object_permissions (object_type, object_id, principal, principal_type, level, granted_by) "
        "VALUES %s ON CONFLICT (object_type, object_id, principal) DO UPDATE SET level = 'MANAGE' "
        "WHERE EXCLUDED.level = 'MANAGE' AND object_permissions.level <> 'MANAGE'"
    )
    written = 0
    for start in range(0, len(rows), batch):
        chunk = [r + (GRANTED_BY,) for r in rows[start:start + batch]]
        execute_values(c, sql, chunk, page_size=len(chunk))
        written += max(c.rowcount, 0)
    return written


def _gather() -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]], List[str]]:
    from database import content_env, get_db_connection

    objects: List[Dict[str, Any]] = []
    subs: List[Tuple[str, str]] = []
    problems: List[str] = []
    content = get_db_connection(content_env(), pooled=False, physical=True)
    try:
        o, s, p = read_store(content, "the content store", drafts_too=True)
        objects += o
        subs += s
        problems += p
        stores, _ = consolidation.open_legacy_stores(consolidation.store_identity(content))
    finally:
        content.close()
    try:
        for store in stores:
            o, s, p = read_store(store.conn, store.env.capitalize())
            objects += o
            subs += s
            problems += p
    finally:
        consolidation.close_stores(stores)
    return objects, subs, problems


def _migrate(conn) -> Tuple[str, Dict[str, Any]]:
    c = conn.cursor()
    mappings = _read_mappings(c)
    conn.commit()
    objects, subs, problems = _gather()

    grants = all_grants(objects, mappings, subs)
    rows = grant_rows(grants)
    admins = admins_from(mappings)
    try:
        seeded = _write_admins(c, admins)
        written = _write_grants(c, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    access._forget_admins()

    personal = {o["object_id"] for o in objects if o["object_type"] == APP and not _flag(o.get("is_global"))}
    subscribed = {str(v) for u, v in subs if is_subscriber(u) and str(v) in personal}
    report = {
        "summary": {
            "admins": len(admins) + (1 if seeded else 0),
            "grants": written,
            "objects": len(grants),
            "mappings": len(mappings),
        },
        "admins": [{"principal": p, "principal_type": t} for p, t in admins] + (
            [{"principal": FALLBACK_ADMIN[0], "principal_type": FALLBACK_ADMIN[1]}] if seeded else []),
        "principals": principal_changes(mappings, objects, admins),
        "notes": mapping_notes(mappings, seeded=seeded, personal_views=len(personal),
                               subscribed_views=len(subscribed),
                               permissions_off=access.permissions_disabled()) + problems,
    }
    logger.warning("Migrated %s role mappings into %s grants on %s objects and %s admins",
                   len(mappings), written, len(grants), report["summary"]["admins"])
    return consolidation.DONE, report


def _admins_only(conn) -> None:
    """After a failed run: at least keep someone able to open the Admin Panel and press Retry."""
    c = conn.cursor()
    _write_admins(c, admins_from(_read_mappings(c)))
    conn.commit()
    access._forget_admins()


def run_once() -> Optional[Dict[str, Any]]:
    """Write the access lists the role mappings implied, once per deployment. Never raises."""
    return consolidation.run_step(STEP, _migrate, on_failure=_admins_only)


def retry() -> Dict[str, Any]:
    """Clear failed steps and run both again, in startup's order. Finished steps are left as they are."""
    consolidation.clear_failures(STEPS)
    consolidation.run_once()
    run_once()
    return build_report(consolidation.read_logs())
