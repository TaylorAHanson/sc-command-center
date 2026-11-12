"""Discover at scale: seed tens of thousands of views into a scratch schema on a
real Lakebase database, build the catalog and its search indexes with the app's
own code, and time what the Discover endpoints do.

    PGHOST=ep-....database.us-west-2.cloud.databricks.com \\
    PGUSER=you@example.com \\
    PGPASSWORD="$(databricks postgres generate-database-credential \\
        projects/<project>/branches/production/endpoints/primary -p <profile> -o json | jq -r .token)" \\
    PYTHONPATH=server .venv/bin/python tools/discover_scale_probe.py --profile <profile>

It only ever writes to the scratch schema it creates (`--schema`, default
lane_discover_scratch) and, when the Lakebase Search extensions aren't
installed yet, to an extension schema it creates for them (`--ext-schema`).
Both are dropped at the end unless `--keep`. It refuses a schema that already
exists and the dev, test, prod and public schemas, which belong to deployments.

`--profile` names the Databricks CLI profile whose workspace serves the
embedding model, so hybrid timings include a real query embedding; without
it, query vectors are synthetic and hybrid numbers leave the model out. The
catalog's own vectors are always synthetic (clustered by domain): embedding
50,000 views would only measure the model.

Latency is measured from wherever this runs, which from a laptop is mostly
network. So every read an operation sends is also run under EXPLAIN ANALYZE
for the database's own time, writes and commits are counted at their wall time
less the floor round trip, and the "in-region" columns are that database time
plus the probe's own Python time (the query embedding included) plus
`--region-rtt` per round trip: what the deployed App, next to its database,
would see.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import psycopg2  # noqa: E402
import psycopg2.extensions as pgext  # noqa: E402

RESERVED = {"dev", "test", "prod", "public", "app"}

AREAS = ["Supplier", "Inventory", "Logistics", "Procurement", "Warehouse", "Demand", "Finance", "Quality",
         "Manufacturing", "Sales", "Customer", "Transport", "Freight", "Returns", "Capacity", "Production",
         "Sourcing", "Distribution", "Fleet", "Maintenance", "Workforce", "Energy", "Packaging", "Pricing",
         "Order", "Shipment", "Plant", "Store", "Carrier", "Vendor"]
SUBJECTS = ["Risk", "Health", "Forecast", "Backlog", "Performance", "Scorecard", "Exceptions", "Lead Times",
            "Spend", "Fill Rate", "On-Time Delivery", "Yield", "Utilization", "Variance", "Aging", "Cost",
            "Compliance", "Throughput", "Accuracy", "Delays", "Margin", "Demand Signals", "Safety Stock",
            "Turns", "Defects", "Claims", "Capacity Plan", "Allocation", "Coverage", "Trends"]
QUALIFIERS = ["", "", "", "", "Weekly", "Daily", "Monthly", "EMEA", "APAC", "Americas", "Q3", "Executive",
              "Plant 12", "v2", "Overview", "Drilldown", "Command Center", "Tracker", "Monitor", "Cockpit"]
DOMAINS = ["Supply Chain", "Finance", "Sales", "Manufacturing", "Logistics", "Procurement", "Quality", "HR",
           "IT", "Marketing", "Customer Service", "Executive"]
TABS = ["Overview", "Details", "Trends", "Exceptions", "By Region", "By Supplier", "Backlog", "KPIs", "Map", "Notes"]
WIDGETS = ["Late POs", "Lead time chart", "Fill rate KPI", "Supplier map", "Backlog table", "Forecast vs actual",
           "Inventory aging", "OTIF trend", "Spend by category", "Defect pareto", "Carrier scorecard",
           "Open orders", "Stockout alerts", "Cycle count", "Freight cost", "Plant OEE", "Returns reasons",
           "Margin bridge", "Headcount", "Ticket queue"]
QUERIES = ["supplier risk", "inventory", "invent", "late pos", "lead times", "on-time delivery", "freight spend",
           "weekly backlog", "emea", "quality defects", "safety stock", "carrier scorecard", "plant 12",
           "forecast accuracy", "demand signals", "warehouse utilization", "procurement", "fill rate",
           "returns claims", "executive cockpit", "capacity plan apac", "vendor compliance", "shipment delays",
           "otif trend", "pricing margin", "fleet maintenance", "energy cost", "production yield", "stockout",
           "order", "sup", "customer service", "distribution coverage", "tracker", "monthly spend",
           "sourcing risk americas", "packaging", "store turns", "workforce", "drilldown"]

# --------------------------------------------------------------- round trips

#: trips: statements and commits sent; db_wall: wall time inside the driver,
#: EXPLAINs included; explain_wall: the EXPLAINs' share of it; db_ms: the
#: database's own time. `explain` is on only while an operation is timed.
PROFILE: Dict[str, Any] = {"trips": 0, "db_wall": 0.0, "explain_wall": 0.0, "db_ms": 0.0, "explain": False,
                           "rtt_floor": 0.0}
_PATH_PREFIX = "SELECT set_config('search_path'"


def _readonly(text: str) -> bool:
    upper = text.lstrip().upper()
    return upper.startswith(("SELECT", "WITH", "(SELECT")) and not any(
        w in upper for w in ("INSERT ", "UPDATE ", "DELETE ", "PG_ADVISORY", "PG_TRY_ADVISORY"))


class CountingCursor(pgext.cursor):
    def execute(self, sql, args=None):
        text = sql.decode() if isinstance(sql, bytes) else str(sql)
        PROFILE["trips"] += 1
        # psycopg2 opens each transaction with a BEGIN of its own.
        if not self.connection.autocommit and self.connection.info.transaction_status == pgext.TRANSACTION_STATUS_IDLE:
            PROFILE["trips"] += 1
        if PROFILE["explain"] and _readonly(text):
            started = time.perf_counter()
            head, body = ("", text)
            if text.startswith(_PATH_PREFIX):
                head, _, body = text.partition(";\n")
                super().execute(head, args)
            super().execute("EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) " + body, args)
            plan = self.fetchone()[0][0]
            PROFILE["db_ms"] += plan.get("Planning Time", 0.0) + plan.get("Execution Time", 0.0)
            spent = (time.perf_counter() - started) * 1000
            PROFILE["explain_wall"] += spent
            PROFILE["db_wall"] += spent
            started = time.perf_counter()
            out = super().execute(sql, args)
            PROFILE["db_wall"] += (time.perf_counter() - started) * 1000
            return out
        started = time.perf_counter()
        out = super().execute(sql, args)
        spent = (time.perf_counter() - started) * 1000
        PROFILE["db_wall"] += spent
        PROFILE["db_ms"] += max(0.0, spent - PROFILE["rtt_floor"])
        return out


class CountingConnection(pgext.connection):
    def cursor(self, *args, **kwargs):
        kwargs.setdefault("cursor_factory", CountingCursor)
        return super().cursor(*args, **kwargs)

    def _ends(self, fn):
        if self.info.transaction_status == pgext.TRANSACTION_STATUS_IDLE:
            return fn()
        PROFILE["trips"] += 1
        started = time.perf_counter()
        try:
            return fn()
        finally:
            spent = (time.perf_counter() - started) * 1000
            PROFILE["db_wall"] += spent
            PROFILE["db_ms"] += max(0.0, spent - PROFILE["rtt_floor"])

    def commit(self):
        return self._ends(super().commit)

    def rollback(self):
        return self._ends(super().rollback)


_real_connect = psycopg2.connect


def _counting_connect(*args, **kwargs):
    kwargs.setdefault("connection_factory", CountingConnection)
    return _real_connect(*args, **kwargs)


# ------------------------------------------------------------------- helpers

def raw_connection():
    return _real_connect(host=os.environ["PGHOST"], port=os.environ.get("PGPORT", "5432"),
                         dbname=os.environ["PGDATABASE"], user=os.environ["PGUSER"],
                         password=os.environ["PGPASSWORD"], sslmode="require")


def pct(values: List[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(round(p / 100 * len(ordered) + 0.5)) - 1))]


class Report:
    def __init__(self, rtt_ms: float, rtt_floor: float, region_rtt: float):
        self.rtt, self.floor, self.region_rtt, self.rows, self.notes = rtt_ms, rtt_floor, region_rtt, [], []

    def add(self, label: str, samples: List[Dict[str, Any]], extra: str = ""):
        probe = [s["probe_ms"] for s in samples]
        db = [s["db_ms"] for s in samples]
        region = [s["region_ms"] for s in samples]
        row = {"op": label, "n": len(samples), "probe_p50": pct(probe, 50), "probe_p95": pct(probe, 95),
               "db_p50": pct(db, 50), "db_p95": pct(db, 95), "trips": statistics.median(s["trips"] for s in samples),
               "region_p50": pct(region, 50), "region_p95": pct(region, 95), "extra": extra}
        self.rows.append(row)
        print(f"  {label:<44} probe p50 {row['probe_p50']:6.0f} p95 {row['probe_p95']:6.0f} | db p50 "
              f"{row['db_p50']:6.1f} p95 {row['db_p95']:6.1f} | trips {row['trips']:3.0f} | in-region p50 "
              f"{row['region_p50']:6.1f} p95 {row['region_p95']:6.1f}  {extra}", flush=True)

    def markdown(self) -> str:
        lines = [f"Round trip from the probe: median {self.rtt:.0f} ms, floor {self.floor:.0f} ms (`SELECT 1`). "
                 f"In-region = database time + Python time (query embedding included) + {self.region_rtt:g} ms "
                 f"per round trip.", "",
                 "| Operation | n | from probe p50 / p95 | database p50 / p95 | round trips | in-region p50 / p95 | notes |",
                 "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
        for r in self.rows:
            lines.append(f"| {r['op']} | {r['n']} | {r['probe_p50']:.0f} / {r['probe_p95']:.0f} | "
                         f"{r['db_p50']:.1f} / {r['db_p95']:.1f} | {r['trips']:.0f} | "
                         f"{r['region_p50']:.0f} / {r['region_p95']:.0f} | {r['extra']} |")
        return "\n".join(lines + [""] + [f"- {n}" for n in self.notes])


REGION_RTT = [2.0]


def timed(fn: Callable[[int], Any], n: int, warmup: int = 3) -> List[Dict[str, Any]]:
    for i in range(warmup):
        fn(i)
    samples = []
    for i in range(n):
        before = {k: PROFILE[k] for k in ("trips", "db_wall", "explain_wall", "db_ms")}
        PROFILE["explain"] = True
        started = time.perf_counter()
        try:
            out = fn(i)
        finally:
            PROFILE["explain"] = False
        wall = (time.perf_counter() - started) * 1000
        delta = {k: PROFILE[k] - before[k] for k in before}
        python_ms = max(0.0, wall - delta["db_wall"])
        samples.append({"probe_ms": wall - delta["explain_wall"], "db_ms": delta["db_ms"], "trips": delta["trips"],
                        "region_ms": python_ms + delta["db_ms"] + delta["trips"] * REGION_RTT[0], "out": out})
    return samples


def step(label: str, fn: Callable[[], Any]) -> float:
    """Run `fn` and return how long it took, in seconds."""
    started = time.perf_counter()
    out = fn()
    elapsed = time.perf_counter() - started
    print(f"{label}: {elapsed:.1f}s" + (f" -> {out}" if isinstance(out, (int, float)) else ""), flush=True)
    return elapsed


# ---------------------------------------------------------------------- seed

def seed(conn, args) -> None:
    c = conn.cursor()
    p = {"areas": AREAS, "subjects": SUBJECTS, "quals": QUALIFIERS, "domains": DOMAINS, "tabs": TABS,
         "widgets": WIDGETS, "n": args.views, "creators": args.creators, "users": args.users,
         "groups": args.groups, "nw": args.widgets, "visits": args.visits}
    c.execute("SELECT setseed(0.42)")
    c.execute("""
        INSERT INTO widgets (id, version, name, domain, tsx_code, created_by)
        SELECT md5(n || 'widget')::uuid::text, 1,
               (%(widgets)s::text[])[1 + floor(random() * array_length(%(widgets)s::text[], 1))::int] || ' ' || n,
               (%(domains)s::text[])[1 + floor(random() * array_length(%(domains)s::text[], 1))::int], '', 'seed'
          FROM generate_series(1, %(nw)s) n""", p)
    c.execute("""
        CREATE TEMP TABLE seed_views AS
        SELECT g, md5(g || 'view')::uuid::text AS id,
               trim((%(areas)s::text[])[1 + floor(random() * array_length(%(areas)s::text[], 1))::int] || ' ' ||
                    (%(subjects)s::text[])[1 + floor(random() * array_length(%(subjects)s::text[], 1))::int] || ' ' ||
                    (%(quals)s::text[])[1 + floor(random() * array_length(%(quals)s::text[], 1))::int]) AS name,
               (%(domains)s::text[])[1 + floor(random() * array_length(%(domains)s::text[], 1))::int] AS domain,
               'u' || lpad((1 + floor(power(random(), 2) * %(creators)s))::int::text, 5, '0') || '@example.com' AS owner,
               now() - random() * interval '720 days' AS ts, random() AS r
          FROM generate_series(1, %(n)s) g""", p)
    c.execute("""
        WITH wid AS (SELECT array_agg(id ORDER BY id) AS ids FROM widgets)
        INSERT INTO dashboard_views (id, version, name, domain, username, is_global, widgets_json, spec_json,
                                     is_locked, pinned_agent_id, timestamp, published_at, published_by)
        SELECT s.id, 1, s.name, s.domain, s.owner, 0, '[]',
               json_build_object('schema', 1, 'presentation', CASE WHEN s.r < 0.15 THEN 'standalone' ELSE 'workspace' END,
                 'assistant', 'on', 'filters', '[]'::json,
                 'tabs', (SELECT json_agg(json_build_object(
                            'id', 't' || t, 'layout', 'canvas', 'pinned_agent_id', NULL,
                            'name', (%(tabs)s::text[])[1 + floor(random() * array_length(%(tabs)s::text[], 1))::int + 0 * s.g],
                            'widgets', (SELECT json_agg(json_build_object('i', 'w' || t || '-' || k,
                                          'type', wid.ids[1 + floor(random() * %(nw)s)::int + 0 * s.g + 0 * t]))
                                          FROM generate_series(1, 1 + (s.g + t) %% 3) k)))
                            FROM generate_series(1, 1 + s.g %% 4) t))::text,
               0, NULL, s.ts, s.ts, s.owner
          FROM seed_views s, wid""", p)
    c.execute("""
        INSERT INTO dashboard_views (id, version, name, domain, username, is_global, widgets_json, spec_json,
                                     is_locked, pinned_agent_id, timestamp, published_at, published_by)
        SELECT id, 2, name, domain, username, 0, widgets_json, spec_json, 0, NULL, t2, t2, username
          FROM (SELECT *, timestamp + random() * (now() - timestamp) AS t2 FROM dashboard_views
                 WHERE version = 1 AND random() < 0.1) x""")
    c.execute("INSERT INTO archived_views (id, archived_by) SELECT id, username FROM dashboard_views "
              "WHERE version = 1 AND random() < 0.02")
    c.execute("INSERT INTO app_links (slug, app_id) SELECT lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g')) "
              "|| '-' || substr(id, 1, 6), id FROM dashboard_views WHERE version = 1 AND random() < 0.4 "
              "ON CONFLICT DO NOTHING")
    c.execute("INSERT INTO object_drafts (object_type, object_id, payload, base_version, updated_by) "
              "SELECT 'app', id, jsonb_build_object('name', name, 'domain', domain, 'username', username), 1, username "
              "FROM dashboard_views WHERE version = 1 AND random() < 0.05")
    acl = "INSERT INTO object_permissions (object_type, object_id, principal, principal_type, level, granted_by, granted_at) "
    c.execute(acl + "SELECT 'app', id, username, 'user', 'MANAGE', username, timestamp FROM dashboard_views WHERE version = 1")
    c.execute(acl + "SELECT 'app', id, '*', 'all', 'USE', username, timestamp + random() * (now() - timestamp) "
                    "FROM dashboard_views WHERE version = 1 AND random() < 0.25")
    c.execute(acl + "SELECT 'app', v.id, 'group' || lpad((1 + floor(power(random(), 1.5) * %(groups)s))::int::text, 3, '0'), "
                    "'group', 'USE', v.username, v.timestamp + random() * (now() - v.timestamp) "
                    "FROM dashboard_views v, generate_series(1, 3) k WHERE v.version = 1 AND random() < 0.25 "
                    "ON CONFLICT DO NOTHING", p)
    c.execute(acl + "SELECT 'app', v.id, 'u' || lpad((1 + floor(random() * %(users)s))::int::text, 5, '0') || '@example.com', "
                    "'user', CASE WHEN random() < 0.2 THEN 'MANAGE' ELSE 'USE' END, v.username, "
                    "v.timestamp + random() * (now() - v.timestamp) "
                    "FROM dashboard_views v, generate_series(1, 2) k WHERE v.version = 1 AND random() < 0.12 "
                    "ON CONFLICT DO NOTHING", p)
    c.execute("INSERT INTO view_curation (app_id, featured_position, featured_by, featured_at) "
              "SELECT id, (row_number() OVER (ORDER BY id)) - 1, 'seed', now() FROM "
              "(SELECT id FROM dashboard_views WHERE version = 1 ORDER BY md5(id) LIMIT 12) x")
    c.execute("INSERT INTO view_curation (app_id, certified, certified_by, certified_at) "
              "SELECT id, TRUE, 'seed', now() FROM dashboard_views WHERE version = 1 AND random() < 0.006 "
              "ON CONFLICT (app_id) DO UPDATE SET certified = TRUE")
    c.execute("CREATE TEMP TABLE seed_ids AS SELECT row_number() OVER (ORDER BY md5(id)) AS rn, id "
              "FROM dashboard_views WHERE version = 1")
    c.execute("""
        WITH picks AS MATERIALIZED (
            SELECT 'u' || lpad((1 + floor(random() * %(users)s))::int::text, 5, '0') || '@example.com' AS username,
                   1 + floor(power(random(), 3) * %(n)s)::int AS rn, CURRENT_DATE - floor(random() * 30)::int AS day,
                   random() AS r
              FROM generate_series(1, %(visits)s))
        INSERT INTO view_visits (username, app_id, day, last_opened_at, opens)
        SELECT p.username, s.id, p.day, p.day + interval '7 hours' + p.r * interval '10 hours', 1
          FROM picks p JOIN seed_ids s ON s.rn = p.rn
        ON CONFLICT DO NOTHING""", p)
    c.execute("""
        WITH picks AS MATERIALIZED (
            SELECT 'u' || lpad((1 + floor(random() * %(users)s))::int::text, 5, '0') || '@example.com' AS username,
                   1 + floor(power(random(), 2) * %(n)s)::int AS rn
              FROM generate_series(1, %(users)s * 10))
        INSERT INTO user_favorites (username, app_id, position)
        SELECT p.username, s.id, 1 FROM picks p JOIN seed_ids s ON s.rn = p.rn ON CONFLICT DO NOTHING""", p)
    conn.commit()


def seed_caller(conn, who, *, visits: int, favorites: int, hidden: int, drafts: int, fresh: int) -> None:
    """The person whose numbers are reported: their own opens, favorites, hidden
    views, never-published drafts and recent shares."""
    c = conn.cursor()
    me = who.username.lower()
    keys = ["*", me] + list(who.groups)
    readable = ("SELECT object_id FROM (SELECT DISTINCT object_id FROM object_permissions "
                "WHERE object_type = 'app' AND principal = ANY(%(keys)s)) r")
    p = {"me": me, "keys": keys, "groups": list(who.groups)}
    c.execute(f"INSERT INTO view_visits (username, app_id, day, last_opened_at, opens) "
              f"SELECT %(me)s, object_id, CURRENT_DATE - floor(random() * 30)::int, now() - random() * interval '30 days', 1 "
              f"FROM ({readable} ORDER BY md5(object_id) LIMIT %(n)s) x ON CONFLICT DO NOTHING", dict(p, n=visits))
    c.execute(f"INSERT INTO user_favorites (username, app_id, position) "
              f"SELECT %(me)s, object_id, row_number() OVER (ORDER BY md5(object_id || 'f')) "
              f"FROM ({readable} ORDER BY md5(object_id || 'f') LIMIT %(n)s) x ON CONFLICT DO NOTHING", dict(p, n=favorites))
    c.execute(f"INSERT INTO view_hidden (username, app_id) SELECT %(me)s, object_id "
              f"FROM ({readable} ORDER BY md5(object_id || 'h') LIMIT %(n)s) x ON CONFLICT DO NOTHING", dict(p, n=hidden))
    for i in range(drafts):
        draft_id = f"00000000-0000-4000-8000-{i:012d}"
        c.execute("INSERT INTO object_drafts (object_type, object_id, payload, updated_by) VALUES ('app', %s, %s, %s) "
                  "ON CONFLICT DO NOTHING",
                  (draft_id, json.dumps({"name": f"Draft idea {i}", "domain": "Finance", "username": me}), me))
        c.execute("INSERT INTO object_permissions (object_type, object_id, principal, principal_type, level, granted_by) "
                  "VALUES ('app', %s, %s, 'user', 'MANAGE', %s) ON CONFLICT DO NOTHING", (draft_id, me, me))
    if who.groups:
        c.execute("INSERT INTO object_permissions (object_type, object_id, principal, principal_type, level, granted_by, "
                  "granted_at) SELECT 'app', id, %(g)s, 'group', 'USE', username, LOCALTIMESTAMP - random() * interval '13 days' "
                  "FROM dashboard_views WHERE version = 1 AND username <> %(me)s ORDER BY md5(id || 'n') LIMIT %(n)s "
                  "ON CONFLICT DO NOTHING", {"g": who.groups[0], "me": me, "n": fresh})
    c.execute("DELETE FROM view_daily")
    c.execute("INSERT INTO view_daily (app_id, day, viewers) SELECT app_id, day, COUNT(*) FROM view_visits GROUP BY 1, 2")
    conn.commit()


def synthetic_vectors(conn, d: Dict[str, Any], dims: int, batch: int = 5000) -> int:
    """Vectors clustered by domain, so nearest neighbours mean something to the index."""
    from services import view_catalog as vc

    vc._ensure_embedding_column(conn, d, dims)
    vs = vc._ident(d.get("pgvector_schema") or d.get("vector_schema"))
    c = conn.cursor()
    done = 0
    while True:
        c.execute(f"""
            UPDATE view_catalog vc SET embedded_hash = vc.embed_hash, embedding = (
                SELECT array_agg(sin(g * (1 + abs(hashtext(COALESCE(vc.domain, ''))) %% 97) * 0.01)
                                 + (random() - 0.5) * 0.6 ORDER BY g)::real[]::{vs}.vector
                  FROM generate_series(1, %s) g)
             WHERE vc.id IN (SELECT id FROM view_catalog WHERE embedded_hash IS NULL LIMIT %s)""", (dims, batch))
        changed = c.rowcount
        conn.commit()
        done += changed
        if changed < batch:
            return done


# ----------------------------------------------------------------------- run

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--schema", default="lane_discover_scratch")
    ap.add_argument("--ext-schema", default="lane_discover_ext")
    ap.add_argument("--views", type=int, default=50_000)
    ap.add_argument("--users", type=int, default=20_000)
    ap.add_argument("--creators", type=int, default=2_000)
    ap.add_argument("--groups", type=int, default=300)
    ap.add_argument("--widgets", type=int, default=2_000)
    ap.add_argument("--visits", type=int, default=1_000_000)
    ap.add_argument("--iterations", type=int, default=40)
    ap.add_argument("--profile", help="Databricks CLI profile serving the embedding model")
    ap.add_argument("--model", default="databricks-gte-large-en")
    ap.add_argument("--dims", type=int, default=1024, help="vector size when no model is called")
    ap.add_argument("--region-rtt", type=float, default=2.0,
                    help="milliseconds per round trip between the App and its database, for the in-region columns")
    ap.add_argument("--keep", action="store_true", help="leave the scratch and extension schemas in place")
    ap.add_argument("--json", help="also write the results here")
    args = ap.parse_args()

    schema = args.schema.strip()
    if schema.lower() in RESERVED or not schema.replace("_", "").isalnum():
        print(f"Refusing schema {schema!r}: use a scratch schema of your own.", file=sys.stderr)
        return 2
    for var in ("PGHOST", "PGUSER", "PGPASSWORD"):
        if not os.environ.get(var):
            print(f"{var} is not set; see the docstring.", file=sys.stderr)
            return 2
    os.environ.setdefault("PGDATABASE", "databricks_postgres")
    os.environ["APP_DB_SCHEMA"] = schema
    os.environ["APP_CONTENT_ENV"], os.environ["APP_SETTINGS_ENV"] = "prod", "dev"
    for var in ("DISABLE_PERMISSION_CHECKS", "DEV_MODE", "SEARCH_MODE", "SEARCH_EMBEDDING_MODEL"):
        os.environ.pop(var, None)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    pre = raw_connection()
    pc = pre.cursor()
    pc.execute("SELECT nspname FROM pg_namespace WHERE nspname IN (%s, %s)", (schema, args.ext_schema))
    existing = {r[0] for r in pc.fetchall()}
    pc.execute("SELECT e.extname, n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
               "WHERE e.extname IN ('lakebase_text', 'lakebase_vector', 'vector')")
    extensions_before = dict(pc.fetchall())
    pre.close()
    if schema in existing:
        print(f"Schema {schema} already exists; drop it or pick another --schema.", file=sys.stderr)
        return 2
    if args.ext_schema in existing and args.ext_schema not in extensions_before.values():
        print(f"Schema {args.ext_schema} exists without the extensions in it; pick another --ext-schema.", file=sys.stderr)
        return 2

    psycopg2.connect = _counting_connect
    import database
    import db_pool
    from services import access, settings_store, view_catalog as vc, view_signals

    assert not access._bypass(), "permission checks must be on for honest numbers"
    vc.EXT_SCHEMA = args.ext_schema
    installed_here = False
    results: Dict[str, Any] = {"args": vars(args), "extensions_before": extensions_before}
    try:
        step("init_db", lambda: (database.init_db("prod"), database.init_db("dev")))
        assert vc.enabled(), "the catalog tables weren't created"
        conn = database.get_db_connection("prod", pooled=False)
        step(f"seed {args.views} views", lambda: seed(conn, args))
        typical = access.Caller("u00500@example.com", ("group010", "group050", "group120", "group200", "group260"), False)
        heavy = access.Caller("u00001@example.com", ("group001", "group002"), False)
        narrow = access.Caller("u19999@example.com", (), False)
        admin = access.Caller("u00002@example.com", (), True)
        step("seed the callers", lambda: [seed_caller(conn, w, visits=150, favorites=40, hidden=5, drafts=5, fresh=25)
                                          for w in (typical, heavy)])
        c = conn.cursor()
        c.execute("SELECT (SELECT COUNT(DISTINCT id) FROM dashboard_views), (SELECT COUNT(*) FROM object_permissions), "
                  "(SELECT COUNT(*) FROM view_visits), (SELECT COUNT(*) FROM view_daily), (SELECT COUNT(*) FROM user_favorites)")
        counts = dict(zip(("views", "acl_entries", "visits", "daily_rows", "favorites"), c.fetchone()))
        conn.commit()
        print("seeded:", counts)
        results["seeded"] = counts

        build_s = time.perf_counter()
        rows = vc.full_build(conn)
        results["full_build_s"] = time.perf_counter() - build_s
        print(f"full_build: {rows} rows in {results['full_build_s']:.1f}s", flush=True)
        ensure_s = time.perf_counter()
        d = vc.ensure_search(conn, force=True)
        results["ensure_search_s"] = time.perf_counter() - ensure_s
        installed_here = not extensions_before and bool(d.get("text_schema"))
        print(f"ensure_search: {results['ensure_search_s']:.1f}s  text={d.get('text_schema')} "
              f"vector={d.get('vector_schema')} bm25={d.get('bm25')}  state.extensions="
              f"{(d.get('state') or {}).get('extensions')}", flush=True)
        if not d.get("bm25"):
            print("No BM25 index: keyword and hybrid can't be measured here.", file=sys.stderr)
        results["rollup_s"] = step("rollup_job", view_signals.rollup_job)

        query_vector: Callable[[str, str], Optional[List[float]]]
        if args.profile:
            host = json.loads(subprocess.check_output(
                ["databricks", "auth", "describe", "-p", args.profile, "-o", "json"]))["details"]["host"].rstrip("/")
            token = json.loads(subprocess.check_output(
                ["databricks", "auth", "token", "-p", args.profile, "-o", "json"]))["access_token"]
            vc.set_embedding_auth(lambda: (host, token))
            dims = len(vc.embed_texts(["probe"], args.model)[0])
        else:
            dims = args.dims
        d = vc.detect(conn.cursor())
        conn.commit()
        if d.get("vector_schema"):
            t0 = time.perf_counter()
            n_vec = synthetic_vectors(conn, d, dims)
            c.execute("SELECT COUNT(*) FROM view_catalog")
            total = c.fetchone()[0]
            vc.set_state(c, "embeddings", {"model": args.model, "dims": dims, "done": n_vec, "total": total,
                                           "error": None}, merge=False)
            conn.commit()
            print(f"synthetic vectors: {n_vec} in {time.perf_counter() - t0:.1f}s", flush=True)
            os.environ["SEARCH_EMBEDDING_MODEL"] = args.model
            settings_store.invalidate()
            ann_s = time.perf_counter()
            vc.embed_job()
            results["ann_build_s"] = time.perf_counter() - ann_s
            print(f"embed_job (vector index build): {results['ann_build_s']:.1f}s", flush=True)
        if not args.profile:
            import random

            rng = random.Random(7)
            fake = {}

            def query_vector(q, model, timeout=vc.QUERY_EMBED_TIMEOUT):
                return fake.setdefault(q, [rng.uniform(-1, 1) for _ in range(dims)])

            vc.embed_query = query_vector
        vc.forget_detection()
        cap = vc.capability_check()
        print("Setup card row:", cap)
        results["capability"] = cap

        rtt_conn = raw_connection()
        rtt_conn.autocommit = True
        rtts = []
        for _ in range(30):
            started = time.perf_counter()
            rtt_conn.cursor().execute("SELECT 1")
            rtts.append((time.perf_counter() - started) * 1000)
        rtt_conn.close()
        PROFILE["rtt_floor"] = min(rtts)
        REGION_RTT[0] = args.region_rtt
        report = Report(statistics.median(rtts), min(rtts), args.region_rtt)
        print(f"round trip: median {report.rtt:.1f} ms, floor {report.floor:.1f} ms", flush=True)
        n = min(args.iterations, len(QUERIES))

        def search_fn(who, mode, *, sort="relevance", facets=False, bpf=True, apf=True, scope="all", cold=False):
            def run(i):
                if cold:
                    vc._query_cache.clear()
                body = vc.search(who, vc.SearchParams(q=QUERIES[i % len(QUERIES)], sort=sort, scope=scope,
                                                      facets=facets, limit=24),
                                 mode=mode, bm25_prefilter=bpf, ann_prefilter=apf)
                return body
            return run

        def modes_used(samples):
            used: Dict[str, int] = {}
            for s in samples:
                used[s["out"]["mode"]] = used.get(s["out"]["mode"], 0) + 1
            return ", ".join(f"{k}×{v}" for k, v in sorted(used.items()))

        def results_of(samples):
            return statistics.median(len(s["out"]["results"]) for s in samples)

        hybrid_ok = bool(d.get("bm25") and d.get("vector_schema"))
        if hybrid_ok and args.profile:
            print("\nquery embedding alone:", flush=True)
            report.add(f"query embedding ({args.model})",
                       timed(lambda i: vc.embed_texts([QUERIES[i % len(QUERIES)] + " " + str(i)], args.model), n),
                       "the model call by itself, from the probe")
        for q in QUERIES:
            if hybrid_ok:
                vc.embed_query(q, args.model, timeout=10.0)

        print("\nsearch, typical caller (5 groups):", flush=True)
        recall: Dict[str, List[List[str]]] = {}
        configs = [("basic", "basic", {}),
                   ("keyword, prefilter on", "keyword", {"bpf": True}),
                   ("keyword, prefilter off", "keyword", {"bpf": False}),
                   ("hybrid, prefilter on", "hybrid", {"bpf": True, "apf": True}),
                   ("hybrid, prefilter off", "hybrid", {"bpf": False, "apf": False})]
        for who_label, who in (("typical", typical), ("narrow", narrow)):
            if who_label == "narrow":
                print("\nsearch, narrow caller (no groups):", flush=True)
            for label, mode, kw in configs:
                if mode != "basic" and not d.get("bm25"):
                    continue
                if mode == "hybrid" and not hybrid_ok:
                    continue
                samples = timed(search_fn(who, mode, **kw), n)
                recall[f"{who_label}:{label}"] = [[r["id"] for r in s["out"]["results"]] for s in samples]
                report.add(f"search {label} ({who_label})", samples,
                           f"modes {modes_used(samples)}; median results {results_of(samples)}"
                           + ("; query embedding cached" if mode == "hybrid" else ""))
            if hybrid_ok:
                samples = timed(search_fn(who, "hybrid", cold=True, bpf=vc.BM25_PREFILTER, apf=vc.ANN_PREFILTER), n)
                report.add(f"search hybrid, query embedded per request ({who_label})", samples,
                           f"modes {modes_used(samples)}; embedding included"
                           + ("" if args.profile else " (synthetic: no model call)"))
        for who_label in ("typical", "narrow"):
            for mode in ("keyword", "hybrid"):
                on, off = recall.get(f"{who_label}:{mode}, prefilter on"), recall.get(f"{who_label}:{mode}, prefilter off")
                if on and off:
                    overlap = [len(set(a) & set(b)) / len(a) for a, b in zip(on, off) if a]
                    short = sum(1 for a, b in zip(on, off) if len(b) < len(a))
                    note = (f"{mode} ({who_label}): prefilter off returns the same first page "
                            f"{statistics.mean(overlap) * 100:.0f}% of the time on average; "
                            f"{short} of {len(on)} pages came back shorter")
                    report.notes.append(note)
                    print("  " + note)

        print("\nother reads (typical caller):", flush=True)
        report.add("search keyword + facets", timed(search_fn(typical, "keyword" if d.get("bm25") else "basic",
                                                               facets=True), n))
        report.add("browse: popular, no query", timed(lambda i: vc.search(typical, vc.SearchParams(sort="popular")), n))
        report.add("browse: updated, no query", timed(lambda i: vc.search(typical, vc.SearchParams(sort="updated")), n))
        report.add("browse: name + query", timed(lambda i: vc.search(
            typical, vc.SearchParams(q=QUERIES[i % len(QUERIES)], sort="name")), n))
        first = vc.search(typical, vc.SearchParams(sort="updated"))
        report.add("browse: updated, page 2 (cursor)", timed(lambda i: vc.search(
            typical, vc.SearchParams(sort="updated", cursor=first["next_cursor"])), n))
        report.add("browse: domain + certified filter", timed(lambda i: vc.search(
            typical, vc.SearchParams(sort="popular", domain=[DOMAINS[i % len(DOMAINS)]], certified=False)), n))
        report.add("admin: scope=everything, keyword", timed(search_fn(admin, "keyword" if d.get("bm25") else "basic",
                                                                       scope="everything"), n))
        report.add("suggest (prefix as typed)", timed(lambda i: vc.suggest(typical, QUERIES[i % len(QUERIES)][:4]), n))
        report.add("rails", timed(lambda i: vc.rails(typical), n))
        homes = timed(lambda i: view_signals.home(typical), n)
        size = len(json.dumps(homes[-1]["out"], default=str))
        report.add("home (typical)", homes, f"{size / 1024:.1f} KB")
        heavy_homes = timed(lambda i: view_signals.home(heavy), n)
        heavy_size = len(json.dumps(heavy_homes[-1]["out"], default=str))
        report.add("home (owns ~1,000 views)", heavy_homes,
                   f"{heavy_size / 1024:.1f} KB; mine_total {heavy_homes[-1]['out']['mine_total']}")
        report.add("visit", timed(lambda i: view_signals.record_visit(typical.username, first["results"][i % 10]["id"]), n))

        print("\nbackground jobs:", flush=True)
        c.execute("SELECT id FROM view_catalog ORDER BY id LIMIT 500")
        ids = [r[0] for r in c.fetchall()]
        conn.commit()
        vc.queue(c, ids)
        conn.commit()
        results["drain_500_s"] = step("drain 500 queued views", lambda: vc.drain(conn, budget=120))
        results["reconcile_s"] = step("reconcile", lambda: vc.reconcile(conn))
        results["rollup_again_s"] = step("rollup_job (incremental)", view_signals.rollup_job)
        results["prune_s"] = step("prune_job", view_signals.prune_job)

        print("\nfail-open checks:", flush=True)
        broken = dict(d, text_schema="no_such_schema", schema="no_such_schema")
        where, wargs = vc.filters(typical, vc.validate(vc.SearchParams(q="supplier risk"), typical))
        pconn = database.get_db_connection("prod")
        try:
            ordered, used = vc.ranked_ids(pconn, broken, "keyword", "supplier risk", ["supplier", "risk"], where, wargs)
        finally:
            pconn.close()
        print(f"  keyword against a missing extension schema answered in {used} mode with {len(ordered)} results")
        report.notes.append(f"Keyword search against a missing extension schema fell back to {used} "
                            f"({len(ordered)} results) instead of failing.")
        os.environ["SEARCH_MODE"] = "basic"
        settings_store.invalidate()
        pinned = vc.search(typical, vc.SearchParams(q="supplier risk"))["mode"]
        os.environ.pop("SEARCH_MODE")
        settings_store.invalidate()
        print(f"  search_mode=basic pinned: answered in {pinned} mode")
        report.notes.append(f"With search_mode pinned to basic, search answered in {pinned} mode.")

        results["report"] = report.rows
        results["notes"] = report.notes
        results["rtt_ms"] = report.rtt
        print("\n" + report.markdown())
        if args.json:
            with open(args.json, "w") as fh:
                json.dump(results, fh, indent=2, default=str)
        conn.close()
        return 0
    finally:
        db_pool.close_all()
        if args.keep:
            print(f"Kept schema {schema}" + (f" and {args.ext_schema}" if installed_here else ""))
        else:
            post = raw_connection()
            post.autocommit = True
            pc = post.cursor()
            pc.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            pc.execute("SELECT e.extname, n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
                       "WHERE e.extname IN ('lakebase_text', 'lakebase_vector', 'vector')")
            after = dict(pc.fetchall())
            if not extensions_before and after and set(after.values()) == {args.ext_schema}:
                pc.execute("DROP EXTENSION IF EXISTS lakebase_vector, lakebase_text, vector CASCADE")
                pc.execute(f'DROP SCHEMA IF EXISTS "{args.ext_schema}" CASCADE')
            pc.execute("SELECT nspname FROM pg_namespace WHERE nspname IN (%s, %s)", (schema, args.ext_schema))
            left = [r[0] for r in pc.fetchall()]
            pc.execute("SELECT extname FROM pg_extension WHERE extname IN ('lakebase_text', 'lakebase_vector', 'vector')")
            left_ext = [r[0] for r in pc.fetchall()]
            post.close()
            print(f"Cleaned up: schemas left {left or 'none'}; search extensions left {left_ext or 'none'} "
                  f"(before the run: {sorted(extensions_before) or 'none'})")


if __name__ == "__main__":
    sys.exit(main())
