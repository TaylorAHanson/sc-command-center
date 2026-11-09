"""Tests for drafts and publishing.

What matters is what reaches people who can only use an object: nothing a
manager is halfway through, and on publish exactly the draft — with the parts
that describe a version (certification, retirement) reset rather than copied.
The SQL is run against a small fake that keeps rows in memory, enough to follow
a draft from first save to second publish.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from fastapi import HTTPException
    from services import drafts
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_drafts: {e}")
    sys.exit(0)

WIDGET_COLUMNS = ["id", "version", "name", "tsx_code", "created_by", "is_certified", "is_deprecated",
                  "timestamp", "published_by", "published_at"]


class FakeCursor:
    """Just the statements drafts.py issues, over in-memory tables."""

    def __init__(self):
        self.drafts = {}
        self.widgets = []
        self.description = None
        self._result = []
        self.rowcount = 0

    def _set(self, names, rows):
        self.description = [(n,) for n in names]
        self._result = [tuple(r.get(n) for n in names) for r in rows]

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("SELECT payload, base_version"):
            d = self.drafts.get(tuple(params))
            self._set(["payload", "base_version", "updated_by", "updated_at"], [d] if d else [])
        elif s.startswith("SELECT object_id, payload"):
            rows = [{"object_id": k[1], **v} for k, v in self.drafts.items() if k[0] == params[0]]
            self._set(["object_id", "payload", "base_version", "updated_by", "updated_at"], rows)
        elif s.startswith("INSERT INTO object_drafts"):
            t, i, payload, base, user = params
            self.drafts[(t, i)] = {"payload": payload.adapted, "base_version": base, "updated_by": user,
                                   "updated_at": datetime.datetime(2026, 11, 9)}
        elif s.startswith("DELETE FROM object_drafts"):
            self.rowcount = 1 if self.drafts.pop(tuple(params), None) else 0
        elif s.startswith("SELECT * FROM widgets LIMIT 0"):
            self._set(WIDGET_COLUMNS, [])
        elif s.startswith("SELECT * FROM widgets WHERE id = %s AND version = %s"):
            self._set(WIDGET_COLUMNS, [r for r in self.widgets if (r["id"], r["version"]) == tuple(params)])
        elif s.startswith("SELECT * FROM widgets WHERE id = %s"):
            rows = [r for r in self.widgets if r["id"] == params[0]]
            if "is_deprecated" in s:
                rows = [r for r in rows if not r.get("is_deprecated")]
            self._set(WIDGET_COLUMNS, sorted(rows, key=lambda r: -r["version"])[:1])
        elif s.startswith("SELECT COALESCE(MAX(version), 0)"):
            versions = [r["version"] for r in self.widgets if r["id"] == params[0]]
            self._set(["v"], [{"v": max(versions or [0])}])
        elif s.startswith("INSERT INTO widgets"):
            names = s[s.index("(") + 1:s.index(")")].split(", ")
            row = dict(zip(names, list(params) + [datetime.datetime(2026, 11, 9)]))
            self.widgets.append(row)
        else:
            raise AssertionError(f"unexpected SQL: {s}")

    def fetchall(self):
        return self._result


def published(c, version, **cols):
    c.widgets.append({"id": "w1", "version": version, "name": "Stock", "tsx_code": "v%d" % version,
                      "created_by": "ana@example.com", "is_certified": 0, "is_deprecated": 0, **cols})


def test_states_read_the_way_the_ui_labels_them():
    assert drafts.state_of(True, None) == "draft_only"
    assert drafts.state_of(False, 4) == "published"
    assert drafts.state_of(True, 4) == "published_with_draft"


def test_a_payload_leaves_out_identity_and_publish_stamps():
    row = {"id": "w1", "version": 3, "timestamp": datetime.datetime(2026, 1, 1), "published_by": "x",
           "published_at": None, "name": "Stock", "updated": datetime.date(2026, 2, 3)}
    assert drafts.payload_of(row) == {"name": "Stock", "updated": "2026-02-03"}


def test_publishing_never_copies_certification():
    # Certification is a review of particular code; the new version hasn't had one.
    out = drafts.insert_columns("widget", {"name": "x", "is_certified": 1, "is_deprecated": 1, "nope": 1},
                                WIDGET_COLUMNS)
    assert out == {"name": "x", "is_certified": 0, "is_deprecated": 0}


def test_views_keep_every_column_they_have():
    out = drafts.insert_columns("app", {"name": "x", "layout": "[]"}, ["id", "version", "name", "layout"])
    assert out == {"name": "x", "layout": "[]"}


def test_a_manager_sees_the_draft_over_what_is_published():
    merged = drafts.merge({"id": "w1", "version": 2, "name": "Old", "tsx_code": "a"},
                          {"payload": {"name": "New"}, "base_version": 2, "updated_by": "ana", "updated_at": None},
                          "w1")
    assert merged["name"] == "New" and merged["tsx_code"] == "a"
    assert merged["is_draft"] is True and merged["version"] == 2


def test_a_draft_that_was_never_published_is_version_zero():
    merged = drafts.merge(None, {"payload": {"name": "New"}, "base_version": None}, "w9")
    assert merged["id"] == "w9" and merged["version"] == 0


def test_unknown_object_types_are_refused():
    try:
        drafts.read(FakeCursor(), "dashboard", "x")
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("expected a 400")


def test_people_who_can_only_use_never_see_the_draft():
    c = FakeCursor()
    published(c, 1)
    drafts.save(c, "widget", "w1", {"name": "Stock", "tsx_code": "work in progress"}, "ana@example.com")
    assert drafts.current(c, "widget", "w1", "USE")["tsx_code"] == "v1"
    assert drafts.current(c, "widget", "w1", "MANAGE")["tsx_code"] == "work in progress"


def test_a_draft_remembers_the_version_it_started_from():
    c = FakeCursor()
    published(c, 3)
    drafts.save(c, "widget", "w1", {"tsx_code": "a"}, "ana")
    drafts.save(c, "widget", "w1", {"tsx_code": "b"}, "ana")
    held = drafts.read(c, "widget", "w1")
    assert held["base_version"] == 3 and held["payload"] == {"tsx_code": "b"}


def test_publishing_makes_the_next_version_and_drops_the_draft():
    c = FakeCursor()
    published(c, 1, is_certified=1)
    drafts.save(c, "widget", "w1", {"name": "Stock", "tsx_code": "v2 code", "is_certified": 1,
                                    "created_by": "ana@example.com"}, "bo@example.com")
    assert drafts.publish(c, "widget", "w1", "bo@example.com") == 2
    assert drafts.read(c, "widget", "w1") is None
    new = drafts.latest(c, "widget", "w1")
    assert new["version"] == 2 and new["tsx_code"] == "v2 code"
    assert new["is_certified"] == 0 and new["published_by"] == "bo@example.com"
    # Who made it stays who made it; publishing isn't authorship.
    assert new["created_by"] == "ana@example.com"


def test_retired_versions_still_count_when_numbering():
    # Reusing a retired number would give two different widgets the same version.
    c = FakeCursor()
    published(c, 1)
    published(c, 2, is_deprecated=1)
    drafts.save(c, "widget", "w1", {"tsx_code": "x"}, "ana")
    assert drafts.publish(c, "widget", "w1", "ana") == 3


def test_publishing_with_nothing_to_publish_is_a_conflict():
    c = FakeCursor()
    published(c, 1)
    try:
        drafts.publish(c, "widget", "w1", "ana")
    except HTTPException as e:
        assert e.status_code == 409
    else:
        raise AssertionError("expected a 409")


def test_a_never_published_widget_publishes_as_version_one():
    c = FakeCursor()
    drafts.save(c, "widget", "w1", {"name": "New", "tsx_code": "x"}, "ana")
    assert drafts.current(c, "widget", "w1", "USE") is None
    assert drafts.publish(c, "widget", "w1", "ana") == 1


def test_reverting_puts_an_old_version_in_the_draft_only():
    c = FakeCursor()
    published(c, 1)
    published(c, 2)
    drafts.revert(c, "widget", "w1", 1, "ana")
    assert drafts.current(c, "widget", "w1", "USE")["tsx_code"] == "v2"
    assert drafts.read(c, "widget", "w1")["payload"]["tsx_code"] == "v1"
    assert drafts.read(c, "widget", "w1")["base_version"] == 2


def test_reverting_to_a_missing_version_is_not_found():
    c = FakeCursor()
    published(c, 1)
    try:
        drafts.revert(c, "widget", "w1", 7, "ana")
    except HTTPException as e:
        assert e.status_code == 404
    else:
        raise AssertionError("expected a 404")


def test_discarding_reports_whether_there_was_a_draft():
    c = FakeCursor()
    drafts.save(c, "widget", "w1", {"tsx_code": "x"}, "ana")
    assert drafts.discard(c, "widget", "w1") is True
    assert drafts.discard(c, "widget", "w1") is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
