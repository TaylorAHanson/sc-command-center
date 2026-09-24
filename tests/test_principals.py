"""Tests for checking a role-mapping name against Databricks before it is saved.

A mapping is matched against a user's groups exactly, so the verdicts that matter
are the ones a free-text box used to let through: a name that exists with other
capitals, and one that doesn't exist at all. Both must block; a lookup that
couldn't run must not, or an outage would make access control uneditable.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from services import principals
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_principals: {e}")
    sys.exit(0)


class FakeApi:
    def __init__(self, groups=(), users=(), fail=False):
        self.groups, self.users, self.fail = list(groups), list(users), fail
        self.calls = []

    def do(self, method, path, query=None):
        self.calls.append((path, dict(query or {})))
        if self.fail:
            raise RuntimeError("SCIM unavailable")
        if path.endswith("/Groups"):
            return {"Resources": [{"displayName": g} for g in self.groups]}
        return {"Resources": [{"userName": u} for u in self.users]}


class FakeClient:
    def __init__(self, **kw):
        self.api_client = FakeApi(**kw)


def test_an_exact_group_is_accepted():
    v = principals.check(FakeClient(groups=["supply-admins"]), "supply-admins")
    assert v["status"] == "group" and not principals.is_blocking(v)


def test_an_exact_user_is_accepted():
    v = principals.check(FakeClient(users=["a@x.com"]), "a@x.com")
    assert v["status"] == "user" and not principals.is_blocking(v)


def test_a_different_case_is_refused_with_the_right_spelling():
    # SCIM finds it; the permission check never would.
    v = principals.check(FakeClient(groups=["supply-admins"]), "Supply-Admins")
    assert v["status"] == "mismatch" and v["suggestion"] == "supply-admins"
    assert principals.is_blocking(v)


def test_a_name_nobody_holds_is_refused():
    v = principals.check(FakeClient(), "typo-admins")
    assert v["status"] == "unknown" and principals.is_blocking(v)


def test_a_failed_lookup_lets_the_save_through():
    v = principals.check(FakeClient(fail=True), "anything")
    assert v["status"] == "unverified" and not principals.is_blocking(v)


def test_blank_is_not_a_principal():
    assert principals.is_blocking(principals.check(FakeClient(), "  "))


def test_quotes_cannot_escape_the_filter():
    assert principals.filter_literal('a" or displayName pr "') == "a or displayName pr"
    assert principals.filter_literal("back\\slash") == "backslash"


def test_a_name_with_quotes_is_unknown_without_asking_scim():
    client = FakeClient(groups=['weird"name'])
    v = principals.check(client, 'weird"name')
    assert v["status"] == "unknown" and client.api_client.calls == []


def test_search_lists_groups_before_anything_is_typed_but_not_users():
    # An unfiltered user list is the whole directory in arbitrary order.
    client = FakeClient(groups=["b", "A"], users=["u@x.com"])
    out = principals.search(client, "")
    assert out["groups"] == ["A", "b"] and out["users"] == []
    assert all("/Users" not in path for path, _ in client.api_client.calls)


def test_search_reports_an_outage_instead_of_an_empty_directory():
    out = principals.search(FakeClient(fail=True), "adm")
    assert out["available"] is False and out["groups"] == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
