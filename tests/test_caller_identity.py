"""Tests for resolving who is calling.

This string is not cosmetic: views, conversations, uploads and widgets are all
owned by it, and a widget can write it into a table of its own. A placeholder
that reads like a person is therefore the worst possible failure mode — it is
indistinguishable from real attribution afterwards. Widgets published in
production were credited to "unknown", and locally to "dev", for exactly that
reason, which is what most of these tests exist to prevent recurring.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import caller_identity  # noqa: E402


class Client:
    """A WorkspaceClient stand-in, answering (or refusing) the SCIM Me call."""

    def __init__(self, user_name=None, fail=False, token="tok"):
        self.user_name = user_name
        self.fail = fail
        self.config = type("Config", (), {"host": "https://example", "token": token, "client_id": None})()
        outer = self

        class Api:
            def do(self, method, path):
                if outer.fail:
                    raise RuntimeError("SCIM is having a moment")
                return {"userName": outer.user_name, "groups": [], "roles": []}

        class CurrentUser:
            def me(self):
                raise RuntimeError("SDK path not used in these tests")

        self.api_client = Api()
        # Mirrors the real SDK: a property returning an object that is NOT callable.
        # Code that does `w.current_user()` raises here, which is the bug that made
        # every widget anonymous.
        self.current_user = CurrentUser()


def setup_function():
    caller_identity.invalidate()
    for var in ("DEV_MODE", "DEV_USERNAME"):
        os.environ.pop(var, None)


teardown_function = setup_function


def test_a_resolved_caller_is_returned_as_is():
    assert caller_identity.username(Client("ana@example.com")) == "ana@example.com"


def test_a_failed_lookup_says_unknown_rather_than_guessing():
    assert caller_identity.username(Client(fail=True, token="a")) == "unknown"
    assert caller_identity.username(None) == "unknown"


def test_no_caller_ever_resolves_to_dev():
    # The literal that ended up in a customer table. It must not come back.
    os.environ["DEV_MODE"] = "true"
    for client in (None, Client(fail=True, token="b"), Client(user_name="", token="c")):
        assert caller_identity.username(client) != "dev"


def test_local_development_can_name_itself():
    # A local run authenticates as a service principal, which SCIM answers for
    # with an application id or nothing. DEV_USERNAME lets a developer own the
    # rows they create instead of a shared placeholder.
    os.environ["DEV_MODE"] = "true"
    os.environ["DEV_USERNAME"] = "taylor@example.com"
    assert caller_identity.username(Client(fail=True, token="d")) == "taylor@example.com"


def test_the_dev_override_never_applies_in_a_deployment():
    # Set in the environment but DEV_MODE off: a deployment must not be able to
    # relabel its users by setting one variable.
    os.environ["DEV_USERNAME"] = "taylor@example.com"
    assert caller_identity.username(Client(fail=True, token="e")) == "unknown"


def test_the_override_does_not_displace_a_real_identity():
    os.environ["DEV_MODE"] = "true"
    os.environ["DEV_USERNAME"] = "taylor@example.com"
    assert caller_identity.username(Client("ana@example.com", token="f")) == "ana@example.com"


APPLICATION_ID = "4f1c9b2a-7d3e-4a55-9c18-0b6e2f7a1d34"


def test_a_service_principal_id_is_replaced_by_the_developers_own_name():
    # The usual local outcome, and the one the override missed: SCIM answers for a
    # service principal with its application id, which is not "unknown", so the
    # UUID sailed through and got stamped on everything built locally.
    os.environ["DEV_MODE"] = "true"
    os.environ["DEV_USERNAME"] = "taylor@example.com"
    assert caller_identity.username(Client(APPLICATION_ID, token="sp")) == "taylor@example.com"


def test_an_application_id_is_kept_when_no_developer_name_is_set():
    # Honest about being a machine, so there is nothing to gain by discarding it —
    # and the leaderboard knows not to credit one.
    os.environ["DEV_MODE"] = "true"
    assert caller_identity.username(Client(APPLICATION_ID, token="sp2")) == APPLICATION_ID
    assert caller_identity.is_application_id(APPLICATION_ID)
    assert not caller_identity.is_application_id("ana@example.com")


def test_a_deployment_keeps_the_service_principal_it_resolved():
    # DEV_MODE off: a real caller is never relabelled, whatever DEV_USERNAME says.
    os.environ["DEV_USERNAME"] = "taylor@example.com"
    assert caller_identity.username(Client(APPLICATION_ID, token="sp3")) == APPLICATION_ID


def test_a_failure_is_not_cached_as_an_answer():
    # A blip must not tell everyone on this worker they're anonymous for the
    # next five minutes.
    client = Client(fail=True, token="shared")
    assert caller_identity.username(client) == "unknown"
    client.fail = False
    client.user_name = "ana@example.com"
    assert caller_identity.username(client) == "ana@example.com"


def test_two_callers_never_share_an_identity():
    ana = Client("ana@example.com", token="ana-token")
    ben = Client("ben@example.com", token="ben-token")
    assert caller_identity.username(ana) == "ana@example.com"
    assert caller_identity.username(ben) == "ben@example.com"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        setup_function()
        try:
            test()
        finally:
            teardown_function()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
