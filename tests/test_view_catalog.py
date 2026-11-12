"""Standalone tests for Discover's view catalog (services/view_catalog.py).

Only the parts that need no database: how a view becomes a catalog row (search
text, readers, the embedding hash), that `readers` matching agrees with the
access check it stands in for, the reconcile's diff, query and cursor
handling, Reciprocal Rank Fusion, which search mode runs, what the Setup card
says, and that the hooks riding on publish, share, archive and delete never
raise into the request they ride on.
"""
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from services import access, view_catalog as vc
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_view_catalog: {e}")
    sys.exit(0)

ID = "3f2a9c1e-0b5c-4d2e-9f40-4a5b8c6d7e8f"
W1 = "0b5c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d"
W2 = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
T0 = datetime(2026, 1, 1)


def entry(principal, ptype, level="USE", at=None):
    return {"principal": principal, "principal_type": ptype, "level": level, "granted_at": at}


def head(**changes):
    spec = {"schema": 1, "presentation": "standalone", "tabs": [
        {"id": "t1", "name": "Overview", "layout": "canvas", "widgets": [{"i": "a", "type": W1}, {"i": "b", "type": "iframe"}]},
        {"id": "t2", "name": "Backlog", "layout": "canvas", "widgets": [{"i": "c", "type": W2}, {"i": "d", "type": W1}]},
    ]}
    row = {"id": ID, "version": 3, "name": "Supplier Risk", "domain": "Supply Chain", "username": "ana@example.com",
           "spec_json": json.dumps(spec), "widgets_json": "[]", "timestamp": T0, "published_at": T0,
           "first_at": T0 - timedelta(days=30)}
    row.update(changes)
    return row


ACL = [entry("Ana.Lopez@Example.com", "user", "MANAGE", T0), entry("planners", "group"),
       entry("bob@example.com", "user", "MANAGE", T0 + timedelta(days=1))]


# ------------------------------------------------------------ readers and owners

def test_readers_are_the_access_list_as_keys():
    assert vc.principal_keys(ACL) == ["g:planners", "u:ana.lopez@example.com", "u:bob@example.com"]
    assert vc.principal_keys([entry("*", "all")]) == ["*"]
    assert vc.principal_keys([entry("x@example.com", "user", "OWNER"), entry("", "group")]) == []


def test_managers_hold_only_can_manage():
    assert vc.principal_keys(ACL, ("MANAGE",)) == ["u:ana.lopez@example.com", "u:bob@example.com"]


def test_readers_match_agrees_with_the_access_check():
    """The SQL prefilter must never hide a view the access list grants, nor show one it doesn't."""
    entries = [entry("*", "all"), entry("Ana@Example.com", "user"), entry("planners", "group"),
               entry("Planners", "group"), entry("bob@example.com", "user", "MANAGE"), entry("ops", "group", "NONE")]
    callers = [("ana@example.com", ()), ("ANA@EXAMPLE.COM", ("planners",)), ("carol@example.com", ("Planners",)),
               ("carol@example.com", ("ops",)), ("bob@example.com", ()), ("", ("planners",)), ("dan@example.com", ())]
    for n in range(1 << len(entries)):
        acl = [e for i, e in enumerate(entries) if n >> i & 1]
        for user, groups in callers:
            who = access.Caller(user, tuple(groups), False)
            granted = access.best_level(acl, user, groups) is not None
            assert vc.readers_match(vc.principal_keys(acl), vc.caller_keys(who)) == granted, (acl, user, groups)


def test_the_owner_is_the_first_person_given_can_manage():
    assert vc.acl_owner(ACL) == "Ana.Lopez@Example.com"
    assert vc.acl_owner([entry("z@example.com", "user", "MANAGE"), entry("a@example.com", "user", "MANAGE", T0)]) \
        == "a@example.com"
    assert vc.acl_owner([entry("planners", "group", "MANAGE")]) is None


# ------------------------------------------------------------------- catalog rows

def test_a_published_head_becomes_a_catalog_row():
    row = vc.catalog_row(head(), acl=ACL, slug="supplier-risk", widget_names={W1: "Late POs", W2: "Lead times"},
                         curation={"featured_position": 2, "certified": True})
    assert row["id"] == ID and row["name"] == "Supplier Risk" and row["sort_name"] == "supplier risk"
    assert row["owner"] == "Ana.Lopez@Example.com" and row["owner_key"] == "ana.lopez@example.com"
    assert row["presentation"] == "standalone" and row["ref"] == "supplier-risk"
    assert row["tab_names"] == ["Overview", "Backlog"]
    assert row["widget_ids"] == sorted([W1, W2]) and row["widget_names"] == ["Late POs", "Lead times"]
    assert row["published_version"] == 3 and row["published_at"] == T0 - timedelta(days=30)
    assert row["featured_position"] == 2 and row["certified"] is True
    assert row["readers"] == vc.principal_keys(ACL) and row["managers"] == vc.principal_keys(ACL, ("MANAGE",))


def test_search_text_is_weighted_name_first():
    row = vc.catalog_row(head(description="Which suppliers slip"), acl=ACL, widget_names={W1: "Late POs"})
    assert row["ta"] == "Supplier Risk"
    assert row["tb"] == "Which suppliers slip Overview Backlog"
    assert row["tc"] == "Ana Lopez Example com Supply Chain"
    assert row["td"] == "Late POs"


def test_a_malformed_spec_still_makes_a_row():
    row = vc.catalog_row(head(spec_json="{not json", widgets_json="nope", name="  ", username="unknown"))
    assert row["name"] == "Untitled view" and row["owner"] is None and row["readers"] == []
    assert row["presentation"] == "workspace" and row["widget_ids"] == []


def test_the_embedding_holds_only_the_views_own_words():
    row = vc.catalog_row(head(description="Which suppliers slip"), acl=ACL, widget_names={W1: "Late POs"})
    text = vc.embedding_text(row)
    assert text == "Supplier Risk\nWhich suppliers slip\nTabs: Overview, Backlog\nDomain: Supply Chain\nWidgets: Late POs"
    for leak in ("ana", "planners", "bob", ID):
        assert leak not in text.lower()


def test_the_embedding_hash_moves_only_with_the_embedded_text():
    base = vc.catalog_row(head(), acl=ACL)["embed_hash"]
    assert vc.catalog_row(head(), acl=[entry("*", "all")], curation={"certified": True})["embed_hash"] == base
    assert vc.catalog_row(head(version=9, timestamp=T0 + timedelta(days=3)), acl=ACL)["embed_hash"] == base
    assert vc.catalog_row(head(name="Supplier risk v2"), acl=ACL)["embed_hash"] != base
    assert len(base) == 32


def test_links_use_the_claimed_name_or_the_name_and_id():
    assert vc.catalog_row(head(), slug="supplier-risk")["ref"] == "supplier-risk"
    assert vc.catalog_row(head())["ref"] == f"supplier-risk-{ID}"
    assert vc.fallback_ref("legacy_view_1", "Old one") == "legacy_view_1"
    assert vc.link_for("a b/c") == "#/app/a%20b%2Fc"


def test_the_reconcile_finds_every_kind_of_drift():
    row = vc.catalog_row(head(), acl=ACL, slug="supplier-risk", widget_names={W1: "Late POs", W2: "Lead times"})
    names = {W1: "Late POs", W2: "Lead times"}

    def diff(catalog=None, versions=None, archived=(), slugs=None, curation=None, acls=None, widget_names=None):
        return vc.stale_ids({ID: row} if catalog is None else catalog, {ID: 3} if versions is None else versions,
                            archived, {ID: "supplier-risk"} if slugs is None else slugs, curation or {},
                            {ID: ACL} if acls is None else acls, names if widget_names is None else widget_names)

    assert diff() == []
    assert diff(versions={ID: 4}) == [ID]
    assert diff(archived=[ID]) == [ID]
    assert diff(slugs={ID: "renamed"}) == [ID]
    assert diff(curation={ID: {"certified": True}}) == [ID]
    assert diff(acls={ID: ACL[:1]}) == [ID]
    assert diff(widget_names={W1: "Late purchase orders", W2: "Lead times"}) == [ID]
    assert diff(catalog={}) == [ID]
    assert diff(versions={}) == [ID]
    assert diff(versions={ID: 3, "other": 1}) == ["other"]


# -------------------------------------------------------------- queries, cursors

def test_query_words_are_safe_inside_a_tsquery():
    assert vc.query_words("Supplier & risk:* | !(late)") == ["supplier", "risk", "late"]
    assert vc.query_words("Lieferant Überblick 東京") == ["lieferant", "überblick", "東京"]
    assert vc.query_words("snake_case") == ["snake", "case"]
    assert len(vc.query_words(" ".join(["w"] * 30))) == vc.MAX_WORDS
    assert vc.query_words(None) == []


def test_prefix_query():
    assert vc.prefix_query(["sup", "risk"]) == "sup:* & risk:*"
    assert vc.prefix_query(["sup"], "A") == "sup:*A"


def test_a_cursor_round_trips_and_anything_else_is_refused():
    for data in ({"s": "relevance", "o": 48}, {"s": "updated", "v": "2026-01-01T00:00:00+00:00", "i": ID, "t": 9}):
        assert vc.decode_cursor(vc.encode_cursor(data)) == data
    assert "=" not in vc.encode_cursor({"s": "name", "v": "ab", "i": "x"})
    for bad in ("", "not-a-cursor", vc.encode_cursor({"o": 1}).rstrip("A"), "W10"):
        try:
            vc.decode_cursor(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


# ----------------------------------------------------------------------- ranking

def test_rrf_adds_one_over_k_plus_rank_and_breaks_ties_on_id():
    fused = vc.rrf_fuse([["a", "b", "c"], ["b", "d"]], k=60)
    assert [i for i, _ in fused] == ["b", "a", "d", "c"]
    assert abs(dict(fused)["b"] - (1 / 62 + 1 / 61)) < 1e-12
    assert [i for i, _ in vc.rrf_fuse([["y", "x"], ["x", "y"]])] == ["x", "y"]
    assert dict(vc.rrf_fuse([["a", "a", "b"]]))["b"] == 1 / 62


def test_popularity_reorders_near_ties_but_never_beats_a_better_match():
    stats = {"pop": {"viewers_30d": 5000, "certified": True, "featured_position": 0}}
    assert vc.rank_candidates([["quiet", "pop"]], stats)[:2] == ["pop", "quiet"]
    assert vc.rank_candidates([["best", "x"], ["best", "pop"]], stats)[0] == "best"
    assert vc.boost(1.0, {}) == 1.0 and abs(vc.boost(1.0, stats["pop"]) - 1.07) < 1e-9


def test_relevance_stops_at_the_cap():
    ids = [f"v{i:04d}" for i in range(900)]
    assert len(vc.rank_candidates([ids], {}, cap=500)) == 500


def test_far_vector_neighbours_are_dropped():
    scored = [("a", 0.20), ("b", 0.25), ("c", 0.33), ("d", 0.5), ("e", None)]
    assert vc.vector_cutoff(scored, spread=0.12) == ["a", "b"]
    assert vc.vector_cutoff([]) == []


# ------------------------------------------------------------------------- modes

NOTHING = {"text_schema": None, "vector_schema": None, "bm25": False, "ann": False, "embedding_dims": None,
           "embedded_model": None, "state": {}}
KEYWORD = dict(NOTHING, text_schema="search_ext", text_usable=True, vector_schema="search_ext", vector_usable=True,
               bm25=True)
HYBRID = dict(KEYWORD, ann=True, embedding_dims=1024, embedded_model="databricks-gte-large-en")
MODEL = "databricks-gte-large-en"


def test_auto_picks_the_best_mode_the_database_can_run():
    assert vc.choose_mode(NOTHING, "auto", MODEL) == ("basic", [])
    assert vc.choose_mode(KEYWORD, "auto", MODEL) == ("keyword", [])
    assert vc.choose_mode(HYBRID, "auto", MODEL) == ("hybrid", [])
    assert vc.choose_mode(HYBRID, "", MODEL) == ("hybrid", [])
    assert vc.choose_mode(dict(KEYWORD, bm25=False), "auto", MODEL) == ("basic", [])


def test_hybrid_needs_this_models_embeddings_and_a_model_at_all():
    assert vc.choose_mode(HYBRID, "auto", None)[0] == "keyword"
    assert vc.choose_mode(dict(HYBRID, embedded_model="other-model"), "auto", MODEL)[0] == "keyword"
    assert vc.choose_mode(dict(HYBRID, ann=False), "auto", MODEL)[0] == "keyword"


def test_a_pinned_mode_runs_if_it_can_and_falls_back_with_a_note_if_not():
    assert vc.choose_mode(HYBRID, "basic", MODEL) == ("basic", [])
    assert vc.choose_mode(HYBRID, "Keyword", MODEL) == ("keyword", [])
    mode, notes = vc.choose_mode(KEYWORD, "hybrid", MODEL)
    assert mode == "keyword" and "can't do yet" in notes[0]
    mode, notes = vc.choose_mode(KEYWORD, "fuzzy", MODEL)
    assert mode == "keyword" and "fuzzy" in notes[0]


def test_install_errors_say_whose_move_it_is():
    assert vc.classify_install_error('extension "lakebase_text" is not available') == "not_enabled"
    assert vc.classify_install_error("could not open extension control file ...") == "not_enabled"
    assert vc.classify_install_error("permission denied to create extension") == "permission"
    assert vc.classify_install_error("must be owner of database databricks_postgres") == "permission"
    assert vc.classify_install_error("server closed the connection") == "error"
    assert vc.classify_install_error("") == "error"


BUILT = {"build": {"built_at": "2026-11-12T10:00:00+00:00"}}


def test_the_setup_row_before_lakebase_search_is_enabled():
    res = vc.capability_result(dict(NOTHING, state=BUILT), "auto", MODEL)
    assert res["available"] is True and res["mode"] == "basic"
    assert "isn't enabled" in res["missing"][0] and "Enable Lakebase Search" in res["next_step"]


def test_the_setup_row_when_the_app_may_not_install_the_extensions():
    state = dict(BUILT, extensions={"kind": "permission", "error": "permission denied"})
    res = vc.capability_result(dict(NOTHING, state=state, role="app-sp"), "auto", MODEL)
    assert res["mode"] == "basic" and "may not install" in res["missing"][0]
    assert 'CREATE EXTENSION IF NOT EXISTS lakebase_text SCHEMA search_ext' in res["next_step"]
    assert 'GRANT USAGE ON SCHEMA search_ext TO "app-sp"' in res["next_step"]


def test_the_setup_row_while_building_and_when_fully_on():
    res = vc.capability_result(dict(NOTHING, state={}), "auto", MODEL)
    assert res["available"] is False and "still being built" in res["missing"][0]
    emb = {"model": MODEL, "done": 10, "total": 40}
    res = vc.capability_result(dict(KEYWORD, state=dict(BUILT, embeddings=emb)), "auto", MODEL)
    assert res["mode"] == "keyword" and res["missing"] == ["Embedding views: 10 of 40 done."]
    done = {"model": MODEL, "done": 40, "total": 40}
    res = vc.capability_result(dict(HYBRID, state=dict(BUILT, embeddings=done)), "auto", MODEL)
    assert res == {"available": True, "mode": "hybrid", "missing": [], "next_step": ""}


def test_the_setup_row_says_when_meaning_search_is_off_or_failing():
    res = vc.capability_result(dict(KEYWORD, state=BUILT), "hybrid", None)
    assert res["mode"] == "keyword"
    assert any("set to off" in m for m in res["missing"]) and any("can't do yet" in m for m in res["missing"])
    failing = dict(BUILT, embeddings={"model": MODEL, "error": "403 Forbidden"})
    res = vc.capability_result(dict(KEYWORD, state=failing), "auto", MODEL)
    assert "403 Forbidden" in res["missing"][0] and "service principal" in res["next_step"]
    assert vc.capability_result(None, "auto", MODEL)["available"] is False


def test_the_extension_schemas_follow_the_content_schema_on_the_path():
    sql, tail = vc._search_path_sql({"text_schema": "search_ext", "vector_schema": "search_ext",
                                     "pgvector_schema": 'odd"name'})
    assert tail == ', "search_ext", "odd""name"'
    assert "current_setting('search_path') || %(sp_tail)s" in sql and "set_config" in sql
    assert vc._search_path_sql(NOTHING)[1] == ""


# ------------------------------------------------------------- search parameters

def test_only_admins_may_search_everything():
    member, admin = access.Caller("ana@example.com", ("planners",), False), access.Caller("root@example.com", (), True)
    try:
        vc.validate(vc.SearchParams(scope="everything"), member)
        raise AssertionError("a member searched everything")
    except vc.Refused:
        pass
    assert vc.validate(vc.SearchParams(scope="everything"), admin).scope == "everything"


def test_bad_parameters_are_refused_and_limits_clamped():
    who = access.Caller("ana@example.com", (), False)
    for bad in ({"scope": "nope"}, {"sort": "random"}, {"status": "archived"}, {"opened": "ever"}):
        try:
            vc.validate(vc.SearchParams(**bad), who)
            raise AssertionError(bad)
        except ValueError:
            pass
    assert vc.validate(vc.SearchParams(limit=5000), who).limit == vc.MAX_LIMIT
    assert vc.validate(vc.SearchParams(limit=0), who).limit == vc.DEFAULT_LIMIT
    assert vc.validate(vc.SearchParams(owner=[" Ana@Example.com ", ""]), who).owner == ["ana@example.com"]


def test_every_scope_but_everything_filters_on_readers():
    member = access.Caller("Ana@Example.com", ("planners",), False)
    admin = access.Caller("root@example.com", (), True)
    for scope in ("all", "mine", "shared", "favorites"):
        where, args = vc.filters(admin, vc.SearchParams(scope=scope))
        assert "vc.readers && %(keys)s::text[]" in where, scope
    where, args = vc.filters(admin, vc.SearchParams(scope="everything"))
    assert not any("readers" in w for w in where)
    where, args = vc.filters(member, vc.SearchParams(status="draft"))
    assert "vc.managers && %(keys)s::text[]" in where
    assert args["keys"] == ["*", "u:ana@example.com", "g:planners"] and args["me"] == "ana@example.com"
    assert not any("managers" in w for w in vc.filters(admin, vc.SearchParams(status="draft"))[0])


def test_a_facet_ignores_its_own_filter():
    who = access.Caller("ana@example.com", (), False)
    p = vc.SearchParams(domain=["Finance"], owner=["bob@example.com"])
    where, _ = vc.filters(who, p, skip=("domain",))
    assert "vc.domain = ANY(%(domain)s)" not in where and "vc.owner_key = ANY(%(owner)s)" in where


LIGHT_KEYS = {"id", "link", "name", "description", "owner", "domain", "presentation", "updated_at", "published_at",
              "viewers_30d", "trend", "favorites", "featured", "certified", "access", "favorite", "hidden",
              "last_opened_at"}


def test_light_rows_carry_the_contract_and_state_only_for_managers():
    row = {"id": ID, "ref": "supplier-risk", "name": "Supplier Risk", "updated_at": T0, "viewers_30d": 3,
           "trend": 0.12345, "featured_position": 0, "certified": True, "favorite": True, "has_draft": True}
    out = vc.light(row, "USE")
    assert LIGHT_KEYS <= set(out) and "state" not in out
    assert out["link"] == "#/app/supplier-risk" and out["featured"] is True and out["trend"] == 0.123
    assert out["updated_at"] == T0.isoformat() and out["access"] == "USE"
    assert vc.light(row, "MANAGE")["state"] == "published_with_draft"
    assert vc.light(dict(row, has_draft=False), "MANAGE")["state"] == "published"


# ------------------------------------------------------------------------- hooks

class RecordingCursor:
    def __init__(self, fail=False):
        self.sql, self.fail = [], fail

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if self.fail and not sql.startswith("ROLLBACK"):
            raise RuntimeError('relation "view_catalog_queue" does not exist')


def ready(flag=True):
    vc._ready = flag
    vc._hook_backoff_until = 0.0


def test_touch_queues_in_one_round_trip_inside_the_transaction():
    ready()
    try:
        c = RecordingCursor()
        vc.touch(c, "app", ID)
        assert len(c.sql) == 1 and "SAVEPOINT" in c.sql[0] and "view_catalog_queue" in c.sql[0]
        vc.touch(c, "widget", ID)
        vc.touch(c, "app", "")
        assert len(c.sql) == 1
    finally:
        ready(False)


def test_touch_never_raises_and_leaves_the_transaction_usable():
    ready()
    try:
        c = RecordingCursor(fail=True)
        vc.touch(c, "app", ID)
        assert c.sql[-1] == "ROLLBACK TO SAVEPOINT view_catalog_touch"
    finally:
        ready(False)


def test_hooks_do_nothing_before_the_tables_exist():
    ready(False)
    c = RecordingCursor()
    vc.touch(c, "app", ID)
    opened = []
    original = vc._content
    vc._content = lambda: opened.append(1)
    try:
        vc.mark_dirty("app", ID)
    finally:
        vc._content = original
    assert c.sql == [] and opened == []


class FakeConn:
    def __init__(self, fail=False):
        self.fail, self.autocommit, self.closed, self.events = fail, False, False, []

    def rollback(self):
        self.events.append("rollback")

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                conn.events.append(("execute", conn.autocommit, params))
                if conn.fail:
                    raise RuntimeError("connection reset")
        return C()

    def close(self):
        self.closed = True


def test_mark_dirty_autocommits_one_statement_and_hands_the_connection_back():
    ready()
    conn = FakeConn()
    original = vc._content
    vc._content = lambda: conn
    try:
        vc.mark_dirty("app", ID)
    finally:
        vc._content = original
        ready(False)
    assert conn.events == ["rollback", ("execute", True, (ID,))]
    assert conn.autocommit is False and conn.closed


def test_mark_dirty_never_raises_and_stands_down_after_a_failure():
    ready()
    original = vc._content
    calls = []

    def unreachable():
        calls.append(1)
        raise RuntimeError("could not connect")

    vc._content = unreachable
    try:
        vc.mark_dirty("app", ID)
        vc.mark_dirty("app", ID)
        assert calls == [1]
        conn = FakeConn(fail=True)
        vc._hook_backoff_until = 0.0
        vc._content = lambda: conn
        vc.mark_dirty("app", ID)
        assert conn.closed
    finally:
        vc._content = original
        ready(False)


def test_the_recheck_drops_what_the_access_list_no_longer_grants():
    who = access.Caller("ana@example.com", (), False)
    rows = [{"id": "a", "name": "A", "listed": True}, {"id": "b", "name": "B", "listed": True},
            {"id": "c", "name": "C", "state": "draft_only"},
            {"id": "d", "name": "A favorite since unshared", "listed": False}]
    original_levels, original_dirty = access.levels_for, vc.mark_dirty
    dirty = []
    access.levels_for = lambda w, t, ids: {"a": "USE"}
    vc.mark_dirty = lambda t, i: dirty.append(i)
    try:
        out = vc.recheck(who, rows)
    finally:
        access.levels_for, vc.mark_dirty = original_levels, original_dirty
    assert [r["id"] for r in out] == ["a"] and out[0]["access"] == "USE"
    assert dirty == ["b"]


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} passed")
