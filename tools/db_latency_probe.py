"""Break a Lakebase round trip into its parts, to see what pooling can win.

Run from the repo root with the server's interpreter:

    server/venv/bin/python tools/db_latency_probe.py [env]

Prints, in milliseconds: resolving credentials, the TCP/TLS/auth handshake, the
per-connection schema statements, and a trivial query on an already-open
connection.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", os.environ.get("DATABRICKS_CONFIG_PROFILE", "DEFAULT"))

import psycopg2  # noqa: E402

import database  # noqa: E402


def ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def main() -> None:
    env = sys.argv[1] if len(sys.argv) > 1 else "dev"

    print(f"env={env}")

    # 1. Whole call, cold: credentials are not cached yet.
    database.invalidate_db_credentials()
    t = time.perf_counter()
    conn = database.get_db_connection(env)
    cold = ms(t)
    conn.close()
    print(f"get_db_connection, cold (credentials + connect + schema) : {cold:8.1f} ms")

    # 2. Whole call, warm: credentials cached, so this is connect + schema.
    warm = []
    for _ in range(3):
        t = time.perf_counter()
        conn = database.get_db_connection(env)
        warm.append(ms(t))
        conn.close()
    print(f"get_db_connection, warm credentials, x3                  : "
          f"{min(warm):8.1f} / {sum(warm) / len(warm):.1f} / {max(warm):.1f} ms (min/avg/max)")

    # 3. The handshake alone, with the schema statements skipped.
    kwargs = database._cached_conn_kwargs(env)
    if not kwargs:
        print("no cached credentials; cannot split the handshake out")
        return
    raw = []
    for _ in range(3):
        t = time.perf_counter()
        c = psycopg2.connect(**kwargs)
        raw.append(ms(t))
        c.close()
    print(f"psycopg2.connect only, x3                                : "
          f"{min(raw):8.1f} / {sum(raw) / len(raw):.1f} / {max(raw):.1f} ms (min/avg/max)")

    # 4. The per-connection schema statements the app adds on top.
    schema = os.environ.get("APP_DB_SCHEMA", "").strip() or (env if env in ("dev", "test", "prod") else "app")
    c = psycopg2.connect(**kwargs)
    t = time.perf_counter()
    cur = c.cursor()
    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    cur.execute(f'SET search_path TO "{schema}"')
    c.commit()
    cur.close()
    schema_ms = ms(t)
    print(f"CREATE SCHEMA + SET search_path + commit                  : {schema_ms:8.1f} ms")

    # 5. Handshake with the search path folded into the startup packet: free.
    opts = dict(kwargs)
    opts["options"] = f"-c search_path={schema}"
    withopts = []
    for _ in range(3):
        t = time.perf_counter()
        c2 = psycopg2.connect(**opts)
        withopts.append(ms(t))
        c2.close()
    print(f"psycopg2.connect with -c search_path, x3                 : "
          f"{min(withopts):8.1f} / {sum(withopts) / len(withopts):.1f} / {max(withopts):.1f} ms (min/avg/max)")

    # 6. What a query costs once the connection is already open — i.e. what a
    #    pooled request would pay.
    queries = []
    for _ in range(5):
        t = time.perf_counter()
        cur = c.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        queries.append(ms(t))
    print(f"SELECT 1 on an open connection, x5                       : "
          f"{min(queries):8.1f} / {sum(queries) / len(queries):.1f} / {max(queries):.1f} ms (min/avg/max)")

    # 7. A real query the app runs on every page load.
    t = time.perf_counter()
    cur = c.cursor()
    cur.execute("SELECT COUNT(*) FROM widgets")
    cur.fetchone()
    cur.close()
    print(f"COUNT(*) FROM widgets on an open connection               : {ms(t):8.1f} ms")
    c.close()

    # 8. What the app now does per call: check out of the pool, query, check in.
    import db_pool  # noqa: PLC0415
    print(f"\npooling enabled: {db_pool.enabled()}")
    served = []
    for _ in range(6):
        t = time.perf_counter()
        pc = database.get_db_connection(env)
        cur = pc.cursor()
        cur.execute("SELECT COUNT(*) FROM widgets")
        cur.fetchone()
        cur.close()
        pc.close()
        served.append(ms(t))
    print(f"pooled checkout + COUNT(*) + checkin, x6                  : "
          f"{min(served):8.1f} / {sum(served) / len(served):.1f} / {max(served):.1f} ms (min/avg/max)")
    print(f"  first call {served[0]:.1f} ms, then {', '.join(f'{v:.1f}' for v in served[1:])} ms")
    print(f"  pool: {db_pool.stats().get(env)}")

    # 9. Several callers at once, as a page load does.
    import concurrent.futures  # noqa: PLC0415

    def one_query():
        pc = database.get_db_connection(env)
        try:
            cur = pc.cursor()
            cur.execute("SELECT COUNT(*) FROM widgets")
            cur.fetchone()
            cur.close()
        finally:
            pc.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        t = time.perf_counter()
        list(pool.map(lambda _: one_query(), range(6)))
        parallel = ms(t)
    print(f"6 queries in parallel, all from the pool                  : {parallel:8.1f} ms total")
    print(f"  pool: {db_pool.stats().get(env)}")


if __name__ == "__main__":
    main()
