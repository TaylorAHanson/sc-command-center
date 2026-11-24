"""Tests for archiving views and widgets nobody uses (services/content_archive.py).

The decision is the part a mistake would get badly wrong, so most of this pins
`is_stale` and the sweep around it:

- nothing is archived merely because no use was recorded: the moment archiving
  was switched on counts as a use, so a first deploy (or switching it back on)
  starts a full grace period, whatever the objects' own dates say;
- a widget a live view places is in use, so archiving a widget never takes it
  from a view anyone can still open, and a widget follows its views out;
- a restore resets the clock, and wins over a sweep that decided before it;
- a source that can't be read means that kind is skipped, never judged unused.

The sweep runs against a fake connection that answers the statements it issues,
so no Postgres is needed; the queries themselves are exercised on a real
database by running the app.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from services import activity, content_archive as ca, view_catalog
    from services import settings_store
    from routes import custom_widgets as cw
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_content_archive: {e}")
    sys.exit(0)

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)
W1, W2, W3 = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
              "33333333-3333-4333-8333-333333333333")


# ------------------------------------------------------------- the decision

def test_off_archives_nothing():
    assert ca.is_stale(NOW, 0, NOW - 400 * DAY, [NOW - 400 * DAY]) is False


def test_nothing_is_stale_before_archiving_was_ever_switched_on():
    assert ca.is_stale(NOW, 60, None, [NOW - 400 * DAY]) is False


def test_no_recorded_history_is_not_the_same_as_unused():
    # A view published a year ago, with no opens recorded because nothing was
    # recording them: the day archiving is switched on, it has a full 60 days.
    since = NOW
    assert ca.is_stale(NOW, 60, since, [NOW - 365 * DAY, None]) is False
    assert ca.is_stale(NOW + 59 * DAY, 60, since, [NOW - 365 * DAY]) is False
    assert ca.is_stale(NOW + 60 * DAY, 60, since, [NOW - 365 * DAY]) is True


def test_the_latest_use_of_any_kind_counts():
    since = NOW - 200 * DAY
    old = NOW - 100 * DAY
    assert ca.is_stale(NOW, 60, since, [old, old]) is True
    assert ca.is_stale(NOW, 60, since, [old, NOW - 10 * DAY]) is False, "opened ten days ago"
    assert ca.is_stale(NOW, 60, since, [None, None]) is True, "nothing since archiving began, 200 days ago"


def test_something_in_use_is_never_stale():
    assert ca.is_stale(NOW, 60, NOW - 400 * DAY, [NOW - 400 * DAY], in_use=True) is False


def test_naive_and_string_moments_are_read_as_utc():
    since = NOW - 200 * DAY
    assert ca.is_stale(NOW, 60, since, [(NOW - 10 * DAY).replace(tzinfo=None)]) is False
    assert ca.is_stale(NOW, 60, since, [(NOW - 10 * DAY).isoformat()]) is False
    assert ca.last_used(None, "", "not a date") is None


def test_switching_on_starts_the_clock_and_switching_off_forgets_it():
    since, state = ca.next_state({}, 60, NOW)
    assert since == NOW and state["enabled_since"] == NOW.isoformat()
    later, state = ca.next_state(state, 60, NOW + 30 * DAY)
    assert later == NOW, "the clock started the first time and stays"
    off, state = ca.next_state(state, 0, NOW + 31 * DAY)
    assert off is None and "enabled_since" not in state
    again, state = ca.next_state(state, 60, NOW + 90 * DAY)
    assert again == NOW + 90 * DAY, "switching back on is a new grace period"


def test_the_plan_takes_the_least_recently_used_first_and_stops_at_the_cap():
    since = NOW - 300 * DAY
    candidates = [
        {"id": "b", "moments": [NOW - 100 * DAY]},
        {"id": "a", "moments": [NOW - 200 * DAY]},
        {"id": "kept", "moments": [NOW - 5 * DAY]},
        {"id": "featured", "moments": [NOW - 250 * DAY], "in_use": True},
    ]
    assert [c["id"] for c in ca.plan(NOW, 60, since, candidates)] == ["a", "b"]
    assert [c["id"] for c in ca.plan(NOW, 60, since, candidates, limit=1)] == ["a"]
    assert ca.plan(NOW, 60, since, candidates)[0]["last_used"] == NOW - 200 * DAY


def test_a_widget_id_in_a_spec_counts_as_placed():
    spec = json.dumps({"tabs": [{"widgets": [{"type": W1, "props": {"_version": 2}}, {"type": "iframe"}]}]})
    assert ca.mentions(spec, [W1, W2]) == {W1}
    assert ca.mentions("", [W1]) == set()


def test_markers_read_as_manual_unless_they_say_otherwise():
    assert ca.describe({"archived_by": "a@x.com", "timestamp": NOW})["reason"] == "manual"
    swept = ca.describe({"archived_by": None, "reason": "unused", "timestamp": NOW})
    assert swept == {"archived_at": NOW.isoformat(), "archived_by": None, "reason": "unused"}


# ------------------------------------------------------------- the sweep

class DB:
    def __init__(self, *, views=(), widgets=(), catalog=None, drafts=(), state=None, built=True,
                 fail=(), last_used=None):
        self.now = NOW
        self.views = list(views)        # candidate rows, as VIEW_CANDIDATES returns them
        self.widgets = list(widgets)    # candidate rows, as WIDGET_CANDIDATES returns them
        self.catalog = dict(catalog or {})  # published live view id -> widget ids it places
        self.drafts = list(drafts)      # spec texts of live views' drafts and queued heads
        self.state = state
        self.built = built
        self.fail = set(fail)           # fold labels that raise
        self.last_used = dict(last_used or {})  # (type, id) -> last use, for the archive guard
        self.archived = {"archived_views": [], "archived_widgets": []}
        self.touched = []
        self.statements = []


class Cursor:
    def __init__(self, db):
        self.db, self.description, self._rows, self.rowcount = db, None, [], 0

    def _answer(self, columns, rows):
        self.description = [(c,) for c in columns]
        self._rows = [tuple(r.get(c) for c in columns) for r in rows]

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        db = self.db
        db.statements.append((s, params))
        self.description, self._rows = [("?column?",)], []
        if s.startswith(("SAVEPOINT", "RELEASE", "ROLLBACK TO")):
            return
        if s == "SELECT now()":
            self._rows = [(db.now,)]
        elif s.startswith("SELECT value FROM content_archive_state"):
            self._rows = [(dict(db.state),)] if db.state else []
        elif s.startswith("INSERT INTO content_archive_state"):
            db.state = json.loads(params[1])
        elif s.startswith("INSERT INTO content_last_used"):
            source = ("view_visits" if "FROM view_visits" in s and "view_catalog" not in s else
                      "view_catalog" if "view_catalog" in s else
                      "widget_runs" if "widget_runs" in s else "action_logs")
            if source in db.fail:
                raise RuntimeError(f"relation {source} does not exist")
        elif s.startswith("SELECT h.id") and "FROM dashboard_views GROUP BY id) h" in s:
            self._answer(["id", "changed_at", "draft_at", "last_used_at", "favorited_at", "featured", "scheduled"],
                         db.views)
        elif s.startswith("SELECT h.id") and "FROM widgets WHERE" in s:
            self._answer(["id", "changed_at", "draft_at", "last_used_at", "scheduled"], db.widgets)
        elif s.startswith("SELECT DISTINCT w FROM view_catalog"):
            wanted, gone, _ = params
            found = {w for v, ws in db.catalog.items() if v not in gone for w in ws if w in wanted}
            self._rows = [(w,) for w in sorted(found)]
        elif s.startswith("SELECT COALESCE(d.spec_json"):
            self._rows = [(t,) for t in db.drafts]
        elif s.startswith("INSERT INTO archived_views") or s.startswith("INSERT INTO archived_widgets"):
            table = s.split()[2]
            done = [i for i in params["ids"]
                    if not (db.last_used.get((params["type"], i)) or NOW - 10_000 * DAY) > params["cutoff"]]
            db.archived[table] += done
            self._rows = [(i,) for i in done]
        else:
            raise AssertionError(f"unexpected statement: {s}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class Conn:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return Cursor(self.db)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def sweep(db, days=60):
    saved = (ca.catalog_built, view_catalog.touch)
    ca.catalog_built = lambda c: db.built
    view_catalog.touch = lambda c, t, i: db.touched.append((t, i))
    try:
        return ca.sweep(Conn(db), days)
    finally:
        ca.catalog_built, view_catalog.touch = saved


def view(i, used=None, changed=NOW - 400 * DAY, featured=False, scheduled=False):
    return {"id": i, "changed_at": changed, "draft_at": None, "last_used_at": used, "favorited_at": None,
            "featured": featured, "scheduled": scheduled}


def widget(i, used=None, changed=NOW - 400 * DAY, scheduled=False):
    return {"id": i, "changed_at": changed, "draft_at": None, "last_used_at": used, "scheduled": scheduled}


ON_SINCE = {"enabled_since": (NOW - 300 * DAY).isoformat(), "folded_through": (NOW - DAY).isoformat()}


def test_the_first_run_after_deploy_archives_nothing_however_old_everything_is():
    db = DB(views=[view("v-old")], widgets=[widget(W1)], catalog={})
    done = sweep(db)
    assert done["views"] == [] and done["widgets"] == []
    assert db.archived == {"archived_views": [], "archived_widgets": []}
    assert db.state["enabled_since"] == NOW.isoformat() and db.state["folded_through"] == NOW.isoformat()


def test_once_the_grace_period_is_over_unused_views_and_widgets_go():
    db = DB(views=[view("v-old"), view("v-used", used=NOW - 3 * DAY)],
            widgets=[widget(W1), widget(W2, used=NOW - 3 * DAY)], state=ON_SINCE)
    done = sweep(db)
    assert done["views"] == ["v-old"] and done["widgets"] == [W1]
    assert db.touched == [("app", "v-old")], "Discover drops the view with the archive"
    assert done["last_used"]["v-old"] == NOW - 300 * DAY, "never used: archiving's start is its last use"


def test_a_widget_on_a_live_view_is_in_use_whatever_its_own_dates_say():
    db = DB(views=[view("v-live", used=NOW - DAY)], widgets=[widget(W1), widget(W2)],
            catalog={"v-live": [W1]}, drafts=[json.dumps({"tabs": [{"widgets": [{"type": W2}]}]})], state=ON_SINCE)
    done = sweep(db)
    assert done["widgets"] == [], "W1 is on a published live view, W2 on a live view's draft"


def test_a_widget_follows_its_only_view_out():
    db = DB(views=[view("v-old")], widgets=[widget(W1)], catalog={"v-old": [W1]}, state=ON_SINCE)
    done = sweep(db)
    assert done["views"] == ["v-old"] and done["widgets"] == [W1]


def test_featured_and_scheduled_things_stay():
    db = DB(views=[view("v-featured", featured=True), view("v-scheduled", scheduled=True)],
            widgets=[widget(W1, scheduled=True)], catalog={"v-featured": [W2]}, state=ON_SINCE)
    done = sweep(db)
    assert done["views"] == [] and done["widgets"] == []


def test_a_restore_after_the_sweep_decided_wins():
    # The run read W1 as unused; someone restored it (resetting its clock) before
    # the write. The write's own guard sees the fresh use and leaves it.
    db = DB(widgets=[widget(W1)], state=ON_SINCE, last_used={("widget", W1): NOW})
    assert sweep(db)["widgets"] == []


def test_a_source_that_cant_be_read_skips_that_kind_and_folds_again_next_time():
    db = DB(views=[view("v-old")], widgets=[widget(W1)], state=ON_SINCE, fail={"view_visits"})
    done = sweep(db)
    assert done["views"] == [], "without opens, views can't be judged"
    assert done["widgets"] == [W1]
    assert db.state["folded_through"] == ON_SINCE["folded_through"], "the next run reads the same window again"


def test_widgets_wait_for_the_catalog():
    db = DB(widgets=[widget(W1)], state=ON_SINCE, built=False)
    assert sweep(db)["widgets"] == []


def test_off_archives_nothing_and_forgets_when_it_was_on():
    db = DB(views=[view("v-old")], widgets=[widget(W1)], state=ON_SINCE)
    done = sweep(db, days=0)
    assert done["views"] == [] and done["widgets"] == [] and "enabled_since" not in db.state


def test_one_run_archives_at_most_the_cap():
    saved = ca.MAX_PER_RUN
    ca.MAX_PER_RUN = 2
    try:
        db = DB(views=[view(f"v{i}", used=NOW - (100 + i) * DAY) for i in range(3)],
                widgets=[widget(W1)], state=ON_SINCE)
        done = sweep(db)
    finally:
        ca.MAX_PER_RUN = saved
    assert done["views"] == ["v2", "v1"] and done["widgets"] == [], "oldest first, and the widget waits"


def test_folding_reads_from_an_hour_before_the_last_run():
    db = DB(state=ON_SINCE)
    sweep(db)
    folds = [p for s, p in db.statements if s.startswith("INSERT INTO content_last_used")]
    assert len(folds) == len(ca.FOLDS)
    assert {p["since"] for p in folds} == {datetime.fromisoformat(ON_SINCE["folded_through"]) - timedelta(hours=1)}


def test_the_job_records_each_archive_under_the_system():
    db = DB(views=[view("v-old")], widgets=[widget(W1)], state=ON_SINCE)
    recorded = []
    import database
    saved = (ca._ready, ca.catalog_built, view_catalog.touch, activity.record, settings_store.get_int_setting,
             database.get_db_connection)
    ca._ready = True
    ca.catalog_built = lambda c: True
    view_catalog.touch = lambda c, t, i: None
    activity.record = lambda *args, **kwargs: recorded.append(args)
    settings_store.get_int_setting = lambda key: {"archive_unused_days": 60}[key]
    database.get_db_connection = lambda *a, **k: Conn(db)
    try:
        ca.sweep_job()
    finally:
        (ca._ready, ca.catalog_built, view_catalog.touch, activity.record, settings_store.get_int_setting,
         database.get_db_connection) = saved
    assert [(r[0], r[1], r[2], r[3]) for r in recorded] == [
        ("system", "view.archive", "app", "v-old"), ("system", "widget.archive", "widget", W1)]
    assert recorded[0][4]["reason"] == "unused" and recorded[0][4]["days"] == 60


def test_the_job_does_nothing_before_the_tables_exist():
    saved = ca._ready
    ca._ready = False
    try:
        assert ca.sweep_job() is None
    finally:
        ca._ready = saved


# ------------------------------------------------------------- restore

class Recorder:
    def __init__(self, answers=None):
        self.statements, self.answers, self.rowcount, self._rows = [], answers or {}, 1, []
        self.description = [("id",)]

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.statements.append((s, params))
        self._rows = next((rows for prefix, rows in self.answers.items() if s.startswith(prefix)), [])

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


def test_restoring_clears_the_marker_and_resets_the_clock():
    saved = ca._ready
    ca._ready = True
    try:
        c = Recorder()
        assert ca.restore(c, "widget", W1) is True
    finally:
        ca._ready = saved
    sql = [s for s, _ in c.statements]
    assert sql[0] == "DELETE FROM archived_widgets WHERE id = %s"
    assert any(s.startswith("INSERT INTO content_last_used") for s in sql), "the next sweep must not undo it"


def test_restoring_a_view_brings_back_only_the_widgets_the_sweep_took():
    from services import app_store, drafts

    spec = json.dumps({"schema": 1, "tabs": [{"id": "v1", "widgets": [{"i": "a", "type": W1}, {"i": "b", "type": W3}]}]})
    saved = (ca._ready, app_store.head, drafts.read)
    ca._ready = True
    app_store.head = lambda c, i: {"id": i, "spec_json": spec, "widgets_json": "[]"}
    drafts.read = lambda c, t, i: None
    try:
        c = Recorder({"DELETE FROM archived_widgets": [(W1,)]})
        assert ca.restore_placed_widgets(c, "v1") == [W1]
    finally:
        ca._ready, app_store.head, drafts.read = saved
    (deleted,) = [p for s, p in c.statements if s.startswith("DELETE FROM archived_widgets")]
    assert sorted(deleted[0]) == sorted([W1, W3]) and deleted[1] == "unused", "one archived by hand stays"


# ------------------------------------------------------------- the library

def test_an_archived_widget_leaves_the_library_and_keeps_rendering():
    rows = [
        {"id": W1, "version": 1, "is_latest": True, "name": "Old"},
        {"id": W2, "version": 1, "is_latest": True, "name": "Live"},
    ]
    marker = {"archived_at": NOW.isoformat(), "archived_by": None, "reason": "unused"}
    out = cw.shape_rows(rows, {}, None, archived={W1: marker})
    by_id = {r["id"]: r for r in out}
    assert by_id[W1]["in_library"] is False and by_id[W1]["archived"] == marker
    assert "in_library" not in by_id[W2] and "archived" not in by_id[W2]
    lent = cw.shape_rows(rows, {}, {}, lent_latest=[W1], archived={W1: marker})
    assert [r["id"] for r in lent] == [W1], "a view that places it still gets it to render"


def test_no_markers_are_read_before_the_tables_exist():
    saved = ca._ready
    ca._ready = False
    try:
        assert ca.archived(Recorder(), "widget") == {}
    finally:
        ca._ready = saved


def test_the_setting_is_described_for_the_admin_panel():
    spec = settings_store.SETTING_SPECS[ca.SETTING]
    assert (spec.kind, spec.default, spec.minimum, spec.group) == ("int", "60", 0, "content")
    assert any(g["key"] == "content" for g in settings_store.SETTING_GROUPS)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
