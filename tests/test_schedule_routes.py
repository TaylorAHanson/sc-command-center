"""Tests for /api/schedules (routes/schedules.py).

Driven through FastAPI's in-process client with the real auth dependency, so an
unsigned request is refused before anything runs. The caller is faked at
`access.caller`, the store is an in-memory stand-in for `schedule_store`'s
database functions (its field checks and shapes are the real ones), and the
vault, capabilities and activity log are stubbed. Pinned here:

- the contract's shapes: `{schedules, can_see_all}`, `{schedule, connection}`,
  every Schedule and Run field, ISO UTC timestamps;
- who may do what: owners, admins (who can't change what runs or who gets it),
  and everyone else, who gets 404;
- creating always creates, as `needs_reconnect` without a connection;
- the 400s (bad SQL, recurrence, recipients, the per-person cap) and 503s, each
  with `detail` as one sentence;
- pause, resume, run now and runs;
- activity verbs with metadata only.
"""
import copy
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
sys.path.insert(0, os.path.dirname(__file__))

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from middleware.auth import get_db_client
    from routes import schedules as schedule_routes
    from services import access, activity, capabilities, schedule_store, scheduler
    from test_email_service import FROM, SES_ENV, configured
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_schedule_routes: {e}")
    sys.exit(0)

ME = "Ana@Example.com"
OWNER = "ana@example.com"
ADMIN = "root@example.com"
STRANGER = "eve@example.com"
ORIGIN = "https://cc.example.com"
CONNECTED = {"connected": True, "connected_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
             "expires_at": datetime(2026, 12, 1, tzinfo=timezone.utc), "needs_reconnect": False, "reason": None}
NOT_CONNECTED = {"connected": False, "connected_at": None, "expires_at": None, "needs_reconnect": False,
                 "reason": "not_connected"}

REPORT = {
    "kind": "email_report", "name": "Daily sales", "sql": "SELECT region, SUM(total) FROM sales GROUP BY region",
    "source_app_id": "app-1", "source_widget_instance": "inst-1", "source_widget_id": "w-1",
    "view_name": "Sales", "view_link": f"{ORIGIN}/#/app/sales", "recipients": ["bob@example.com"],
    "subject": "Sales today", "message": "Here you go.", "send_when": "has_rows", "attach_csv": True,
    "recurrence": {"freq": "weekly", "days": [1, 3], "time": "09:00", "tz": "Europe/London"},
}
ACTION = {
    "kind": "run_statement", "name": "Approve old orders", "sql": "UPDATE orders SET approved = true",
    "source_widget_id": "w-exec", "recurrence": {"freq": "daily", "time": "06:30", "tz": "UTC"},
}

SCHEDULE_KEYS = {"id", "owner", "kind", "name", "sql", "source_app_id", "source_widget_instance", "source_widget_id",
                 "view_name", "view_link", "recipients", "subject", "message", "send_when", "attach_csv",
                 "recurrence", "next_run_at", "last_run", "status", "paused_reason", "failure_count", "created_at",
                 "updated_at"}
RUN_KEYS = {"id", "schedule_id", "trigger", "started_at", "finished_at", "status", "rows", "emailed", "error"}


class Store:
    """`schedule_store`'s database half, in memory."""

    def __init__(self):
        self.rows = {}
        self.run_rows = {}
        self.clock = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)

    def _tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def _api(self, row):
        runs = sorted(self.run_rows.get(row["id"], []), key=lambda r: r["started_at"], reverse=True)
        return schedule_store.to_api(row, runs[0] if runs else None)

    def list_schedules(self, owner):
        rows = [r for r in self.rows.values() if owner is None or r["owner"] == owner]
        return [self._api(r) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]

    def get_row(self, schedule_id):
        row = self.rows.get(schedule_id)
        return copy.deepcopy(row) if row else None

    def get_api(self, schedule_id):
        row = self.rows.get(schedule_id)
        return self._api(row) if row else None

    def create(self, fields, owner, max_per_person):
        if sum(1 for r in self.rows.values() if r["owner"] == owner) >= max_per_person:
            return None
        at = self._tick()
        row = {"paused_reason": None, "failure_count": 0, "run_requested": False, "claimed_by": None,
               "claimed_until": None, "created_at": at, "updated_at": at, **copy.deepcopy(fields)}
        self.rows[row["id"]] = row
        return self._api(row)

    def update(self, schedule_id, fields, touch=True):
        row = self.rows.get(schedule_id)
        if row is None:
            return None
        row.update(copy.deepcopy(fields))
        if touch:
            row["updated_at"] = self._tick()
        return self._api(row)

    def delete(self, schedule_id):
        self.run_rows.pop(schedule_id, None)
        return self.rows.pop(schedule_id, None) is not None

    def runs(self, schedule_id, limit=20):
        limit = max(1, min(int(limit), schedule_store.MAX_RUNS))
        rows = sorted(self.run_rows.get(schedule_id, []), key=lambda r: r["started_at"], reverse=True)
        return [schedule_store.run_to_api(r) for r in rows[:limit]]

    def add_run(self, schedule_id, minutes_ago, **fields):
        started = self.clock - timedelta(minutes=minutes_ago)
        run = {"id": f"run-{len(self.run_rows.get(schedule_id, [])) + 1}", "schedule_id": schedule_id,
               "trigger": "schedule", "started_at": started, "finished_at": started + timedelta(seconds=2),
               "status": "ok", "row_count": 4, "emailed": True, "error": None, **fields}
        self.run_rows.setdefault(schedule_id, []).append(run)
        return run


class World:
    def __init__(self):
        self.store = Store()
        self.events = []
        self.caps = {"scheduling", "email"}
        self.status = dict(CONNECTED)
        self.status_fails = False
        self.widget = (None, "Approve orders")
        self.resumed = []

    def connection(self, owner):
        if self.status_fails:
            raise RuntimeError("vault database down")
        return dict(self.status), scheduler.connection_usable(self.status, datetime.now(timezone.utc))


def make_app(authenticated=True):
    app = FastAPI()
    app.include_router(schedule_routes.router, prefix="/api/schedules")
    if authenticated:
        app.dependency_overrides[get_db_client] = lambda: object()
    return app


@contextmanager
def signed_in(who=ME, admin=False, world=None, rows=None):
    world = world or World()
    identity = {"who": who, "admin": admin}
    store_attrs = ("list_schedules", "get_row", "get_api", "create", "update", "delete", "runs")
    saved = ({k: getattr(schedule_store, k) for k in store_attrs}, access.caller, activity.record,
             capabilities.available, scheduler.connection, scheduler.widget_check, scheduler.resume_owner)
    for k in store_attrs:
        setattr(schedule_store, k, getattr(world.store, k))
    access.caller = lambda _w: access.Caller(identity["who"], ("analysts",), identity["admin"])
    activity.record = lambda who_, verb, object_type=None, object_id=None, detail=None: world.events.append(
        (who_, verb, object_type, object_id, activity.clean_detail(detail)))
    capabilities.available = lambda name: name in world.caps
    scheduler.connection = world.connection
    scheduler.widget_check = lambda owner, groups, wid: world.widget
    scheduler.resume_owner = lambda owner: world.resumed.append(owner) or 0
    try:
        with configured({"email_from_address": FROM, **(rows or {})}, SES_ENV):
            yield TestClient(make_app()), world, identity
    finally:
        for k, v in saved[0].items():
            setattr(schedule_store, k, v)
        (access.caller, activity.record, capabilities.available, scheduler.connection, scheduler.widget_check,
         scheduler.resume_owner) = saved[1:]


def create(client, body=None, **extra):
    return client.post("/api/schedules", json={**(body or REPORT), **extra}, headers={"Origin": ORIGIN})


def sentence(response):
    detail = response.json()["detail"]
    assert isinstance(detail, str) and detail.endswith(".") and "\n" not in detail, detail
    return detail


def is_utc_iso(value):
    parsed = datetime.fromisoformat(value)
    return parsed.utcoffset() == timedelta(0)


# --- signed in, and the shapes -------------------------------------------------------

def test_an_unsigned_request_is_refused():
    saved = os.environ.pop("DEV_MODE", None)
    try:
        response = TestClient(make_app(authenticated=False)).get("/api/schedules")
    finally:
        if saved is not None:
            os.environ["DEV_MODE"] = saved
    assert response.status_code == 401


def test_creating_a_report_returns_the_schedule_and_the_connection():
    with signed_in() as (client, world, _id):
        response = create(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"schedule", "connection"}
    s = body["schedule"]
    assert set(s) == SCHEDULE_KEYS
    assert s["owner"] == OWNER and s["kind"] == "email_report" and s["status"] == "active"
    assert s["recipients"] == ["bob@example.com"] and s["send_when"] == "has_rows" and s["attach_csv"] is True
    assert s["recurrence"] == REPORT["recurrence"] and s["last_run"] is None
    assert s["paused_reason"] is None and s["failure_count"] == 0
    for key in ("next_run_at", "created_at", "updated_at"):
        assert is_utc_iso(s[key]), key
    assert datetime.fromisoformat(s["next_run_at"]).isoweekday() in (1, 3)
    assert body["connection"]["connected"] is True and body["connection"]["expires_at"].startswith("2026-12-01")
    row = world.store.rows[s["id"]]
    assert row["owner_email"] == ME and row["owner_groups"] == ["analysts"]


def test_creating_without_a_connection_still_creates_waiting_for_one():
    world = World()
    world.status = dict(NOT_CONNECTED)
    with signed_in(world=world) as (client, _world, _id):
        response = create(client)
    assert response.status_code == 200, response.text
    assert response.json()["schedule"]["status"] == "needs_reconnect"
    assert response.json()["connection"]["reason"] == "not_connected"


def test_an_expired_connection_counts_as_none():
    world = World()
    world.status = {**CONNECTED, "expires_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}
    with signed_in(world=world) as (client, _world, _id):
        assert create(client).json()["schedule"]["status"] == "needs_reconnect"


def test_listing_is_the_callers_own_newest_first():
    with signed_in() as (client, world, identity):
        first = create(client).json()["schedule"]["id"]
        second = create(client, name="Weekly sales").json()["schedule"]["id"]
        identity["who"] = STRANGER
        create(client, recipients=["bob@example.com"])
        identity["who"] = ME
        world.store.add_run(first, 5, status="failed", error="boom", emailed=False)
        world.store.add_run(first, 1)
        response = client.get("/api/schedules")
    assert response.status_code == 200
    body = response.json()
    assert body["can_see_all"] is False
    assert [s["id"] for s in body["schedules"]] == [second, first]
    last = body["schedules"][1]["last_run"]
    assert set(last) == RUN_KEYS and last["status"] == "ok" and last["rows"] == 4 and is_utc_iso(last["started_at"])


def test_everyones_schedules_are_for_admins():
    with signed_in() as (client, _world, identity):
        create(client)
        identity["who"] = STRANGER
        create(client)
        response = client.get("/api/schedules?all=true")
        assert response.status_code == 403 and "administrators" in sentence(response)
        identity.update(who=ADMIN, admin=True)
        body = client.get("/api/schedules?all=true").json()
        mine = client.get("/api/schedules").json()
    assert body["can_see_all"] is True and len(body["schedules"]) == 2
    assert mine["schedules"] == []


def test_listing_resumes_schedules_once_their_owner_has_connected():
    world = World()
    world.status = dict(NOT_CONNECTED)
    with signed_in(world=world) as (client, _world, _id):
        create(client)
        client.get("/api/schedules")
    assert world.resumed == [OWNER]


# --- creating: what's refused ------------------------------------------------------------

def test_a_report_that_changes_data_is_refused():
    with signed_in() as (client, world, _id):
        response = create(client, sql="MERGE INTO sales USING updates ON sales.id = updates.id "
                                      "WHEN MATCHED THEN UPDATE SET *")
    assert response.status_code == 400 and "read-only" in sentence(response) and "MERGE" in sentence(response)
    assert world.store.rows == {}


def test_each_bad_field_is_one_sentence():
    cases = [
        ({"kind": "cron_job"}, "kind"),
        ({"name": "  "}, "name"),
        ({"sql": ""}, "query"),
        ({"sql": "SELECT 1 " + "x" * schedule_store.MAX_SQL_CHARS}, "too long"),
        ({"recipients": []}, "recipient"),
        ({"recipients": ["not an address"]}, "Not an email address"),
        ({"recipients": ["mallory@elsewhere.net"]}, "your own domain"),
        ({"send_when": "sometimes"}, "Send when"),
        ({"attach_csv": "yes"}, "Attach CSV"),
        ({"recurrence": {"freq": "weekly", "time": "09:00"}}, "weekday"),
        ({"recurrence": {"freq": "daily", "time": "25:00"}}, "HH:MM"),
        ({"message": "x" * 20_001}, "too long"),
    ]
    with signed_in() as (client, world, _id):
        for change, phrase in cases:
            response = create(client, **change)
            assert response.status_code == 400, (change, response.text)
            assert phrase in sentence(response), (change, response.json())
    assert world.store.rows == {}


def test_too_many_recipients_follows_the_email_setting():
    with signed_in(rows={"email_max_recipients": "2"}) as (client, _world, _id):
        response = create(client, recipients=["a@example.com", "b@example.com", "c@example.com"])
    assert response.status_code == 400 and "At most 2 recipients" in sentence(response)


def test_the_per_person_cap_is_a_setting():
    with signed_in(rows={"schedule_max_per_person": "2"}) as (client, world, identity):
        assert create(client).status_code == 200
        assert create(client).status_code == 200
        response = create(client)
        assert response.status_code == 400 and "already have 2 schedules" in sentence(response)
        identity["who"] = STRANGER
        assert create(client).status_code == 200
    assert len(world.store.rows) == 3


def test_scheduling_and_email_must_be_set_up():
    world = World()
    world.caps = {"email"}
    with signed_in(world=world) as (client, _world, _id):
        response = create(client)
        assert response.status_code == 503 and sentence(response) == "Scheduling isn't set up in this app yet."
        world.caps = {"scheduling"}
        response = create(client)
        assert response.status_code == 503 and sentence(response) == "Email isn't set up in this app yet."
        assert create(client, ACTION).status_code == 200


def test_an_unreadable_connection_status_creates_nothing():
    world = World()
    world.status_fails = True
    with signed_in(world=world) as (client, _world, _id):
        response = create(client)
    assert response.status_code == 503 and "connection status" in sentence(response)
    assert world.store.rows == {}


def test_a_view_link_from_another_origin_is_dropped():
    with signed_in() as (client, _world, _id):
        s = create(client, view_link="https://evil.example.net/#/app/sales").json()["schedule"]
        kept = create(client).json()["schedule"]
    assert s["view_link"] is None and kept["view_link"] == REPORT["view_link"]


def test_an_action_needs_an_executable_widget_the_owner_can_use():
    world = World()
    with signed_in(world=world) as (client, _world, _id):
        response = create(client, ACTION)
        assert response.status_code == 200, response.text
        assert response.json()["schedule"]["recipients"] == []
        world.widget = ((400, scheduler.NOT_EXECUTABLE), "Approve orders")
        response = create(client, ACTION)
        assert response.status_code == 400 and "executable" in sentence(response)
        world.widget = ((404, scheduler.NOT_FOUND), "")
        assert create(client, ACTION).status_code == 404
        response = create(client, {**ACTION, "source_widget_id": ""})
        assert response.status_code == 400 and "executable widget" in sentence(response)


def test_an_unidentified_caller_cant_create():
    with signed_in(who="unknown") as (client, _world, _id):
        response = create(client)
    assert response.status_code == 403 and "couldn't tell who you are" in sentence(response)


def test_creating_records_metadata_only():
    with signed_in() as (client, world, _id):
        sid = create(client).json()["schedule"]["id"]
    (who, verb, object_type, object_id, detail), = world.events
    assert (who, verb, object_type, object_id) == (ME, "schedule.create", "schedule", sid)
    assert detail == {"kind": "email_report", "status": "active", "freq": "weekly", "recipient_count": 1}


# --- item routes: who may ------------------------------------------------------------------

def test_anyone_but_the_owner_or_an_admin_gets_404():
    with signed_in() as (client, _world, identity):
        sid = create(client).json()["schedule"]["id"]
        identity["who"] = STRANGER
        for method, path in (("patch", ""), ("delete", ""), ("post", "/pause"), ("post", "/resume"),
                             ("post", "/run"), ("get", "/runs")):
            kwargs = {"json": {"name": "x"}} if method == "patch" else {}
            response = getattr(client, method)(f"/api/schedules/{sid}{path}", **kwargs)
            assert response.status_code == 404, (method, path)
            assert sentence(response) == "That schedule wasn't found."
        assert client.get("/api/schedules/nope/runs").status_code == 404


def test_the_owner_edits_what_runs_and_the_timing_moves_next_run():
    with signed_in() as (client, world, _id):
        s = create(client).json()["schedule"]
        response = client.patch(f"/api/schedules/{s['id']}", headers={"Origin": ORIGIN},
                                json={"sql": "SELECT 1", "recurrence": {"freq": "hourly", "time": "00:15"},
                                      "recipients": ["carol@example.com"], "status": "paused",
                                      "failure_count": 99, "next_run_at": "2030-01-01T00:00:00+00:00"})
    assert response.status_code == 200, response.text
    out = response.json()
    assert set(out) == SCHEDULE_KEYS
    assert out["sql"] == "SELECT 1" and out["recipients"] == ["carol@example.com"]
    assert out["recurrence"] == {"freq": "hourly", "days": [], "time": "00:15", "tz": "UTC"}
    assert datetime.fromisoformat(out["next_run_at"]).minute == 15
    assert out["status"] == "active" and out["failure_count"] == 0
    assert out["updated_at"] > s["updated_at"]
    assert world.events[-1][1] == "schedule.update"
    assert world.events[-1][4] == {"kind": "email_report", "fields": "recipients,recurrence,sql", "count": 3}


def test_an_edit_keeps_a_report_read_only():
    with signed_in() as (client, _world, _id):
        sid = create(client).json()["schedule"]["id"]
        response = client.patch(f"/api/schedules/{sid}", json={"sql": "DROP TABLE sales"})
    assert response.status_code == 400 and "read-only" in sentence(response)


def test_fixed_fields_cant_change_but_may_be_sent_back():
    with signed_in() as (client, _world, _id):
        s = create(client).json()["schedule"]
        for key, value in (("kind", "run_statement"), ("owner", STRANGER), ("id", "other")):
            response = client.patch(f"/api/schedules/{s['id']}", json={key: value})
            assert response.status_code == 400 and "can't be changed" in sentence(response), key
        response = client.patch(f"/api/schedules/{s['id']}", headers={"Origin": ORIGIN},
                                json={**s, "name": "Renamed"})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Renamed"


def test_an_admin_may_rename_and_retime_but_not_change_what_runs():
    with signed_in() as (client, world, identity):
        s = create(client).json()["schedule"]
        identity.update(who=ADMIN, admin=True)
        response = client.patch(f"/api/schedules/{s['id']}", json={"name": "Ops: daily sales",
                                                                   "recurrence": {"freq": "daily", "time": "07:00"}})
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Ops: daily sales"
        for change in ({"sql": "SELECT 2"}, {"recipients": ["root@example.com"]}, {"message": "Hi"}):
            response = client.patch(f"/api/schedules/{s['id']}", json=change)
            assert response.status_code == 403, change
            assert "Only the schedule's owner" in sentence(response)
        current = client.get("/api/schedules?all=true").json()["schedules"][0]
        response = client.patch(f"/api/schedules/{s['id']}", json={**current, "name": "Ops 2"})
        assert response.status_code == 200
    row = world.store.rows[s["id"]]
    assert row["owner_email"] == ME and row["sql"] == REPORT["sql"]


def test_editing_an_actions_statement_rechecks_its_widget():
    world = World()
    with signed_in(world=world) as (client, _world, _id):
        sid = create(client, ACTION).json()["schedule"]["id"]
        world.widget = ((400, scheduler.NOT_EXECUTABLE), "Approve orders")
        assert client.patch(f"/api/schedules/{sid}", json={"name": "Renamed"}).status_code == 200
        response = client.patch(f"/api/schedules/{sid}", json={"sql": "DELETE FROM orders WHERE stale"})
    assert response.status_code == 400 and "executable" in sentence(response)


def test_deleting():
    with signed_in() as (client, world, _id):
        sid = create(client).json()["schedule"]["id"]
        response = client.delete(f"/api/schedules/{sid}")
        assert response.status_code == 200 and response.json() == {"deleted": True}
        assert client.get("/api/schedules").json()["schedules"] == []
    assert world.events[-1][:4] == (ME, "schedule.delete", "schedule", sid)


# --- pause, resume, run, runs ------------------------------------------------------------

def test_pause_and_resume():
    with signed_in() as (client, world, _id):
        sid = create(client).json()["schedule"]["id"]
        world.store.rows[sid]["failure_count"] = 2
        paused = client.post(f"/api/schedules/{sid}/pause").json()
        assert paused["status"] == "paused" and paused["paused_reason"] == "owner"
        again = client.post(f"/api/schedules/{sid}/pause").json()
        assert again["status"] == "paused"
        resumed = client.post(f"/api/schedules/{sid}/resume").json()
        assert resumed["status"] == "active" and resumed["paused_reason"] is None
        assert resumed["failure_count"] == 0 and is_utc_iso(resumed["next_run_at"])
    verbs = [e[1] for e in world.events]
    assert verbs == ["schedule.create", "schedule.pause", "schedule.resume"]


def test_resuming_without_a_connection_waits_for_one():
    world = World()
    with signed_in(world=world) as (client, _world, _id):
        sid = create(client).json()["schedule"]["id"]
        client.post(f"/api/schedules/{sid}/pause")
        world.status = dict(NOT_CONNECTED)
        resumed = client.post(f"/api/schedules/{sid}/resume").json()
    assert resumed["status"] == "needs_reconnect"


def test_resuming_an_auto_paused_schedule_clears_why():
    with signed_in() as (client, world, _id):
        sid = create(client).json()["schedule"]["id"]
        world.store.rows[sid].update(status="paused", paused_reason="failures", failure_count=3)
        resumed = client.post(f"/api/schedules/{sid}/resume").json()
        world.caps = set()
        world.store.rows[sid].update(status="paused", paused_reason="owner")
        response = client.post(f"/api/schedules/{sid}/resume")
    assert resumed["status"] == "active" and resumed["paused_reason"] is None and resumed["failure_count"] == 0
    assert response.status_code == 503


def test_run_now_queues_a_run_for_the_next_tick():
    with signed_in() as (client, world, _id):
        s = create(client).json()["schedule"]
        response = client.post(f"/api/schedules/{s['id']}/run")
        assert response.status_code == 200, response.text
        assert set(response.json()) == SCHEDULE_KEYS
        assert world.store.rows[s["id"]]["run_requested"] is True
        assert response.json()["updated_at"] == s["updated_at"]
        assert world.events[-1][1:] == ("schedule.run", "schedule", s["id"], {"kind": "email_report",
                                                                              "via": "manual"})
        client.post(f"/api/schedules/{s['id']}/pause")
        response = client.post(f"/api/schedules/{s['id']}/run")
        assert response.status_code == 400 and "paused" in sentence(response)
        world.store.rows[s["id"]]["status"] = "needs_reconnect"
        response = client.post(f"/api/schedules/{s['id']}/run")
        assert response.status_code == 400 and "connect" in sentence(response)
        world.store.rows[s["id"]]["status"] = "active"
        world.caps = {"scheduling"}
        response = client.post(f"/api/schedules/{s['id']}/run")
        assert response.status_code == 503 and "Email" in sentence(response)


def test_an_admin_can_run_someone_elses_schedule():
    with signed_in() as (client, world, identity):
        sid = create(client).json()["schedule"]["id"]
        identity.update(who=ADMIN, admin=True)
        assert client.post(f"/api/schedules/{sid}/run").status_code == 200
    assert world.events[-1][0] == ADMIN and world.store.rows[sid]["owner_email"] == ME


def test_runs_are_newest_first_and_capped():
    with signed_in() as (client, world, _id):
        sid = create(client).json()["schedule"]["id"]
        for minutes in (30, 10, 20):
            world.store.add_run(sid, minutes)
        runs = client.get(f"/api/schedules/{sid}/runs").json()["runs"]
        two = client.get(f"/api/schedules/{sid}/runs?limit=2").json()["runs"]
    assert [r["started_at"] for r in runs] == sorted((r["started_at"] for r in runs), reverse=True)
    assert len(runs) == 3 and len(two) == 2 and all(set(r) == RUN_KEYS for r in runs)


def test_activity_never_carries_the_query_or_the_addresses():
    with signed_in() as (client, world, _id):
        sid = create(client).json()["schedule"]["id"]
        client.patch(f"/api/schedules/{sid}", json={"recipients": ["carol@example.com"]})
        client.post(f"/api/schedules/{sid}/run")
    text = repr(world.events)
    for secret in ("SELECT", "bob@example.com", "carol@example.com", "Here you go"):
        assert secret not in text, secret


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
