"""Pure-function tests for the Agent Studio store.

The Command Center repo has no pytest harness yet, so these are written to run
either under pytest (when one is added) OR standalone:

    PYTHONPATH=server python3 tests/test_agent_studio_store.py

Only the stdlib-backed helpers are covered here (no Databricks SDK / network):
frontmatter parsing, slug generation, AGENT.md/SKILL.md composition, and the
bounded TTL job store.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import agent_studio_store as store  # noqa: E402


def test_parse_frontmatter_flow_block_and_meta():
    flow = store.parse_frontmatter("---\nname: A\ntools: [x, y]\nupdated_at: T1\n---\nBODY")
    assert flow["name"] == "A"
    assert flow["tools"] == ["x", "y"]
    assert flow["updated_at"] == "T1"
    assert flow["body"] == "BODY"

    block = store.parse_frontmatter("---\nname: A\ntools:\n  - x\n  - y\n---\nBODY")
    assert block["tools"] == ["x", "y"]


def test_slugify():
    assert store.slugify("My Agent!! v2") == "my-agent-v2"
    assert store.slugify("  Spaces  ") == "spaces"


def test_build_agent_markdown_roundtrips_updated_at():
    md = store.build_agent_markdown("A", "d", "ep1", ["x", "y"], "BODY", "T2")
    meta = store.parse_frontmatter(md)
    assert meta["updated_at"] == "T2"
    assert meta["tools"] == ["x", "y"]
    assert meta["body"].strip() == "BODY"


def test_build_agent_markdown_omits_updated_at_when_blank():
    md = store.build_agent_markdown("A", "d", "", [], "BODY")
    assert "updated_at:" not in md


def test_build_skill_markdown_builds_frontmatter_from_body():
    sk = store.build_skill_markdown("Skill One", "desc", "do the thing")
    assert sk.startswith("---")
    assert "name: Skill One" in sk
    assert "description: desc" in sk
    assert "do the thing" in sk


def test_build_skill_markdown_passthrough_when_already_frontmattered():
    # Content that already carries frontmatter must NOT be double-wrapped.
    already = "---\nname: X\n---\nbody"
    out = store.build_skill_markdown("Ignored", "", already)
    assert out.count("---") == 2


def test_job_store_evicts_by_size():
    js = store_job_store(ttl_s=3600, max_jobs=2)
    js["a"] = {"status": "done"}
    js["b"] = {"status": "done"}
    js["c"] = {"status": "done"}
    # Oldest ("a") evicted once we exceed max_jobs.
    assert "a" not in js
    assert "c" in js
    # Stored payload is returned without the internal timestamp key.
    assert js["c"] == {"status": "done"}


class _Skip(Exception):
    """Raised to skip a test when an optional dependency is unavailable."""


def store_job_store(ttl_s, max_jobs):
    """Import _JobStore lazily (its module pulls FastAPI/psycopg2, often absent
    in a bare environment). Skips cleanly when those deps aren't installed."""
    try:
        from routes.agent_studio_profiles import _JobStore
    except Exception as exc:  # noqa: BLE001
        raise _Skip(f"_JobStore unavailable (missing dep): {exc}")
    return _JobStore(ttl_s=ttl_s, max_jobs=max_jobs)


if __name__ == "__main__":
    # Standalone runner (no pytest needed) — skips the _JobStore test if FastAPI
    # isn't importable in this environment.
    import traceback

    passed = failed = skipped = 0
    for _name, _fn in sorted(globals().items()):
        if not (_name.startswith("test_") and callable(_fn)):
            continue
        try:
            _fn()
            passed += 1
            print(f"PASS {_name}")
        except _Skip as exc:
            skipped += 1
            print(f"SKIP {_name}: {exc}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {_name}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    sys.exit(1 if failed else 0)
