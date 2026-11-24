"""The queries behind Admin Panel → Action Logs: search, filters, sort and pages.

`action_logs` is the audit trail of every executable widget action, scheduled
action run and data migration, and it is never purged, so the tab can't load it
whole and filter in the browser the way it used to (it showed the newest 100 and
searched only those). Everything is decided here, in SQL, and the browser asks for
one page at a time.

Pure functions that return `(sql, params)`, so the shape of every query is
tested without a database (`tests/test_action_log_query.py`). Two rules hold
throughout:

- **Values are parameters, never text.** The only things spliced into the SQL
  are constants from this module: a sort column comes from `SORTS`, a direction
  from `DIRECTIONS`. Anything else a caller sends is a `%s`.
- **Search is a substring, not a pattern.** `%`, `_` and `\\` in what someone
  typed are escaped, so searching `50%` finds "50%" rather than everything that
  starts with 50.

Pages are offset, not keyset. Keyset paging only works along one fixed order and
can't say "page 4 of 12"; this tab sorts by any column and shows page numbers.
The cost is that a row logged while someone reads shifts later pages by one,
which for an administrator reading an audit trail is a fair trade (the Activity
tab, which is a live feed, pages by keyset instead).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_QUERY_LENGTH = 200
# Distinct values offered in each filter. Past this a dropdown stops being
# usable, and the free-text search still reaches the rest.
MAX_FACET_VALUES = 500

# Sortable columns: what the browser may name -> the SQL it stands for. Text
# columns put blanks last in either direction, so sorting by user doesn't open
# on a page of rows logged before names were recorded. `timestamp` keeps
# Postgres's default NULL order, which is what lets the (timestamp, id) index
# serve both directions; the column has a default and is never blank in practice.
SORTS = {
    "timestamp": ("al.timestamp", False),
    "widget_name": ("al.widget_name", True),
    "action_name": ("al.action_name", True),
    "username": ("al.username", True),
    "domain": ("w.domain", True),
    "id": ("al.id", False),
}
DIRECTIONS = {"asc": "ASC", "desc": "DESC"}
DEFAULT_SORT, DEFAULT_DIRECTION = "timestamp", "desc"

# The columns a free-text search reads. Not `dashboard_context`: it is a JSON
# snapshot of a whole tab, large enough to make every search a slow one, and its
# matches (a widget setting, a column name) are mostly noise.
SEARCH_COLUMNS = (
    "al.widget_name", "al.widget_id", "al.action_name", "al.username",
    "al.user_explanation", "al.request_id", "w.domain",
)

# Each logged widget's current domain: the newest live version's. The log keeps
# the id, not the domain at the time, so a widget moved to another domain is
# listed under its new one, and a removed widget under none.
DOMAIN_JOIN = """
    LEFT JOIN (
        SELECT id, domain
        FROM widgets
        WHERE is_deprecated = 0
        AND version = (
            SELECT MAX(version) FROM widgets w2
            WHERE w2.id = widgets.id AND w2.is_deprecated = 0
        )
    ) w ON al.widget_id = w.id"""

COLUMNS = ("al.id, al.widget_id, al.widget_name, al.action_name, al.username, al.request_id, "
           "al.user_explanation, al.dashboard_context, al.timestamp, w.domain")

_ID_SEARCH = re.compile(r"^#?(\d{1,18})$")


@dataclass(frozen=True)
class Filters:
    q: str = ""
    widget_id: str = ""
    action_name: str = ""
    username: str = ""
    domain: str = ""
    since: Optional[datetime] = None
    until: Optional[datetime] = None

    @property
    def needs_domain(self) -> bool:
        # The join is only worth making when something reads `w.domain`.
        return bool(self.q or self.domain)


# ------------------------------------------------------------------ parsing

def parse_sort(sort: Optional[str], direction: Optional[str]) -> Tuple[str, str]:
    """A whitelisted sort and direction; raises ValueError, so a typo is a 400."""
    key = (sort or DEFAULT_SORT).strip().lower()
    way = (direction or DEFAULT_DIRECTION).strip().lower()
    if key not in SORTS:
        raise ValueError(f"Can't sort by '{sort}'. Sort by one of: {', '.join(SORTS)}.")
    if way not in DIRECTIONS:
        raise ValueError(f"'{direction}' isn't a direction; use asc or desc.")
    return key, way


def parse_time(raw: Optional[str]) -> Optional[datetime]:
    """An ISO date or time from a filter; one without a zone is taken as UTC."""
    if not raw or not raw.strip():
        return None
    try:
        value = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"'{raw}' isn't a date and time.") from e
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def make_filters(q: str = "", widget_id: str = "", action_name: str = "", username: str = "",
                 domain: str = "", since: Optional[str] = None, until: Optional[str] = None) -> Filters:
    """Filters from query parameters, trimmed and checked; raises ValueError."""
    text = (q or "").strip()
    if len(text) > MAX_QUERY_LENGTH:
        raise ValueError(f"Search for at most {MAX_QUERY_LENGTH} characters.")
    start, end = parse_time(since), parse_time(until)
    if start and end and start >= end:
        raise ValueError("The start of the date range must be before its end.")
    return Filters(
        q=text,
        widget_id=(widget_id or "").strip(),
        action_name=(action_name or "").strip(),
        username=(username or "").strip(),
        domain=(domain or "").strip(),
        since=start,
        until=end,
    )


def escape_like(text: str) -> str:
    """`text` as a literal inside an ILIKE pattern (whose escape character is `\\`)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ------------------------------------------------------------------ queries

def where_clause(f: Filters) -> Tuple[str, List[Any]]:
    """` WHERE ...` and its parameters, or `("", [])` when nothing narrows the log."""
    where: List[str] = []
    params: List[Any] = []
    if f.q:
        pattern = "%" + escape_like(f.q) + "%"
        # Backslash is ILIKE's default escape character; naming it with
        # `ESCAPE '\'` would depend on standard_conforming_strings being on.
        terms = [f"{col} ILIKE %s" for col in SEARCH_COLUMNS]
        params += [pattern] * len(SEARCH_COLUMNS)
        # "#42" or "42" also finds action 42, as the Action ID column shows it.
        match = _ID_SEARCH.match(f.q)
        if match:
            terms.append("al.id = %s")
            params.append(int(match.group(1)))
        where.append("(" + " OR ".join(terms) + ")")
    if f.widget_id:
        where.append("al.widget_id = %s")
        params.append(f.widget_id)
    if f.action_name:
        where.append("al.action_name = %s")
        params.append(f.action_name)
    if f.username:
        # Case-insensitive, as usernames are everywhere else (SCIM isn't
        # consistent about case), which the LOWER(username) index serves.
        where.append("LOWER(al.username) = LOWER(%s)")
        params.append(f.username)
    if f.domain:
        where.append("w.domain = %s")
        params.append(f.domain)
    # `timestamp` has no zone; compared with a zoned value, Postgres reads it in
    # the session's zone, the one CURRENT_TIMESTAMP wrote it in.
    if f.since:
        where.append("al.timestamp >= %s")
        params.append(f.since)
    if f.until:
        where.append("al.timestamp < %s")
        params.append(f.until)
    return ((" WHERE " + " AND ".join(where)) if where else ""), params


def order_clause(sort: str, direction: str) -> str:
    """` ORDER BY ...` for a sort that `parse_sort` accepted.

    The id always breaks ties, in the same direction, so a page boundary never
    falls between rows that sort equal and repeats or skips one of them.
    """
    column, nulls_last = SORTS[sort]
    way = DIRECTIONS[direction]
    first = f"{column} {way}" + (" NULLS LAST" if nulls_last else "")
    if sort == "id":
        return f" ORDER BY {first}"
    return f" ORDER BY {first}, al.id {way}"


def page_query(f: Filters, sort: str, direction: str, limit: int, offset: int) -> Tuple[str, List[Any]]:
    where, params = where_clause(f)
    sql = (f"SELECT {COLUMNS} FROM action_logs al{DOMAIN_JOIN}{where}"
           f"{order_clause(sort, direction)} LIMIT %s OFFSET %s")
    return sql, params + [limit, offset]


def count_query(f: Filters) -> Tuple[str, List[Any]]:
    where, params = where_clause(f)
    join = DOMAIN_JOIN if f.needs_domain else ""
    return f"SELECT COUNT(*) AS total FROM action_logs al{join}{where}", params


def facet_queries(limit: int = MAX_FACET_VALUES) -> List[Tuple[str, str, List[Any]]]:
    """`(name, sql, params)` for each filter's choices, from the whole log.

    The widget's name is the one it was most recently logged under, since a
    widget can be renamed between actions and the filter is on its id.
    """
    return [
        ("widgets",
         "SELECT al.widget_id AS value, (ARRAY_AGG(al.widget_name ORDER BY al.timestamp DESC NULLS LAST))[1] AS label,"
         " COUNT(*) AS count FROM action_logs al WHERE al.widget_id IS NOT NULL AND al.widget_id <> ''"
         " GROUP BY al.widget_id ORDER BY label NULLS LAST, al.widget_id LIMIT %s",
         [limit]),
        ("actions",
         "SELECT al.action_name AS value, COUNT(*) AS count FROM action_logs al"
         " WHERE al.action_name IS NOT NULL AND al.action_name <> ''"
         " GROUP BY al.action_name ORDER BY al.action_name LIMIT %s",
         [limit]),
        ("users",
         "SELECT MIN(al.username) AS value, COUNT(*) AS count FROM action_logs al"
         " WHERE al.username IS NOT NULL AND al.username <> ''"
         " GROUP BY LOWER(al.username) ORDER BY LOWER(al.username) LIMIT %s",
         [limit]),
        ("domains",
         f"SELECT w.domain AS value, COUNT(*) AS count FROM action_logs al{DOMAIN_JOIN}"
         " WHERE w.domain IS NOT NULL AND w.domain <> ''"
         " GROUP BY w.domain ORDER BY w.domain LIMIT %s",
         [limit]),
    ]


def facet_values(rows: List[Any]) -> List[dict]:
    """Facet rows as `{value, label, count}`, whatever cursor read them."""
    out = []
    for r in rows:
        row = dict(r) if hasattr(r, "keys") else None
        if row is None:
            values = list(r)
            row = {"value": values[0], "label": values[1], "count": values[2]} if len(values) == 3 \
                else {"value": values[0], "count": values[1]}
        value = row.get("value")
        if value is None:
            continue
        out.append({"value": value, "label": row.get("label") or value, "count": int(row.get("count") or 0)})
    return out
