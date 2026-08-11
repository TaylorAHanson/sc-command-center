"""Tests for ranking widget creators.

A leaderboard is only worth having if people believe it, so most of what is
checked here is about not crediting the wrong thing: placeholder usernames that
were never a person, creators inflating their own reach, runs left over from
deleted widgets, and ties that reshuffle every time the panel opens.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services.creator_stats import (  # noqa: E402
    NOT_A_PERSON, WEIGHTS, is_person, same_person, tally, unowned_sql, widget_key,
)

ANA = "ana@example.com"
BEN = "ben@example.com"
CAI = "cai@example.com"


def by_name(rows):
    return {row["username"]: row for row in rows}


# ------------------------------------------------------------------ crediting

def test_publishing_a_widget_is_what_puts_you_on_the_board():
    rows = tally({"w1": ANA, "w2": ANA, "w3": BEN}, [], [])
    assert [r["username"] for r in rows] == [ANA, BEN]
    assert by_name(rows)[ANA]["published"] == 2
    assert by_name(rows)[ANA]["score"] == 2 * WEIGHTS["published"]


def test_usage_credits_the_author_not_the_user():
    rows = tally({"w1": ANA}, runs=[("w1", BEN)], placements=[("w1", BEN)])
    assert [r["username"] for r in rows] == [ANA], "Ben used it; Ana made it"
    ana = by_name(rows)[ANA]
    assert ana["adds"] == 1 and ana["placements"] == 1 and ana["reach"] == 1


def test_reach_counts_people_and_placements_count_appearances():
    # One person with the widget on three views is one person, three placements.
    rows = tally(
        {"w1": ANA},
        runs=[],
        placements=[("w1", BEN), ("w1", BEN), ("w1", BEN), ("w1", CAI)],
    )
    ana = by_name(rows)[ANA]
    assert ana["reach"] == 2
    assert ana["placements"] == 4


def test_using_your_own_widget_does_not_count_as_reach():
    # Otherwise the way to top the board is to fill your own dashboards.
    rows = tally({"w1": ANA}, runs=[("w1", ANA)], placements=[("w1", ANA)] * 5)
    ana = by_name(rows)[ANA]
    assert ana["reach"] == 0
    assert ana["placements"] == 5, "the placements are still real, they just aren't reach"


def test_the_same_person_in_different_letter_case_is_one_person():
    rows = tally({"w1": ANA}, runs=[("w1", "Ana@Example.com"), ("w1", ANA)], placements=[])
    assert by_name(rows)[ANA]["reach"] == 0, "still the author, whatever the casing"
    rows = tally({"w1": ANA}, runs=[("w1", "BEN@example.com"), ("w1", BEN)], placements=[])
    assert by_name(rows)[ANA]["reach"] == 1


# ------------------------------------------------------- who is not a person

def test_placeholder_authors_are_never_credited():
    # "dev" and "unknown" are what a failed identity lookup used to write. Counting
    # them would put a fictional person at the top of the board.
    rows = tally({"w1": "dev", "w2": "unknown", "w3": "", "w4": None, "w5": ANA}, [], [])
    assert [r["username"] for r in rows] == [ANA]


def test_a_placeholder_user_is_a_run_but_not_a_person_reached():
    rows = tally({"w1": ANA}, runs=[("w1", "unknown"), ("w1", None), ("w1", BEN)], placements=[])
    ana = by_name(rows)[ANA]
    assert ana["adds"] == 3, "every add is still an add"
    assert ana["reach"] == 1, "only the one we can name counts as a person"


def test_usage_of_a_widget_nobody_authored_credits_nobody():
    # Core widgets and deleted ones both show up in runs; neither has an author.
    assert tally({}, runs=[("core-chart", BEN)], placements=[("core-chart", BEN)]) == []


def test_a_service_principal_is_not_a_creator():
    # A local run authenticates as the app's own service principal, and SCIM answers
    # with its application id. That is the right owner to record on the row, but a
    # UUID collecting points is not a leaderboard of people.
    sp = "4f1c9b2a-7d3e-4a55-9c18-0b6e2f7a1d34"
    assert not is_person(sp)
    assert tally({"w1": sp, "w2": ANA}, [], []) [0]["username"] == ANA
    assert len(tally({"w1": sp, "w2": ANA}, [], [])) == 1


def test_the_same_author_written_two_ways_is_one_person():
    assert same_person(ANA, "Ana@Example.com ")
    assert not same_person(ANA, BEN)
    # Nobody owns a row with no author, which is what lets anyone tidy one up.
    assert not same_person(None, None) and not same_person("", "")


def test_is_person_and_widget_key():
    assert is_person(ANA)
    assert not is_person("  DEV ") and not is_person(None) and not is_person("unknown")
    # A view can pin a widget to a version; it's the same widget for crediting.
    assert widget_key("w1@3") == "w1"
    assert widget_key("w1") == "w1"
    assert widget_key(None) == ""


# --------------------------------------------------------------------- order

def test_the_ranking_puts_used_widgets_above_merely_numerous_ones():
    rows = tally(
        {f"a{i}": ANA for i in range(4)} | {"b1": BEN},
        runs=[],
        placements=[("b1", CAI), ("b1", "dee@example.com"), ("b1", "eve@example.com")] * 3,
    )
    ranked = [r["username"] for r in rows]
    assert ranked == [BEN, ANA], "three teams using one widget beats four unused ones"
    assert rows[0]["rank"] == 1 and rows[1]["rank"] == 2


def test_ties_break_the_same_way_every_time():
    # Same score for both; the order must not depend on dict iteration.
    first = tally({"w1": BEN, "w2": ANA}, [], [])
    second = tally({"w2": ANA, "w1": BEN}, [], [])
    assert [r["username"] for r in first] == [r["username"] for r in second] == [ANA, BEN]


def test_the_score_is_the_sum_of_the_parts_it_reports():
    rows = tally(
        {"w1": ANA, "w2": ANA},
        runs=[("w1", BEN)],
        placements=[("w1", BEN), ("w2", CAI)],
    )
    ana = by_name(rows)[ANA]
    assert ana == {
        "username": ANA, "published": 2, "placements": 2, "adds": 1, "reach": 2,
        "score": 2 * WEIGHTS["published"] + 2 * WEIGHTS["reach"] + 2 * WEIGHTS["placements"],
        "rank": 1,
    }


# ---------------------------------------------------------------- claiming

def test_the_claim_condition_asks_about_every_placeholder_we_know():
    """`unowned_sql` is `is_person` for Postgres, and the two must not drift.

    A value missing from the SQL is a widget nobody can claim; a value in the SQL
    that `is_person` accepts would let someone take a widget with a real author.
    """
    condition, params = unowned_sql()
    assert params[:-1] == sorted(NOT_A_PERSON), "every placeholder is passed to the query"
    assert condition.count("%s") == len(params), "one slot per parameter"
    for name in params[:-1]:
        assert not is_person(name), f"{name!r} is in the SQL, so it must not be a person"


def test_the_claim_condition_names_the_column_it_is_given():
    assert "created_by IS NULL" in unowned_sql()[0]
    qualified, _ = unowned_sql("w.created_by")
    assert "w.created_by IS NULL" in qualified
    assert "lower(btrim(w.created_by))" in qualified, "a joined query needs the table too"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
