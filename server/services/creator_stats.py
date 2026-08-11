"""Who builds the widgets people actually use.

The Widget Library credits an author on every card, and this is the same question
asked the other way round: for each person, how much is out there and how far has
it travelled. Three things go into that, and they answer different questions:

- **published** — live widgets they authored. Output, and the only figure that is
  entirely within one person's control.
- **reach** — how many *other* people have one of their widgets on a view. The
  honest measure of usefulness, and the reason a creator's own dashboards don't
  count towards it.
- **placements** — how many times their widgets appear across everyone's views.
  Rewards a widget that people keep coming back to without letting one enthusiast
  outweigh a widget that spread.

The score weights them in that order of trust (`WEIGHTS`), and every component is
reported alongside it so a rank can always be explained rather than taken on faith.

The aggregation is deliberately separate from the queries: `tally` is given plain
data and can be reasoned about — and tested — without a database.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Points per unit. Reach is worth more than a placement because a second person
#: adopting a widget says more than the same person using it twice, and publishing
#: is worth most per unit because there are far fewer of them.
WEIGHTS = {"published": 5, "reach": 3, "placements": 1}

#: Author values that aren't people. These are what unresolved identities used to
#: be written as, and counting them would invent a prolific creator called "dev".
NOT_A_PERSON = {"", "unknown", "dev", "none", "null", "system", "n/a"}


def is_person(name: Optional[str]) -> bool:
    """Whether an author string names someone we can credit.

    Also the rule for whether a row has an owner at all: a widget whose author is a
    placeholder belongs to nobody, so anyone may delete it. That check used to know
    about one placeholder and not the others, which left every widget the identity
    bug stamped "dev" owned by a user who cannot exist, and so undeletable.

    A service principal's application id is excluded too. It is a real caller, and
    right to record as the owner of what it created, but a leaderboard of people
    should not have a UUID sitting in it collecting points for someone's local run.
    """
    from services.caller_identity import is_application_id

    value = str(name or "").strip()
    return bool(value) and value.lower() not in NOT_A_PERSON and not is_application_id(value)


def same_person(a: Optional[str], b: Optional[str]) -> bool:
    """Whether two author strings name the same person.

    Case-insensitive: SCIM is not consistent about the case of an address, and two
    spellings of one person must not read as two creators — or as someone else's
    widget when they go to delete their own.
    """
    return bool(a) and bool(b) and str(a).strip().lower() == str(b).strip().lower()


def unowned_sql(column: str = "created_by") -> Tuple[str, List[str]]:
    """`is_person` inverted, as a SQL condition and its parameters.

    Claiming a widget has to fill the blank and check it is still blank in the one
    statement, or two people who both recognise their work race and the loser
    silently overwrites the winner. That means Postgres has to be able to ask the
    question, so the answer is built here from the same `NOT_A_PERSON` list rather
    than written out again in a query where it would quietly drift.
    """
    from services.caller_identity import APPLICATION_ID_PATTERN

    names = sorted(NOT_A_PERSON)
    slots = ",".join(["%s"] * len(names))
    condition = (
        f"({column} IS NULL OR lower(btrim({column})) IN ({slots}) OR {column} ~* %s)"
    )
    return condition, names + [APPLICATION_ID_PATTERN]


def widget_key(widget_type: Optional[str]) -> str:
    """The widget id behind a placement.

    A view stores the registry key, which is usually the plain id but carries an
    `@version` suffix for a pinned widget. Both are the same widget for crediting.
    """
    return str(widget_type or "").split("@", 1)[0].strip()


def tally(
    authors: Dict[str, str],
    runs: Iterable[Tuple[str, Optional[str]]],
    placements: Iterable[Tuple[str, Optional[str]]],
) -> List[Dict[str, Any]]:
    """Rank creators from widget authorship, library adds and view placements.

    `authors` maps widget id to the person who published it. `runs` and
    `placements` are `(widget_id, username)` pairs — an add from the library and an
    appearance on someone's view respectively, either of which may have no username
    attached (runs recorded before we stored one, or a view with no owner).
    """
    people: Dict[str, Dict[str, Any]] = {}

    def entry(person: str) -> Dict[str, Any]:
        return people.setdefault(person, {
            "username": person,
            "published": 0,
            "placements": 0,
            "adds": 0,
            "_reach": set(),
        })

    for widget_id, author in authors.items():
        if is_person(author):
            entry(author)["published"] += 1

    def credit(pairs: Iterable[Tuple[str, Optional[str]]], field: str) -> None:
        for widget_id, user in pairs:
            author = authors.get(widget_key(widget_id))
            if not is_person(author):
                continue  # a run against a deleted or core widget credits nobody
            record = entry(author)
            record[field] += 1
            # Using your own widget is not reach. Without this a creator could top
            # the board on their own dashboards, which is exactly the kind of thing
            # that makes people stop trusting a leaderboard.
            if is_person(user) and not same_person(user, author):
                record["_reach"].add(str(user).strip().lower())

    credit(runs, "adds")
    credit(placements, "placements")

    ranked = []
    for record in people.values():
        record["reach"] = len(record.pop("_reach"))
        record["score"] = (
            WEIGHTS["published"] * record["published"]
            + WEIGHTS["reach"] * record["reach"]
            + WEIGHTS["placements"] * record["placements"]
        )
        ranked.append(record)

    # Score first, then output, then name — so the order is stable between calls
    # rather than shuffling among ties every time the panel is opened.
    ranked.sort(key=lambda r: (-r["score"], -r["published"], r["username"].lower()))
    for position, record in enumerate(ranked, start=1):
        record["rank"] = position
    return ranked


def _latest_widget_authors(cursor) -> Dict[str, str]:
    """Widget id to author, for the newest live version of each widget."""
    cursor.execute(
        """
        SELECT w.id, w.created_by
        FROM widgets w
        INNER JOIN (
            SELECT id, MAX(version) AS version
            FROM widgets
            WHERE is_deprecated = 0
            GROUP BY id
        ) latest ON w.id = latest.id AND w.version = latest.version
        WHERE w.is_deprecated = 0
        """
    )
    return {str(row[0]): (row[1] or "") for row in cursor.fetchall()}


def _runs(cursor) -> List[Tuple[str, Optional[str]]]:
    cursor.execute("SELECT widget_id, username FROM widget_runs")
    return [(str(row[0]), row[1]) for row in cursor.fetchall()]


def _placements(cursor) -> List[Tuple[str, Optional[str]]]:
    """Every widget sitting on the current version of someone's view."""
    cursor.execute(
        """
        SELECT dv.widgets_json, dv.username
        FROM dashboard_views dv
        INNER JOIN (
            SELECT id, MAX(version) AS version
            FROM dashboard_views
            GROUP BY id
        ) latest ON dv.id = latest.id AND dv.version = latest.version
        """
    )
    found: List[Tuple[str, Optional[str]]] = []
    for widgets_json, owner in cursor.fetchall():
        try:
            widgets = json.loads(widgets_json or "[]")
        except (TypeError, ValueError):
            continue  # a malformed view is not worth failing the whole board over
        if not isinstance(widgets, list):
            continue
        for widget in widgets:
            if isinstance(widget, dict) and widget.get("type"):
                found.append((str(widget["type"]), owner))
    return found


def leaderboard(env: str = "dev", limit: int = 10) -> Dict[str, Any]:
    """The ranked creators, plus the weights so the UI can explain the ranking."""
    from database import get_db_connection

    conn = get_db_connection(env)
    try:
        cursor = conn.cursor()
        authors = _latest_widget_authors(cursor)
        ranked = tally(authors, _runs(cursor), _placements(cursor))
    finally:
        conn.close()

    unattributed = sum(1 for author in authors.values() if not is_person(author))
    return {
        "creators": ranked[:limit] if limit else ranked,
        "total_creators": len(ranked),
        # Surfaced rather than hidden: widgets whose author never resolved are the
        # symptom of an identity problem, and silently dropping them from the board
        # makes that invisible.
        "unattributed_widgets": unattributed,
        "weights": WEIGHTS,
    }
