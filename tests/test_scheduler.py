"""Tests for running schedules (services/scheduler.py).

No database, warehouse, vault or SES: the connection is a recording fake, and
the vault, the statement path and email are stubbed where the scheduler calls
them. Pinned here:

- who a run is: the owner's vault token in a bearer-token client, and the service
  principal only with DEV_MODE=true *and* APP_ENVIRONMENT=local, never either alone;
- the `scheduling` capability: `dev` locally, otherwise the vault's, as `oauth`;
- claiming: due rows taken with SKIP LOCKED under a lease, the next time counted
  from now (a late run fires once, as `recovery`), committed before anything runs,
  and never more than the worker has room for;
- reports: read-only re-checked at run time, `send_when`, the email sent as the
  owner with the run id, and which failures count toward pausing;
- actions: the widget re-checked, an action_logs row written first, the statement
  tagged with the run id, and the optional outcome note;
- after a run: reconnect waits, vault trouble doesn't count, enough failures in a
  row pause the schedule and tell its owner, a success resets the count;
- reconnects resume schedules, reminders go out once per threshold, a lapsed
  connection parks its owner's schedules;
- nothing logged carries a token, a row or a recipient.
"""
import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    import database
    from routes import sql_query
    from services import activity, capabilities, email_service, recurrence, schedule_store, scheduler, token_vault
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_scheduler: {e}")
    sys.exit(0)

OWNER = "ana@example.com"
TOKEN = "dapi-secret-access-token-123"
NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
HOURLY = {"freq": "hourly", "days": [], "time": "00:00", "tz": "UTC"}


def schedule(**overrides):
    row = {
        "id": "s-1", "owner": OWNER, "owner_email": OWNER, "owner_groups": ["analysts"], "kind": "email_report",
        "name": "Daily sales", "sql": "SELECT region, total FROM sales", "source_app_id": "app-1",
        "source_widget_instance": "inst-1", "source_widget_id": "w-1", "view_name": "Sales",
        "view_link": "https://cc.example.com/#/app/sales", "recipients": ["bob@example.com"],
        "subject": "Sales today", "message": "Here you go.", "send_when": "always", "attach_csv": True,
        "recurrence": HOURLY, "next_run_at": NOW, "status": "active", "paused_reason": None,
        "failure_count": 0, "run_requested": False, "claimed_by": None, "claimed_until": None,
        "created_at": NOW, "updated_at": NOW,
    }
    row.update(overrides)
    return row


@contextmanager
def patched(obj, **attrs):
    saved = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


@contextmanager
def env(**values):
    saved = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


DEPLOYED = {"DEV_MODE": None, "APP_ENVIRONMENT": "prod"}


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self._rows = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        text = " ".join(sql.split())
        self.conn.log.append((text, params))
        for needle, answer in self.conn.answers:
            if needle in text:
                columns, rows = answer(params) if callable(answer) else answer
                self.description = [(c,) for c in columns]
                self._rows = [tuple(r) for r in rows]
                self.rowcount = len(self._rows)
                return
        self.description, self._rows = None, []
        self.rowcount = self.conn.rowcount

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None


class FakeConn:
    def __init__(self, answers=(), rowcount=1):
        self.answers = list(answers)
        self.rowcount = rowcount
        self.log = []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.log.append(("COMMIT", None))

    def rollback(self):
        self.log.append(("ROLLBACK", None))

    def close(self):
        self.log.append(("CLOSE", None))

    def sql(self):
        return [t for t, _ in self.log]


def columns_and(row):
    cols = list(row)
    return cols, [[row[c] for c in cols]]


class Mail:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"ok": True, "status": "sent"}

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return dict(self.result)


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, who, verb, object_type=None, object_id=None, detail=None):
        self.events.append((who, verb, object_type, object_id, dict(detail or {})))


def statement_returning(columns, rows, total=None):
    calls = []

    def run(sql, w, cap, all_rows, retryable):
        calls.append({"sql": sql, "w": w, "cap": cap, "all_rows": all_rows, "retryable": retryable})
        return sql_query.StatementRows(columns, iter(rows), len(rows) if total is None else total, False, "st-1",
                                       False)

    run.calls = calls
    return run


def available(*names):
    return lambda name: name in names


# --- who a run is ---------------------------------------------------------------

def test_the_service_principal_needs_dev_mode_and_a_local_run_together():
    with env(DEV_MODE="true", APP_ENVIRONMENT="local"):
        assert scheduler.dev_fallback() is True
    for values in ({"DEV_MODE": "true", "APP_ENVIRONMENT": "prod"}, {"DEV_MODE": "true", "APP_ENVIRONMENT": None},
                   {"DEV_MODE": "false", "APP_ENVIRONMENT": "local"}, {"DEV_MODE": None, "APP_ENVIRONMENT": "local"}):
        with env(**values):
            assert scheduler.dev_fallback() is False, values


def test_a_deployed_run_is_the_owner_through_the_vault():
    import databricks.sdk
    import middleware.auth

    built, asked = [], []

    def fake_client(**kwargs):
        built.append(kwargs)
        return "owner-client"

    def sp(*_a, **_k):
        raise AssertionError("a deployed run used the service principal")

    with env(DEV_MODE="true", APP_ENVIRONMENT="prod", DATABRICKS_HOST="https://dbc-1.cloud.databricks.com"), \
            patched(token_vault, access_token_for=lambda who: asked.append(who) or TOKEN), \
            patched(databricks.sdk, WorkspaceClient=fake_client), patched(middleware.auth, get_db_client=sp):
        assert scheduler.client_for(OWNER) == "owner-client"
    assert asked == [OWNER]
    assert built == [{"host": "https://dbc-1.cloud.databricks.com", "token": TOKEN, "auth_type": "pat"}]


def test_a_local_dev_run_is_the_service_principal_and_skips_the_vault():
    import middleware.auth

    def vault(_who):
        raise AssertionError("the vault was asked on a dev run")

    with env(DEV_MODE="true", APP_ENVIRONMENT="local"), patched(token_vault, access_token_for=vault), \
            patched(middleware.auth, get_db_client=lambda token: ("sp", token)):
        assert scheduler.client_for(OWNER) == ("sp", None)


def test_needing_a_reconnect_and_vault_trouble_come_through():
    def needs(_who):
        raise token_vault.NeedsReconnect("expired")

    def broken(_who):
        raise token_vault.VaultError("unavailable", "The token vault's database didn't answer (OperationalError)")

    with env(**DEPLOYED), patched(token_vault, access_token_for=needs):
        out = scheduler.perform(schedule(), "run-1", "schedule")
    assert out.status == "needs_reconnect" and out.counts is False and "expired" in out.error
    with env(**DEPLOYED), patched(token_vault, access_token_for=broken):
        out = scheduler.perform(schedule(), "run-1", "schedule")
    assert out.status == "failed" and out.counts is False and "didn't answer" in out.error


# --- the capability ---------------------------------------------------------------

def test_the_capability_is_dev_on_a_developers_machine():
    with env(DEV_MODE="true", APP_ENVIRONMENT="local"), \
            patched(token_vault, capability=lambda: capabilities.result(False, missing=["A client id"])):
        res = scheduler.capability()
    assert res["available"] is True and res["mode"] == "dev"
    assert res["missing"] == ["A client id"] and "service principal" in res["next_step"]


def test_the_capability_is_the_vaults_as_oauth_when_deployed():
    ready = capabilities.result(True, next_step="Optional: set TOKEN_VAULT_KEY")
    with env(DEV_MODE="true", APP_ENVIRONMENT="prod"), patched(token_vault, capability=lambda: ready):
        res = scheduler.capability()
    assert res["available"] is True and res["mode"] == "oauth" and res["next_step"].startswith("Optional")
    off = capabilities.result(False, missing=["A client id"], next_step="Ask an account admin.")
    with env(**DEPLOYED), patched(token_vault, capability=lambda: off):
        res = scheduler.capability()
    assert res["available"] is False and res["mode"] is None and res["missing"] == ["A client id"]


# --- claiming ---------------------------------------------------------------------

def test_a_due_run_counts_its_next_time_from_now():
    plan = scheduler.plan_claim(NOW - timedelta(minutes=1), False, HOURLY, NOW)
    assert plan == scheduler.Claim("schedule", NOW + timedelta(hours=1), None)


def test_a_missed_run_fires_once_as_recovery():
    plan = scheduler.plan_claim(NOW - timedelta(days=3), False, HOURLY, NOW)
    assert plan.trigger == "recovery" and plan.next_run_at == NOW + timedelta(hours=1)


def test_run_now_keeps_the_timetable():
    later = NOW + timedelta(minutes=40)
    assert scheduler.plan_claim(later, True, HOURLY, NOW) == scheduler.Claim("manual", later, None)
    assert scheduler.plan_claim(NOW - timedelta(seconds=5), True, HOURLY, NOW).trigger == "manual"


def test_an_unreadable_recurrence_fails_and_looks_again_in_an_hour():
    plan = scheduler.plan_claim(NOW, False, {"freq": "fortnightly"}, NOW)
    assert plan.problem == scheduler.UNREADABLE and plan.next_run_at == NOW + timedelta(hours=1)
    out = scheduler.perform(schedule(), "run-1", plan.trigger, plan.problem)
    assert out.status == "failed" and out.counts is True


def test_claiming_locks_leases_advances_and_commits_first():
    db_now = NOW + timedelta(seconds=7)
    row = {**schedule(next_run_at=NOW - timedelta(hours=2)), "recurrence": json.dumps(HOURLY), "db_now": db_now}
    conn = FakeConn([("FROM schedules s WHERE s.status = 'active'", columns_and(row))])
    with patched(database, get_db_connection=lambda *a, **k: conn):
        claimed = scheduler.claim(3)
    select = conn.sql()[0]
    assert "FOR UPDATE SKIP LOCKED" in select and "LIMIT %s" in select
    assert "(s.next_run_at <= now() OR s.run_requested)" in select
    assert "(s.claimed_until IS NULL OR s.claimed_until < now())" in select
    assert conn.log[0][1] == (3,)
    update_sql, params = conn.log[1]
    assert update_sql.startswith("UPDATE schedules SET claimed_by = %s, claimed_until = %s, next_run_at = %s")
    assert params == (scheduler.WORKER, db_now + scheduler.LEASE, NOW + timedelta(hours=1), "s-1")
    assert conn.sql()[2:] == ["COMMIT", "CLOSE"]
    (got, plan), = claimed
    assert got["id"] == "s-1" and "db_now" not in got and plan.trigger == "recovery"


def test_nothing_is_claimed_without_room():
    with patched(database, get_db_connection=lambda *a, **k: (_ for _ in ()).throw(AssertionError("opened"))):
        assert scheduler.claim(0) == []


def test_a_tick_claims_only_what_the_worker_has_room_for():
    asked, ran = [], []

    def fake_claim(limit):
        asked.append(limit)
        return [(schedule(id=f"s-{i}"), scheduler.Claim("schedule", NOW, None)) for i in range(limit)]

    started = []

    def hold(target, *args):
        started.append(args[0]["id"])  # never finishes: the slots stay full

    with patched(capabilities, available=available("scheduling")), patched(scheduler, claim=fake_claim, _spawn=hold,
                                                                             TICK_BUDGET_SECONDS=0.05), \
            patched(scheduler, _in_flight=1):
        n = scheduler.tick()
        in_flight = scheduler._in_flight
    assert asked == [scheduler.MAX_PARALLEL - 1] and n == scheduler.MAX_PARALLEL - 1
    assert in_flight == scheduler.MAX_PARALLEL and len(started) == n and ran == []


def test_a_tick_keeps_claiming_as_runs_finish_and_stops_when_nothing_is_due():
    batches = [scheduler.MAX_PARALLEL, 1]
    asked, executed = [], []

    def fake_claim(limit):
        asked.append(limit)
        n = batches.pop(0) if batches else 0
        return [(schedule(id=f"s-{len(asked)}-{i}"), scheduler.Claim("schedule", NOW, None)) for i in range(n)]

    def run_now(target, *args):
        target(*args)

    with patched(capabilities, available=available("scheduling")), \
            patched(scheduler, claim=fake_claim, _spawn=run_now, execute=lambda row, plan: executed.append(row["id"])):
        n = scheduler.tick()
    assert asked == [scheduler.MAX_PARALLEL, scheduler.MAX_PARALLEL] and n == scheduler.MAX_PARALLEL + 1
    assert len(executed) == n and scheduler._in_flight == 0


def test_a_tick_does_nothing_while_scheduling_is_off():
    with patched(capabilities, available=available()), \
            patched(scheduler, claim=lambda n: (_ for _ in ()).throw(AssertionError("claimed"))):
        assert scheduler.tick() == 0


def test_a_run_that_cant_start_gives_its_claim_back():
    released = []

    def no_threads(*_a):
        raise RuntimeError("can't start new thread")

    with patched(scheduler, _spawn=no_threads, release=released.append):
        scheduler._dispatch(schedule(), scheduler.Claim("schedule", NOW, None))
    assert released == ["s-1"] and scheduler._in_flight == 0


# --- reports ------------------------------------------------------------------------

@contextmanager
def report_world(statement=None, mail=None, caps=("email", "scheduling")):
    statement = statement or statement_returning(["region", "total"], [["west", "10"], ["east", "4"]])
    mail = mail or Mail()
    with patched(sql_query, execute_rows=statement), patched(email_service, send_email=mail), \
            patched(capabilities, available=available(*caps)):
        yield statement, mail


def test_a_report_runs_its_query_as_the_owner_and_emails_the_result():
    with report_world() as (statement, mail):
        out = scheduler.run_report(schedule(), "owner-client", "run-7")
    assert out == scheduler.Outcome("ok", rows=2, emailed=True)
    call = statement.calls[0]
    assert call["w"] == "owner-client" and call["sql"] == "SELECT region, total FROM sales"
    assert call["cap"] == scheduler.REPORT_MAX_ROWS and call["retryable"] is True
    (args, kwargs), = mail.calls
    assert args[:5] == (OWNER, OWNER, ["bob@example.com"], "Sales today", "Here you go.")
    assert kwargs["table"] == {"columns": ["region", "total"], "rows": [["west", "10"], ["east", "4"]]}
    assert kwargs["attach_csv"] is True and kwargs["source"] == "schedule" and kwargs["request_id"] == "run-7"
    assert kwargs["view_name"] == "Sales" and kwargs["view_link"] == "https://cc.example.com/#/app/sales"


def test_a_report_without_a_subject_uses_its_name():
    with report_world() as (_statement, mail):
        scheduler.run_report(schedule(subject=None), "w", "run-1")
    assert mail.calls[0][0][3] == "Daily sales"


def test_a_query_that_changes_data_is_refused_at_run_time():
    with report_world() as (statement, mail):
        out = scheduler.run_report(schedule(sql="DELETE FROM sales"), "w", "run-1")
    assert out.status == "failed" and out.counts is True and "read-only" in out.error
    assert statement.calls == [] and mail.calls == []


def test_send_when_skips_without_emailing():
    empty = statement_returning(["region"], [])
    with report_world(statement=empty) as (_s, mail):
        out = scheduler.run_report(schedule(send_when="has_rows"), "w", "run-1")
    assert out == scheduler.Outcome("skipped", rows=0) and mail.calls == []
    with report_world() as (_s, mail):
        out = scheduler.run_report(schedule(send_when="no_rows"), "w", "run-1")
    assert out.status == "skipped" and out.rows == 2 and mail.calls == []
    with report_world(statement=statement_returning(["region"], [])) as (_s, mail):
        out = scheduler.run_report(schedule(send_when="no_rows"), "w", "run-1")
    assert out.status == "ok" and len(mail.calls) == 1


def test_the_row_count_is_the_whole_result_not_the_rows_read():
    big = statement_returning(["n"], [["1"]] * 3, total=25_000)
    with report_world(statement=big):
        out = scheduler.run_report(schedule(), "w", "run-1")
    assert out.rows == 25_000


def test_email_being_off_fails_the_run_without_counting():
    with report_world(caps=("scheduling",)) as (statement, mail):
        out = scheduler.run_report(schedule(), "w", "run-1")
    assert out.status == "failed" and out.counts is False and out.error == email_service.UNAVAILABLE
    assert statement.calls == [] and mail.calls == []
    with report_world(mail=Mail({"ok": False, "status": "unavailable", "error": email_service.UNAVAILABLE})):
        out = scheduler.run_report(schedule(), "w", "run-1")
    assert out.status == "failed" and out.counts is False


def test_a_refused_or_failed_email_fails_the_run_and_counts():
    for result in ({"ok": False, "status": "refused", "error": "Email can only go to example.com."},
                   {"ok": False, "status": "failed", "error": "SES said no."}):
        with report_world(mail=Mail(result)):
            out = scheduler.run_report(schedule(), "w", "run-1")
        assert out.status == "failed" and out.counts is True and out.error == result["error"] and out.rows == 2


def test_a_failing_query_counts_but_a_missing_warehouse_doesnt():
    from fastapi import HTTPException

    def bad_sql(*_a, **_k):
        raise sql_query.SqlStatementError(status_code=400, detail="TABLE_OR_VIEW_NOT_FOUND: sales")

    def no_warehouse(*_a, **_k):
        raise HTTPException(status_code=500, detail="No SQL Warehouse ID configured.")

    with report_world(statement=bad_sql) as (_s, mail):
        out = scheduler.run_report(schedule(), "w", "run-1")
    assert out.status == "failed" and out.counts is True and "TABLE_OR_VIEW_NOT_FOUND" in out.error
    assert mail.calls == []
    with report_world(statement=no_warehouse):
        out = scheduler.run_report(schedule(), "w", "run-1")
    assert out.status == "failed" and out.counts is False


def test_a_warehouse_refusal_reads_like_the_widget_path():
    from databricks.sdk.errors import PermissionDenied

    def denied(*_a, **_k):
        raise PermissionDenied("User does not have SELECT on table sales")

    with report_world(statement=denied):
        out = scheduler.run_report(schedule(), "w", "run-1")
    assert out.status == "failed" and out.counts is True and "does not have SELECT" in out.error


# --- actions ------------------------------------------------------------------------

@contextmanager
def action_world(check=(None, "Approve orders"), statement=None, mail=None, caps=("email", "scheduling"),
                 log_fails=False):
    statement = statement or statement_returning(["num_affected_rows", "num_inserted_rows"], [["3", "0"]])
    mail = mail or Mail()
    order, logged = [], []

    def log_user_action(widget_id, widget_name, explanation, context, action_name="", username=None,
                        request_id=None, env="dev"):
        if log_fails:
            raise RuntimeError("connection reset")
        order.append("action_log")
        logged.append({"widget_id": widget_id, "widget_name": widget_name, "explanation": explanation,
                       "context": json.loads(context), "action_name": action_name, "username": username,
                       "request_id": request_id})
        return {"status": "success", "action_id": 1}

    def run(*args, **kwargs):
        order.append("statement")
        return statement(*args, **kwargs)

    run.calls = statement.calls
    with patched(scheduler, widget_check=lambda owner, groups, wid: check), \
            patched(database, log_user_action=log_user_action), patched(sql_query, execute_rows=run), \
            patched(email_service, send_email=mail), patched(capabilities, available=available(*caps)):
        yield run, mail, order, logged


def action(**overrides):
    return schedule(**{"kind": "run_statement", "sql": "UPDATE orders SET approved = true WHERE age_days > 7",
                       "recipients": [], "subject": None, "message": None, **overrides})


def test_an_action_is_logged_then_runs_tagged_with_the_run_id():
    with action_world() as (statement, mail, order, logged):
        out = scheduler.run_action(action(), "owner-client", "run-42", "schedule")
    assert out == scheduler.Outcome("ok", rows=3)
    assert order == ["action_log", "statement"]
    entry, = logged
    assert entry["request_id"] == "run-42" and entry["username"] == OWNER and entry["widget_id"] == "w-1"
    assert entry["widget_name"] == "Approve orders" and entry["action_name"] == "schedule"
    assert entry["context"]["schedule_id"] == "s-1" and entry["context"]["trigger"] == "schedule"
    call = statement.calls[0]
    assert call["sql"].startswith("/* cc-action: run-42 */\nUPDATE orders")
    assert call["retryable"] is False and call["w"] == "owner-client"
    assert mail.calls == []


def test_an_action_whose_widget_stopped_qualifying_doesnt_run():
    for check in (((400, scheduler.NOT_EXECUTABLE), "Approve orders"), ((404, scheduler.NOT_FOUND), "")):
        with action_world(check=check) as (statement, _mail, order, _logged):
            out = scheduler.run_action(action(), "w", "run-1", "schedule")
        assert out.status == "failed" and out.counts is True and out.error == check[0][1]
        assert order == [] and statement.calls == []


def test_no_action_log_row_means_no_statement():
    with action_world(log_fails=True) as (statement, _mail, _order, _logged):
        out = scheduler.run_action(action(), "w", "run-1", "schedule")
    assert out.status == "failed" and out.counts is False and out.error == scheduler.UNRECORDED
    assert statement.calls == []


def test_an_actions_recipients_get_a_short_note():
    with action_world() as (_statement, mail, _order, _logged):
        out = scheduler.run_action(action(recipients=["ops@example.com"]), "w", "run-1", "manual")
    assert out.status == "ok" and out.emailed is True
    (args, kwargs), = mail.calls
    assert args[2] == ["ops@example.com"] and args[3] == "Daily sales: done" and "changed 3 rows" in args[4]
    assert kwargs["source"] == "schedule" and kwargs["request_id"] == "run-1"


def test_a_failed_action_tells_its_recipients_too():
    def broken(*_a, **_k):
        raise sql_query.SqlStatementError(status_code=400, detail="DELTA_CONCURRENT_APPEND")

    broken.calls = []
    with action_world(statement=broken) as (_statement, mail, _order, _logged):
        out = scheduler.run_action(action(recipients=["ops@example.com"]), "w", "run-1", "schedule")
    assert out.status == "failed" and out.counts is True and out.emailed is True
    assert mail.calls[0][0][3] == "Daily sales: failed" and "DELTA_CONCURRENT_APPEND" in mail.calls[0][0][4]


def test_a_note_that_isnt_sent_leaves_the_run_ok_and_says_so():
    with action_world(mail=Mail({"ok": False, "status": "refused", "error": "Daily limit."})) as (_s, _m, _o, _l):
        out = scheduler.run_action(action(recipients=["ops@example.com"]), "w", "run-1", "schedule")
    assert out.status == "ok" and out.emailed is False and "wasn't sent: Daily limit." in out.error
    with action_world(caps=("scheduling",)) as (_s, mail, _o, _l):
        out = scheduler.run_action(action(recipients=["ops@example.com"]), "w", "run-1", "schedule")
    assert out == scheduler.Outcome("ok", rows=3) and mail.calls == []


def test_widget_check_reads_the_latest_published_version_as_the_owner():
    from services import access

    conn = FakeConn([("FROM widgets", (["is_executable", "name"], [[1, "Approve orders"]]))])
    seen = []
    with patched(database, get_db_connection=lambda *a, **k: conn), \
            patched(access, acting_as=lambda who, groups: access.Caller(who, tuple(groups), False),
                    level_for=lambda who, t, i: seen.append((who.username, who.groups, t, i)) or "USE"):
        problem, name = scheduler.widget_check(OWNER, ["analysts"], "w-1")
    assert problem is None and name == "Approve orders"
    assert seen == [(OWNER, ("analysts",), access.WIDGET, "w-1")]
    assert "is_deprecated = 0 ORDER BY version DESC LIMIT 1" in conn.sql()[0]

    conn = FakeConn([("FROM widgets", (["is_executable", "name"], [[0, "Approve orders"]]))])
    with patched(database, get_db_connection=lambda *a, **k: conn), \
            patched(access, acting_as=lambda who, groups: access.Caller(who, tuple(groups), True)):
        problem, _name = scheduler.widget_check(OWNER, [], "w-1")
    assert problem == (400, scheduler.NOT_EXECUTABLE)

    conn = FakeConn([("FROM widgets", (["is_executable", "name"], []))])
    with patched(database, get_db_connection=lambda *a, **k: conn), \
            patched(access, acting_as=lambda who, groups: access.Caller(who, tuple(groups), True)):
        assert scheduler.widget_check(OWNER, [], "w-gone")[0] == (404, scheduler.NOT_FOUND)


def test_a_widget_lent_by_a_view_is_usable_and_one_nobody_lent_is_not():
    from routes import custom_widgets
    from services import access

    def world(lent):
        conn = FakeConn([("FROM widgets", (["is_executable", "name"], [[1, "Approve orders"]]))])
        return patched(database, get_db_connection=lambda *a, **k: conn), \
            patched(access, acting_as=lambda who, groups: access.Caller(who, (), False), level_for=lambda *a: None), \
            patched(custom_widgets, lent_by_views=lambda c, who: lent)

    a, b, c = world(({"w-1"}, set()))
    with a, b, c:
        assert scheduler.widget_check(OWNER, [], "w-1")[0] is None
    a, b, c = world((set(), {"w-1@3"}))
    with a, b, c:
        assert scheduler.widget_check(OWNER, [], "w-1")[0] is None
    a, b, c = world(({"w-2"}, {"w-10@1"}))
    with a, b, c:
        assert scheduler.widget_check(OWNER, [], "w-1")[0] == (404, scheduler.NOT_FOUND)


# --- after a run ----------------------------------------------------------------------

def ok():
    return scheduler.Outcome("ok", rows=1, emailed=True)


def failed(counts=True):
    return scheduler.Outcome("failed", error="boom", counts=counts)


def test_a_success_or_skip_resets_the_failure_count():
    for outcome in (ok(), scheduler.Outcome("skipped", rows=0)):
        assert scheduler.next_state("active", None, 2, outcome, 3) == scheduler.Transition("active", None, 0, None)


def test_enough_failures_in_a_row_pause_the_schedule():
    assert scheduler.next_state("active", None, 0, failed(), 3) == scheduler.Transition("active", None, 1, None)
    assert scheduler.next_state("active", None, 1, failed(), 3) == scheduler.Transition("active", None, 2, None)
    assert scheduler.next_state("active", None, 2, failed(), 3) == \
        scheduler.Transition("paused", "failures", 3, "auto_pause")
    assert scheduler.next_state("active", None, 0, failed(), 1).event == "auto_pause"


def test_failures_that_arent_the_schedules_dont_count():
    assert scheduler.next_state("active", None, 2, failed(counts=False), 3) == \
        scheduler.Transition("active", None, 2, None)


def test_needing_a_reconnect_parks_the_schedule_without_counting():
    out = scheduler.Outcome("needs_reconnect", error="Connect again.", counts=False)
    assert scheduler.next_state("active", None, 2, out, 3) == \
        scheduler.Transition("needs_reconnect", None, 2, "needs_reconnect")


def test_a_schedule_paused_while_it_ran_stays_paused():
    assert scheduler.next_state("paused", "owner", 2, failed(), 3) == \
        scheduler.Transition("paused", "owner", 3, None)
    assert scheduler.next_state("paused", "owner", 2, ok(), 3) == scheduler.Transition("paused", "owner", 0, None)


def test_recording_writes_the_run_and_releases_only_its_own_claim():
    conn = FakeConn([("SELECT status, paused_reason, failure_count FROM schedules",
                      (["status", "paused_reason", "failure_count"], [["active", None, 2]]))])
    started, finished = NOW, NOW + timedelta(seconds=3)
    with patched(database, get_db_connection=lambda *a, **k: conn):
        t = scheduler.record("s-1", "run-1", "manual", started, finished, failed(), 3)
    assert t == scheduler.Transition("paused", "failures", 3, "auto_pause")
    sqls = conn.sql()
    assert "FOR UPDATE" in sqls[0]
    assert sqls[1].startswith("INSERT INTO schedule_runs")
    assert conn.log[1][1] == ("run-1", "s-1", "manual", started, finished, "failed", None, False, "boom")
    assert "CASE WHEN claimed_by = %s THEN NULL" in sqls[2]
    assert conn.log[2][1] == ("paused", "failures", 3, "paused", scheduler.WORKER, scheduler.WORKER, "s-1")
    assert sqls[3:] == ["COMMIT", "CLOSE"]


def test_a_schedule_deleted_mid_run_records_nothing():
    conn = FakeConn([("SELECT status, paused_reason, failure_count FROM schedules",
                      (["status", "paused_reason", "failure_count"], []))])
    with patched(database, get_db_connection=lambda *a, **k: conn):
        assert scheduler.record("s-1", "run-1", "schedule", NOW, NOW, ok(), 3) is None
    assert not any(s.startswith("INSERT") for s in conn.sql())


def test_an_auto_pause_is_recorded_and_the_owner_told():
    events, mail = Recorder(), Mail()
    t = scheduler.Transition("paused", "failures", 3, "auto_pause")
    with patched(activity, record=events), patched(email_service, send_email=mail), \
            patched(capabilities, available=available("email")):
        scheduler.after(schedule(), "run-9", t, failed())
    (who, verb, object_type, object_id, detail), = events.events
    assert (who, verb, object_type, object_id) == (OWNER, "schedule.auto_pause", "schedule", "s-1")
    assert detail == {"kind": "email_report", "failure_count": 3, "run_id": "run-9"}
    (args, kwargs), = mail.calls
    assert args[2] == [OWNER] and args[3] == "Paused: Daily sales" and "3 times in a row" in args[4]
    assert kwargs["source"] == "schedule" and kwargs["request_id"] == "run-9"


def test_an_auto_pause_without_email_is_still_recorded():
    events, mail = Recorder(), Mail()
    with patched(activity, record=events), patched(email_service, send_email=mail), \
            patched(capabilities, available=available()):
        scheduler.after(schedule(), "run-9", scheduler.Transition("paused", "failures", 3, "auto_pause"), failed())
    assert [e[1] for e in events.events] == ["schedule.auto_pause"] and mail.calls == []


def test_a_needs_reconnect_is_recorded():
    events = Recorder()
    with patched(activity, record=events):
        scheduler.after(schedule(), "run-9", scheduler.Transition("needs_reconnect", None, 0, "needs_reconnect"),
                        scheduler.Outcome("needs_reconnect", counts=False))
    assert [(e[1], e[3]) for e in events.events] == [("schedule.needs_reconnect", "s-1")]


def test_a_run_from_start_to_finish_shares_one_run_id():
    seen = {}

    def perform(row, run_id, trigger, problem=None):
        seen["perform"] = run_id
        return failed()

    def record(schedule_id, run_id, trigger, started, finished, outcome, max_failures):
        seen["record"] = (run_id, trigger, max_failures)
        return scheduler.Transition("paused", "failures", 3, "auto_pause")

    def after(row, run_id, t, outcome):
        seen["after"] = run_id

    with patched(scheduler, perform=perform, record=record, after=after, _max_failures=lambda: 3):
        scheduler.execute(schedule(), scheduler.Claim("manual", NOW, None))
    assert seen["perform"] == seen["record"][0] == seen["after"]
    assert seen["record"][1:] == ("manual", 3)


def test_a_run_that_raises_is_a_failed_run_not_a_crash():
    def explode(*_a, **_k):
        raise KeyError("columns")

    with env(**DEPLOYED), patched(token_vault, access_token_for=lambda who: TOKEN), \
            patched(scheduler, client_for=lambda who: "w", run_report=explode):
        out = scheduler.perform(schedule(), "run-1", "schedule")
    assert out.status == "failed" and out.counts is True and "KeyError" in out.error


def test_the_failure_limit_is_a_setting():
    from services import settings_store

    spec = settings_store.SETTING_SPECS["schedule_max_failures"]
    assert (spec.default, spec.minimum, spec.maximum, spec.group) == ("3", 1, 20, "scheduling")
    spec = settings_store.SETTING_SPECS["schedule_max_per_person"]
    assert (spec.default, spec.minimum, spec.maximum, spec.group) == ("25", 1, 500, "scheduling")
    assert settings_store.validate_value("schedule_max_failures", "21")[1]
    assert settings_store.validate_value("schedule_max_failures", "5") == ("5", None)


# --- reconnecting ----------------------------------------------------------------------

def test_a_reconnected_owners_schedules_resume_from_now():
    applied = []
    connected = {"connected": True, "expires_at": NOW + timedelta(days=20)}
    with env(**DEPLOYED), patched(token_vault, status=lambda who: connected), patched(scheduler, _now=lambda: NOW), \
            patched(schedule_store, recurrences=lambda owner, status: [("s-1", HOURLY)],
                    set_status_where=lambda owner, status, updates: applied.append((owner, status, list(updates)))
                    or ["s-1"]):
        assert scheduler.resume_owner(OWNER) == 1
    (owner, from_status, updates), = applied
    assert (owner, from_status) == (OWNER, "needs_reconnect")
    assert updates == [("s-1", {"status": "active", "next_run_at": NOW + timedelta(hours=1), "failure_count": 0})]


def test_an_owner_still_disconnected_or_expired_stays_waiting():
    def never(*_a):
        raise AssertionError("changed")

    for status in ({"connected": False}, {"connected": True, "expires_at": NOW - timedelta(minutes=1)}):
        with env(**DEPLOYED), patched(token_vault, status=lambda who: status), \
                patched(scheduler, _now=lambda: NOW), patched(schedule_store, set_status_where=never):
            assert scheduler.resume_owner(OWNER) == 0


def test_an_unreadable_connection_is_tried_again_later():
    def down(_who):
        raise RuntimeError("db down")

    with env(**DEPLOYED), patched(token_vault, status=down):
        assert scheduler.resume_owner(OWNER) == 0


# --- reminders ---------------------------------------------------------------------------

def test_which_reminder_is_due():
    assert scheduler.reminder_kind(NOW + timedelta(days=8), NOW) is None
    assert scheduler.reminder_kind(NOW + timedelta(days=7), NOW) == "7d"
    assert scheduler.reminder_kind(NOW + timedelta(days=2), NOW) == "7d"
    assert scheduler.reminder_kind(NOW + timedelta(hours=23), NOW) == "1d"
    assert scheduler.reminder_kind(NOW - timedelta(minutes=1), NOW) is None


@contextmanager
def reminder_world(soon, owners, caps=("scheduling", "email")):
    sent_rows, mail, events, lapsed = set(), Mail(), Recorder(), []

    def claim_reminder(user, expires, kind):
        key = (user, expires, kind)
        fresh = key not in sent_rows
        sent_rows.add(key)
        return fresh

    def lapse(user):
        lapsed.append(user)
        return ["s-1", "s-2"]

    with env(**DEPLOYED), patched(token_vault, expiring=lambda days: list(soon)), \
            patched(schedule_store, active_owners=lambda users: {u: owners[u] for u in users if u in owners}), \
            patched(scheduler, _claim_reminder=claim_reminder, lapse=lapse, _now=lambda: NOW, _prune=lambda: None,
                    _app_origin=lambda: "https://cc.example.com"), \
            patched(email_service, send_email=mail), patched(capabilities, available=available(*caps)):
        yield mail, lapsed


def test_reminders_go_once_at_seven_days_and_once_at_one():
    week = NOW + timedelta(days=6)
    with reminder_world([(OWNER, week)], {OWNER: (OWNER, 2)}) as (mail, _lapsed):
        assert scheduler.send_reminders() == {"sent": 1, "lapsed": 0}
        assert scheduler.send_reminders() == {"sent": 0, "lapsed": 0}
    (args, kwargs), = mail.calls
    assert args[2] == [OWNER] and "in a week" in args[4] and "2 schedules run as you" in args[4]
    assert "https://cc.example.com" in args[4] and kwargs["source"] == "reminder"
    day = NOW + timedelta(hours=20)
    with reminder_world([(OWNER, day)], {OWNER: (OWNER, 1)}) as (mail, _lapsed):
        scheduler.send_reminders()
        scheduler.send_reminders()
    assert len(mail.calls) == 1 and "tomorrow" in mail.calls[0][0][4] and "1 schedule runs as you" in \
        mail.calls[0][0][4]


def test_only_owners_with_active_schedules_are_reminded():
    with reminder_world([("bob@example.com", NOW + timedelta(days=3))], {}) as (mail, lapsed):
        assert scheduler.send_reminders() == {"sent": 0, "lapsed": 0}
    assert mail.calls == [] and lapsed == []


def test_reminders_wait_while_email_is_off_but_lapses_still_happen():
    soon = [(OWNER, NOW + timedelta(days=3)), ("bob@example.com", NOW - timedelta(hours=1))]
    owners = {OWNER: (OWNER, 1), "bob@example.com": ("bob@example.com", 2)}
    with reminder_world(soon, owners, caps=("scheduling",)) as (mail, lapsed):
        assert scheduler.send_reminders() == {"sent": 0, "lapsed": 2}
    assert mail.calls == [] and lapsed == ["bob@example.com"]


def test_a_lapse_parks_active_schedules_and_records_each():
    events, applied = Recorder(), []
    with patched(activity, record=events), \
            patched(schedule_store, recurrences=lambda owner, status: [("s-1", HOURLY), ("s-2", HOURLY)],
                    set_status_where=lambda owner, status, updates: applied.append((status, list(updates)))
                    or ["s-1", "s-2"]):
        assert scheduler.lapse(OWNER) == ["s-1", "s-2"]
    assert applied == [("active", [("s-1", {"status": "needs_reconnect"}), ("s-2", {"status": "needs_reconnect"})])]
    assert [(e[1], e[3], e[4]) for e in events.events] == [
        ("schedule.needs_reconnect", "s-1", {"reason": "expired"}),
        ("schedule.needs_reconnect", "s-2", {"reason": "expired"})]


def test_a_dev_run_sends_no_reminders():
    def never(_days):
        raise AssertionError("asked the vault")

    with env(DEV_MODE="true", APP_ENVIRONMENT="local"), patched(token_vault, expiring=never), \
            patched(scheduler, _prune=lambda: None):
        assert scheduler.send_reminders() == {"sent": 0, "lapsed": 0}


# --- logs --------------------------------------------------------------------------------

class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def test_nothing_logged_carries_a_token_a_row_or_a_recipient():
    capture = Capture()
    root = logging.getLogger()
    root.addHandler(capture)
    old_level = root.level
    root.setLevel(logging.DEBUG)
    secret_rows = statement_returning(["ssn"], [["123-45-6789"]])
    try:
        with env(**DEPLOYED), patched(token_vault, access_token_for=lambda who: TOKEN), \
                patched(scheduler, client_for=lambda who: "w", _max_failures=lambda: 3,
                        record=lambda *a: scheduler.Transition("active", None, 0, None)), \
                report_world(statement=secret_rows):
            scheduler.execute(schedule(recipients=["secret.person@example.com"]), scheduler.Claim("schedule", NOW, None))
    finally:
        root.removeHandler(capture)
        root.setLevel(old_level)
    text = "\n".join(capture.lines)
    assert "s-1" in text
    for secret in (TOKEN, "123-45-6789", "secret.person@example.com", "SELECT region"):
        assert secret not in text, secret


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
