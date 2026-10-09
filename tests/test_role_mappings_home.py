"""Tests for role mappings living in one schema for the whole deployment.

Access used to be read from whichever workspace (dev/test/prod schema) a request
named. It is now read from one, and startup moves anything left in the other two
into it. That move deletes rows, so what is pinned here is what keeps it safe:
a schema that is really the same one is never emptied, the lockout-prevention
seed never travels, duplicates aren't doubled, and what was moved is cleared at
its source so a mapping removed later doesn't come back on restart.
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


class Schema:
    """One schema's `role_mappings`, and where it says it is."""

    def __init__(self, database_name, schema, rows=()):
        self.where = (database_name, schema)
        self.rows = [list(r) for r in rows]
        self.next_id = 1 + max((r[0] for r in self.rows), default=0)


class Cursor:
    def __init__(self, schema):
        self.schema = schema
        self.result = []

    def execute(self, sql, params=()):
        s = self.schema
        if sql.startswith("SELECT current_database()"):
            self.result = [s.where]
        elif sql.startswith("SELECT id, external_role"):
            self.result = [tuple(r) for r in s.rows]
        elif sql.startswith("SELECT 1 FROM role_mappings"):
            self.result = [(1,)] if any(tuple(r[1:]) == tuple(params) for r in s.rows) else []
        elif sql.startswith("INSERT INTO role_mappings"):
            s.rows.append([s.next_id, *params])
            s.next_id += 1
        elif sql.startswith("DELETE FROM role_mappings"):
            gone = set(params[0])
            s.rows = [r for r in s.rows if r[0] not in gone]
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return list(self.result)


class Conn:
    def __init__(self, schema):
        self.schema = schema

    def cursor(self):
        return Cursor(self.schema)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def gather(home_env, schemas):
    saved = database.get_db_connection
    database.get_db_connection = lambda env, pooled=True: Conn(schemas[env])
    try:
        database._gather_role_mappings(Conn(schemas[home_env]), home_env)
    finally:
        database.get_db_connection = saved


def mappings(schema):
    return sorted(tuple(r[1:]) for r in schema.rows)


def test_mappings_left_in_other_workspaces_move_home_and_leave_their_source():
    schemas = {
        "dev": Schema("db", "dev", [(1, "cc-admins", "Global", "admin")]),
        "test": Schema("db", "test", [(1, "testers", "Supply", "editor")]),
        "prod": Schema("db", "prod", [(1, "planners", "Supply", "viewer")]),
    }
    gather("dev", schemas)
    assert mappings(schemas["dev"]) == [
        ("cc-admins", "Global", "admin"),
        ("planners", "Supply", "viewer"),
        ("testers", "Supply", "editor"),
    ]
    assert schemas["test"].rows == [] and schemas["prod"].rows == []


def test_a_mapping_already_home_is_not_doubled():
    schemas = {
        "dev": Schema("db", "dev", [(1, "testers", "Supply", "editor")]),
        "test": Schema("db", "test", [(1, "testers", "Supply", "editor")]),
        "prod": Schema("db", "prod"),
    }
    gather("dev", schemas)
    assert mappings(schemas["dev"]) == [("testers", "Supply", "editor")]


def test_the_seeded_everyone_is_admin_row_never_travels():
    # Every workspace seeded it while each had its own mappings. Carried into a
    # home whose admins replaced it, it would make every user admin again.
    schemas = {
        "dev": Schema("db", "dev", [(1, "cc-admins", "Global", "admin")]),
        "test": Schema("db", "test", [(1, "users", "Global", "admin")]),
        "prod": Schema("db", "prod", [(1, "users", "global", "admin")]),
    }
    gather("dev", schemas)
    assert mappings(schemas["dev"]) == [("cc-admins", "Global", "admin")]
    assert schemas["test"].rows == [] and schemas["prod"].rows == []


def test_one_schema_behind_every_workspace_is_left_alone():
    # APP_DB_SCHEMA points all three envs at one schema: "moving" from it to
    # itself and deleting at the source would empty the table.
    shared = Schema("db", "public", [(1, "cc-admins", "Global", "admin"), (2, "testers", "Supply", "editor")])
    gather("dev", {"dev": shared, "test": shared, "prod": shared})
    assert mappings(shared) == [("cc-admins", "Global", "admin"), ("testers", "Supply", "editor")]


def test_snapshots_read_and_write_role_mappings_where_access_is_read():
    saved = dm_routes.settings_store.settings_env
    dm_routes.settings_store.settings_env = lambda: "prod"
    try:
        parts = dm_routes._partition(dm.tables_for(["access", "settings"]), "test")
    finally:
        dm_routes.settings_store.settings_env = saved
    assert [s.name for s in parts["prod"]] == ["role_mappings", "app_settings"]
    assert [s.name for s in parts["test"]] == ["widget_categories", "widget_domains"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
