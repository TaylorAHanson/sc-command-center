"""Weigh the widget library's answer to the app's first request.

Run from the repo root with the server's interpreter:

    server/venv/bin/python tools/widget_payload_probe.py [env]

Runs the queries behind `/api/widgets/custom` and `/api/widgets/custom/snapshots`
alongside the `SELECT *` they replaced, and prints how many rows, how many
megabytes and how many milliseconds each costs. Read-only.

The gap between the two is the point: the old query sent every version of every
widget with its source and its base64 thumbnail, on every page load, to everyone.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from database import get_db_connection  # noqa: E402

OLD = "SELECT * FROM widgets WHERE is_deprecated = 0 ORDER BY timestamp DESC"

LIST = '''
    SELECT id, version, name, description, category, domain,
           default_w, default_h, configuration_mode, config_schema,
           data_source_type, data_source, help_text, open_in_new_tab_link,
           is_executable, is_certified, created_by, timestamp,
           (snapshot IS NOT NULL AND snapshot <> '') AS has_snapshot,
           (version = MAX(version) OVER (PARTITION BY id)) AS is_latest,
           CASE WHEN version = MAX(version) OVER (PARTITION BY id)
                THEN tsx_code END AS tsx_code
    FROM widgets
    WHERE is_deprecated = 0
    ORDER BY timestamp DESC
'''

SNAPSHOTS = '''
    SELECT id, domain, snapshot FROM (
        SELECT id, domain, snapshot, version,
               MAX(version) OVER (PARTITION BY id) AS latest
        FROM widgets WHERE is_deprecated = 0
    ) w
    WHERE version = latest AND snapshot IS NOT NULL AND snapshot <> ''
'''


def run(conn, sql: str, label: str) -> list:
    cur = conn.cursor()
    started = time.perf_counter()
    cur.execute(sql)
    rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    elapsed = (time.perf_counter() - started) * 1000
    megabytes = len(json.dumps(rows, default=str)) / 1048576
    print(f"  {label:<24} {len(rows):>5} rows {megabytes:>8.2f} MB {elapsed:>8.0f} ms")
    return rows


SEED_PREFIX = "probe-tmp-"


def seed(conn, widgets: int, versions: int) -> None:
    """Fill dev with a throwaway library, for when there isn't one to measure.

    Every row is prefixed `probe-tmp-` and deleted again on the way out. Refuses
    to run anywhere but dev.
    """
    cur = conn.cursor()
    for i in range(widgets):
        for v in range(1, versions + 1):
            cur.execute(
                """INSERT INTO widgets (id, version, name, description, category, domain,
                       default_w, default_h, tsx_code, snapshot, is_certified, is_deprecated,
                       created_by, configuration_mode)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (f"{SEED_PREFIX}{i}", v, f"Probe {i}", "seeded", "Ops", "General",
                 4, 4, "export default function W() { return <div>hi</div>; }\n" * 60,
                 "data:image/png;base64," + "A" * 40000, 0, 0, "probe@example.com", "none"),
            )
    conn.commit()
    print(f"  seeded {widgets} widgets x {versions} versions")


def unseed(conn) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM widgets WHERE id LIKE %s", (SEED_PREFIX + "%",))
    removed = cur.rowcount
    conn.commit()
    print(f"  removed {removed} seeded rows")


def main() -> None:
    env = sys.argv[1] if len(sys.argv) > 1 else "dev"
    seeding = "--seed" in sys.argv
    if seeding and env != "dev":
        raise SystemExit("--seed only runs against dev")

    conn = get_db_connection(env)
    print(f"env={env}")
    try:
        if seeding:
            seed(conn, widgets=30, versions=8)
        old = run(conn, OLD, "old /custom")
        new = run(conn, LIST, "new /custom")
        snapshots = run(conn, SNAPSHOTS, "new /custom/snapshots")

        widgets = {r["id"] for r in old}
        current = {r["id"] for r in new if r["is_latest"]}
        carrying_code = [r for r in new if r["tsx_code"]]

        print(f"\n  {len(widgets)} widgets, {len(old)} versions, "
              f"{len(carrying_code)} carrying source, {len(snapshots)} with a thumbnail")

        assert current == widgets, "every widget must have exactly one current version"
        assert len(carrying_code) <= len(current), "source travels with current versions only"
        for row in new:
            assert row["tsx_code"] is None or row["is_latest"], "an old version brought its source"
        print("  checks passed")
    finally:
        if seeding:
            unseed(conn)
        conn.close()


if __name__ == "__main__":
    main()
