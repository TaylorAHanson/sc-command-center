"""Time the API endpoints that hit Lakebase, against one or two running servers.

    python3 tools/api_latency_probe.py http://localhost:8001 [http://localhost:8002]

With two URLs it prints them side by side, which is how the connection pool was
measured: one server with LAKEBASE_POOL=0 and one with it on.
"""
import statistics
import sys
import time
import urllib.request

ENDPOINTS = [
    "/api/views/?env=dev",
    "/api/widgets/custom?env=dev",
    "/api/widgets/popularity?env=dev",
    "/api/taxonomy/categories?env=dev",
    "/api/taxonomy/domains?env=dev",
    "/api/roles/my-permissions",
    "/api/settings",
    "/api/conversations?limit=50",
    "/api/agent/studio/profiles",
]
ROUNDS = 5


def timed(url: str) -> float:
    started = time.perf_counter()
    with urllib.request.urlopen(url, timeout=120) as r:
        r.read()
    return (time.perf_counter() - started) * 1000


def measure(base: str):
    results = {}
    for path in ENDPOINTS:
        samples = []
        for _ in range(ROUNDS):
            try:
                samples.append(timed(base + path))
            except Exception as e:  # noqa: BLE001
                print(f"  {path}: FAILED {e}")
                samples = []
                break
        if samples:
            results[path] = samples
    return results


def page_load(base: str) -> float:
    """Every endpoint at once, the way the dashboard fires them on load."""
    import concurrent.futures

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(ENDPOINTS)) as pool:
        list(pool.map(lambda p: timed(base + p), ENDPOINTS))
    return (time.perf_counter() - started) * 1000


def main() -> None:
    bases = sys.argv[1:] or ["http://localhost:8001"]
    print(f"{ROUNDS} calls per endpoint, median of each\n")
    runs = []
    for base in bases:
        print(f"warming and measuring {base} …")
        measure(base)  # discard the first pass: caches, credentials, first connect
        runs.append(measure(base))

    width = max(len(p) for p in ENDPOINTS) + 2
    header = "endpoint".ljust(width) + "".join(b.split("//")[-1].rjust(22) for b in bases)
    print("\n" + header)
    print("-" * len(header))
    totals = [0.0 for _ in bases]
    for path in ENDPOINTS:
        row = path.ljust(width)
        for i, run in enumerate(runs):
            samples = run.get(path)
            if not samples:
                row += "n/a".rjust(22)
                continue
            med = statistics.median(samples)
            totals[i] += med
            row += f"{med:8.0f} ms".rjust(22)
        print(row)
    print("-" * len(header))
    row = "total (one of each)".ljust(width)
    for total in totals:
        row += f"{total:8.0f} ms".rjust(22)
    print(row)
    row = "all of them at once".ljust(width)
    parallel = []
    for base in bases:
        page_load(base)  # warm
        best = min(page_load(base) for _ in range(3))
        parallel.append(best)
        row += f"{best:8.0f} ms".rjust(22)
    print(row)

    if len(totals) == 2 and totals[0]:
        print(f"\n{bases[1]} vs {bases[0]}:")
        print(f"  one call of each endpoint : {totals[0] / totals[1]:.1f}x faster"
              if totals[1] else "")
        print(f"  all of them in parallel   : {parallel[0] / parallel[1]:.1f}x faster"
              if parallel[1] else "")


if __name__ == "__main__":
    main()
