"""Per-person signals for Discover: opens, favorites, hidden views, curation,
and what is new for you.

Popularity never needs a count-distinct over millions of rows: `view_visits`
holds one row per person, view and day, and `view_daily` gains a viewer only
when that row is first inserted. The rollup folds `view_daily` into the
catalog every fifteen minutes. Visits are pruned after 35 days, by which time
the catalog's `last_opened_at` has absorbed them.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from fastapi import HTTPException

from services import access, view_catalog

logger = logging.getLogger(__name__)

APP = access.APP

RETENTION_DAYS = 35
NEW_FOR_YOU_DAYS = 14
HOME_FAVORITES = 15
# The sidebar shows the five latest that aren't favorites, and every favorite
# can be among the views opened last.
HOME_RECENT = HOME_FAVORITES + 5
HOME_MINE = 50
PRUNE_BATCH = 10_000
MAX_ID = 200
MAX_FEATURED_POSITION = 10_000

_content = view_catalog._content
_settings = view_catalog._settings
_rows = view_catalog._rows


def _me(who: access.Caller) -> str:
    return (who.username or "").strip().lower()


# --------------------------------------------------------------------- visits

#: One statement: the visit upsert, and a viewer for the day only when this was
#: the person's first open of the view today (`xmax = 0` means inserted).
VISIT_SQL = """
WITH v AS (
    INSERT INTO view_visits (username, app_id, day) VALUES (%(u)s, %(a)s, CURRENT_DATE)
    ON CONFLICT (username, app_id, day)
    DO UPDATE SET last_opened_at = now(), opens = view_visits.opens + 1
    RETURNING (xmax = 0) AS first
)
INSERT INTO view_daily (app_id, day, viewers)
SELECT %(a)s, CURRENT_DATE, 1 FROM v WHERE v.first
ON CONFLICT (app_id, day) DO UPDATE SET viewers = view_daily.viewers + 1
"""


def record_visit(username: str, app_id: str) -> None:
    """Count an open. Never raises: a lost visit costs a statistic, not a page."""
    user = (username or "").strip().lower()
    if not view_catalog.enabled() or not user or user == "unknown" or not app_id or len(app_id) > MAX_ID:
        return
    conn = None
    try:
        conn = _content()
        conn.rollback()
        conn.autocommit = True
        conn.cursor().execute(VISIT_SQL, {"u": user, "a": app_id})
    except Exception as e:  # noqa: BLE001
        logger.info("Could not record an open of %s: %s", app_id, e)
    finally:
        if conn is not None:
            try:
                conn.autocommit = False
            except Exception:  # noqa: BLE001
                pass
            conn.close()


ROLLUP_SQL = """
WITH d AS (
    SELECT app_id,
           SUM(viewers) FILTER (WHERE day > CURRENT_DATE - 30) AS v30,
           SUM(viewers) FILTER (WHERE day > CURRENT_DATE - 7) AS v7,
           SUM(viewers) FILTER (WHERE day <= CURRENT_DATE - 7 AND day > CURRENT_DATE - 14) AS p7
      FROM view_daily
     WHERE day > CURRENT_DATE - 30
     GROUP BY app_id
), fav AS (
    SELECT app_id, COUNT(*) AS n FROM user_favorites GROUP BY app_id
), opened AS (
    SELECT app_id, MAX(last_opened_at) AS at FROM view_visits WHERE last_opened_at > %(since)s GROUP BY app_id
), fresh AS (
    SELECT vc.id,
           COALESCE(d.v30, 0)::int AS v30,
           COALESCE(d.v7, 0)::int AS v7,
           ROUND((COALESCE(d.v7, 0) - COALESCE(d.p7, 0))::numeric / (COALESCE(d.p7, 0) + 5), 3)::real AS trend,
           COALESCE(fav.n, 0)::int AS favs,
           GREATEST(vc.last_opened_at, opened.at) AS opened_at
      FROM view_catalog vc
      LEFT JOIN d ON d.app_id = vc.id
      LEFT JOIN fav ON fav.app_id = vc.id
      LEFT JOIN opened ON opened.app_id = vc.id
)
UPDATE view_catalog vc
   SET viewers_30d = f.v30, viewers_7d = f.v7, trend = f.trend, favorites = f.favs, last_opened_at = f.opened_at
  FROM fresh f
 WHERE vc.id = f.id
   AND (vc.viewers_30d, vc.viewers_7d, vc.trend, vc.favorites, vc.last_opened_at)
       IS DISTINCT FROM (f.v30, f.v7, f.trend, f.favs, f.opened_at)
"""


def trend(this_week: int, last_week: int) -> float:
    """The rollup's trend, for tests and the probe: growth over last week,
    damped so 3 viewers after 0 doesn't outrank 200 after 100."""
    return round((this_week - last_week) / (last_week + 5), 3)


def rollup_job() -> None:
    """Fold daily viewers, favorites and last opens into the catalog. Only
    rows whose numbers changed are written."""
    if not view_catalog.enabled():
        return
    conn = _content()
    try:
        c = conn.cursor()
        state = view_catalog._state(c, "stats")
        c.execute("SELECT now()")
        now = c.fetchone()[0]
        # An hour's overlap covers visits whose transaction committed after the
        # previous rollup read the clock.
        try:
            since = _parse(state["opened_through"]) - timedelta(hours=1)
        except (KeyError, TypeError, ValueError):
            since = "-infinity"
        c.execute(ROLLUP_SQL, {"since": since})
        changed = c.rowcount
        view_catalog.set_state(c, "stats", {"at": now, "opened_through": now, "changed": changed})
        conn.commit()
    finally:
        conn.close()


def _parse(stamp: Any) -> datetime:
    then = datetime.fromisoformat(str(stamp))
    return then if then.tzinfo else then.replace(tzinfo=timezone.utc)


def prune_job() -> None:
    """Drop visits and daily counts older than the 35 days anything reads."""
    if not view_catalog.enabled():
        return
    conn = _content()
    try:
        c = conn.cursor()
        for table in ("view_visits", "view_daily"):
            for _ in range(100):
                c.execute(f"DELETE FROM {table} WHERE ctid IN (SELECT ctid FROM {table} "
                          "WHERE day < CURRENT_DATE - %s LIMIT %s)", (RETENTION_DAYS, PRUNE_BATCH))
                deleted = c.rowcount
                conn.commit()
                if deleted < PRUNE_BATCH:
                    break
    finally:
        conn.close()


# ------------------------------------------------------------ favorites, hidden

def favorite_ids(c, who: access.Caller, limit: Optional[int] = None) -> List[str]:
    c.execute("SELECT app_id FROM user_favorites WHERE username = %s ORDER BY position, created_at, app_id"
              + (" LIMIT %s" if limit else ""), (_me(who), limit) if limit else (_me(who),))
    return [r[0] for r in c.fetchall()]


def favorites(who: access.Caller) -> List[Dict[str, Any]]:
    conn = _content()
    try:
        c = conn.cursor()
        rows = view_catalog.light_rows(c, who, favorite_ids(c, who))
        conn.commit()
    finally:
        conn.close()
    return view_catalog.recheck(who, rows)


def add_favorite(who: access.Caller, app_id: str) -> None:
    """Star a view the caller can use; 404 as for a view that doesn't exist otherwise."""
    access.require(who, APP, app_id, not_found="View not found")
    conn = _content()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO user_favorites (username, app_id, position) "
                  "SELECT %(u)s, %(a)s, COALESCE(MAX(position), 0) + 1 FROM user_favorites WHERE username = %(u)s "
                  "ON CONFLICT (username, app_id) DO NOTHING", {"u": _me(who), "a": app_id})
        conn.commit()
    finally:
        conn.close()


def remove_favorite(who: access.Caller, app_id: str) -> None:
    conn = _content()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM user_favorites WHERE username = %s AND app_id = %s", (_me(who), app_id))
        conn.commit()
    finally:
        conn.close()


def order_favorites(who: access.Caller, ids: Sequence[str]) -> List[str]:
    """Put these favorites first, in this order; any not named keep their order after them."""
    ids = [i for i in dict.fromkeys(ids) if i][:1000]
    conn = _content()
    try:
        c = conn.cursor()
        c.execute("UPDATE user_favorites f SET position = d.pos FROM unnest(%s::text[]) WITH ORDINALITY AS d(app_id, pos) "
                  "WHERE f.username = %s AND f.app_id = d.app_id", (ids, _me(who)))
        c.execute("UPDATE user_favorites SET position = position + %s WHERE username = %s AND NOT (app_id = ANY(%s))",
                  (len(ids), _me(who), ids))
        order = favorite_ids(c, who)
        conn.commit()
    finally:
        conn.close()
    return order


def hide(who: access.Caller, app_id: str) -> None:
    if not app_id or len(app_id) > MAX_ID:
        raise HTTPException(status_code=400, detail="Not a view id")
    conn = _content()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO view_hidden (username, app_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                  (_me(who), app_id))
        conn.commit()
    finally:
        conn.close()


def unhide(who: access.Caller, app_id: str) -> None:
    conn = _content()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM view_hidden WHERE username = %s AND app_id = %s", (_me(who), app_id))
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------- curation

def curate(who: access.Caller, app_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    """Feature or certify a view (admins; the route checks). Only the fields
    present in `changes` change; `featured_position: None` unfeatures."""
    if "featured_position" in changes and changes["featured_position"] is not None:
        position = int(changes["featured_position"])
        if not 0 <= position <= MAX_FEATURED_POSITION:
            raise HTTPException(status_code=400, detail=f"featured_position must be 0 to {MAX_FEATURED_POSITION}")
    conn = _content()
    try:
        c = conn.cursor()
        c.execute("SELECT 1 FROM dashboard_views WHERE id = %s LIMIT 1", (app_id,))
        if c.fetchone() is None:
            raise HTTPException(status_code=404, detail="View not found")
        c.execute("SELECT featured_position, featured_by, featured_at, certified, certified_by, certified_at "
                  "FROM view_curation WHERE app_id = %s", (app_id,))
        found = _rows(c)
        row = found[0] if found else {"featured_position": None, "featured_by": None, "featured_at": None,
                                      "certified": False, "certified_by": None, "certified_at": None}
        c.execute("SELECT now()")
        now = c.fetchone()[0]
        if "featured_position" in changes:
            row.update(featured_position=changes["featured_position"], featured_by=who.username, featured_at=now)
        if "certified" in changes:
            row.update(certified=bool(changes["certified"]), certified_by=who.username, certified_at=now)
        c.execute(
            "INSERT INTO view_curation (app_id, featured_position, featured_by, featured_at, certified, certified_by, "
            "certified_at) VALUES (%(id)s, %(featured_position)s, %(featured_by)s, %(featured_at)s, %(certified)s, "
            "%(certified_by)s, %(certified_at)s) ON CONFLICT (app_id) DO UPDATE SET "
            "featured_position = EXCLUDED.featured_position, featured_by = EXCLUDED.featured_by, "
            "featured_at = EXCLUDED.featured_at, certified = EXCLUDED.certified, "
            "certified_by = EXCLUDED.certified_by, certified_at = EXCLUDED.certified_at",
            dict(row, id=app_id),
        )
        # The rails read the catalog; write it now rather than wait for a rebuild.
        c.execute("UPDATE view_catalog SET featured_position = %s, certified = %s WHERE id = %s",
                  (row["featured_position"], row["certified"], app_id))
        conn.commit()
    finally:
        conn.close()
    return {"app_id": app_id, **{k: view_catalog.iso(v) if k.endswith("_at") else v for k, v in row.items()}}


# -------------------------------------------------------- recent, new for you

def recent_ids(c, who: access.Caller, limit: int) -> List[str]:
    c.execute("SELECT app_id, MAX(last_opened_at) AS at FROM view_visits WHERE username = %s "
              "GROUP BY app_id ORDER BY at DESC, app_id LIMIT %s", (_me(who), limit))
    return [r[0] for r in c.fetchall()]


def new_for_you_ids(who: access.Caller, limit: Optional[int] = None) -> List[str]:
    """Views shared with the caller or their groups in the last 14 days, newest
    grant first, that they haven't opened, hidden or made.

    Everyone-shares are left out: a view shared with the whole company isn't
    news to any one person in it.
    """
    me = _me(who)
    if not me:
        return []
    conn = _settings()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT object_id, MAX(granted_at) AS at FROM object_permissions "
            "WHERE object_type = %(t)s AND granted_at >= LOCALTIMESTAMP - make_interval(days => %(days)s) "
            "AND principal <> '*' AND principal_type <> 'all' "
            "AND ((principal_type = 'user' AND LOWER(principal) = %(me)s) "
            "OR (principal_type = 'group' AND principal = ANY(%(groups)s))) "
            "AND (granted_by IS NULL OR LOWER(granted_by) <> %(me)s) "
            "GROUP BY object_id ORDER BY at DESC, object_id LIMIT 500",
            {"t": APP, "days": NEW_FOR_YOU_DAYS, "me": me, "groups": list(who.groups)},
        )
        granted = [r[0] for r in c.fetchall()]
        conn.commit()
    finally:
        conn.close()
    if not granted:
        return []
    conn = _content()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT vc.id FROM view_catalog vc WHERE vc.id = ANY(%(ids)s) "
            "AND vc.owner_key IS DISTINCT FROM %(me)s "
            "AND NOT EXISTS (SELECT 1 FROM view_visits v WHERE v.username = %(me)s AND v.app_id = vc.id) "
            "AND NOT EXISTS (SELECT 1 FROM view_hidden h WHERE h.username = %(me)s AND h.app_id = vc.id)",
            {"ids": granted, "me": me},
        )
        keep = {r[0] for r in c.fetchall()}
        conn.commit()
    finally:
        conn.close()
    fresh = [i for i in granted if i in keep]
    return fresh[:limit] if limit else fresh


# ----------------------------------------------------------------------- home

_DRAFT_ONLY = """
FROM object_drafts d
WHERE d.object_type = 'app' AND LOWER(d.payload->>'username') = %(me)s
  AND NOT EXISTS (SELECT 1 FROM dashboard_views v WHERE v.id = d.object_id)
"""


def home(who: access.Caller) -> Dict[str, Any]:
    """`GET /api/discover/home`: what the sidebar shows, all light rows."""
    me = _me(who)
    fresh = new_for_you_ids(who)
    conn = _content()
    try:
        c = conn.cursor()
        fav_ids = favorite_ids(c, who, HOME_FAVORITES)
        recent = recent_ids(c, who, HOME_RECENT * 2)
        listed = view_catalog.light_rows(c, who, fav_ids + recent)
        c.execute(f"SELECT {view_catalog._LIGHT} FROM view_catalog vc {view_catalog._JOINS} "
                  "WHERE vc.owner_key = %(me)s ORDER BY vc.updated_at DESC, vc.id DESC LIMIT %(n)s",
                  {"me": me, "keys": view_catalog.caller_keys(who), "n": HOME_MINE})
        mine = _rows(c)
        c.execute("SELECT COUNT(*) FROM view_catalog WHERE owner_key = %s", (me,))
        mine_total = int(c.fetchone()[0])
        c.execute("SELECT d.object_id AS id, d.payload->>'name' AS name, d.payload->>'domain' AS domain, "
                  "d.updated_at, EXISTS (SELECT 1 FROM user_favorites f WHERE f.username = %(me)s "
                  "AND f.app_id = d.object_id) AS favorite " + _DRAFT_ONLY
                  + "ORDER BY d.updated_at DESC NULLS LAST LIMIT %(n)s", {"me": me, "n": HOME_MINE})
        draft_only = [_draft_row(r, who) for r in _rows(c)]
        c.execute("SELECT COUNT(*) " + _DRAFT_ONLY, {"me": me})
        mine_total += int(c.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    mine = sorted(mine + draft_only, key=lambda r: (_sortable(r.get("updated_at")), r["id"]), reverse=True)[:HOME_MINE]
    unique = {r["id"]: r for r in listed + mine + draft_only}
    allowed = {r["id"]: r for r in view_catalog.recheck(who, list(unique.values()))}
    # `drafts` is capped on its own: in `mine` they compete with published views
    # for the 50, and Discover's Mine lists them because search can't find them.
    return {
        "favorites": [allowed[i] for i in fav_ids if i in allowed],
        "recent": [allowed[i] for i in recent if i in allowed][:HOME_RECENT],
        "mine": [allowed[r["id"]] for r in mine if r["id"] in allowed],
        "drafts": [allowed[r["id"]] for r in draft_only if r["id"] in allowed],
        "mine_total": mine_total,
        "new_for_you_count": len(fresh),
    }


def _draft_row(r: Dict[str, Any], who: access.Caller) -> Dict[str, Any]:
    """A never-published view as a light row: no link name yet, no statistics."""
    name = (r.get("name") or "").strip() or "Untitled view"
    return {"id": r["id"], "ref": view_catalog.fallback_ref(r["id"], name), "name": name, "description": "",
            "owner": who.username, "domain": r.get("domain"), "presentation": "workspace",
            "updated_at": r.get("updated_at"), "published_at": None, "favorite": r.get("favorite"),
            "state": "draft_only"}


def _sortable(value: Any) -> str:
    return view_catalog.iso(value) or ""
