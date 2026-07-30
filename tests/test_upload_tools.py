"""Standalone tests for the tools an agent uses to read an attached file.

The storage layer is stubbed out: what matters here is that a model's structured
query produces the right rows, that a bad argument comes back as advice the model
can act on rather than a traceback, and that document search cites pages.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import pandas as pd  # noqa: E402

from services import upload_store, upload_tools  # noqa: E402

TABLE = {
    "id": "up-table", "filename": "orders.xlsx", "kind": "table", "mime": "",
    "size_bytes": 2048, "warnings": [],
    "profile": {
        "primary_sheet": "Orders",
        "sheets": [{
            "name": "Orders", "member": "Orders.parquet", "rows": 6, "truncated": False,
            "columns": [
                {"name": "region", "dtype": "object", "nulls": 0, "unique": 3, "sample_values": ["EMEA"]},
                {"name": "units", "dtype": "int64", "nulls": 0, "unique": 6, "sample_values": [10]},
            ],
        }],
    },
}

DOCUMENT = {
    "id": "up-doc", "filename": "contract.pdf", "kind": "document", "mime": "application/pdf",
    "size_bytes": 9000, "warnings": [],
    "profile": {"pages": 3, "chars": 400, "words": 60, "headings": ["Term"], "preview": "Agreement"},
}

IMAGE = {
    "id": "up-img", "filename": "chart.png", "kind": "image", "mime": "image/png",
    "size_bytes": 1800, "warnings": [], "profile": {},
}

FRAME = pd.DataFrame({
    "region": ["EMEA", "EMEA", "APAC", "AMER", "APAC", None],
    "units": [10, 25, 7, 40, 13, 5],
    "price": [2.0, 4.0, 1.0, 5.0, 3.0, 6.0],
    "owner": ["ana", "bo", "cy", "dee", "eli", "fern"],
    "closed": pd.to_datetime(["2026-01-05", "2026-02-11", "2026-02-20", "2026-03-01", "2026-03-15", "2026-04-02"]),
})

PAGED_TEXT = (
    "[page 1]\nThis agreement begins on the commencement date.\n\n"
    "[page 2]\nTermination requires ninety days written notice to the counterparty.\n\n"
    "[page 3]\nGoverning law is the State of Delaware.\n"
)


def _install_stubs(frame=FRAME, text=PAGED_TEXT):
    """Point the tools at in-memory data instead of Postgres."""
    upload_store.load_table = lambda env, upload_id, sheet=None: frame  # type: ignore[assignment]
    upload_store.load_text = lambda env, upload_id: text  # type: ignore[assignment]


def _run(name, args, attachments=(TABLE, DOCUMENT)):
    _install_stubs()
    return upload_tools.run_tool("dev", name, args, list(attachments))


def test_query_filters_rows_and_reports_the_full_denominator():
    out = _run("query_file", {
        "file_id": "up-table",
        "filters": [{"column": "region", "op": "eq", "value": "EMEA"}],
    })
    assert "2 matching row(s) of 6" in out, out
    assert "ana" in out and "bo" in out
    assert "cy" not in out


def test_numeric_filter_accepts_a_string_value_from_the_model():
    # Models routinely send "20" for a numeric column; a string comparison against
    # an int column would either raise or silently match nothing.
    out = _run("query_file", {
        "file_id": "up-table",
        "filters": [{"column": "units", "op": "gt", "value": "20"}],
    })
    assert "2 matching row(s) of 6" in out, out
    assert "dee" in out


def test_group_by_with_aggregation_totals_every_row():
    out = _run("query_file", {
        "file_id": "up-table",
        "group_by": ["region"],
        "aggregations": [{"column": "units", "func": "sum", "alias": "total"}],
        "sort": [{"column": "total", "desc": True}],
    })
    # EMEA 35, APAC 20, AMER 40 -> AMER is the first data row (line 4, after the
    # header line, a blank, the column row and the separator).
    assert "AMER" in out.split("\n")[4], out
    assert "35" in out and "20" in out


def test_group_by_alone_counts_per_group():
    out = _run("query_file", {"file_id": "up-table", "group_by": ["region"]})
    assert "count" in out
    assert "group(s)" in out


def test_aggregation_without_group_by_returns_one_row():
    out = _run("query_file", {
        "file_id": "up-table",
        "aggregations": [{"column": "units", "func": "sum"}, {"column": "*", "func": "count"}],
    })
    assert "100" in out, out


def test_limit_and_offset_page_the_result():
    first = _run("query_file", {"file_id": "up-table", "columns": ["owner"], "limit": 2})
    assert "Showing rows 1-2 of 6" in first, first
    second = _run("query_file", {"file_id": "up-table", "columns": ["owner"], "limit": 2, "offset": 4})
    assert "Showing rows 5-6 of 6" in second, second
    assert "eli" in second and "ana" not in second


def test_contains_filter_is_case_insensitive_and_not_a_regex():
    out = _run("query_file", {
        "file_id": "up-table",
        "filters": [{"column": "owner", "op": "contains", "value": "AN"}],
    })
    assert "1 matching row(s)" in out, out
    # A regex-flavored value must be treated literally rather than blowing up.
    literal = _run("query_file", {
        "file_id": "up-table",
        "filters": [{"column": "owner", "op": "contains", "value": "a("}],
    })
    assert "0 matching row(s)" in literal, literal


def test_between_and_null_filters():
    ranged = _run("query_file", {
        "file_id": "up-table",
        "filters": [{"column": "units", "op": "between", "value": [10, 25]}],
    })
    assert "3 matching row(s) of 6" in ranged, ranged
    missing = _run("query_file", {
        "file_id": "up-table",
        "filters": [{"column": "region", "op": "is_null"}],
    })
    assert "1 matching row(s) of 6" in missing, missing


def test_computed_column_multiplies_row_by_row_then_aggregates():
    # The distinction that matters: sum(units * price) is not sum(units) * mean(price).
    out = _run("query_file", {
        "file_id": "up-table",
        "computed": [{"alias": "revenue", "left": "units", "op": "multiply", "right": "price"}],
        "group_by": ["region"],
        "aggregations": [{"column": "revenue", "func": "sum", "alias": "total"}],
    })
    # EMEA: 10*2 + 25*4 = 120. APAC: 7*1 + 13*3 = 46. AMER: 40*5 = 200.
    assert "120" in out and "46" in out and "200" in out, out


def test_computed_column_accepts_a_numeric_literal():
    out = _run("query_file", {
        "file_id": "up-table",
        "computed": [{"alias": "double", "left": "units", "op": "multiply", "right": 2}],
        "columns": ["owner", "double"],
        "sort": [{"column": "double", "desc": True}],
        "limit": 1,
    })
    assert "80" in out, out


def test_computed_date_part_supports_grouping_by_month():
    out = _run("query_file", {
        "file_id": "up-table",
        "computed": [{"alias": "month", "left": "closed", "op": "year_month"}],
        "group_by": ["month"],
        "aggregations": [{"column": "units", "func": "sum", "alias": "units"}],
        "sort": [{"column": "month"}],
    })
    assert "2026-01" in out and "2026-02" in out, out


def test_divide_by_zero_yields_no_value_rather_than_an_error():
    frame = pd.DataFrame({"a": [10, 5], "b": [2, 0]})
    _install_stubs(frame=frame)
    out = upload_tools.run_tool("dev", "query_file", {
        "file_id": "up-table",
        "computed": [{"alias": "ratio", "left": "a", "op": "divide", "right": "b"}],
        "columns": ["ratio"],
    }, [TABLE])
    assert "| 5 |" in out, out


def test_bad_computed_op_lists_the_supported_ones():
    out = _run("query_file", {
        "file_id": "up-table",
        "computed": [{"alias": "x", "left": "units", "op": "exponentiate", "right": 2}],
    })
    assert "Unsupported computed op 'exponentiate'" in out
    assert "multiply" in out


def test_unknown_column_returns_the_available_ones_instead_of_failing():
    out = _run("query_file", {
        "file_id": "up-table",
        "filters": [{"column": "regionn", "op": "eq", "value": "EMEA"}],
    })
    assert "No column 'regionn'" in out
    assert "region" in out and "units" in out


def test_unknown_file_id_lists_the_attached_files():
    out = _run("query_file", {"file_id": "nope"})
    assert "No attached file 'nope'" in out
    assert "orders.xlsx" in out and "contract.pdf" in out


def test_a_file_id_given_as_a_filename_still_resolves():
    out = _run("query_file", {"file_id": "orders.xlsx", "limit": 1})
    assert "matching row(s) of 6" in out, out


def test_querying_a_document_explains_what_to_use_instead():
    out = _run("query_file", {"file_id": "up-doc"})
    assert "not tabular" in out
    assert "search_file" in out


def test_bad_aggregation_is_reported_not_raised():
    out = _run("query_file", {
        "file_id": "up-table",
        "group_by": ["region"],
        "aggregations": [{"column": "units", "func": "wobble"}],
    })
    assert "Unsupported aggregation 'wobble'" in out


def test_search_cites_the_page_it_found():
    out = _run("search_file", {"file_id": "up-doc", "query": "How much notice to terminate?"})
    assert "[page 2]" in out, out
    assert "ninety days" in out


def test_search_without_a_match_suggests_reading_instead():
    out = _run("search_file", {"file_id": "up-doc", "query": "indemnification carveouts"})
    assert "Nothing in" in out
    assert "read_file" in out


def test_search_on_a_scanned_document_says_so():
    upload_store.load_text = lambda env, upload_id: "   "  # type: ignore[assignment]
    out = upload_tools.run_tool("dev", "search_file", {"file_id": "up-doc", "query": "term"}, [DOCUMENT])
    assert "scanned" in out


def test_read_returns_a_requested_page_and_rejects_one_that_does_not_exist():
    good = _run("read_file", {"file_id": "up-doc", "page": 3})
    assert "Delaware" in good
    bad = _run("read_file", {"file_id": "up-doc", "page": 9})
    assert "No page 9" in bad


def test_read_pages_a_table_by_rows():
    out = _run("read_file", {"file_id": "up-table", "offset": 2, "limit": 2})
    assert "rows 3-4 of 6" in out, out
    assert "cy" in out and "dee" in out


def test_read_a_document_reports_how_to_continue():
    _install_stubs(text="x" * 9000)
    out = upload_tools.run_tool("dev", "read_file", {"file_id": "up-doc", "limit": 500}, [DOCUMENT])
    assert "Continue with offset=500" in out, out


def test_inspect_lists_every_column_for_a_table():
    out = _run("inspect_file", {"file_id": "up-table"})
    assert "Sheet 'Orders'" in out
    assert "region" in out and "int64" in out


def test_tool_specs_follow_the_kinds_attached():
    table_only = {s["function"]["name"] for s in upload_tools.tool_specs([TABLE])}
    assert "query_file" in table_only
    assert "search_file" not in table_only
    doc_only = {s["function"]["name"] for s in upload_tools.tool_specs([DOCUMENT])}
    assert "query_file" not in doc_only
    assert "search_file" in doc_only
    assert upload_tools.tool_specs([]) == []


def test_prompt_block_names_the_file_id_and_warns_against_guessing():
    block = upload_tools.attachments_prompt([TABLE, IMAGE])
    assert "file_id `up-table`" in block
    assert "orders.xlsx" in block
    # The card is a summary; the agent must be told not to answer from it.
    assert "never claim a total" in block
    assert "query_file" in block
    assert "images are included directly" in block


def test_result_tables_cap_their_width():
    wide = pd.DataFrame({f"c{i}": [i] for i in range(60)})
    _install_stubs(frame=wide)
    out = upload_tools.run_tool("dev", "query_file", {"file_id": "up-table"}, [TABLE])
    header = out.split("\n")[2]
    assert header.count("|") == upload_tools.MAX_COLUMNS + 1, header
    assert "further column(s) not shown" in out


if __name__ == "__main__":
    tests = [
        test_query_filters_rows_and_reports_the_full_denominator,
        test_numeric_filter_accepts_a_string_value_from_the_model,
        test_group_by_with_aggregation_totals_every_row,
        test_group_by_alone_counts_per_group,
        test_aggregation_without_group_by_returns_one_row,
        test_limit_and_offset_page_the_result,
        test_contains_filter_is_case_insensitive_and_not_a_regex,
        test_between_and_null_filters,
        test_computed_column_multiplies_row_by_row_then_aggregates,
        test_computed_column_accepts_a_numeric_literal,
        test_computed_date_part_supports_grouping_by_month,
        test_divide_by_zero_yields_no_value_rather_than_an_error,
        test_bad_computed_op_lists_the_supported_ones,
        test_unknown_column_returns_the_available_ones_instead_of_failing,
        test_unknown_file_id_lists_the_attached_files,
        test_a_file_id_given_as_a_filename_still_resolves,
        test_querying_a_document_explains_what_to_use_instead,
        test_bad_aggregation_is_reported_not_raised,
        test_search_cites_the_page_it_found,
        test_search_without_a_match_suggests_reading_instead,
        test_search_on_a_scanned_document_says_so,
        test_read_returns_a_requested_page_and_rejects_one_that_does_not_exist,
        test_read_pages_a_table_by_rows,
        test_read_a_document_reports_how_to_continue,
        test_inspect_lists_every_column_for_a_table,
        test_tool_specs_follow_the_kinds_attached,
        test_prompt_block_names_the_file_id_and_warns_against_guessing,
        test_result_tables_cap_their_width,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
