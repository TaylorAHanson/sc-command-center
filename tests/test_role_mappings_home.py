"""Tests for where access is written now that role mappings are retired.

Access lists and administrators live in the settings schema, and `role_mappings`
is never written again: the access migration reads it once, and a rollback to
the previous release must find it as that release left it. Snapshots are the
one path that could still write it, so that is what is pinned here.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    import database
    from routes import data_migration as dm_routes
    from services import data_migration as dm
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_role_mappings_home: {e}")
    sys.exit(0)


def test_startup_no_longer_moves_or_seeds_role_mappings():
    assert not hasattr(database, "_gather_role_mappings")


def test_snapshots_write_access_lists_where_access_is_read_and_role_mappings_nowhere():
    saved = (dm_routes.settings_store.settings_env, dm_routes.content_env)
    dm_routes.settings_store.settings_env = lambda: "dev"
    dm_routes.content_env = lambda: "prod"
    try:
        parts = dict(dm_routes._stores(dm.tables_for(["access", "settings"])))
    finally:
        dm_routes.settings_store.settings_env, dm_routes.content_env = saved
    assert [s.name for s in parts["dev"]] == ["object_permissions", "app_admins", "known_principals", "app_settings"]
    assert [s.name for s in parts["prod"]] == ["widget_categories", "widget_domains"]
    assert not any(s.name == "role_mappings" for specs in parts.values() for s in specs)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
