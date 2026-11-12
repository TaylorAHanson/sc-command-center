"""Running schedules: the background tick, each run, and what follows from it.

Three jobs on the background runner (registered in `main.py`):

  * `scheduler`, every 30 s: claim what's due and run it.
  * `schedule_reconnect`, every minute: schedules waiting on an owner who has since
    connected go back to active.
  * `schedule_reminders`, hourly: owners whose connection is about to end are told,
    once at 7 days and once at 1 day; a connection that has ended moves their
    schedules to `needs_reconnect`. Old runs are pruned here too.

**Who a run is.** A run is its owner: a token from the vault
(`token_vault.access_token_for`), in a client that sends it as a bearer token,
so Unity Catalog decides what the run may read exactly as it would for them. The
only exception is a developer's machine: with `DEV_MODE=true` *and*
`APP_ENVIRONMENT=local`, runs use the service principal the local server already
signs in as, because there is no OAuth integration to connect through. Either
setting alone is not enough, so a deployed app with DEV_MODE left on still runs
every schedule as its owner, or not at all.

**Claiming.** The background runner already runs the tick on one worker at a
time; the claim is what keeps two runs of one schedule apart regardless. One
transaction picks due rows with `FOR UPDATE SKIP LOCKED`, gives each a lease
(`claimed_by`, `claimed_until`), moves `next_run_at` to the next time after now,
and commits before anything runs. So a run that's late (the app was down) runs
once, marked `recovery`, rather than once per missed time, and a worker that dies
mid-run leaves a lease that simply expires: that run is lost, never repeated.
Delivery is at most once, which for email and for statements that change data is
the right side to err on.

**Outcomes.** A run that needs the owner to reconnect isn't a failure: the
schedule waits as `needs_reconnect` until they do. A vault or warehouse
configuration problem fails the run without counting against the schedule.
Anything else counts, and `schedule_max_failures` in a row pauses it and emails
the owner. A success, or a run skipped by `send_when`, resets the count.

Nothing here logs a token, a query's rows, or a recipient's address; logs carry
schedule and run ids and counts.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from services import recurrence, schedule_store, token_vault

logger = logging.getLogger(__name__)

TICK_SECONDS = 30
RECONNECT_SECONDS = 60
REMINDER_SECONDS = 3600

#: Runs at once on one worker. Each holds a thread and, for most of its life, a
#: warehouse statement; the warehouse is the shared resource worth sparing.
MAX_PARALLEL = 4
#: How long one tick keeps claiming as runs finish, when more is due than fits.
#: Under the tick's own interval, so the runner's other jobs aren't held up long.
TICK_BUDGET_SECONDS = 20.0
#: Far longer than a run can take (a statement waits 50 s, an email a few), so a
#: lease only expires on a worker that died.
LEASE = timedelta(minutes=15)
#: A due run claimed later than this was missed (the app was down or busy).
LATE_AFTER = timedelta(minutes=5)
#: When a stored recurrence can't be read, look again in an hour rather than every tick.
UNREADABLE_RETRY = timedelta(hours=1)
#: Rows a report reads, which is also as many as its CSV can carry.
REPORT_MAX_ROWS = 10_000
ACTION_MAX_ROWS = 500
REMINDERS = (("1d", timedelta(days=1)), ("7d", timedelta(days=7)))
RUNS_KEPT_DAYS = 180
MAX_ERROR_CHARS = 1000

UNREADABLE = "This schedule's timing can't be read. Edit it to say how often it runs."
NOT_FOUND = "That widget wasn't found."
NOT_EXECUTABLE = ("That widget isn't marked executable, so its statement can't run on a schedule. "
                  "Its author can mark it executable in Widget Studio.")
UNRECORDED = "The run couldn't be written to the action log, so its statement didn't run."
DEV_STEP = ("This is a local run with DEV_MODE on, so scheduled work runs as the app's service principal "
            "instead of each owner. A deployed app always runs it as the owner, through their connection.")

#: This process's name on the claims it takes.
WORKER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _short(text: Any) -> str:
    out = str(text or "").strip()
    return out if len(out) <= MAX_ERROR_CHARS else out[:MAX_ERROR_CHARS - 1] + "…"


def _conn():
    from database import get_db_connection

    return get_db_connection()


# --------------------------------------------------------------------- who a run is

def dev_fallback() -> bool:
    """Whether runs use the service principal: a developer's machine, and only there."""
    from config.settings import get_app_environment

    return os.environ.get("DEV_MODE", "").strip().lower() == "true" and get_app_environment() == "local"


def client_for(owner: str):
    """A WorkspaceClient that is `owner`, for one run.

    Raises `token_vault.NeedsReconnect` when only the owner can fix it and
    `token_vault.VaultError` when the vault can't answer.
    """
    if dev_fallback():
        from middleware.auth import get_db_client

        return get_db_client(None)
    token = token_vault.access_token_for(owner)
    from databricks.sdk import WorkspaceClient

    # auth_type="pat" sends the token as a bearer token and stops the SDK from
    # also finding the app's own credentials in the environment.
    return WorkspaceClient(host=token_vault.workspace_url(), token=token, auth_type="pat")


def connection_usable(status: Dict[str, Any], now: datetime) -> bool:
    if not status.get("connected"):
        return False
    expires = _aware(status.get("expires_at"))
    return expires is None or expires > now


def connection(owner: str) -> Tuple[Dict[str, Any], bool]:
    """(`/api/oauth/status` body as stored, whether runs can use it). Raises when the vault can't be read,
    except on a developer's machine, where runs don't need a connection."""
    if dev_fallback():
        try:
            status = token_vault.status(owner)
        except Exception:  # noqa: BLE001 - locally the vault may not be set up at all
            status = {"connected": False, "connected_at": None, "expires_at": None,
                      "needs_reconnect": False, "reason": "not_connected"}
        return status, True
    status = token_vault.status(owner)
    return status, connection_usable(status, _now())


def capability() -> Dict[str, Any]:
    """The `scheduling` check: the vault's, with mode `oauth`, or `dev` on a developer's machine."""
    from services import capabilities

    if dev_fallback():
        try:
            missing = list(token_vault.capability().get("missing") or [])
        except Exception:  # noqa: BLE001
            missing = []
        return capabilities.result(True, mode="dev", missing=missing, next_step=DEV_STEP)
    res = token_vault.capability()
    if res.get("available"):
        return capabilities.result(True, mode="oauth", missing=res.get("missing") or (),
                                   next_step=res.get("next_step") or "")
    return res


# --------------------------------------------------------------------- claiming

class Claim(NamedTuple):
    trigger: str
    next_run_at: Optional[datetime]
    #: A sentence when the run can't happen (the recurrence is unreadable).
    problem: Optional[str]


def plan_claim(next_run_at: Optional[datetime], run_requested: bool, rec: Any, now: datetime) -> Claim:
    """What claiming a schedule at `now` means: why it runs and when it runs next.

    A due schedule's next time is counted from now, not from the time it missed,
    so however long the app was down it runs once. A run someone asked for that
    isn't due anyway leaves the timetable alone.
    """
    due = next_run_at is not None and next_run_at <= now
    if not due:
        return Claim("manual", next_run_at, None)
    try:
        upcoming, problem = recurrence.next_run(rec, now), None
    except ValueError:
        upcoming, problem = now + UNREADABLE_RETRY, UNREADABLE
    if run_requested:
        trigger = "manual"
    elif now - next_run_at > LATE_AFTER:
        trigger = "recovery"
    else:
        trigger = "schedule"
    return Claim(trigger, upcoming, problem)


CLAIM_SQL = f"""
    SELECT {schedule_store.COLUMNS_SQL}, now() AS db_now
    FROM schedules s
    WHERE s.status = 'active'
      AND (s.next_run_at <= now() OR s.run_requested)
      AND (s.claimed_until IS NULL OR s.claimed_until < now())
    ORDER BY s.next_run_at NULLS LAST
    LIMIT %s
    FOR UPDATE SKIP LOCKED
"""
CLAIM_UPDATE_SQL = ("UPDATE schedules SET claimed_by = %s, claimed_until = %s, next_run_at = %s, "
                    "run_requested = FALSE WHERE id = %s")


def claim(limit: int) -> List[Tuple[Dict[str, Any], Claim]]:
    """Take up to `limit` due schedules for this worker, committed before any of them runs."""
    if limit <= 0:
        return []
    out: List[Tuple[Dict[str, Any], Claim]] = []
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(CLAIM_SQL, (limit,))
        for row in schedule_store.dict_rows(c):
            now = _aware(row.pop("db_now")) or _now()
            plan = plan_claim(_aware(row.get("next_run_at")), bool(row.get("run_requested")),
                              schedule_store.from_json(row.get("recurrence")), now)
            c.execute(CLAIM_UPDATE_SQL, (WORKER, now + LEASE, plan.next_run_at, row["id"]))
            out.append((row, plan))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return out


def release(schedule_id: str) -> None:
    """Give back a claim that won't run, so the lease doesn't hold the schedule for nothing."""
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("UPDATE schedules SET claimed_by = NULL, claimed_until = NULL WHERE id = %s AND claimed_by = %s",
                  (schedule_id, WORKER))
        conn.commit()
    except Exception as e:  # noqa: BLE001 - the lease expires by itself
        conn.rollback()
        logger.warning("Couldn't release schedule %s: %s", schedule_id, type(e).__name__)
    finally:
        conn.close()


# --------------------------------------------------------------------- one run

class Outcome(NamedTuple):
    status: str
    rows: Optional[int] = None
    emailed: bool = False
    error: Optional[str] = None
    #: Whether a failure counts toward pausing the schedule.
    counts: bool = True


class RunError(Exception):
    def __init__(self, message: str, counts: bool = True):
        super().__init__(message)
        self.message = message
        self.counts = counts


def run_statement(sql: str, w: Any, cap: int, retryable: bool) -> Tuple[List[str], List[list], int]:
    """(columns, up to `cap` rows, row count) through the same path `/api/sql/execute-*` use."""
    import httpx
    from databricks.sdk.errors import DatabricksError
    from fastapi import HTTPException
    from routes import sql_query

    try:
        result = sql_query.execute_rows(sql, w, cap, all_rows=False, retryable=retryable)
        rows = list(itertools.islice(result.rows, cap))
    except sql_query.SqlStatementError as e:
        raise RunError(_short(e.detail)) from None
    except DatabricksError as e:
        raise RunError(_short(sql_query._refusal(e, sql).detail)) from None
    except HTTPException as e:
        # No warehouse configured: the app's to fix, not the schedule's.
        raise RunError(_short(e.detail), counts=False) from None
    except httpx.HTTPError as e:
        raise RunError(f"The result couldn't be downloaded ({type(e).__name__}).") from None
    total = result.total if result.total is not None else len(rows)
    return result.columns, rows, int(total)


def _email_available() -> bool:
    from services import capabilities

    return capabilities.available("email")


def run_report(row: Dict[str, Any], w: Any, run_id: str) -> Outcome:
    from services import email_service

    problem = schedule_store.read_only_problem(row.get("sql") or "")
    if problem:
        return Outcome("failed", error=problem)
    if not _email_available():
        return Outcome("failed", error=email_service.UNAVAILABLE, counts=False)
    try:
        columns, rows, total = run_statement(row["sql"], w, REPORT_MAX_ROWS, retryable=True)
    except RunError as e:
        return Outcome("failed", error=e.message, counts=e.counts)

    send_when = row.get("send_when") or "always"
    if (send_when == "has_rows" and total == 0) or (send_when == "no_rows" and total > 0):
        return Outcome("skipped", rows=total)
    result = email_service.send_email(
        row["owner"], row.get("owner_email") or row["owner"], list(row.get("recipients") or []),
        row.get("subject") or row.get("name"), row.get("message") or "",
        table={"columns": columns, "rows": rows} if columns else None,
        attach_csv=bool(row.get("attach_csv")), view_name=row.get("view_name"), view_link=row.get("view_link"),
        source="schedule", request_id=run_id,
    )
    if result.get("ok"):
        return Outcome("ok", rows=total, emailed=True)
    return Outcome("failed", rows=total, error=_short(result.get("error") or email_service.UNAVAILABLE),
                   counts=result.get("status") != "unavailable")


def widget_check(owner: str, groups: Sequence[str], widget_id: str) -> Tuple[Optional[Tuple[int, str]], str]:
    """((status, sentence) or None, the widget's name) for scheduling `widget_id`'s statement as `owner`.

    The owner must be able to use the widget (directly, as an admin, or through a
    view that carries it) and its published version must be executable. Checked
    when the schedule is made and again before every run, since either can change.
    No access reads as not found, as it does everywhere else.
    """
    from services import access

    who = access.acting_as(owner, groups)
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT is_executable, name FROM widgets WHERE id = %s AND is_deprecated = 0 "
                  "ORDER BY version DESC LIMIT 1", (widget_id,))
        found = c.fetchone()
        usable = False
        if found is not None:
            usable = bool(access.level_for(who, access.WIDGET, widget_id))
            if not usable:
                from routes.custom_widgets import lent_by_views

                latest, pins = lent_by_views(c, who)
                usable = widget_id in latest or any(p.rpartition("@")[0] == widget_id for p in pins)
        conn.commit()
    finally:
        conn.close()
    if found is None or not usable:
        return (404, NOT_FOUND), ""
    if int(found[0] or 0) != 1:
        return (400, NOT_EXECUTABLE), found[1] or ""
    return None, found[1] or ""


def _affected(columns: List[str], rows: List[list], total: int) -> int:
    # DML answers with one row of counts rather than the rows it touched.
    if columns and columns[0] == "num_affected_rows" and rows and rows[0]:
        try:
            return int(rows[0][0])
        except (TypeError, ValueError):
            pass
    return total


def _note(row: Dict[str, Any], run_id: str, outcome: Outcome, at: datetime) -> Outcome:
    """Tell an action's recipients how it went, when it has any and email works."""
    from services import email_service

    recipients = list(row.get("recipients") or [])
    if not recipients or not _email_available():
        return outcome
    name = row.get("name") or "A scheduled action"
    when = at.strftime("%Y-%m-%d %H:%M UTC")
    if outcome.status == "ok":
        changed = f" and changed {outcome.rows:,} row{'' if outcome.rows == 1 else 's'}" if outcome.rows else ""
        subject, message = f"{name}: done", f"The scheduled action **{name}** ran at {when}{changed}."
    else:
        subject, message = f"{name}: failed", f"The scheduled action **{name}** failed at {when}.\n\n{outcome.error}"
    result = email_service.send_email(
        row["owner"], row.get("owner_email") or row["owner"], recipients, subject, message,
        view_name=row.get("view_name"), view_link=row.get("view_link"), source="schedule", request_id=run_id,
    )
    if result.get("ok"):
        return outcome._replace(emailed=True)
    if outcome.status == "ok":
        return outcome._replace(error=_short(f"It ran, but the note to its recipients wasn't sent: "
                                             f"{result.get('error') or email_service.UNAVAILABLE}"))
    return outcome


def run_action(row: Dict[str, Any], w: Any, run_id: str, trigger: str) -> Outcome:
    import database
    from routes import sql_query

    widget_id = row.get("source_widget_id") or ""
    problem, widget_name = widget_check(row["owner"], row.get("owner_groups") or (), widget_id)
    if problem:
        return Outcome("failed", error=problem[1])
    context = json.dumps({"schedule_id": row["id"], "trigger": trigger, "view_name": row.get("view_name"),
                          "source_app_id": row.get("source_app_id"),
                          "source_widget_instance": row.get("source_widget_instance")})
    try:
        database.log_user_action(widget_id, widget_name or row.get("name") or "", f"Scheduled: {row.get('name')}",
                                 context, action_name="schedule", username=row["owner"], request_id=run_id)
    except Exception as e:  # noqa: BLE001 - no record, no run
        logger.warning("Schedule %s run %s: action log write failed: %s", row["id"], run_id, type(e).__name__)
        return Outcome("failed", error=UNRECORDED, counts=False)
    try:
        columns, rows, total = run_statement(sql_query.tag_statement(row["sql"], run_id), w, ACTION_MAX_ROWS,
                                             retryable=False)
        outcome = Outcome("ok", rows=_affected(columns, rows, total))
    except RunError as e:
        outcome = Outcome("failed", error=e.message, counts=e.counts)
    return _note(row, run_id, outcome, _now())


def perform(row: Dict[str, Any], run_id: str, trigger: str, problem: Optional[str] = None) -> Outcome:
    """Run one claimed schedule as its owner. Never raises."""
    if problem:
        return Outcome("failed", error=problem)
    try:
        w = client_for(row["owner"])
    except token_vault.NeedsReconnect as e:
        return Outcome("needs_reconnect", error=str(e), counts=False)
    except token_vault.VaultError as e:
        return Outcome("failed", error=_short(e), counts=False)
    except Exception as e:  # noqa: BLE001
        return Outcome("failed", error=f"The app couldn't sign in as the schedule's owner ({type(e).__name__}).",
                       counts=False)
    try:
        if row.get("kind") == "email_report":
            return run_report(row, w, run_id)
        if row.get("kind") == "run_statement":
            return run_action(row, w, run_id, trigger)
        return Outcome("failed", error="This schedule's kind isn't one the app runs.")
    except Exception as e:  # noqa: BLE001 - one run's failure is that run's
        # Where, not what: an exception's message can quote the rows it choked on.
        tb = e.__traceback__
        while tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
        where = f"{os.path.basename(tb.tb_frame.f_code.co_filename)}:{tb.tb_lineno}" if tb else "?"
        logger.warning("Schedule %s run %s stopped: %s at %s", row.get("id"), run_id, type(e).__name__, where)
        return Outcome("failed", error=f"The run stopped unexpectedly ({type(e).__name__}).")


# --------------------------------------------------------------------- after a run

class Transition(NamedTuple):
    status: str
    paused_reason: Optional[str]
    failure_count: int
    #: "auto_pause", "needs_reconnect", or None when the status stays.
    event: Optional[str]


def next_state(status: str, paused_reason: Optional[str], failure_count: int, outcome: Outcome,
               max_failures: int) -> Transition:
    """The schedule after a run. Only an active schedule changes status: one paused or
    deleted while it ran keeps what its owner chose."""
    count = failure_count
    if outcome.status in ("ok", "skipped"):
        count = 0
    elif outcome.status == "failed" and outcome.counts:
        count += 1
    if status != "active":
        return Transition(status, paused_reason, count, None)
    if outcome.status == "needs_reconnect":
        return Transition("needs_reconnect", paused_reason, count, "needs_reconnect")
    if outcome.status == "failed" and outcome.counts and count >= max(1, max_failures):
        return Transition("paused", "failures", count, "auto_pause")
    return Transition(status, paused_reason, count, None)


INSERT_RUN_SQL = ("INSERT INTO schedule_runs (id, schedule_id, trigger, started_at, finished_at, status, "
                  "row_count, emailed, error) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)")
FINISH_SQL = """
    UPDATE schedules
       SET status = %s, paused_reason = %s, failure_count = %s,
           updated_at = CASE WHEN status <> %s THEN now() ELSE updated_at END,
           claimed_by = CASE WHEN claimed_by = %s THEN NULL ELSE claimed_by END,
           claimed_until = CASE WHEN claimed_by = %s THEN NULL ELSE claimed_until END
     WHERE id = %s
"""


def record(schedule_id: str, run_id: str, trigger: str, started: datetime, finished: datetime,
           outcome: Outcome, max_failures: int) -> Optional[Transition]:
    """Write the run and its effect on the schedule, and release the claim. None if
    the schedule was deleted while it ran, in which case there is nothing to record against."""
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT status, paused_reason, failure_count FROM schedules WHERE id = %s FOR UPDATE",
                  (schedule_id,))
        current = c.fetchone()
        if current is None:
            conn.commit()
            return None
        t = next_state(current[0], current[1], int(current[2] or 0), outcome, max_failures)
        c.execute(INSERT_RUN_SQL, (run_id, schedule_id, trigger, started, finished, outcome.status,
                                   outcome.rows, bool(outcome.emailed), outcome.error))
        c.execute(FINISH_SQL, (t.status, t.paused_reason, t.failure_count, t.status, WORKER, WORKER, schedule_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return t


def _app_origin() -> str:
    url = token_vault.callback_url()
    return url[:-len(token_vault.CALLBACK_PATH)] if url.endswith(token_vault.CALLBACK_PATH) else ""


def _tell_owner_paused(row: Dict[str, Any], run_id: str, t: Transition, outcome: Outcome) -> None:
    from services import email_service

    owner_email = row.get("owner_email") or row["owner"]
    name = row.get("name") or "A schedule"
    message = (f"Your schedule **{name}** failed {t.failure_count} times in a row, so it has been paused "
               "and won't run again until you resume it.\n\n"
               f"The last run said: {outcome.error or 'no error was recorded.'}")
    result = email_service.send_email(row["owner"], owner_email, [owner_email], f"Paused: {name}", message,
                                      source="schedule", request_id=run_id)
    if not result.get("ok"):
        logger.info("Schedule %s paused; its owner wasn't emailed (%s)", row["id"], result.get("status"))


def after(row: Dict[str, Any], run_id: str, t: Transition, outcome: Outcome) -> None:
    """Activity and the owner's email for a run that changed the schedule's status."""
    from services import activity

    if t.event == "auto_pause":
        activity.record(row["owner"], "schedule.auto_pause", "schedule", row["id"],
                        {"kind": row.get("kind"), "failure_count": t.failure_count, "run_id": run_id})
        if _email_available():
            _tell_owner_paused(row, run_id, t, outcome)
    elif t.event == "needs_reconnect":
        activity.record(row["owner"], "schedule.needs_reconnect", "schedule", row["id"],
                        {"kind": row.get("kind"), "run_id": run_id})


def _max_failures() -> int:
    from services.settings_store import get_int_setting

    return get_int_setting("schedule_max_failures")


def execute(row: Dict[str, Any], plan: Claim) -> Optional[Outcome]:
    """One claimed schedule from start to finish: run, record, follow up. Never raises."""
    run_id = schedule_store.new_id()
    started = _now()
    outcome = perform(row, run_id, plan.trigger, plan.problem)
    finished = _now()
    try:
        t = record(row["id"], run_id, plan.trigger, started, finished, outcome, _max_failures())
    except Exception as e:  # noqa: BLE001 - the lease expires and the next time runs as usual
        logger.warning("Schedule %s run %s: couldn't record the outcome: %s", row["id"], run_id, type(e).__name__)
        return outcome
    logger.info("Schedule %s run %s (%s): %s, rows=%s, emailed=%s, %.1fs", row["id"], run_id, plan.trigger,
                outcome.status, outcome.rows, outcome.emailed, (finished - started).total_seconds())
    if t is None:
        logger.info("Schedule %s was deleted while run %s ran; nothing recorded", row["id"], run_id)
    elif t.event:
        try:
            after(row, run_id, t, outcome)
        except Exception as e:  # noqa: BLE001
            logger.warning("Schedule %s: follow-up after run %s failed: %s", row["id"], run_id, type(e).__name__)
    return outcome


# --------------------------------------------------------------------- the tick

_flight = threading.Condition()
_in_flight = 0


def _spawn(target: Callable[..., Any], *args: Any) -> None:
    threading.Thread(target=target, args=args, name="schedule-run", daemon=True).start()


def _run_then_free(row: Dict[str, Any], plan: Claim) -> None:
    global _in_flight
    try:
        execute(row, plan)
    finally:
        with _flight:
            _in_flight -= 1
            _flight.notify_all()


def _dispatch(row: Dict[str, Any], plan: Claim) -> None:
    global _in_flight
    with _flight:
        _in_flight += 1
    try:
        _spawn(_run_then_free, row, plan)
    except Exception as e:  # noqa: BLE001 - can't start a thread: give the claim back
        with _flight:
            _in_flight -= 1
            _flight.notify_all()
        logger.error("Couldn't start schedule %s: %s", row.get("id"), e)
        release(row["id"])


def tick() -> int:
    """Claim and start what's due, as fast as this worker's runs free up, for at most
    TICK_BUDGET_SECONDS. Runs continue on their own threads after it returns.
    The number started."""
    from services import capabilities

    if not capabilities.available("scheduling"):
        # Not set up: schedules wait, and the first tick after setup runs each once.
        return 0
    deadline = time.monotonic() + TICK_BUDGET_SECONDS
    started = 0
    while True:
        with _flight:
            while _in_flight >= MAX_PARALLEL:
                left = deadline - time.monotonic()
                if left <= 0:
                    return started
                _flight.wait(left)
            free = MAX_PARALLEL - _in_flight
        claimed = claim(free)
        for row, plan in claimed:
            _dispatch(row, plan)
        started += len(claimed)
        if len(claimed) < free or time.monotonic() >= deadline:
            if started:
                logger.info("Scheduler started %d run(s)", started)
            return started


# --------------------------------------------------------------------- reconnecting

def resume_owner(owner: str) -> int:
    """Back to active, with the next time counted from now, for `owner`'s schedules
    waiting on a reconnect, if their connection works now. How many."""
    try:
        _status, usable = connection(owner)
    except Exception as e:  # noqa: BLE001 - try again next pass
        logger.info("Couldn't read a schedule owner's connection: %s", type(e).__name__)
        return 0
    if not usable:
        return 0
    now = _now()
    updates = []
    for schedule_id, rec in schedule_store.recurrences(owner, "needs_reconnect"):
        try:
            upcoming = recurrence.next_run(rec, now)
        except ValueError:
            upcoming = now + UNREADABLE_RETRY
        updates.append((schedule_id, {"status": "active", "next_run_at": upcoming, "failure_count": 0}))
    changed = schedule_store.set_status_where(owner, "needs_reconnect", updates)
    if changed:
        logger.info("Resumed %d schedule(s) after their owner reconnected: %s", len(changed), ", ".join(changed))
    return len(changed)


def resume_reconnected() -> int:
    from services import capabilities

    if not capabilities.available("scheduling"):
        return 0
    return sum(resume_owner(owner) for owner in schedule_store.owners_needing_reconnect())


# --------------------------------------------------------------------- reminders

def reminder_kind(expires_at: datetime, now: datetime) -> Optional[str]:
    """Which reminder a connection ending at `expires_at` is due: the nearest threshold it's inside."""
    left = expires_at - now
    if left <= timedelta(0):
        return None
    for kind, within in REMINDERS:
        if left <= within:
            return kind
    return None


def _claim_reminder(username: str, expires_at: datetime, kind: str) -> bool:
    """Record that this reminder goes out; False if it already has. Recorded first, so
    a send that fails isn't retried hourly into the owner's inbox."""
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO schedule_reminders (username, expires_at, kind) VALUES (%s, %s, %s) "
                  "ON CONFLICT DO NOTHING RETURNING username", (username, expires_at, kind))
        fresh = c.fetchone() is not None
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return fresh


def _send_reminder(username: str, owner_email: str, expires_at: datetime, kind: str, count: int) -> None:
    from services import email_service

    when = "tomorrow" if kind == "1d" else "in a week"
    origin = _app_origin()
    where = f"[Open Command Center]({origin}) and connect your account again" if origin else \
        "Open Command Center and connect your account again"
    message = (f"Your connection to Command Center ends {when}, on **{expires_at.strftime('%Y-%m-%d %H:%M')} UTC**. "
               f"{count} schedule{'' if count == 1 else 's'} run{'s' if count == 1 else ''} as you, and "
               f"{'it' if count == 1 else 'they'} will stop then.\n\n{where} to keep "
               f"{'it' if count == 1 else 'them'} running.")
    address = owner_email or username
    result = email_service.send_email(username, address, [address], "Reconnect to keep your schedules running",
                                      message, source="reminder")
    if not result.get("ok"):
        logger.info("A %s connection reminder wasn't sent (%s)", kind, result.get("status"))


def lapse(username: str) -> List[str]:
    """Move `username`'s active schedules to needs_reconnect: their connection has ended."""
    from services import activity

    updates = [(sid, {"status": "needs_reconnect"}) for sid, _ in schedule_store.recurrences(username, "active")]
    changed = schedule_store.set_status_where(username, "active", updates)
    for schedule_id in changed:
        activity.record(username, "schedule.needs_reconnect", "schedule", schedule_id, {"reason": "expired"})
    return changed


def _prune() -> None:
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM schedule_runs WHERE started_at < now() - make_interval(days => %s)",
                  (RUNS_KEPT_DAYS,))
        runs = c.rowcount
        c.execute("DELETE FROM schedule_reminders WHERE expires_at < now() - interval '30 days'")
        conn.commit()
    except Exception as e:  # noqa: BLE001 - next hour
        conn.rollback()
        logger.info("Couldn't prune old schedule runs: %s", type(e).__name__)
        return
    finally:
        conn.close()
    if runs:
        logger.info("Pruned %d schedule run(s) older than %d days", runs, RUNS_KEPT_DAYS)


def send_reminders() -> Dict[str, int]:
    """The hourly pass: reminders for connections about to end, and lapses for ended ones."""
    from services import capabilities

    sent = lapsed = 0
    if not dev_fallback() and capabilities.available("scheduling"):
        now = _now()
        soon = token_vault.expiring(7)
        owners = schedule_store.active_owners([u for u, _ in soon]) if soon else {}
        email_ok = _email_available() if owners else False
        for username, expires_at in soon:
            if username not in owners:
                continue
            owner_email, count = owners[username]
            if expires_at <= now:
                lapsed += len(lapse(username))
                continue
            kind = reminder_kind(expires_at, now)
            if kind and email_ok and _claim_reminder(username, expires_at, kind):
                _send_reminder(username, owner_email, expires_at, kind, count)
                sent += 1
        if sent or lapsed:
            logger.info("Schedule reminders: %d sent, %d schedule(s) waiting on a reconnect", sent, lapsed)
    _prune()
    return {"sent": sent, "lapsed": lapsed}
