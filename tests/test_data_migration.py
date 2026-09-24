"""Tests for moving a deployment's data between apps as a snapshot file.

What is pinned here is what decides whether a migration is safe to repeat and
survives the trip through JSON: which rows a merge skips, that serial ids are left
to the target, that bytes and timestamps come back as themselves, and that a file
that isn't a snapshot is refused before anything is written. The SQL itself needs
a database and is exercised against one by hand, not here.
"""
import datetime as dt
import decimal
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from services import data_migration as dm
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_data_migration: {e}")
    sys.exit(0)


def roundtrip(value):
    return dm.decode_value(json.loads(json.dumps(dm.encode_value(value))))


def test_bytes_survive_json_as_bytes():
    # chat_uploads.raw is the original file. Written back as base64 text it would
    # be a file nobody can open.
    raw = b"\x00\x1f\x8b binary \xff"
    assert roundtrip(raw) == raw
    assert roundtrip(memoryview(raw)) == raw


def test_timestamps_become_strings_postgres_reads_back():
    stamp = dt.datetime(2026, 9, 24, 10, 30, 5, 123456)
    assert dm.encode_value(stamp) == "2026-09-24T10:30:05.123456"


def test_plain_values_pass_through():
    for value in (None, 0, 3, "text", True):
        assert roundtrip(value) == value
    assert dm.encode_value(decimal.Decimal("1.50")) == "1.50"


def test_a_dict_that_merely_mentions_b64_is_not_bytes():
    assert dm.decode_value({"$b64": "AA==", "other": 1}) == {"$b64": "AA==", "other": 1}


def test_merge_skips_versions_the_target_already_has():
    spec = dm.SPECS["widgets"]
    cols = ["id", "version", "name"]
    rows = [["w1", 1, "A"], ["w1", 2, "A2"], ["w2", 1, "B"]]
    keep, skipped = dm.plan_merge(rows, cols, spec, [("w1", 1)])
    assert keep == [["w1", 2, "A2"], ["w2", 1, "B"]]
    assert skipped == 1


def test_a_repeated_merge_writes_nothing():
    spec = dm.SPECS["widget_runs"]
    cols = ["id", "widget_id", "username", "timestamp"]
    rows = [[1, "w1", "a@x.com", "2026-01-01T00:00:00"], [2, "w1", None, "2026-01-02T00:00:00"]]
    existing = [dm.row_key(r, cols, spec.key) for r in rows]
    keep, skipped = dm.plan_merge(rows, cols, spec, existing)
    assert keep == [] and skipped == 2


def test_identical_activity_rows_are_counted_not_collapsed():
    # Two identical rows are two events. A key the target holds once skips one of
    # them, not both — otherwise a merge would quietly lose history.
    spec = dm.SPECS["widget_runs"]
    cols = ["id", "widget_id", "username", "timestamp"]
    twin = ["w1", "a@x.com", "2026-01-01T00:00:00"]
    rows = [[1] + twin, [2] + twin]
    keep, skipped = dm.plan_merge(rows, cols, spec, [tuple(twin)])
    assert skipped == 1 and len(keep) == 1


def test_serial_ids_are_never_the_merge_key():
    # The two databases numbered their rows independently; id 7 in dev and id 7 in
    # test are unrelated role mappings.
    for spec in dm.TABLES:
        if spec.serial:
            assert "id" not in spec.key, spec.name


def test_merge_leaves_serial_ids_to_the_target():
    spec = dm.SPECS["role_mappings"]
    cols, dropped = dm.choose_columns(["id", "external_role", "domain", "permission_level"],
                                      ["id", "external_role", "domain", "permission_level", "timestamp"],
                                      spec, "merge")
    assert cols == ["external_role", "domain", "permission_level"] and dropped == []


def test_replace_keeps_serial_ids():
    spec = dm.SPECS["role_mappings"]
    cols, _ = dm.choose_columns(["id", "external_role"], ["id", "external_role"], spec, "replace")
    assert cols == ["id", "external_role"]


def test_columns_the_target_lacks_are_reported_not_written():
    # A snapshot from a newer app may carry a column this one hasn't added yet.
    spec = dm.SPECS["widgets"]
    cols, dropped = dm.choose_columns(["id", "version", "shiny_new"], ["id", "version", "name"], spec, "merge")
    assert cols == ["id", "version"] and dropped == ["shiny_new"]


def test_every_table_the_schema_creates_is_covered():
    # A table added to init_db and forgotten here would be silently left behind by
    # every migration.
    source = open(os.path.join(os.path.dirname(__file__), "..", "server", "database.py")).read()
    import re
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", source))
    assert created == set(dm.SPECS), created ^ set(dm.SPECS)


def test_every_table_belongs_to_a_known_group():
    for spec in dm.TABLES:
        assert spec.group in dm.GROUP_KEYS, spec.name


def test_conversations_are_opt_in():
    # Everyone's chats and attached files, in a file anyone holding it can read.
    assert next(g for g in dm.GROUPS if g["key"] == "conversations")["default"] is False


def snapshot(**tables):
    return {"format": dm.FORMAT, "format_version": dm.FORMAT_VERSION, "tables": tables}


def test_a_well_formed_snapshot_is_accepted():
    assert dm.validate_snapshot(snapshot(widgets={"columns": ["id", "version"], "rows": [["a", 1]]})) == []


def test_other_files_are_refused():
    assert dm.validate_snapshot([1, 2]) != []
    assert dm.validate_snapshot({"tables": {}}) != []


def test_a_newer_format_is_refused_with_a_reason():
    problems = dm.validate_snapshot({"format": dm.FORMAT, "format_version": dm.FORMAT_VERSION + 1, "tables": {}})
    assert problems and "newer" in problems[0]


def test_column_names_are_checked_before_they_reach_sql():
    # Column names are interpolated (quoted) into INSERTs, so a snapshot is not
    # allowed to smuggle anything else in as one.
    bad = snapshot(widgets={"columns": ['id", "x'], "rows": []})
    assert dm.validate_snapshot(bad) != []


def test_ragged_rows_are_refused():
    bad = snapshot(widgets={"columns": ["id", "version"], "rows": [["a"]]})
    assert dm.validate_snapshot(bad) != []


def test_unknown_tables_are_ignored_not_fatal():
    ok = snapshot(from_the_future={"columns": ["x"], "rows": [[1]]})
    assert dm.validate_snapshot(ok) == []


def test_groups_select_their_tables():
    names = [t.name for t in dm.tables_for(["access"])]
    assert names == ["widget_categories", "widget_domains", "role_mappings"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
