"""Tests for removing a view: archive, restore, and delete permanently.

Deleting a view takes every version and its draft away for good, so a view other
people can open must be archived first, where someone could notice it gone. A
view only its owner can see is theirs to delete outright, as closing it always
has been. All of it needs Can manage. What is pinned here is the order of those
steps and who may take them, against the fake content store and access list in
`test_apps_routes.py` — enough to see that a refused request wrote nothing,
which is the part a mistake would get wrong.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from test_apps_routes import ME, OTHER, MANAGE, USE, Store, apps, draft_of, refused, row, run  # noqa: E402


def private():
    return Store(row("v1", owner=ME), acl={"v1": {ME: MANAGE}})


def shared(archived=False, level=MANAGE):
    return Store(row("v1", owner=OTHER), acl={"v1": {OTHER: MANAGE, ME: level}},
                 archived={"v1"} if archived else ())


def test_archiving_records_who_and_keeps_every_version():
    store = shared()
    assert run(store, apps.archive_app, "v1")["archived"] is True
    inserts = [p for s, p in store.statements if s.startswith("INSERT INTO archived_views")]
    assert inserts == [("v1", ME)] and store.committed
    assert not [s for s, _ in store.writes() if s.startswith("DELETE")], "archiving deletes nothing"


def test_archiving_a_view_that_does_not_exist_is_a_404():
    store = Store(acl={"nope": {ME: MANAGE}})
    assert refused(store, apps.archive_app, "nope").status_code == 404


def test_only_a_manager_may_archive():
    store = shared(level=USE)
    assert refused(store, apps.archive_app, "v1").status_code == 403
    assert store.writes() == []
    assert refused(Store(row("v1")), apps.archive_app, "v1").status_code == 404, "no access reads as missing"


def test_restoring_clears_the_archive_and_nothing_else():
    store = shared(archived=True)
    run(store, apps.restore_app, "v1")
    assert store.archived == set() and len(store.versions("v1")) == 1 and store.committed


def test_restoring_needs_the_same_right_as_archiving():
    store = shared(archived=True, level=USE)
    assert refused(store, apps.restore_app, "v1").status_code == 403
    assert store.writes() == []


def test_a_shared_view_cannot_be_deleted_until_it_is_archived():
    store = shared()
    exc = refused(store, apps.delete_app, "v1")
    assert exc.status_code == 409 and "Archive" in exc.detail
    assert store.writes() == [] and store.acl_deleted == []


def test_an_archived_view_is_deleted_for_good_with_its_draft_names_and_access_list():
    store = shared(archived=True)
    store.drafts[("app", "v1")] = draft_of(row("v1"))
    store.links = {"v1-name": "v1"}
    store.hidden = {(OTHER, "v1")}
    run(store, apps.delete_app, "v1")
    assert store.versions("v1") == [] and ("app", "v1") not in store.drafts
    # The marker goes with the view, or the id would stay hidden if it were reused.
    assert store.archived == set() and store.links == {} and store.hidden == set()
    assert store.acl_deleted == [("app", "v1")]


def test_deleting_for_good_still_needs_can_manage():
    store = shared(archived=True, level=USE)
    assert refused(store, apps.delete_app, "v1").status_code == 403
    assert store.writes() == []


def test_a_view_only_its_owner_can_see_is_deleted_outright():
    store = private()
    run(store, apps.delete_app, "v1")
    assert store.versions("v1") == [] and store.acl_deleted == [("app", "v1")]


def test_a_draft_nobody_else_has_seen_is_deleted_outright():
    store = Store(drafts={"d1": draft_of(row("d1", owner=ME))}, acl={"d1": {ME: MANAGE}})
    run(store, apps.delete_app, "d1")
    assert ("app", "d1") not in store.drafts


def test_the_archive_lists_only_views_the_caller_manages():
    store = Store(row("a", name="Orders"), row("b", name="Margins"), archived={"a", "b"},
                  acl={"a": {ME: MANAGE}, "b": {OTHER: MANAGE, ME: USE}})
    assert [v["id"] for v in run(store, apps.list_archived_apps)["apps"]] == ["a"]
    assert [v["id"] for v in run(store, apps.list_archived_apps, admin=True)["apps"]] == ["a", "b"]


def test_an_archived_draft_is_listed_by_its_draft_name():
    store = Store(drafts={"d1": draft_of(row("d1"), name="Soon")}, archived={"d1"}, acl={"d1": {ME: MANAGE}})
    (listed,) = run(store, apps.list_archived_apps)["apps"]
    assert (listed["name"], listed["version"]) == ("Soon", 0)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
