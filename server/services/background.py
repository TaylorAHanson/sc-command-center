"""Periodic work inside the app: index upkeep, usage rollups, retention, due schedules.

The App runs two uvicorn workers, and either can be restarted at any moment, so
no single process can own a timer. Every worker runs the same loop instead, and
a job runs only when two things agree:

  * its Postgres advisory lock is free, so a run that outlasts its interval is
    never overlapped by the other worker; and
  * its `background_jobs` row says it is due, claimed with one conditional
    upsert, so it runs once per interval across the deployment rather than once
    per worker.

The row is also what the Admin Panel reads to say when each job last ran and how
it ended.

Jobs are registered by hand in `main.py`'s startup, before `start()`, so the
list of everything that runs on a timer is in one place. Nothing here raises: a
failing job is logged and recorded, a database outage skips a tick, and a
startup failure would take down the whole app (see `database.init_db`).
`BACKGROUND_JOBS=0` turns the loop off, for tools and probes that import the app.
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import threading
import time
from typing import Any, Callable, Dict, List, NamedTuple

logger = logging.getLogger(__name__)

TICK_SECONDS = 5.0
# How soon to look again at a job another worker was running, or that could not
# be checked because the database was unreachable.
_RETRY_SECONDS = 30.0
_MAX_ERROR_CHARS = 1000


class Job(NamedTuple):
    name: str
    every: float
    fn: Callable[[], Any]


_jobs: Dict[str, Job] = {}
_jobs_lock = threading.Lock()
_started = False
_conn: Any = None


def register(name: str, every_seconds: float, fn: Callable[[], Any]) -> None:
    """Run `fn` about every `every_seconds`, on one worker at a time.

    Logs rather than raises on a bad registration: this is called during startup,
    where an exception stops the whole app.
    """
    if not name or not callable(fn):
        logger.error("Background job %r not registered: it needs a name and a function", name)
        return
    if every_seconds < TICK_SECONDS:
        logger.error("Background job %s not registered: it can't run more often than every %gs",
                     name, TICK_SECONDS)
        return
    with _jobs_lock:
        _jobs[name] = Job(name, float(every_seconds), fn)


def jobs() -> List[Job]:
    with _jobs_lock:
        return list(_jobs.values())


def lock_key(name: str) -> int:
    """A stable signed 64-bit advisory-lock key for a job name.

    Hashed rather than numbered so that adding a job can't shift another job's
    key, and prefixed so it can't collide with `database._advisory_lock_key`.
    """
    digest = hashlib.sha256(f"cc-background:{name}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _close_quietly(conn: Any) -> None:
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def run_job(job: Job, conn: Any) -> str:
    """One attempt at `job` over `conn`. Returns what happened, and never raises:

    `busy` (the other worker holds it), `not_due` (it ran recently enough),
    `ran`, or `failed` (the job raised; recorded on its row). A database error
    while claiming or recording propagates as `error` so the caller can drop the
    connection.
    """
    c = conn.cursor()
    key = lock_key(job.name)
    c.execute("SELECT pg_try_advisory_lock(%s)", (key,))
    row = c.fetchone()
    conn.commit()
    if not row or not row[0]:
        return "busy"
    try:
        c.execute(
            """
            INSERT INTO background_jobs (name, last_started_at, runs)
            VALUES (%s, now(), 1)
            ON CONFLICT (name) DO UPDATE
               SET last_started_at = now(), runs = background_jobs.runs + 1
             WHERE background_jobs.last_started_at IS NULL
                OR background_jobs.last_started_at <= now() - make_interval(secs => %s)
            RETURNING name
            """,
            (job.name, job.every),
        )
        claimed = c.fetchone()
        conn.commit()
        if not claimed:
            return "not_due"

        started = time.monotonic()
        status, error = "ok", None
        try:
            job.fn()
        except Exception as e:  # noqa: BLE001 - one job's failure must not stop the loop
            status, error = "failed", f"{type(e).__name__}: {e}"[:_MAX_ERROR_CHARS]
            logger.warning("Background job %s failed: %s", job.name, error, exc_info=True)
        c.execute(
            """
            UPDATE background_jobs
               SET last_finished_at = now(), last_status = %s, last_error = %s, last_duration_ms = %s
             WHERE name = %s
            """,
            (status, error, int((time.monotonic() - started) * 1000), job.name),
        )
        conn.commit()
        return "ran" if status == "ok" else "failed"
    finally:
        try:
            c.execute("SELECT pg_advisory_unlock(%s)", (key,))
            conn.commit()
        except Exception:  # noqa: BLE001 - a dropped session releases it anyway
            pass


def next_check(outcome: str, every: float, now: float) -> float:
    """When this worker should look at a job again, given the last outcome."""
    if outcome in ("busy", "error"):
        return now + min(every, _RETRY_SECONDS)
    return now + every


def _connection() -> Any:
    """The loop's own connection, reopened after any failure.

    Unpooled because the advisory lock belongs to the session: a pooled
    connection could carry it to another caller. Kept open between ticks so the
    loop doesn't pay for a handshake every few seconds.
    """
    global _conn
    if _conn is None or getattr(_conn, "closed", 0):
        from database import content_env, get_db_connection

        _conn = get_db_connection(content_env(), pooled=False)
    return _conn


def _drop_connection() -> None:
    global _conn
    if _conn is not None:
        _close_quietly(_conn)
    _conn = None


def _loop() -> None:
    now = time.monotonic()
    # Spread first checks out so both workers don't arrive at every job together.
    due_at: Dict[str, float] = {j.name: now + random.uniform(0, min(j.every, _RETRY_SECONDS)) for j in jobs()}
    while True:
        time.sleep(TICK_SECONDS)
        for job in jobs():
            now = time.monotonic()
            if due_at.get(job.name, 0.0) > now:
                continue
            try:
                outcome = run_job(job, _connection())
            except Exception as e:  # noqa: BLE001 - an outage skips a tick
                logger.info("Background job %s skipped: %s", job.name, e)
                _drop_connection()
                outcome = "error"
            due_at[job.name] = next_check(outcome, job.every, time.monotonic())


def start() -> None:
    """Start this worker's loop. Safe to call more than once; never raises."""
    global _started
    if os.environ.get("BACKGROUND_JOBS", "1").strip().lower() in ("0", "false", "no", "off"):
        logger.info("Background jobs are turned off (BACKGROUND_JOBS)")
        return
    with _jobs_lock:
        if _started:
            return
        _started = True
    try:
        threading.Thread(target=_loop, name="background-jobs", daemon=True).start()
        logger.info("Background jobs started: %s", ", ".join(j.name for j in jobs()) or "none registered")
    except Exception as e:  # noqa: BLE001
        logger.error("Could not start background jobs: %s", e)


def describe() -> List[Dict[str, Any]]:
    """Every registered job with its last run, for the Admin Panel. Never raises."""
    rows: Dict[str, Dict[str, Any]] = {}
    try:
        from database import get_db_connection

        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT name, last_started_at, last_finished_at, last_status, last_error, last_duration_ms, runs "
                "FROM background_jobs"
            )
            for name, started, finished, status, error, duration, runs in c.fetchall():
                rows[name] = {
                    "last_started_at": started.isoformat() if started else None,
                    "last_finished_at": finished.isoformat() if finished else None,
                    "last_status": status,
                    "last_error": error,
                    "last_duration_ms": duration,
                    "runs": runs,
                }
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.info("Could not read background job history: %s", e)
    return [{"name": j.name, "every_seconds": j.every, **rows.get(j.name, {})} for j in jobs()]


def _reset_for_tests() -> None:
    global _started
    with _jobs_lock:
        _jobs.clear()
        _started = False
    _drop_connection()
