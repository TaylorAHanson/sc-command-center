"""The names in links to global views: `#/app/supply-hub` instead of `#/app/<uuid>`.

Only global views are linked by name. A personal view is open to anyone holding
its id (`app_spec.can_read`), so its id is the secret its link carries; a name
anyone could guess would turn every personal view into one anyone could open.
Its link is `<name>-<id>` instead: readable, and still unguessable. A global
view needs a role in its domain whatever its link says, so its name is safe to
publish.

A name, once a view has held it, stays with that view (`app_links`), so a link
handed out before a rename still opens the view and nobody else's. The newest
name a view claimed is the one its links use. Two views can't share a name; the
second to want one gets `-2`, then `-3`.

Claimed on every save of a global version (`app_store.insert_version`), by
promotion, and at startup for views that predate this or arrived by snapshot,
never on opening one: opening a view writes nothing.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

MAX_LENGTH = 60
#: How many views may want one name before the rest fall back to their id.
MAX_SUFFIX = 20

# A personal view's link ends in its id, and an id is what a link resolves first,
# so a name may not look like one: a global view named after someone's personal
# view would otherwise take over that view's link.
_UUID_TAIL = re.compile(
    r"(?:^|-)([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


def slugify(name: Any) -> str:
    """`name` as it reads in a link: lower case, accents dropped, words joined by '-'."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^\w]+|_+", "-", text).strip("-")
    text = _UUID_TAIL.sub("", text).strip("-")
    return text[:MAX_LENGTH].strip("-") or "view"


def id_in(ref: str) -> Optional[str]:
    """The id a personal view's `<name>-<id>` link ends in, if it ends in one."""
    match = _UUID_TAIL.search(ref or "")
    return match.group(1).lower() if match else None


def _first(row: Any) -> Any:
    if row is None:
        return None
    return next(iter(row.values())) if hasattr(row, "values") else row[0]


def claim(c, app_id: str, name: str) -> Optional[str]:
    """Make `name` (or the first free `name-N`) this view's link name, and return it.

    A name the view already holds is reclaimed rather than suffixed, so renaming a
    view back gives it its old link back. None when every candidate belongs to
    another view; its links then carry its id, which always works.
    """
    base = slugify(name)
    for n in range(1, MAX_SUFFIX + 1):
        slug = base if n == 1 else f"{base[:MAX_LENGTH - 4]}-{n}"
        c.execute(
            """
            INSERT INTO app_links (slug, app_id) VALUES (%s, %s)
            ON CONFLICT (slug) DO UPDATE SET claimed_at = clock_timestamp()
             WHERE app_links.app_id = EXCLUDED.app_id
            RETURNING slug
            """,
            (slug, app_id),
        )
        if c.fetchone() is not None:
            return slug
    return None


def owner(c, slug: str) -> Optional[str]:
    """The view a link name belongs to, if any; whether it is still global is the caller's to check."""
    c.execute("SELECT app_id FROM app_links WHERE slug = %s", (slug,))
    return _first(c.fetchone())


def current(c, app_ids: List[str]) -> Dict[str, str]:
    """The link name each view's links use now: the newest it claimed."""
    if not app_ids:
        return {}
    c.execute(
        """
        SELECT DISTINCT ON (app_id) app_id, slug FROM app_links
         WHERE app_id = ANY(%s)
         ORDER BY app_id, claimed_at DESC
        """,
        (list(app_ids),),
    )
    out: Dict[str, str] = {}
    for row in c.fetchall() or []:
        app_id, slug = (row["app_id"], row["slug"]) if hasattr(row, "keys") else (row[0], row[1])
        out[app_id] = slug
    return out


def forget(c, app_id: str) -> None:
    """Free a deleted view's names. An archived view keeps them: it can come back."""
    c.execute("DELETE FROM app_links WHERE app_id = %s", (app_id,))


def backfill(c) -> int:
    """Name every global view that has no link name yet, oldest first, so it keeps the plain name."""
    c.execute(
        """
        SELECT v.id, v.name
          FROM dashboard_views v
          JOIN (SELECT id, MAX(version) AS version, MIN(timestamp) AS created
                  FROM dashboard_views GROUP BY id) h
            ON v.id = h.id AND v.version = h.version
         WHERE v.is_global = 1
           AND NOT EXISTS (SELECT 1 FROM app_links l WHERE l.app_id = v.id)
         ORDER BY h.created NULLS LAST, v.id
        """
    )
    rows = [(r["id"], r["name"]) if hasattr(r, "keys") else (r[0], r[1]) for r in c.fetchall() or []]
    for app_id, name in rows:
        claim(c, app_id, name)
    return len(rows)
