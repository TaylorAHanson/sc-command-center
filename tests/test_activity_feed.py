"""Tests for the Admin Panel's Activity tab and the events that feed it.

Pinned with fakes in place of Postgres, so no database or Databricks is reached:

- that filters become the SQL and parameters they should, and a bad one is
  refused rather than quietly matching nothing;
- that paging through two sources by keyset shows every row exactly once, in
  order, ties included, which is what an offset would get wrong;
- that the feed names each object and says whether it can still be opened;
- that retention deletes `activity_events` in batches and never `action_logs`;
- that only an administrator can read any of it;
- that the sites which record events record metadata and never content.

    PYTHONPATH=server .venv/bin/python tests/test_activity_feed.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

# The admin gate is what is under test, so neither bypass may be on.
os.environ.pop("DEV_MODE", None)
os.environ.pop("DISABLE_PERMISSION_CHECKS", None)

try:
    from fastapi import HTTPException
    import database
    from routes import activity as activity_routes
    from services import access, activity, activity_feed as feed, settings_store
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_activity_feed: {e}")
    sys.exit(0)

T0 = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


# ------------------------------------------------------------- query builder

def test_no_filters_reads_the_newest_events_first():
    sql, params = feed.events_query(feed.Filters(), None, 51)
    assert sql == ("SELECT id, at, username, verb, object_type, object_id, detail FROM activity_events"
                   " ORDER BY at DESC, id DESC LIMIT %s")
    assert params == [51]


def test_every_filter_becomes_one_condition_with_its_parameter():
    f = feed.Filters(person="Ann@X.com", verbs=feed.parse_verbs("view.*, *.share,chat_x.turn"),
                     object_type="app", object_id="v1", since=at(0), until=at(60))
    sql, params = feed.events_query(f, None, 11)
    assert " WHERE LOWER(username) = LOWER(%s) AND (verb LIKE %s OR verb LIKE %s OR verb LIKE %s)" \
           " AND object_type = %s AND object_id = %s AND at >= %s AND at < %s ORDER BY" in sql
    # `*` is ours; `_` would be a LIKE wildcard if it weren't escaped.
    assert params == ["Ann@X.com", "view.%", "%.share", r"chat\_x.turn", "app", "v1", at(0), at(60), 11]


def test_a_filter_that_is_not_an_event_kind_is_refused():
    for bad in ("view;drop", "VIEW.%", "view..publish", "view publish"):
        try:
            feed.parse_verbs(bad)
            raise AssertionError(f"{bad!r} was accepted")
        except ValueError:
            pass
    assert feed.parse_verbs(" View.Publish ,view.publish,") == ("view.publish",)
    try:
        feed.parse_verbs(",".join(f"v{i}.x" for i in range(13)))
        raise AssertionError("too many kinds")
    except ValueError:
        pass


def test_times_without_a_zone_are_utc_and_nonsense_is_refused():
    assert feed.parse_time("2026-11-12T09:00:00Z") == T0
    assert feed.parse_time("2026-11-12T09:00:00") == T0
    assert feed.parse_time("") is None
    try:
        feed.parse_time("yesterday")
        raise AssertionError("not a time")
    except ValueError:
        pass


def test_widget_actions_join_the_feed_only_when_the_filters_allow_them():
    assert feed.actions_query(feed.Filters(object_type="app"), None, 5) is None
    assert feed.actions_query(feed.Filters(verbs=("view.*",)), None, 5) is None
    for verbs in ((), ("widget.*",), ("*.action",), ("widget.action",)):
        assert feed.actions_query(feed.Filters(verbs=verbs), None, 5) is not None, verbs
    sql, params = feed.actions_query(feed.Filters(person="ann@x.com", object_id="w1", object_type="widget"), None, 5)
    assert "a.timestamp IS NOT NULL AND LOWER(a.username) = LOWER(%s) AND a.widget_id = %s" in sql
    assert "a.timestamp::timestamptz AS at" in sql and "user_explanation" not in sql
    assert params == ["ann@x.com", "w1", 5]


# ------------------------------------------------------------- keyset cursor

def test_a_cursor_survives_the_round_trip_and_a_tampered_one_is_refused():
    cursor = feed.Cursor(at(5), feed.ACTION, 42)
    assert feed.decode_cursor(feed.encode_cursor(cursor)) == cursor
    assert feed.decode_cursor(None) is None
    for bad in ("not-base64!!", feed.encode_cursor(cursor)[:-3], "c29tZXRoaW5nfGVsc2U"):
        try:
            feed.decode_cursor(bad)
            raise AssertionError(f"{bad!r} was accepted")
        except ValueError:
            pass


def test_each_source_reads_past_the_cursor_by_time_then_source_then_id():
    after_event = feed.Cursor(at(5), feed.EVENT, 7)
    sql, params = feed.events_query(feed.Filters(), after_event, 3)
    assert "(at < %s OR (at = %s AND id < %s))" in sql and params == [at(5), at(5), 7, 3]
    sql, params = feed.actions_query(feed.Filters(), after_event, 3)
    assert "a.timestamp <= %s" in sql and params == [at(5), 3], "actions at the same instant come after events"

    after_action = feed.Cursor(at(5), feed.ACTION, 9)
    sql, params = feed.events_query(feed.Filters(), after_action, 3)
    assert "at < %s" in sql and "at = %s" not in sql and params == [at(5), 3]
    sql, params = feed.actions_query(feed.Filters(), after_action, 3)
    assert "(a.timestamp < %s OR (a.timestamp = %s AND a.id < %s))" in sql and params == [at(5), at(5), 9, 3]


class FeedCursor:
    """Answers the two feed queries over in-memory rows, applying the keyset clause the SQL carries."""

    def __init__(self, events, actions):
        self.events, self.actions = events, actions
        self.description, self.rows = [], []

    @staticmethod
    def _after(rows, sql, params, col):
        # Postgres compares `timestamp` with `timestamptz` in the session zone, UTC here.
        def when(r):
            return r["at"] if r["at"].tzinfo else r["at"].replace(tzinfo=timezone.utc)
        tie = f"({col} < %s OR ({col} = %s AND "
        if tie in sql:
            t, _, i = params[:3]
            return [r for r in rows if when(r) < t or (when(r) == t and r["id"] < i)]
        if f"{col} <= %s" in sql:
            return [r for r in rows if when(r) <= params[0]]
        if f"{col} < %s" in sql:
            return [r for r in rows if when(r) < params[0]]
        return rows

    def execute(self, sql, params=()):
        if "FROM activity_events" in sql:
            rows = self._after(self.events, sql, params, "at")
            cols = ["id", "at", "username", "verb", "object_type", "object_id", "detail"]
        elif "FROM action_logs" in sql:
            rows = self._after(self.actions, sql, params, "a.timestamp")
            cols = ["id", "at", "username", "widget_id", "widget_name", "action_name"]
        else:
            raise AssertionError(f"unexpected SQL: {sql}")
        rows = sorted(rows, key=lambda r: (r["at"], r["id"]), reverse=True)[:params[-1]]
        self.description = [(c,) for c in cols]
        self.rows = [tuple(r.get(c) for c in cols) for r in rows]

    def fetchall(self):
        return self.rows


def _event(i, minutes):
    return {"id": i, "at": at(minutes), "username": "ann@x.com", "verb": "chat.turn", "detail": {}}


def _action(i, minutes):
    # action_logs.timestamp has no zone; the query casts it, and the merge must cope either way.
    return {"id": i, "at": at(minutes).replace(tzinfo=None), "username": "bo@x.com",
            "widget_id": None, "widget_name": "Orders", "action_name": "Refund"}


def test_paging_through_both_sources_shows_every_row_once_in_order():
    events = [_event(i, m) for i, m in ((1, 0), (2, 3), (3, 3), (4, 5), (5, 8), (6, 8), (7, 9))]
    actions = [_action(i, m) for i, m in ((1, 3), (2, 5), (3, 5), (4, 7), (5, 9))]
    c = FeedCursor(events, actions)
    seen, cursor, pages = [], None, 0
    while True:
        page = feed.read_page(c, feed.Filters(), cursor, 3)
        seen += [e["key"] for e in page["events"]]
        pages += 1
        if not page["next_cursor"]:
            break
        cursor = feed.decode_cursor(page["next_cursor"])
        assert pages < 10, "the cursor stopped moving"
    expected = sorted([(e["at"], 1, e["id"], f"event:{e['id']}") for e in events]
                      + [(a["at"].replace(tzinfo=timezone.utc), 0, a["id"], f"action:{a['id']}") for a in actions],
                      reverse=True)
    assert seen == [k for *_, k in expected]
    assert pages == 4


def test_merge_ends_without_a_cursor_when_both_sources_are_exhausted():
    rows = [feed.event_row(_event(1, 1)), feed.action_row(_action(1, 2))]
    page, after = feed.merge(rows[:1], rows[1:], 2)
    assert [r["source"] for r in page] == ["action", "event"] and after is None
    page, after = feed.merge(rows[:1], rows[1:], 1)
    assert after == feed.Cursor(at(2), feed.ACTION, 1)


def test_an_action_row_carries_names_never_the_explanation():
    row = feed.action_row({**_action(3, 1), "widget_id": "w1", "user_explanation": "because the customer said so"})
    assert (row["verb"], row["object_type"], row["object_id"]) == ("widget.action", "widget", "w1")
    assert row["detail"] == {"widget_name": "Orders", "action_name": "Refund"}


# ------------------------------------------------------------- object names

class NamesCursor:
    def __init__(self):
        self.description, self.rows, self.statements = [], [], []

    def _answer(self, cols, rows):
        self.description = [(c,) for c in cols]
        self.rows = rows

    def execute(self, sql, params=()):
        self.statements.append(sql)
        if "FROM object_drafts" in sql:
            self._answer(["object_type", "object_id", "name"],
                         [("app", "v-draft", "Draft view"), ("widget", "w-pub", "Renamed")])
        elif "FROM archived_views" in sql:
            self._answer(["id"], [("v-arch",)])
        elif "FROM dashboard_views" in sql:
            self._answer(["id", "name"], [("v-pub", "Orders"), ("v-arch", "Old")])
        elif "FROM widgets" in sql:
            self._answer(["id", "name", "retired"], [("w-pub", "Widget", 0), ("w-gone", "Gone", 1)])
        elif "FROM agent_profiles" in sql:
            self._answer(["id", "name", "retired"], [])
        else:
            raise AssertionError(sql)

    def fetchall(self):
        return self.rows


def test_objects_are_named_with_whether_they_can_still_be_opened():
    c = NamesCursor()
    refs = [("app", "v-pub"), ("app", "v-draft"), ("app", "v-arch"), ("widget", "w-pub"), ("widget", "w-gone"),
            ("agent", "a-missing"), ("settings", None), (None, None), ("app", "v-pub")]
    names = feed.describe_objects(c, refs)
    assert names == {
        ("app", "v-pub"): {"name": "Orders", "state": "published"},
        ("app", "v-draft"): {"name": "Draft view", "state": "draft"},
        ("app", "v-arch"): {"name": "Old", "state": "archived"},
        ("widget", "w-pub"): {"name": "Renamed", "state": "published"},
        ("widget", "w-gone"): {"name": "Gone", "state": "deleted"},
        ("agent", "a-missing"): {"name": None, "state": "deleted"},
    }
    assert feed.describe_objects(NamesCursor(), [("settings", None), ("principal", "x")]) == {}


# ------------------------------------------------------------- retention

class PurgeConn:
    def __init__(self, deleted):
        self.deleted = list(deleted)
        self.statements, self.commits, self.closed, self.rowcount = [], 0, False, 0

    def cursor(self):
        return self

    def execute(self, sql, params=()):
        self.statements.append((" ".join(sql.split()), params))
        self.rowcount = self.deleted.pop(0) if self.deleted else 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def test_retention_deletes_old_events_a_committed_batch_at_a_time():
    conn = PurgeConn([2, 2, 1])
    assert feed.purge(conn, 30, batch=2) == 5
    assert conn.commits == 3 and len(conn.statements) == 3
    for sql, params in conn.statements:
        assert sql.startswith("DELETE FROM activity_events WHERE id IN (SELECT id FROM activity_events WHERE at <")
        assert "action_logs" not in sql, "approved actions are never this setting's to expire"
        assert params == (30, 2)


def test_retention_stops_after_its_batches_for_the_run_and_zero_keeps_everything():
    conn = PurgeConn([2] * 10)
    assert feed.purge(conn, 30, batch=2, max_batches=3) == 6 and len(conn.statements) == 3
    conn = PurgeConn([5])
    assert feed.purge(conn, 0) == 0 and conn.statements == []


def test_the_job_reads_the_setting_and_opens_nothing_when_it_is_zero():
    saved = (settings_store.get_int_setting, database.get_db_connection)
    opened = []
    try:
        settings_store.get_int_setting = lambda key: {"activity_retention_days": 0}[key]
        database.get_db_connection = lambda *a, **k: opened.append(a) or PurgeConn([])
        feed.retention_job()
        assert opened == []
        settings_store.get_int_setting = lambda key: {"activity_retention_days": 90}[key]
        conn = PurgeConn([3])
        database.get_db_connection = lambda *a, **k: conn
        feed.retention_job()
        assert conn.statements[0][1] == (90, feed.PURGE_BATCH) and conn.closed
    finally:
        settings_store.get_int_setting, database.get_db_connection = saved


# ------------------------------------------------------------- admin gate

class EmptyConn:
    def __init__(self):
        self.closed = False

    def cursor(self):
        return FeedCursor([], [])

    def commit(self):
        pass

    def close(self):
        self.closed = True


def _as(admin, fn, **kwargs):
    """Call a route as an admin or not; returns (result or HTTPException, connections opened)."""
    opened = []
    saved = (access.caller, activity_routes.get_db_connection)
    access.caller = lambda w: access.Caller("ann@x.com", (), admin)
    activity_routes.get_db_connection = lambda *a, **k: opened.append(a) or EmptyConn()
    try:
        return fn(w=None, **kwargs), opened
    except HTTPException as exc:
        return exc, opened
    finally:
        access.caller, activity_routes.get_db_connection = saved


FEED_ARGS = dict(person="", verb="", object_type="", object_id="", since=None, until=None, cursor=None, limit=50)


def test_only_an_administrator_can_read_activity():
    for fn, kwargs in ((activity_routes.list_activity, FEED_ARGS),
                       (activity_routes.active_now, {"minutes": 15}),
                       (activity_routes.person, {"username": "bo@x.com", "days": 30})):
        refused, opened = _as(False, fn, **kwargs)
        assert isinstance(refused, HTTPException) and refused.status_code == 403, fn.__name__
        assert opened == [], f"{fn.__name__} touched the database before refusing"
    page, opened = _as(True, activity_routes.list_activity, **FEED_ARGS)
    assert page == {"events": [], "next_cursor": None} and len(opened) == 1


def test_a_bad_filter_is_a_400_before_any_query():
    exc, opened = _as(True, activity_routes.list_activity, **{**FEED_ARGS, "verb": "view;drop"})
    assert exc.status_code == 400 and opened == []
    exc, opened = _as(True, activity_routes.list_activity, **{**FEED_ARGS, "cursor": "garbage"})
    assert exc.status_code == 400 and opened == []


# ------------------------------------------------------------- recording sites

def _no_content(recorded):
    for who, verb, *rest in recorded:
        detail = rest[2] if len(rest) > 2 else {}
        assert set(detail or {}) & activity._CONTENT_KEYS == set(), (verb, detail)
        assert activity.clean_detail(detail) == (detail or {}), f"{verb} sends what clean_detail would drop"


def test_view_publish_archive_and_delete_are_recorded_with_who_and_which():
    from test_apps_routes import ME, apps, draft_of, mine, row, run

    store = mine(row("v1", version=3), drafts={"v1": draft_of(row("v1"), name="Supply Hub")})
    run(store, apps.publish_app, "v1", apps.PublishRequest())
    run(store, apps.archive_app, "v1")
    run(store, apps.delete_app, "v1")
    assert store.activity == [
        (ME, "view.publish", "app", "v1", {"version": 4, "with": 0}),
        (ME, "view.archive", "app", "v1"),
        (ME, "view.delete", "app", "v1"),
    ]
    _no_content(store.activity)


def test_a_refused_change_records_nothing():
    from test_apps_routes import mine, refused, row, apps

    store = mine(row("v1"))
    refused(store, apps.publish_app, "v1", apps.PublishRequest())
    assert store.activity == []


def test_a_widget_publish_is_recorded_without_its_code():
    from test_widget_publish import World, cw

    with World() as world:
        world.publish("w1", 1)
        world.acl["w1"] = {"ana@example.com": "MANAGE"}
        cw.update_custom_widget("w1", {"tsx_code": "SECRET_CODE"}, w=None)
        cw.publish_widget("w1", w=None)
        assert world.activity == [("ana@example.com", "widget.publish", "widget", "w1", {"version": 2})]
        assert "SECRET_CODE" not in repr(world.activity)


def test_agent_changes_are_recorded_after_they_commit():
    import test_agent_studio_store as t

    world = t.World()
    undo = t._install(world)
    try:
        world.pending["a"] = t._draft("A", prompt="PRIVATE PROMPT")
        s = t.store.get_agent_studio_store()
        s.publish(t.ADMIN, "a")
        s.delete_profile(t.ADMIN, "a")
    finally:
        undo()
    assert [r[1] for r in world.activity] == ["agent.publish", "agent.delete"]
    assert world.activity[0] == ("root@x.com", "agent.publish", "agent", "a", {"version": 1})
    assert "PRIVATE" not in repr(world.activity)


def test_a_share_records_how_widely_not_with_whom():
    from routes import sharing

    entries = [{"principal": "*", "principal_type": "all", "level": "USE"},
               {"principal": "ann@x.com", "principal_type": "user", "level": "MANAGE"}]
    recorded = []
    saved = {name: getattr(access, name) for name in ("caller", "replace_acl", "owner_of", "get_acl")}
    saved_record = activity.record
    try:
        access.caller = lambda w: access.Caller("ann@x.com", (), False)
        access.replace_acl = lambda who, t, i, e: entries
        access.owner_of = lambda t, i: "ann@x.com"
        access.get_acl = lambda t, i: entries
        activity.record = lambda *args, **kwargs: recorded.append(args)
        body = sharing.AclUpdate(entries=[sharing.Entry(**e) for e in entries])
        sharing.put_acl("app", "v1", body, w=None)
    finally:
        for name, fn in saved.items():
            setattr(access, name, fn)
        activity.record = saved_record
    assert recorded == [("ann@x.com", "view.share", "app", "v1", {"entries": 2, "everyone": True, "managers": 1})]


def test_a_settings_change_records_which_settings_never_their_values():
    from routes import app_settings

    recorded = []
    patches = {
        "require_global_admin": lambda w: None,
        "_get_current_username": lambda w: "root@x.com",
        "save_settings": lambda values, who: {"saved": ["widget_app_hosts"], "cleared": ["chat_model"], "errors": {}},
        "describe_settings": lambda: [],
    }
    saved = {name: getattr(app_settings, name) for name in patches}
    saved_record, saved_invalidate = activity.record, app_settings.capabilities.invalidate
    try:
        for name, fn in patches.items():
            setattr(app_settings, name, fn)
        activity.record = lambda *args, **kwargs: recorded.append(args)
        app_settings.capabilities.invalidate = lambda: None
        app_settings.update_settings(app_settings.SettingsUpdate(settings={"widget_app_hosts": "secret-host.example"}), w=None)
    finally:
        for name, fn in saved.items():
            setattr(app_settings, name, fn)
        activity.record, app_settings.capabilities.invalidate = saved_record, saved_invalidate
    assert recorded == [("root@x.com", "settings.update", "settings", None,
                         {"keys": "chat_model,widget_app_hosts", "count": 2})]
    assert "secret-host" not in repr(recorded)


def test_a_chat_turn_is_recorded_as_having_happened_never_what_was_said():
    from routes import agent_proxy

    recorded, appended = [], []
    saved_record, saved_append = activity.record, agent_proxy.conversation_store.append_message
    try:
        activity.record = lambda *args, **kwargs: recorded.append(args)
        agent_proxy.conversation_store.append_message = lambda *a, **k: appended.append(a)
        agent_proxy._turn_recorder("dev", None, "ann@x.com", "agent-1")("THE ANSWER", [{"name": "sql"}], None)
        assert appended == [], "a turn nobody asked to remember is not saved"

        def boom(*a, **k):
            raise RuntimeError("database down")
        agent_proxy.conversation_store.append_message = boom
        try:
            agent_proxy._turn_recorder("dev", "c1", "ann@x.com", "")("THE ANSWER", [], "failed")
        except RuntimeError:
            pass
    finally:
        activity.record, agent_proxy.conversation_store.append_message = saved_record, saved_append
    assert recorded == [
        ("ann@x.com", "chat.turn", "agent", "agent-1", {"saved": False, "tools": 1, "failed": False}),
        ("ann@x.com", "chat.turn", None, None, {"saved": True, "tools": 0, "failed": True}),
    ], "the turn is logged even when saving the answer fails"
    assert "THE ANSWER" not in repr(recorded)


def test_a_widget_studio_turn_is_recorded_without_the_prompt_or_code():
    from routes import widget_studio

    recorded = []
    widget_studio.generation_jobs.persist = False
    widget_studio.generation_jobs.create("job-1", {"status": "completed", "result": {"code": "SECRET_CODE"}})
    saved_record, saved_username = activity.record, widget_studio.caller_identity.username
    try:
        activity.record = lambda *args, **kwargs: recorded.append(args)
        widget_studio.caller_identity.username = lambda w: "ann@x.com"
        req = widget_studio.GenerateRequest(prompt="PRIVATE PROMPT", current_code="OLD CODE")
        widget_studio._record_generation("job-1", req, None)
    finally:
        activity.record, widget_studio.caller_identity.username = saved_record, saved_username
    assert recorded == [("ann@x.com", "widget.generate", None, None,
                         {"status": "completed", "edit": True, "layout": "card"})]
    _no_content(recorded)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
