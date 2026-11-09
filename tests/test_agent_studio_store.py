"""Tests for the Agent Studio store.

The Command Center repo has no pytest harness yet, so these are written to run
either under pytest (when one is added) OR standalone:

    PYTHONPATH=server python3 tests/test_agent_studio_store.py

No Databricks SDK or database is reached: the text helpers (frontmatter, slugs,
AGENT.md/SKILL.md) and the access/draft rules are pure, and the store's flows run
against in-memory stand-ins for the content store (`drafts`), the access lists
(`access`) and the connection.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from fastapi import HTTPException  # noqa: E402

import agent_studio_store as store  # noqa: E402
import database  # noqa: E402
from services import access, drafts  # noqa: E402

ANN = access.Caller("ann@x.com", (), False)
BOB = access.Caller("bob@x.com", ("analysts",), False)
ADMIN = access.Caller("root@x.com", (), True)


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


# ------------------------------------------------------------- pure rules

def _row(object_id, version, name, username="ann@x.com", updated_at="T1", **extra):
    return {"id": object_id, "version": version, "name": name, "username": username,
            "updated_at": updated_at, "tools_json": "[]", "domain": "General", **extra}


def _draft(name, updated_at="T2", **payload):
    return {"payload": {"name": name, "updated_at": updated_at, **payload},
            "base_version": 1, "updated_by": "ann@x.com", "updated_at": "2026-01-01"}


def test_payload_validates_and_normalises():
    p = store.profile_payload(name="  A  ", prompt="p", tools=["genie_ask", "", "genie_ask", 3], domain="",
                              owner="ann@x.com", updated_at="T9")
    assert p["name"] == "A" and p["domain"] == "General" and p["username"] == "ann@x.com"
    assert p["tools_json"] == '["genie_one"]', "tools are saved under their current names, once"
    assert p["is_deprecated"] == 0 and p["updated_at"] == "T9" and p["visibility"] == "personal"
    assert "id" not in p and "version" not in p, "identity is never part of a draft"
    for bad in ("", "   "):
        try:
            store.profile_payload(name=bad, prompt="p")
            raise AssertionError("an agent needs a name")
        except store.AgentStudioError:
            pass
    os.environ["AGENT_STUDIO_MAX_BYTES"] = "10"
    try:
        store.profile_payload(name="A", prompt="x" * 11)
        raise AssertionError("an oversized agent must be refused")
    except store.AgentStudioError as exc:
        assert "max size" in str(exc)
    finally:
        del os.environ["AGENT_STUDIO_MAX_BYTES"]


def test_a_stale_edit_is_refused():
    store.check_unchanged({"updated_at": "T1"}, "T1")
    store.check_unchanged({"updated_at": "T1"}, None)
    store.check_unchanged(None, "T1")
    try:
        store.check_unchanged({"updated_at": "T2"}, "T1")
        raise AssertionError("someone else's newer edit must not be overwritten")
    except store.ProfileConflictError:
        pass


def test_legacy_visibility_is_never_wider_than_the_access_list():
    everyone = [{"principal": "*", "principal_type": "all", "level": "USE"}]
    group = [{"principal": "analysts", "principal_type": "group", "level": "USE"}]
    assert store.legacy_visibility(everyone, "personal") == "global"
    assert store.legacy_visibility(group, "global") == "personal", "Everyone was removed: narrower on rollback"
    assert store.legacy_visibility(group, "domain") == "domain"
    assert store.legacy_visibility([], None) == "personal"


def test_only_a_manager_asking_for_it_gets_the_draft():
    pub, draft = _row("a", 2, "Published"), _draft("Draft")
    assert store.pick_view(access.MANAGE, None, pub, draft, "a")["name"] == "Draft"
    assert store.pick_view(access.MANAGE, "draft", pub, draft, "a")["is_draft"] is True
    assert store.pick_view(access.MANAGE, "published", pub, draft, "a")["name"] == "Published"
    assert store.pick_view(access.USE, "draft", pub, draft, "a")["name"] == "Published"
    assert store.pick_view(access.USE, None, None, draft, "a") is None, "never published: nothing to use"
    assert store.pick_view(None, None, pub, None, "a") is None


def test_listing_hides_drafts_from_people_who_can_only_use():
    published = {"pub": _row("pub", 3, "Live"), "both": _row("both", 1, "Old name", username="bob@x.com")}
    pending = {"both": _draft("New name"), "new": _draft("Unpublished")}
    levels = {"pub": access.USE, "both": access.MANAGE, "new": access.MANAGE, "gone": access.USE}

    rows = {p.id: p for p in store.listing(published, pending, levels, "ann@x.com")}
    assert set(rows) == {"pub", "both", "new"}, "an id with a grant but no agent is skipped"
    assert (rows["pub"].access, rows["pub"].state, rows["pub"].name) == ("USE", "published", "Live")
    assert (rows["both"].state, rows["both"].name, rows["both"].version) == ("published_with_draft", "New name", 1)
    assert (rows["new"].state, rows["new"].published_version, rows["new"].version) == ("draft_only", None, 0)

    # Same rows, but the caller can only use "both" and "new".
    use_only = {"pub": access.USE, "both": access.USE, "new": access.USE}
    rows = {p.id: p for p in store.listing(published, pending, use_only, "ann@x.com")}
    assert set(rows) == {"pub", "both"}, "a never-published agent doesn't exist for its users"
    assert rows["both"].name == "Old name" and rows["both"].state == "published"


def test_the_chat_picker_lists_published_versions_only():
    published = {"both": _row("both", 1, "Old name")}
    pending = {"both": _draft("New name"), "new": _draft("Unpublished")}
    rows = store.listing(published, pending, None, "ann@x.com", usable_only=True)
    assert [(p.id, p.name, p.access) for p in rows] == [("both", "Old name", "MANAGE")], \
        "chat runs the published version, so even a manager picks that"


def test_an_admin_lists_everything_and_own_agents_come_first():
    published = {"z": _row("z", 1, "Zed", username="ANN@x.com"), "a": _row("a", 1, "Alpha", username="bob@x.com")}
    rows = store.listing(published, {}, None, "ann@x.com")
    assert [p.id for p in rows] == ["z", "a"], "owned_by_me ignores case, and sorts first"
    assert all(p.access == "MANAGE" for p in rows)


def test_to_dict_carries_access_and_state():
    ref = store.listing({"a": _row("a", 4, "A")}, {"a": _draft("A2")}, {"a": access.MANAGE}, "ann@x.com")[0]
    d = ref.to_dict()
    assert (d["access"], d["state"], d["published_version"], d["has_draft"], d["writable"]) == \
        ("MANAGE", "published_with_draft", 4, True, True)
    assert "visibility" not in d and "location_label" not in d
    use = store.listing({"a": _row("a", 4, "A")}, {}, {"a": access.USE}, "ann@x.com")[0].to_dict()
    assert (use["writable"], use["has_draft"]) == (False, False)


# ------------------------------------------------------------- store flows

class FakeCursor:
    def __init__(self, world):
        self.world = world
        self.rowcount = 0
        self.description = []
        self.rows = []

    def execute(self, sql, params=None):
        self.world.events.append(("sql", " ".join(sql.split()), params))
        if sql.startswith("UPDATE agent_profiles SET is_deprecated"):
            rows = self.world.published.get(params[0], [])
            for r in rows:
                r["is_deprecated"] = 1
            self.rowcount = len(rows)
        elif "FROM agent_profiles ap" in sql:
            ids = params[0] if params else list(self.world.published)
            rows = [r for r in (self.world.newest(i) for i in ids) if r]
            cols = sorted({k for r in rows for k in r})
            self.description = [(k,) for k in cols]
            self.rows = [tuple(r.get(k) for k in cols) for r in rows]

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, world):
        self.world = world

    def cursor(self):
        return FakeCursor(self.world)

    def commit(self):
        self.world.events.append(("commit",))

    def rollback(self):
        self.world.events.append(("rollback",))

    def close(self):
        pass


class World:
    """The content store and access lists the store's calls are answered from."""

    def __init__(self):
        self.published = {}   # id -> [rows, oldest first]
        self.pending = {}     # id -> draft
        self.levels = {}      # (username, id) -> level
        self.acl = {}         # id -> entries
        self.events = []

    def newest(self, object_id):
        live = [r for r in self.published.get(object_id, []) if not r.get("is_deprecated")]
        return dict(live[-1]) if live else None


def _install(world):
    """Answer `drafts`, `access` and `database` from ``world``; returns an undo."""
    saved = []

    def patch(module, name, value):
        saved.append((module, name, getattr(module, name)))
        setattr(module, name, value)

    def get_db_connection(env="dev", pooled=True, physical=False):
        return FakeConn(world)

    def save(c, t, object_id, payload, username, base_version=drafts._KEEP):
        world.events.append(("save", object_id, base_version))
        world.pending[object_id] = {"payload": dict(payload), "base_version": base_version,
                                    "updated_by": username, "updated_at": "now"}

    def publish(c, t, object_id, username):
        draft = world.pending.pop(object_id, None)
        if draft is None:
            raise HTTPException(status_code=409, detail="There are no unpublished changes to publish.")
        version = len(world.published.get(object_id, [])) + 1
        world.published.setdefault(object_id, []).append(
            {**draft["payload"], "id": object_id, "version": version, "published_by": username})
        return version

    def levels_for(who, t, ids):
        return {i: world.levels[(who.username, i)] for i in ids if (who.username, i) in world.levels}

    def grants_for(who, t):
        return {i: lv for (u, i), lv in world.levels.items() if u == who.username}

    patch(database, "get_db_connection", get_db_connection)
    patch(drafts, "latest", lambda c, t, i: world.newest(i))
    patch(drafts, "read", lambda c, t, i: world.pending.get(i))
    patch(drafts, "drafts", lambda c, t, ids=None: {
        i: d for i, d in world.pending.items() if ids is None or i in ids})
    patch(drafts, "save", save)
    patch(drafts, "publish", publish)
    patch(drafts, "discard", lambda c, t, i: world.pending.pop(i, None) is not None)
    patch(access, "levels_for", levels_for)
    patch(access, "grants_for", grants_for)
    patch(access, "get_acl", lambda t, i: list(world.acl.get(i, [])))
    patch(access, "grant_owner", lambda t, i, u: world.events.append(("grant_owner", i, u)))
    patch(access, "delete_acl", lambda t, i: world.events.append(("delete_acl", i)))

    def undo():
        for module, name, value in reversed(saved):
            setattr(module, name, value)
    return undo


def _with_world(fn):
    def run():
        world = World()
        undo = _install(world)
        try:
            fn(world)
        finally:
            undo()
    run.__name__ = fn.__name__
    return run


def _status(fn):
    try:
        fn()
    except HTTPException as exc:
        return exc.status_code
    raise AssertionError("expected an HTTPException")


@_with_world
def test_creating_an_agent_saves_a_draft_then_makes_its_creator_a_manager(world):
    ref = store.get_agent_studio_store().save_draft(ANN, name="Helper", prompt="Be helpful.")
    assert (ref.access, ref.state, ref.version, ref.username, ref.is_draft) == \
        ("MANAGE", "draft_only", 0, "ann@x.com", True)
    kinds = [e[0] for e in world.events if e[0] in ("save", "commit", "grant_owner")]
    assert kinds == ["save", "commit", "grant_owner"], "the owner is granted only after the content commits"
    assert ("save", ref.id, None) in world.events, "a new agent's draft has no published base"
    assert world.published == {}, "saving never publishes"


@_with_world
def test_an_unidentified_caller_cannot_create_an_agent_nobody_could_manage(world):
    assert _status(lambda: store.get_agent_studio_store().save_draft(
        access.Caller("unknown", (), False), name="A", prompt="p")) == 401
    assert world.pending == {}


@_with_world
def test_editing_needs_can_manage_and_keeps_the_author(world):
    world.published["a"] = [_row("a", 1, "Live", updated_at="T1")]
    s = store.get_agent_studio_store()
    assert _status(lambda: s.save_draft(BOB, name="X", prompt="p", profile_id="a")) == 404, \
        "not shared: reads as missing"
    world.levels[("bob@x.com", "a")] = access.USE
    assert _status(lambda: s.save_draft(BOB, name="X", prompt="p", profile_id="a")) == 403
    world.levels[("bob@x.com", "a")] = access.MANAGE
    ref = s.save_draft(BOB, name="Edited", prompt="p", profile_id="a", expected_updated_at="T1")
    assert (ref.name, ref.username, ref.state, ref.version) == ("Edited", "ann@x.com", "published_with_draft", 1)
    assert world.newest("a")["name"] == "Live", "users still get the published version"
    try:
        s.save_draft(BOB, name="Again", prompt="p", profile_id="a", expected_updated_at="T1")
        raise AssertionError("the draft has moved on since T1")
    except store.ProfileConflictError:
        pass


@_with_world
def test_people_who_can_only_use_an_agent_never_get_its_draft(world):
    world.published["a"] = [_row("a", 1, "Live")]
    world.pending["a"] = _draft("Draft")
    world.pending["new"] = _draft("Unpublished")
    world.levels.update({("bob@x.com", "a"): access.USE, ("bob@x.com", "new"): access.USE})
    s = store.get_agent_studio_store()
    got = s.get_profile(BOB, "a", mode="draft")
    assert (got.name, got.state, got.access) == ("Live", "published", "USE")
    assert _status(lambda: s.get_profile(BOB, "new")) == 404
    assert [p.id for p in s.list_profiles(BOB)] == ["a"]


@_with_world
def test_a_manager_reads_the_draft_unless_asking_for_the_published_version(world):
    world.published["a"] = [_row("a", 1, "Live")]
    world.pending["a"] = _draft("Draft")
    world.pending["new"] = _draft("Unpublished")
    s = store.get_agent_studio_store()
    assert s.get_profile(ADMIN, "a").name == "Draft"
    published = s.get_profile(ADMIN, "a", mode="published")
    assert (published.name, published.state, published.is_draft) == ("Live", "published_with_draft", False)
    try:
        s.get_profile(ADMIN, "new", mode="published")
        raise AssertionError("a never-published agent has no published version")
    except HTTPException as exc:
        assert exc.status_code == 404 and "hasn't been published" in exc.detail


@_with_world
def test_chat_resolves_only_a_published_agent_the_caller_can_use(world):
    world.published["a"] = [_row("a", 1, "Live", prompt="v1")]
    world.pending["a"] = _draft("Draft", prompt="v2")
    world.pending["new"] = _draft("Unpublished")
    world.levels.update({("ann@x.com", "a"): access.MANAGE, ("ann@x.com", "new"): access.MANAGE})
    s = store.get_agent_studio_store()
    ref = s.resolve_published(ANN, "a")
    assert (ref.name, ref.prompt) == ("Live", "v1"), "chat runs the published version, managers included"
    assert s.resolve_published(ANN, "new") is None
    assert s.resolve_published(BOB, "a") is None, "not shared with Bob"


@_with_world
def test_publishing_stamps_a_rollback_safe_visibility(world):
    world.pending["a"] = _draft("A", visibility="personal")
    world.acl["a"] = [{"principal": "*", "principal_type": "all", "level": "USE"}]
    s = store.get_agent_studio_store()
    assert s.publish(ADMIN, "a") == 1
    stamp = [e for e in world.events if e[0] == "sql" and e[1].startswith("UPDATE agent_profiles SET visibility")]
    assert stamp and stamp[0][2] == ("global", "a", 1)
    assert _status(lambda: s.publish(ADMIN, "a")) == 409, "nothing left to publish"


@_with_world
def test_discarding_needs_a_published_version_to_go_back_to(world):
    world.pending["new"] = _draft("Unpublished")
    s = store.get_agent_studio_store()
    assert _status(lambda: s.discard(ADMIN, "new")) == 409
    assert "new" in world.pending
    world.published["a"] = [_row("a", 1, "Live")]
    world.pending["a"] = _draft("Draft")
    s.discard(ADMIN, "a")
    assert "a" not in world.pending


@_with_world
def test_deleting_keeps_the_access_list_only_while_versions_remain(world):
    world.published["a"] = [_row("a", 1, "Live")]
    world.pending["a"] = _draft("Draft")
    world.pending["new"] = _draft("Unpublished")
    s = store.get_agent_studio_store()
    world.levels[("bob@x.com", "a")] = access.USE
    assert _status(lambda: s.delete_profile(BOB, "a")) == 403
    s.delete_profile(ADMIN, "a")
    assert world.newest("a") is None and "a" not in world.pending
    assert ("delete_acl", "a") not in world.events, "retired versions keep their access list"
    s.delete_profile(ADMIN, "new")
    assert ("delete_acl", "new") in world.events, "nothing of a draft-only agent is left"


if __name__ == "__main__":
    # Standalone runner (no pytest needed).
    import traceback

    passed = failed = 0
    for _name, _fn in sorted(globals().items()):
        if not (_name.startswith("test_") and callable(_fn)):
            continue
        try:
            _fn()
            passed += 1
            print(f"PASS {_name}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {_name}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
