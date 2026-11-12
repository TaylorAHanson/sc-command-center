"""Tests for the capabilities registry (services/capabilities.py).

Features whose setup only the customer can provide stay off until it exists, and
this registry is how the UI and the Setup card find out. A broken check must cost
one feature rather than the page, and only administrators may see what the
deployment is missing.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from services import capabilities
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_capabilities: {e}")
    sys.exit(0)


def _fresh():
    capabilities._reset_for_tests()


def test_everyone_sees_availability_but_only_admins_see_the_setup():
    _fresh()
    capabilities.register("email", "Email", lambda: capabilities.result(
        False, missing=["A From address"], next_step="Set the From address in Settings → Email."))
    public = capabilities.describe(admin=False)
    assert public == [{"name": "email", "label": "Email", "available": False, "mode": None}]
    admin = capabilities.describe(admin=True)[0]
    assert admin["missing"] == ["A From address"]
    assert admin["next_step"].startswith("Set the From address")


def test_a_check_that_raises_reads_as_unavailable():
    _fresh()

    def broken():
        raise RuntimeError("endpoint lookup timed out")

    capabilities.register("search", "Search", broken)
    capabilities.register("email", "Email", lambda: capabilities.result(True))
    items = {i["name"]: i for i in capabilities.describe(admin=True)}
    assert items["search"]["available"] is False
    assert "endpoint lookup timed out" in items["search"]["missing"][0]
    # The other capability is untouched by its neighbour failing.
    assert items["email"]["available"] is True


def test_results_are_cached_until_invalidated():
    _fresh()
    calls = []

    def check():
        calls.append(1)
        return capabilities.result(True, mode="keyword")

    capabilities.register("search", "Search", check)
    capabilities.describe(admin=False)
    capabilities.describe(admin=False)
    assert len(calls) == 1
    capabilities.invalidate()
    assert capabilities.get("search")["mode"] == "keyword"
    assert len(calls) == 2
    capabilities.describe(admin=True, force=True)
    assert len(calls) == 3


def test_unknown_capabilities_are_unavailable():
    _fresh()
    assert capabilities.available("scheduling") is False


def test_registration_order_is_display_order():
    _fresh()
    for name in ("search", "email", "scheduling"):
        capabilities.register(name, name.title(), lambda: capabilities.result(True))
    assert [i["name"] for i in capabilities.describe(admin=False)] == ["search", "email", "scheduling"]


def test_a_bad_registration_is_ignored_not_raised():
    _fresh()
    capabilities.register("", "Nothing", lambda: {})
    capabilities.register("email", "Email", None)
    assert capabilities.describe(admin=True) == []


def test_result_normalises_what_a_check_returns():
    _fresh()
    capabilities.register("email", "Email", lambda: {"available": 1, "missing": ["", "AWS keys", None]})
    item = capabilities.describe(admin=True)[0]
    assert item["available"] is True
    assert item["missing"] == ["AWS keys"]
    assert item["next_step"] == ""
    _fresh()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
