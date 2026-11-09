"""Tests for the rules behind sharing: who an entry matches and what level wins.

These are the decisions every view, widget and agent request goes through, so a
mistake here is either a leak (someone reaches what wasn't shared with them) or
a lockout (an owner can't reach their own work). The storage around them is
exercised against a real database; the rules are pure and tested here.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from fastapi import HTTPException
    from services import access
    from services.access import Caller
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_access: {e}")
    sys.exit(0)

ME = "ana@example.com"
SP = "5f2b6c1e-3a4d-4e8f-9b0a-1c2d3e4f5a6b"


def entry(principal, level, ptype=None):
    return {"principal": principal, "principal_type": ptype or access.infer_type(principal), "level": level}


def raises(fn, status):
    try:
        fn()
    except HTTPException as e:
        assert e.status_code == status, e.status_code
        return e.detail
    raise AssertionError("expected an HTTPException")


def test_names_are_typed_the_way_people_write_them():
    assert access.infer_type(ME) == "user"
    # A service principal signs in under its application id.
    assert access.infer_type(SP) == "user"
    assert access.infer_type("supply-planners") == "group"
    assert access.infer_type("*") == "all"


def test_everyone_matches_anyone_signed_in():
    assert access.best_level([entry("*", "USE")], "someone@else.com", []) == "USE"


def test_users_match_without_regard_to_case():
    # Databricks treats user names case-insensitively; an ACL typed with capitals
    # must not lock that person out.
    assert access.best_level([entry("Ana@Example.com", "MANAGE")], ME, []) == "MANAGE"


def test_groups_match_exactly():
    assert access.best_level([entry("planners", "USE", "group")], ME, ["planners"]) == "USE"
    assert access.best_level([entry("Planners", "USE", "group")], ME, ["planners"]) is None


def test_a_user_entry_never_matches_a_group_of_the_same_name():
    assert access.best_level([entry("planners", "USE", "user")], ME, ["planners"]) is None


def test_the_highest_level_wins():
    entries = [entry("*", "USE"), entry("planners", "MANAGE", "group"), entry(ME, "USE")]
    assert access.best_level(entries, ME, ["planners"]) == "MANAGE"


def test_nothing_shared_is_no_access():
    assert access.best_level([entry("bob@example.com", "MANAGE")], ME, ["planners"]) is None
    assert access.best_level([], ME, []) is None


def test_unknown_levels_grant_nothing():
    assert access.best_level([{"principal": ME, "principal_type": "user", "level": "OWNER"}], ME, []) is None


def test_normalising_keeps_the_higher_of_two_entries_for_one_person():
    out = access.normalise_entries([entry(ME, "USE"), entry("ANA@example.com", "MANAGE")])
    assert len(out) == 1 and out[0]["level"] == "MANAGE"


def test_normalising_fills_in_the_type_and_level_case():
    out = access.normalise_entries([{"principal": " planners ", "level": "use"}])
    assert out == [{"principal": "planners", "principal_type": "group", "level": "USE"}]


def test_everyone_is_always_typed_all():
    out = access.normalise_entries([{"principal": "*", "principal_type": "group", "level": "USE"}])
    assert out[0]["principal_type"] == "all"


def test_bad_entries_are_refused_with_a_readable_reason():
    assert "name" in raises(lambda: access.normalise_entries([{"principal": " ", "level": "USE"}]), 400)
    assert "Can use" in raises(lambda: access.normalise_entries([{"principal": ME, "level": "OWN"}]), 400)
    raises(lambda: access.normalise_entries([{"principal": "planners", "principal_type": "all", "level": "USE"}]), 400)
    raises(lambda: access.normalise_entries([{"principal": ME, "principal_type": "robot", "level": "USE"}]), 400)


def test_a_list_nobody_can_manage_is_refused():
    who = Caller(ME, (), False)
    detail = raises(lambda: access.check_keeps_a_manager([entry("*", "USE")], who), 400)
    assert "Can manage" in detail
    access.check_keeps_a_manager([entry("planners", "MANAGE")], who)


def test_an_admin_may_leave_an_object_with_no_manager():
    # Admins can always reach it again, which is the point of the guard.
    access.check_keeps_a_manager([], Caller(ME, (), True))


def test_entries_sort_managers_first_then_people_then_groups():
    out = access.sort_entries([entry("*", "USE"), entry("zed", "USE"), entry(ME, "USE"), entry("b@x.com", "MANAGE")])
    assert [e["principal"] for e in out] == ["b@x.com", ME, "zed", "*"]


def test_summaries_match_the_icon_people_see():
    assert access.summary_of([entry(ME, "MANAGE")], owner=ME) == "private"
    assert access.summary_of([entry(ME, "MANAGE"), entry("planners", "USE")], owner=ME) == "shared"
    assert access.summary_of([entry(ME, "MANAGE"), entry("*", "USE")], owner=ME) == "everyone"


def test_admins_hold_manage_without_a_query():
    admin = Caller(ME, (), True)
    assert access.level_for(admin, "app", "anything") == "MANAGE"
    assert access.levels_for(admin, "widget", ["a", "b", "a", ""]) == {"a": "MANAGE", "b": "MANAGE"}
    assert access.visible_ids(admin, "agent") is None


def test_no_ids_is_no_query():
    assert access.levels_for(Caller(ME, (), False), "app", []) == {}


def _with_level(level):
    original = access.level_for
    access.level_for = lambda who, t, i: level
    return original


def test_no_access_reads_as_missing():
    # A 403 would confirm the id exists to someone it wasn't shared with.
    original = _with_level(None)
    try:
        raises(lambda: access.require(Caller(ME, (), False), "app", "x"), 404)
    finally:
        access.level_for = original


def test_use_is_not_enough_to_manage():
    original = _with_level("USE")
    try:
        detail = raises(lambda: access.require(Caller(ME, (), False), "widget", "x", access.MANAGE), 403)
        assert "Can manage on this widget" in detail
        assert access.require(Caller(ME, (), False), "widget", "x") == "USE"
    finally:
        access.level_for = original


def test_the_kill_switch_makes_everyone_an_admin_but_keeps_who_they_are():
    from services import caller_identity

    saved = (os.environ.get("DISABLE_PERMISSION_CHECKS"), caller_identity.username, caller_identity.entitlements,
             access._record)
    os.environ["DISABLE_PERMISSION_CHECKS"] = "true"
    caller_identity.username = lambda w: ME
    caller_identity.entitlements = lambda w: ["planners"]
    access._record = lambda *a: None
    try:
        who = access.caller(object())
        assert who == Caller(ME, ("planners",), True)
    finally:
        if saved[0] is None:
            os.environ.pop("DISABLE_PERMISSION_CHECKS", None)
        else:
            os.environ["DISABLE_PERMISSION_CHECKS"] = saved[0]
        caller_identity.username, caller_identity.entitlements, access._record = saved[1:]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
