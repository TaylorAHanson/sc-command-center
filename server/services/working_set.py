"""The sidebar's working set (`GET /api/apps/`): what one person starred, opened
lately and made, and how many views are new to them. Light rows, never a spec.

Built on `view_signals.home`, which reads the view catalog, then corrected for
what the catalog doesn't hold or only learns on its next drain:

- A manager sees their draft's name, as `GET /api/apps/{ref}` shows it to them;
  the catalog holds the newest published version.
- An archived view leaves at once rather than a drain later.
- A view the caller closed stays out of Recent until they open it again
  (`sidebar_hidden`, compared with their last open).
- Each row says how widely it is shared, for the sidebar's access icon.

Rows are trimmed to what the sidebar needs, so the payload is bounded by the
list caps (15 favorites, 20 recent, 50 of the caller's own), never by the
deployment. The sidebar draws only favorites and recent; the caller's own views
give the My views count and the view that opens when nothing was opened lately.
Until the catalog has finished its first build (the first start after an
upgrade, or a worker that couldn't create its tables), those are read from the
source tables instead, so nobody's views look deleted meanwhile.
"""
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from services import access, app_links, drafts, view_catalog, view_signals

logger = logging.getLogger(__name__)

APP, MANAGE = access.APP, access.MANAGE

#: What the sidebar draws of a Discover light row; `sharing` is added here.
FIELDS = ("id", "ref", "name", "owner", "domain", "presentation", "updated_at", "access", "state", "favorite",
          "last_opened_at")

EMPTY = {"favorites": [], "recent": [], "mine": [], "mine_total": 0, "new_for_you_count": 0}

# Once the first build has finished it stays finished: a format rebuild keeps
# answering from the old rows, so there is no need to ask again.
_built = False


def _me(who: access.Caller) -> str:
    return (who.username or "").strip().lower()


def _row(r: Dict[str, Any], held: Optional[Dict[str, Any]], facts: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = {k: r.get(k) for k in FIELDS}
    out["presentation"] = out["presentation"] or "workspace"
    out["favorite"] = bool(out["favorite"])
    if out["access"] != MANAGE or not out["state"]:
        out.pop("state")
    if held and out["access"] == MANAGE:
        out["name"] = (held.get("name") or "").strip() or out["name"]
        if held.get("domain") is not None:
            out["domain"] = held["domain"]
        if held.get("updated_at"):
            out["updated_at"] = view_catalog.iso(held["updated_at"])
    out["sharing"] = (facts or {}).get("sharing")
    return out


def overlay(home: Dict[str, Any], *, held: Optional[Dict[str, Dict[str, Any]]] = None, archived: Iterable[str] = (),
            closed: Iterable[str] = (), facts: Optional[Dict[str, Dict[str, Any]]] = None,
            favorites_total: Optional[int] = None) -> Dict[str, Any]:
    """`home`'s lists as the sidebar draws them; see the note at the top.

    `held` is the draft over each row (name, domain, updated_at), `closed` the
    ids to leave out of Recent, `facts` what `access.acl_facts` says of each.
    """
    held, facts, archived, closed = held or {}, facts or {}, set(archived), set(closed)

    def rows(listed: Optional[Sequence[Dict[str, Any]]], drop: Iterable[str] = ()) -> List[Dict[str, Any]]:
        gone = archived | set(drop)
        return [_row(r, held.get(r["id"]), facts.get(r["id"])) for r in listed or [] if r["id"] not in gone]

    favorites = rows(home.get("favorites"))
    # A draft saved since the last publish is the newest change, so it decides the order.
    mine = sorted(rows(home.get("mine")), key=lambda r: (r.get("updated_at") or "", r["id"]), reverse=True)
    left = sum(1 for r in home.get("mine") or [] if r["id"] in archived)
    return {
        "favorites": favorites,
        "favorites_total": max(int(favorites_total or 0), len(favorites)),
        "recent": rows(home.get("recent"), closed),
        "mine": mine,
        "mine_total": max(int(home.get("mine_total") or 0) - left, len(mine)),
        "new_for_you_count": int(home.get("new_for_you_count") or 0),
    }


def _ids(home: Dict[str, Any]) -> List[str]:
    return list(dict.fromkeys(r["id"] for key in ("favorites", "recent", "mine") for r in home.get(key) or []))


def _catalog_built(c) -> bool:
    global _built
    if not _built:
        _built = bool(view_catalog._state(c, "build").get("built_at"))
    return _built


def own_views(c, who: access.Caller, limit: int = view_signals.HOME_MINE) -> Tuple[List[Dict[str, Any]], int]:
    """The caller's own views, newest change first, read from their sources.

    Only grants that name the caller are read, so this is bounded by what one
    person was given by name, never by what is shared with everyone.
    """
    me = _me(who)
    if not me:
        return [], 0
    conn = view_catalog._settings()
    try:
        sc = conn.cursor()
        sc.execute("SELECT DISTINCT object_id FROM object_permissions WHERE object_type = %s "
                   "AND principal_type = %s AND LOWER(principal) = %s AND level = %s", (APP, access.USER, me, MANAGE))
        ids = [r[0] for r in sc.fetchall()]
        conn.commit()
    finally:
        conn.close()
    facts = access.acl_facts(APP, ids)
    ids = [i for i in ids if (facts.get(i, {}).get("owner") or "").lower() == me]
    if not ids:
        return [], 0
    c.execute("SELECT id FROM archived_views WHERE id = ANY(%s)", (ids,))
    archived = {r[0] for r in c.fetchall()}
    ids = [i for i in ids if i not in archived]
    c.execute("SELECT dv.id, dv.name, dv.domain, dv.timestamp AS updated_at FROM dashboard_views dv JOIN ("
              "SELECT id, MAX(version) AS version FROM dashboard_views WHERE id = ANY(%s) GROUP BY id"
              ") latest ON dv.id = latest.id AND dv.version = latest.version", (ids,))
    published = {r["id"]: r for r in view_catalog._rows(c)}
    held = _held(c, ids)
    links = app_links.current(c, list(published))
    out = []
    for i in ids:
        pub, draft = published.get(i), held.get(i)
        if not pub and not draft:
            continue
        name = ((draft or {}).get("name") or (pub or {}).get("name") or "").strip() or "Untitled view"
        out.append({
            "id": i, "ref": links.get(i) or view_catalog.fallback_ref(i, name), "name": name,
            "owner": who.username, "domain": (draft or pub).get("domain"), "presentation": "workspace",
            "updated_at": view_catalog.iso((draft or pub).get("updated_at")), "access": MANAGE,
            "state": drafts.state_of(draft is not None, 1 if pub else None), "favorite": False,
            "last_opened_at": None,
        })
    out.sort(key=lambda r: (r.get("updated_at") or "", r["id"]), reverse=True)
    return out[:limit], len(out)


def _held(c, ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """The draft's name, domain and last save for each id that has one; never the spec."""
    if not ids:
        return {}
    c.execute("SELECT object_id AS id, payload->>'name' AS name, payload->>'domain' AS domain, updated_at "
              "FROM object_drafts WHERE object_type = %s AND object_id = ANY(%s)", (APP, list(ids)))
    return {r["id"]: r for r in view_catalog._rows(c)}


def read(who: access.Caller) -> Dict[str, Any]:
    """`GET /api/apps/`."""
    ready = view_catalog.enabled()
    home: Optional[Dict[str, Any]] = None
    if ready:
        try:
            home = view_signals.home(who)
        except Exception as e:  # noqa: BLE001 - My views can still be read from the source tables
            logger.warning("The sidebar couldn't read the view catalog: %s", e)
    conn = view_catalog._content()
    try:
        c = conn.cursor()
        if home is None or not _catalog_built(c):
            mine, total = own_views(c, who)
            home = {**EMPTY, **(home or {}), "mine": mine, "mine_total": total}
        ids = _ids(home)
        managed = [r["id"] for key in ("favorites", "recent", "mine") for r in home.get(key) or []
                   if r.get("access") == MANAGE]
        held = _held(c, list(dict.fromkeys(managed)))
        archived: set = set()
        closed: set = set()
        favorites_total = None
        if ids:
            c.execute("SELECT id FROM archived_views WHERE id = ANY(%s)", (ids,))
            archived = {r[0] for r in c.fetchall()}
        recent = [r["id"] for r in home.get("recent") or []]
        if ready and recent:
            c.execute("SELECT h.app_id FROM sidebar_hidden h WHERE h.username = %(user)s AND h.app_id = ANY(%(ids)s) "
                      "AND NOT EXISTS (SELECT 1 FROM view_visits v WHERE v.username = %(me)s "
                      "AND v.app_id = h.app_id AND v.last_opened_at > h.timestamp)",
                      {"user": who.username, "me": _me(who), "ids": recent})
            closed = {r[0] for r in c.fetchall()}
        if ready:
            c.execute("SELECT COUNT(*) FROM user_favorites WHERE username = %s", (_me(who),))
            favorites_total = int(c.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    return overlay(home, held=held, archived=archived, closed=closed, facts=access.acl_facts(APP, ids),
                   favorites_total=favorites_total)
