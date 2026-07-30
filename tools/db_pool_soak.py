"""Exercise a running server hard enough to catch pooling mistakes.

    python3 tools/db_pool_soak.py [base-url]

Checks that writes still commit, that a request which fails does not leave a
transaction behind for the next caller, that parallel load doesn't lose leases,
and that the pool's own counters end up consistent.
"""
import concurrent.futures
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"
failures = []


def call(method: str, path: str, body=None, expect=(200,)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        payload = e.read()
        status = e.code
    elapsed = (time.perf_counter() - started) * 1000
    if expect and status not in expect:
        failures.append(f"{method} {path} -> {status} (wanted {expect}): {payload[:200]}")
    try:
        return status, json.loads(payload or b"null"), elapsed
    except Exception:  # noqa: BLE001
        return status, None, elapsed


def check(label, ok, detail=""):
    if not ok:
        failures.append(f"{label}{': ' + detail if detail else ''}")
    print(f"  {'PASS' if ok else 'FAIL'} {label}{' — ' + detail if detail else ''}")


def pool_stats():
    _, body, _ = call("GET", "/api/health")
    return (body or {}).get("db_pool", {})


def main() -> None:
    print(f"soaking {BASE}\n")
    print("pool at start:", json.dumps(pool_stats().get("dev", {})))

    print("\n--- writes still commit ---")
    name = f"pool-soak-{int(time.time())}"
    status, created, _ = call("POST", "/api/taxonomy/categories", {"name": name}, expect=(200, 201))
    _, cats, _ = call("GET", "/api/taxonomy/categories?env=dev")
    names = [c.get("name") for c in (cats.get("categories") if isinstance(cats, dict) else cats) or []]
    check("a created category is visible to the next request", name in names,
          f"created={created} in list={name in names}")

    item_id = None
    for c in (cats.get("categories") if isinstance(cats, dict) else cats) or []:
        if c.get("name") == name:
            item_id = c.get("id")
    if item_id is not None:
        call("DELETE", f"/api/taxonomy/categories/{item_id}", expect=(200, 204))
        _, cats2, _ = call("GET", "/api/taxonomy/categories?env=dev")
        names2 = [c.get("name") for c in (cats2.get("categories") if isinstance(cats2, dict) else cats2) or []]
        check("the delete committed too", name not in names2)
    else:
        check("could find the created category to clean up", False)

    print("\n--- a failing request doesn't poison the connection ---")
    call("GET", "/api/views/history?view_id=does-not-exist&env=dev", expect=None)
    call("DELETE", "/api/views/definitely-not-a-view?env=dev", expect=None)
    call("GET", "/api/conversations/not-a-conversation", expect=None)
    status, body, _ = call("GET", "/api/taxonomy/categories?env=dev")
    check("reads still work afterwards", status == 200)
    name2 = f"pool-soak-after-error-{int(time.time())}"
    call("POST", "/api/taxonomy/categories", {"name": name2}, expect=(200, 201))
    _, cats3, _ = call("GET", "/api/taxonomy/categories?env=dev")
    listed = [c for c in (cats3.get("categories") if isinstance(cats3, dict) else cats3) or []
              if c.get("name") == name2]
    check("writes still work afterwards", bool(listed))
    if listed:
        call("DELETE", f"/api/taxonomy/categories/{listed[0]['id']}", expect=(200, 204))

    print("\n--- 60 requests, 12 at a time ---")
    paths = [
        "/api/views/?env=dev",
        "/api/widgets/custom?env=dev",
        "/api/taxonomy/categories?env=dev",
        "/api/roles/my-permissions",
        "/api/conversations?limit=20",
        "/api/settings",
    ]
    work = [paths[i % len(paths)] for i in range(60)]
    times = []
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for status, _, elapsed in pool.map(lambda p: call("GET", p), work):
            times.append(elapsed)
    wall = (time.perf_counter() - started) * 1000
    print(f"  {len(times)} requests in {wall:.0f} ms; median {statistics.median(times):.0f} ms, "
          f"p90 {sorted(times)[int(len(times) * 0.9)]:.0f} ms, max {max(times):.0f} ms")

    stats = pool_stats()
    print("\npool per env after the soak:")
    for env, s in stats.items():
        print(f"  {env}: {json.dumps(s)}")
    dev = stats.get("dev", {})
    check("no connection left checked out", dev.get("leased") == 0, f"leased={dev.get('leased')}")
    check("connections were reused, not reopened each time",
          dev.get("reused", 0) > dev.get("opened", 0),
          f"reused={dev.get('reused')} opened={dev.get('opened')}")
    check("idle count is within the configured ceiling", dev.get("idle", 0) <= 16, f"idle={dev.get('idle')}")
    # Some discards are expected under a burst: connections opened past the size
    # limit, and returns that arrive when the idle quota is already full. What
    # would be wrong is churn — throwing connections away as fast as we use them.
    check("connections are not being churned",
          dev.get("discarded", 0) <= max(3, dev.get("reused", 0) // 5),
          f"discarded={dev.get('discarded')} reused={dev.get('reused')} overflow={dev.get('overflow')}")

    print()
    if failures:
        print(f"{len(failures)} PROBLEM(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("SOAK CLEAN")


if __name__ == "__main__":
    main()
