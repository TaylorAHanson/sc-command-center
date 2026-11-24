"""Tests for services/action_log_query.py, the SQL behind Admin Panel → Action Logs.

The tab searches, filters, sorts and pages on the server, so what matters is the
shape of each statement: every value a parameter, only whitelisted columns in the
ORDER BY, search wildcards escaped, and a tie-break that keeps pages from
repeating rows. No database: the builders return `(sql, params)`.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import action_log_query as alq  # noqa: E402

HOSTILE = "x'; DROP TABLE action_logs; --"


def raises(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError as e:
        return str(e)
    raise AssertionError("expected a ValueError")


# ------------------------------------------------------------------ escaping

def test_like_wildcards_in_a_search_are_literal():
    assert alq.escape_like("50%") == "50\\%"
    assert alq.escape_like("a_b") == "a\\_b"
    assert alq.escape_like("c:\\tmp") == "c:\\\\tmp"
    assert alq.escape_like("plain") == "plain"


def test_the_backslash_is_escaped_before_the_wildcards_it_escapes():
    # Otherwise "\%" would become "\\%": an escaped backslash and a live wildcard.
    assert alq.escape_like("\\%") == "\\\\\\%"


# ------------------------------------------------------------------ where clause

def test_no_filters_means_no_where_clause():
    assert alq.where_clause(alq.Filters()) == ("", [])


def test_a_search_reads_every_search_column_as_one_parameterized_pattern():
    where, params = alq.where_clause(alq.Filters(q="refund"))
    assert where.count("ILIKE %s") == len(alq.SEARCH_COLUMNS)
    assert params == ["%refund%"] * len(alq.SEARCH_COLUMNS)
    assert "refund" not in where, "the value travels as a parameter, never in the text"
    for col in alq.SEARCH_COLUMNS:
        assert col in where
    assert "dashboard_context" not in where


def test_a_search_with_wildcards_sends_them_escaped():
    _, params = alq.where_clause(alq.Filters(q="100%_done"))
    assert params[0] == "%100\\%\\_done%"


def test_a_number_also_finds_the_action_with_that_id():
    for q in ("42", "#42"):
        where, params = alq.where_clause(alq.Filters(q=q))
        assert "al.id = %s" in where
        assert params[-1] == 42
    where, _ = alq.where_clause(alq.Filters(q="42a"))
    assert "al.id" not in where


def test_hostile_text_never_reaches_the_sql():
    f = alq.Filters(q=HOSTILE, widget_id=HOSTILE, action_name=HOSTILE, username=HOSTILE, domain=HOSTILE)
    where, params = alq.where_clause(f)
    assert "DROP" not in where
    assert HOSTILE in params


def test_each_filter_is_an_exact_match_and_the_user_ignores_case():
    where, params = alq.where_clause(alq.Filters(widget_id="w1", action_name="approve",
                                                 username="Taylor@Example.com", domain="Sales"))
    assert "al.widget_id = %s" in where
    assert "al.action_name = %s" in where
    assert "LOWER(al.username) = LOWER(%s)" in where
    assert "w.domain = %s" in where
    assert params == ["w1", "approve", "Taylor@Example.com", "Sales"]
    assert where.count(" AND ") == 3


def test_the_date_range_includes_its_start_and_excludes_its_end():
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    end = datetime(2026, 11, 2, tzinfo=timezone.utc)
    where, params = alq.where_clause(alq.Filters(since=start, until=end))
    assert "al.timestamp >= %s" in where and "al.timestamp < %s" in where
    assert params == [start, end]


# ------------------------------------------------------------------ sorting

def test_only_whitelisted_columns_can_be_sorted():
    assert alq.parse_sort(None, None) == ("timestamp", "desc")
    assert alq.parse_sort("Widget_Name", "ASC") == ("widget_name", "asc")
    assert "Can't sort by" in raises(alq.parse_sort, "dashboard_context", "asc")
    assert "Can't sort by" in raises(alq.parse_sort, "timestamp; DROP TABLE action_logs", "asc")
    assert "isn't a direction" in raises(alq.parse_sort, "timestamp", "sideways")


def test_every_sort_breaks_ties_by_id_in_the_same_direction():
    for key in alq.SORTS:
        for way in ("asc", "desc"):
            order = alq.order_clause(key, way)
            assert order.startswith(" ORDER BY ")
            assert order.rstrip().endswith(f"al.id {alq.DIRECTIONS[way]}"), order


def test_text_columns_put_blanks_last_but_time_keeps_the_index_order():
    assert "NULLS LAST" in alq.order_clause("username", "desc")
    assert "NULLS LAST" in alq.order_clause("username", "asc")
    assert alq.order_clause("timestamp", "desc") == " ORDER BY al.timestamp DESC, al.id DESC"
    assert alq.order_clause("timestamp", "asc") == " ORDER BY al.timestamp ASC, al.id ASC"


# ------------------------------------------------------------------ whole queries

def test_a_page_query_ends_with_its_limit_and_offset_as_parameters():
    sql, params = alq.page_query(alq.Filters(action_name="approve"), "username", "asc", 25, 50)
    assert sql.endswith("LIMIT %s OFFSET %s")
    assert params == ["approve", 25, 50]
    assert sql.count("%s") == len(params)
    assert "w.domain" in sql, "a page always shows each row's domain"


def test_the_count_joins_widgets_only_when_the_domain_is_read():
    plain, _ = alq.count_query(alq.Filters(action_name="approve"))
    assert "LEFT JOIN" not in plain
    for f in (alq.Filters(domain="Sales"), alq.Filters(q="sales")):
        sql, params = alq.count_query(f)
        assert "LEFT JOIN" in sql
        assert sql.count("%s") == len(params)


def test_the_page_and_the_count_filter_identically():
    f = alq.Filters(q="x", username="u", since=datetime(2026, 1, 1, tzinfo=timezone.utc))
    page_sql, page_params = alq.page_query(f, "timestamp", "desc", 10, 0)
    count_sql, count_params = alq.count_query(f)
    where, _ = alq.where_clause(f)
    assert where in page_sql and where in count_sql
    assert page_params[:-2] == count_params


def test_facets_come_from_the_whole_log_with_a_cap():
    queries = alq.facet_queries(limit=7)
    assert [name for name, _, _ in queries] == ["widgets", "actions", "users", "domains"]
    for _, sql, params in queries:
        assert "FROM action_logs" in sql and "OFFSET" not in sql
        assert sql.endswith("LIMIT %s") and params == [7]


def test_facet_rows_read_the_same_from_either_kind_of_cursor():
    assert alq.facet_values([{"value": "w1", "label": "Refunds", "count": 3}]) == \
        [{"value": "w1", "label": "Refunds", "count": 3}]
    assert alq.facet_values([("approve", 2)]) == [{"value": "approve", "label": "approve", "count": 2}]
    assert alq.facet_values([("w1", None, 1)]) == [{"value": "w1", "label": "w1", "count": 1}]
    assert alq.facet_values([{"value": None, "count": 4}]) == []


# ------------------------------------------------------------------ parsing filters

def test_filters_are_trimmed_and_times_without_a_zone_are_utc():
    f = alq.make_filters(q="  refund ", username=" me@x.com ", since="2026-11-01T00:00:00",
                         until="2026-11-02T00:00:00Z")
    assert f.q == "refund" and f.username == "me@x.com"
    assert f.since == datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert f.until == datetime(2026, 11, 2, tzinfo=timezone.utc)


def test_bad_filters_are_refused_rather_than_ignored():
    assert "isn't a date" in raises(alq.make_filters, since="last tuesday")
    assert "before its end" in raises(alq.make_filters, since="2026-11-02", until="2026-11-01")
    assert "at most" in raises(alq.make_filters, q="x" * (alq.MAX_QUERY_LENGTH + 1))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
