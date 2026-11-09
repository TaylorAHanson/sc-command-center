"""Who may use or manage a view, widget or agent: direct sharing, as dashboards do.

Every object has an access list: entries granting **MANAGE** or **USE** to a
user, a group, or everyone (`*`). The highest level a caller holds — directly,
through any of their groups, or through `*` — is theirs. App admins
(`app_admins`) hold MANAGE on everything. This replaced domain role mappings,
where access followed a label on the object rather than the object itself.

The tables live in the settings schema (`settings_env()`), not the content
store: who may do what is a fact about the deployment, the same as the settings,
and keyed by object id it needs nothing from the versioned rows. That also means
an ACL write is a separate transaction from the content write it accompanies,
which is why `grant_owner` is called after the content commit — a failure there
leaves an object only admins can reach, never one the wrong person can.

Groups are matched on their SCIM display name exactly, as role mappings were;
users case-insensitively, because SCIM is not consistent about case
(`creator_stats.same_person`). Names are free text: listing workspace groups
needs the `scim` scope, which a deployed App can't request, and doing it as the
service principal would widen what that identity is used for. `known_principals`
— everyone who has signed in, and their groups — is what the share dialog's
typeahead offers instead.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from fastapi import HTTPException

from services import caller_identity

logger = logging.getLogger(__name__)

APP, WIDGET, AGENT = "app", "widget", "agent"
TYPES = (APP, WIDGET, AGENT)
MANAGE, USE = "MANAGE", "USE"
LEVELS = (MANAGE, USE)
EVERYONE = "*"
USER, GROUP, ALL = "user", "group", "all"
PRINCIPAL_TYPES = (USER, GROUP, ALL)

_RANK = {USE: 1, MANAGE: 2}
_NOUNS = {APP: "view", WIDGET: "widget", AGENT: "agent"}
_MAX_PRINCIPAL = 256
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


@dataclass(frozen=True)
class Caller:
    username: str
    groups: Tuple[str, ...]
    is_admin: bool


def permissions_disabled() -> bool:
    """TEMPORARY demo kill-switch. When DISABLE_PERMISSION_CHECKS is truthy, every
    caller is an app admin. Set via databricks.yml (var.disable_permission_checks).
    MUST be turned off after the demo — it removes all access control."""
    return os.environ.get("DISABLE_PERMISSION_CHECKS", "").strip().lower() in ("1", "true", "yes", "on")


def _bypass() -> bool:
    return permissions_disabled() or os.environ.get("DEV_MODE", "").strip().lower() == "true"


# --------------------------------------------------------------------- pure rules

def infer_type(principal: str) -> str:
    """What a bare name most likely is: `*`, a user (an address or an application id), or a group."""
    p = (principal or "").strip()
    if p == EVERYONE:
        return ALL
    if "@" in p or _UUID.match(p):
        return USER
    return GROUP


def matches(entry_principal: str, entry_type: str, username: str, groups: Iterable[str]) -> bool:
    if entry_type == ALL or entry_principal == EVERYONE:
        return True
    if entry_type == USER:
        return bool(username) and entry_principal.strip().lower() == username.strip().lower()
    return entry_principal in set(groups)


def best_level(entries: Iterable[Dict[str, Any]], username: str, groups: Sequence[str]) -> Optional[str]:
    """The highest level any entry grants this caller, or None."""
    best: Optional[str] = None
    for e in entries:
        level = e.get("level")
        if level not in _RANK:
            continue
        if not matches(e.get("principal") or "", e.get("principal_type") or "", username, groups):
            continue
        if best is None or _RANK[level] > _RANK[best]:
            best = level
    return best


def normalise_entries(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Validated, de-duplicated entries; the highest level wins for a principal named twice.

    Raises 400 with a sentence a person can act on, since this is what the share
    dialog shows.
    """
    out: Dict[str, Dict[str, str]] = {}
    for raw in entries or []:
        principal = str((raw or {}).get("principal") or "").strip()
        if not principal:
            raise HTTPException(status_code=400, detail="Every entry needs a user or group name.")
        if len(principal) > _MAX_PRINCIPAL:
            raise HTTPException(status_code=400, detail="That name is too long to be a user or group.")
        level = str(raw.get("level") or "").strip().upper()
        if level not in _RANK:
            raise HTTPException(status_code=400, detail="Access must be Can use or Can manage.")
        ptype = str(raw.get("principal_type") or "").strip().lower() or infer_type(principal)
        if principal == EVERYONE:
            ptype = ALL
        if ptype not in PRINCIPAL_TYPES or (ptype == ALL) != (principal == EVERYONE):
            raise HTTPException(status_code=400, detail=f"'{principal}' isn't a user, a group or everyone.")
        key = principal.lower() if ptype == USER else principal
        held = out.get(key)
        if held is None or _RANK[level] > _RANK[held["level"]]:
            out[key] = {"principal": principal, "principal_type": ptype, "level": level}
    return list(out.values())


def check_keeps_a_manager(entries: Sequence[Dict[str, str]], who: Caller) -> None:
    """Refuse a list nobody could manage, unless an admin (who always can) wrote it."""
    if who.is_admin:
        return
    if not any(e["level"] == MANAGE for e in entries):
        raise HTTPException(
            status_code=400,
            detail="Keep at least one person or group with Can manage, or nobody but an admin can change this again.",
        )


def sort_entries(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    order = {USER: 0, GROUP: 1, ALL: 2}
    return sorted(entries, key=lambda e: (-_RANK.get(e.get("level"), 0), order.get(e.get("principal_type"), 3),
                                          (e.get("principal") or "").lower()))


# --------------------------------------------------------------------- storage

def _conn():
    from database import get_db_connection
    from services.settings_store import settings_env

    return get_db_connection(settings_env(), physical=True)


def _rows(c) -> List[Dict[str, Any]]:
    names = [d[0] for d in c.description]
    return [dict(zip(names, r)) if not hasattr(r, "keys") else dict(r) for r in c.fetchall()]


def _timestamp(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _match_sql(who: Caller) -> Tuple[str, list]:
    return (
        "(principal = '*' OR (principal_type = 'user' AND LOWER(principal) = LOWER(%s))"
        " OR (principal_type = 'group' AND principal = ANY(%s)))",
        [who.username or "", list(who.groups)],
    )


_admins_cache: Dict[str, Any] = {"at": 0.0, "rows": None}
_admins_lock = threading.Lock()
_ADMINS_TTL = 15.0


def _admin_rows(force: bool = False) -> List[Dict[str, Any]]:
    now = time.monotonic()
    with _admins_lock:
        if not force and _admins_cache["rows"] is not None and now - _admins_cache["at"] < _ADMINS_TTL:
            return _admins_cache["rows"]
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT principal, principal_type, added_by, added_at FROM app_admins ORDER BY principal")
        rows = _rows(c)
        conn.commit()
    finally:
        conn.close()
    with _admins_lock:
        _admins_cache.update(at=now, rows=rows)
    return rows


def _forget_admins() -> None:
    with _admins_lock:
        _admins_cache.update(at=0.0, rows=None)


def is_admin(username: str, groups: Sequence[str]) -> bool:
    return any(matches(r["principal"], r["principal_type"], username, groups) for r in _admin_rows())


_seen: Dict[str, float] = {}
_seen_lock = threading.Lock()
_SEEN_EVERY = 600.0


def _record(username: str, groups: Sequence[str]) -> None:
    """Remember a signed-in caller and their groups for the share dialog's typeahead.

    At most once per caller per ten minutes per worker, and never allowed to fail
    the request it rides on.
    """
    if not username or username == "unknown":
        return
    now = time.monotonic()
    with _seen_lock:
        if now - _seen.get(username, -_SEEN_EVERY) < _SEEN_EVERY:
            return
        _seen[username] = now
    try:
        conn = _conn()
        try:
            c = conn.cursor()
            for principal, ptype in [(username, USER)] + [(g, GROUP) for g in groups if g]:
                c.execute(
                    "INSERT INTO known_principals (principal, principal_type, last_seen) VALUES (%s, %s, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (principal) DO UPDATE SET last_seen = CURRENT_TIMESTAMP",
                    (principal, ptype),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.info("Could not record %s as a known principal: %s", username, e)


def caller(w: Any) -> Caller:
    """The caller's identity, groups and whether they are an app admin.

    Bypassing the checks never bypasses identity: the username is still the real
    one, because rows all over the app are owned by it.
    """
    if isinstance(w, Caller):
        return w
    username = caller_identity.username(w)
    groups = tuple(caller_identity.entitlements(w)) if w is not None else ()
    _record(username, groups)
    if _bypass():
        return Caller(username, groups, True)
    try:
        admin = is_admin(username, groups)
    except Exception as e:  # noqa: BLE001 - an unreadable admin list grants nothing
        logger.warning("Could not read app admins: %s", e)
        admin = False
    return Caller(username, groups, admin)


def level_for(who: Caller, object_type: str, object_id: str) -> Optional[str]:
    if who.is_admin:
        return MANAGE
    return levels_for(who, object_type, [object_id]).get(object_id)


def levels_for(who: Caller, object_type: str, ids: Iterable[str]) -> Dict[str, str]:
    """The caller's level on each of ``ids`` that they hold one on."""
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    if who.is_admin:
        return {i: MANAGE for i in ids}
    match, params = _match_sql(who)
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            f"SELECT object_id, level FROM object_permissions WHERE object_type = %s AND object_id = ANY(%s) AND {match}",
            [object_type, ids, *params],
        )
        out: Dict[str, str] = {}
        for r in _rows(c):
            held = out.get(r["object_id"])
            if held is None or _RANK.get(r["level"], 0) > _RANK[held]:
                out[r["object_id"]] = r["level"]
        conn.commit()
        return out
    finally:
        conn.close()


def grants_for(who: Caller, object_type: str) -> Dict[str, str]:
    """Every object of this type the caller holds a level on (not admin-implied ones)."""
    match, params = _match_sql(who)
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(f"SELECT object_id, level FROM object_permissions WHERE object_type = %s AND {match}",
                  [object_type, *params])
        out: Dict[str, str] = {}
        for r in _rows(c):
            held = out.get(r["object_id"])
            if held is None or _RANK.get(r["level"], 0) > _RANK[held]:
                out[r["object_id"]] = r["level"]
        conn.commit()
        return out
    finally:
        conn.close()


def visible_ids(who: Caller, object_type: str) -> Optional[Set[str]]:
    """Ids the caller can at least use; None means every object (an admin)."""
    if who.is_admin:
        return None
    return set(grants_for(who, object_type))


def require(who: Caller, object_type: str, object_id: str, level: str = USE, not_found: str = "Not found") -> str:
    """The caller's level, or 404 if they have none, or 403 if they can use but must manage.

    No access at all reads as missing, so an id or link never confirms that
    something exists to someone it isn't shared with.
    """
    held = level_for(who, object_type, object_id)
    if held is None:
        raise HTTPException(status_code=404, detail=not_found)
    if level == MANAGE and held != MANAGE:
        noun = _NOUNS.get(object_type, "item")
        raise HTTPException(status_code=403, detail=f"You need Can manage on this {noun} to do that.")
    return held


def require_app_admin(w: Any) -> Caller:
    who = caller(w)
    if not who.is_admin:
        raise HTTPException(status_code=403, detail="Only app administrators can do that.")
    return who


def grant_owner(object_type: str, object_id: str, username: str) -> None:
    """Give the creator Can manage. Idempotent; never lowers a level."""
    if not username or username == "unknown":
        return
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO object_permissions (object_type, object_id, principal, principal_type, level, granted_by) "
            "VALUES (%s, %s, %s, 'user', 'MANAGE', %s) "
            "ON CONFLICT (object_type, object_id, principal) DO UPDATE SET level = 'MANAGE'",
            (object_type, object_id, username, username),
        )
        conn.commit()
    finally:
        conn.close()


def get_acl(object_type: str, object_id: str) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT principal, principal_type, level, granted_by, granted_at FROM object_permissions "
            "WHERE object_type = %s AND object_id = %s",
            (object_type, object_id),
        )
        rows = _rows(c)
        conn.commit()
    finally:
        conn.close()
    return sort_entries({**r, "granted_at": _timestamp(r.get("granted_at"))} for r in rows)


def owner_of(object_type: str, object_id: str) -> Optional[str]:
    """Who to show as the owner: the first person given Can manage, which is the creator.

    Display only. Ownership confers nothing that the access list doesn't, so
    transferring an object is just sharing it and removing yourself.
    """
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT principal FROM object_permissions WHERE object_type = %s AND object_id = %s "
            "AND principal_type = 'user' AND level = 'MANAGE' ORDER BY granted_at, principal LIMIT 1",
            (object_type, object_id),
        )
        rows = _rows(c)
        conn.commit()
    finally:
        conn.close()
    return rows[0]["principal"] if rows else None


def replace_acl(who: Caller, object_type: str, object_id: str, entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Make the access list exactly ``entries``. Needs MANAGE; keeps who granted what."""
    if object_type not in TYPES:
        raise HTTPException(status_code=400, detail="Unknown kind of object.")
    require(who, object_type, object_id, MANAGE)
    wanted = normalise_entries(entries)
    check_keeps_a_manager(wanted, who)

    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT principal, principal_type, level, granted_by, granted_at FROM object_permissions "
            "WHERE object_type = %s AND object_id = %s",
            (object_type, object_id),
        )
        before = {(r["principal"], r["level"]): r for r in _rows(c)}
        c.execute("DELETE FROM object_permissions WHERE object_type = %s AND object_id = %s", (object_type, object_id))
        for e in wanted:
            kept = before.get((e["principal"], e["level"]))
            c.execute(
                "INSERT INTO object_permissions (object_type, object_id, principal, principal_type, level, granted_by, granted_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP))",
                (object_type, object_id, e["principal"], e["principal_type"], e["level"],
                 kept["granted_by"] if kept else who.username, kept["granted_at"] if kept else None),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_acl(object_type, object_id)


def delete_acl(object_type: str, object_id: str) -> None:
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM object_permissions WHERE object_type = %s AND object_id = %s", (object_type, object_id))
        conn.commit()
    finally:
        conn.close()


def acl_summaries(object_type: Optional[str] = None) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Per object: how many entries, and whether everyone can use it. For listings."""
    conn = _conn()
    try:
        c = conn.cursor()
        sql = ("SELECT object_type, object_id, COUNT(*) AS entries, BOOL_OR(principal = '*') AS everyone "
               "FROM object_permissions")
        params: list = []
        if object_type:
            sql += " WHERE object_type = %s"
            params.append(object_type)
        c.execute(sql + " GROUP BY object_type, object_id", params or None)
        rows = _rows(c)
        conn.commit()
    finally:
        conn.close()
    return {(r["object_type"], r["object_id"]): {"entries": int(r["entries"]), "everyone": bool(r["everyone"])}
            for r in rows}


def acl_facts(object_type: str, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Per id: the owner (as `owner_of` defines it) and the access summary, in one read.

    For listings, which would otherwise pay a query per row. Ids with no access
    list are left out; a failed read returns {} so a listing degrades to showing
    less rather than failing.
    """
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    try:
        conn = _conn()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT object_id, principal, principal_type, level FROM object_permissions "
                "WHERE object_type = %s AND object_id = ANY(%s) ORDER BY granted_at, principal",
                (object_type, ids),
            )
            rows = _rows(c)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("Couldn't read access lists for %s: %s", object_type, e)
        return {}
    by_id: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_id.setdefault(r["object_id"], []).append(r)
    out: Dict[str, Dict[str, Any]] = {}
    for object_id, entries in by_id.items():
        owner = next((e["principal"] for e in entries if e["principal_type"] == USER and e["level"] == MANAGE), None)
        out[object_id] = {"owner": owner, "sharing": summary_of(entries, owner)}
    return out


def summary_of(entries: Iterable[Dict[str, Any]], owner: Optional[str] = None) -> str:
    """'everyone', 'shared' (anyone besides the owner) or 'private'. Mirrors `accessSummary` in src/sharing.ts."""
    entries = list(entries)
    if any(e.get("principal") == EVERYONE for e in entries):
        return "everyone"
    others = [e for e in entries
              if not (e.get("principal_type") == USER and owner and (e.get("principal") or "").lower() == owner.lower())]
    return "shared" if others else "private"


# --------------------------------------------------------------------- admins

def list_admins() -> List[Dict[str, Any]]:
    return [{**r, "added_at": _timestamp(r.get("added_at"))} for r in _admin_rows(force=True)]


def add_admin(who: Caller, principal: str, principal_type: Optional[str] = None) -> List[Dict[str, Any]]:
    entry = normalise_entries([{"principal": principal, "principal_type": principal_type, "level": MANAGE}])[0]
    if entry["principal_type"] == ALL:
        raise HTTPException(status_code=400, detail="Name a user or a group; everyone can't be an administrator.")
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO app_admins (principal, principal_type, added_by) VALUES (%s, %s, %s) "
            "ON CONFLICT (principal) DO UPDATE SET principal_type = EXCLUDED.principal_type",
            (entry["principal"], entry["principal_type"], who.username),
        )
        conn.commit()
    finally:
        conn.close()
    _forget_admins()
    return list_admins()


def remove_admin(principal: str) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM app_admins")
        row = c.fetchone()
        count = row[0] if not hasattr(row, "keys") else list(row.values())[0]
        c.execute("SELECT 1 FROM app_admins WHERE principal = %s", (principal,))
        if c.fetchone() is None:
            raise HTTPException(status_code=404, detail="That administrator isn't on the list.")
        if count <= 1:
            raise HTTPException(status_code=400, detail="Add another administrator before removing the last one.")
        c.execute("DELETE FROM app_admins WHERE principal = %s", (principal,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _forget_admins()
    return list_admins()


# --------------------------------------------------------------------- typeahead

def search_principals(who: Caller, q: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Names to offer in the share dialog: the caller's own groups first, then anyone seen."""
    q = (q or "").strip()
    needle = q.lower()
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def add(principal: str, ptype: str, mine: bool) -> None:
        key = principal.lower() if ptype == USER else principal
        if key in seen or len(out) >= limit:
            return
        seen.add(key)
        out.append({"principal": principal, "principal_type": ptype, "mine": mine})

    if needle and ("everyone".startswith(needle) or "every" in needle):
        add(EVERYONE, ALL, False)
    for g in who.groups:
        if not needle or needle in g.lower():
            add(g, GROUP, True)

    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT principal, principal_type FROM (
                SELECT principal, principal_type FROM known_principals
                UNION SELECT principal, principal_type FROM object_permissions WHERE principal <> '*'
                UNION SELECT principal, principal_type FROM app_admins
            ) p
            WHERE principal ILIKE %s
            ORDER BY CASE WHEN principal ILIKE %s THEN 0 ELSE 1 END, principal_type, principal
            LIMIT %s
            """,
            (f"%{q}%", f"{q}%", limit * 2),
        )
        for r in _rows(c):
            add(r["principal"], r["principal_type"], False)
        conn.commit()
    except Exception as e:  # noqa: BLE001 - suggestions are a convenience; free text still works
        conn.rollback()
        logger.info("Principal search failed: %s", e)
    finally:
        conn.close()
    return out
