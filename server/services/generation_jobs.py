"""Widget Studio's generation jobs, readable from every worker.

A generation runs as a background task in whichever uvicorn worker took the
`POST /generate`, and the studio then polls `GET /generate/{id}` every two
seconds. The app runs two workers, so roughly half of those polls — and half of
the Stop requests — reach a process that never saw the job. With the jobs in a
module-level dict that meant a 404: the poll loop shrugged it off and asked
again, which hid the problem, but a Stop that landed on the wrong worker was
dropped without a word, and a worker restart lost every job it was running.

So the worker running a job keeps it in memory, as before, and writes each
change through to `widget_generation_jobs`. Any worker can answer a poll from
that table, and Stop is a column on the row that the running worker checks.

Two rules keep this from costing the generation anything:

  * **The database is a copy, never a dependency.** A failed write is logged
    and the job carries on in memory, so a Lakebase outage costs cross-worker
    polls, not generations. After a failure, intermediate writes back off for a
    few seconds rather than each paying the timeout; the settled state is always
    attempted, because it is the one a poll on the other worker is waiting for.
  * **Cancellation lives in its own column.** Saves write `state` only, so a
    progress update from the running worker cannot overwrite a Stop that another
    worker recorded a moment earlier.

The table lives in the settings schema (`settings_store.settings_env`), because
`GET`/`DELETE` are addressed by job id alone and a job is deployment-wide state
rather than dev/test/prod data.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

TABLE = "widget_generation_jobs"

#: How long a finished job stays in this worker's memory. The studio reads the
#: result within seconds of it settling; this only has to outlast a slow poll.
LOCAL_KEEP_SECONDS = 30 * 60

#: Rows older than this are deleted as new jobs are created.
ROW_KEEP_HOURS = 24

#: After a failed write, how long to skip the intermediate ones.
BACKOFF_SECONDS = 15.0

#: How often the running worker asks the database whether Stop was pressed on
#: another worker. The studio polls every two seconds, so this is never the delay
#: anyone notices.
CANCEL_POLL_SECONDS = 1.0


class JobStore:
    """The jobs this worker is running, mirrored to a table the others can read.

    Reads and writes of a job's in-memory state keep the dict shape the route
    always had (`store[job_id]`, `store.get(job_id)`), so the generation code and
    its tests are unchanged apart from asking `is_cancelled` instead of reading a
    flag, which may have been set by the other worker.
    """

    def __init__(self, table: str = TABLE) -> None:
        self.table = table
        #: Off in the standalone tests, which have no database; on everywhere else.
        self.persist = True
        self._local: Dict[str, Dict[str, Any]] = {}
        self._touched: Dict[str, float] = {}
        self._cancel_checked: Dict[str, float] = {}
        self._backoff_until = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------ dict surface

    def __contains__(self, job_id: str) -> bool:
        return job_id in self._local

    def __getitem__(self, job_id: str) -> Dict[str, Any]:
        return self._local[job_id]

    def __setitem__(self, job_id: str, state: Dict[str, Any]) -> None:
        self.replace(job_id, state)

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._local))

    def get(self, job_id: str, default: Any = None) -> Any:
        return self._local.get(job_id, default)

    # ------------------------------------------------------------------ writes

    def create(self, job_id: str, state: Dict[str, Any]) -> None:
        """Start tracking a new job, and tidy away old rows while we're here."""
        self._evict_local()
        with self._lock:
            self._local[job_id] = state
            self._touched[job_id] = time.monotonic()
        self._save(job_id, force=True, prune=True)

    def replace(self, job_id: str, state: Dict[str, Any], *, final: bool = False) -> None:
        with self._lock:
            self._local[job_id] = state
            self._touched[job_id] = time.monotonic()
        self._save(job_id, force=final)

    def update(self, job_id: str, **fields: Any) -> None:
        """Merge `fields` into a job this worker is running. Unknown ids are ignored."""
        job = self._local.get(job_id)
        if job is None:
            return
        job.update(fields)
        self._touched[job_id] = time.monotonic()
        self._save(job_id)

    def save(self, job_id: str) -> None:
        """Write through a change made to the job's dict in place (e.g. the trace)."""
        if job_id in self._local:
            self._touched[job_id] = time.monotonic()
            self._save(job_id)

    def cancel(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Record Stop. Returns the job's current state, or None if nobody has it."""
        local = self._local.get(job_id)
        if local is not None:
            local["cancelled"] = True
        recorded = self._set_cancelled(job_id)
        if local is not None:
            return local
        if not recorded:
            return None
        return self.snapshot(job_id) or {"status": "running", "cancelled": True}

    # ------------------------------------------------------------------- reads

    def snapshot(self, job_id: str) -> Optional[Dict[str, Any]]:
        """The job as a poll should see it: this worker's copy, else the table's."""
        local = self._local.get(job_id)
        if local is not None:
            # A copy, because the response is encoded on a request thread while the
            # job's own thread is still adding keys (`stages`, `stage_code`) to it.
            return dict(local)
        return self._load(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        """Whether Stop was pressed, wherever it was received."""
        local = self._local.get(job_id)
        if local is not None and local.get("cancelled"):
            return True
        if not self.persist:
            return False
        now = time.monotonic()
        if now - self._cancel_checked.get(job_id, 0.0) < CANCEL_POLL_SECONDS:
            return False
        self._cancel_checked[job_id] = now
        if self._read_cancelled(job_id):
            if local is not None:
                local["cancelled"] = True
            return True
        return False

    # ----------------------------------------------------------------- storage

    def _conn(self):
        from database import get_db_connection
        from services.settings_store import settings_env

        return get_db_connection(settings_env())

    def _save(self, job_id: str, *, force: bool = False, prune: bool = False) -> None:
        if not self.persist:
            return
        if not force and time.monotonic() < self._backoff_until:
            return
        job = self._local.get(job_id)
        if job is None:
            return
        # `dict(job)` first: a Stop adds `cancelled` to this dict from a request
        # thread, and iterating it while that happens raises RuntimeError — which
        # nothing here would catch, so the generation itself would fail. The copy
        # is one C call under the GIL, so it can't see a change half-made.
        state = dict(job)
        state.pop("cancelled", None)
        try:
            payload = json.dumps(state, default=str)
        except (TypeError, ValueError) as exc:
            logger.warning("Could not serialise generation job %s: %s", job_id, exc)
            return
        conn = None
        try:
            conn = self._conn()
            c = conn.cursor()
            if prune:
                c.execute(
                    f"DELETE FROM {self.table} WHERE updated_at < NOW() - make_interval(hours => %s)",
                    (ROW_KEEP_HOURS,),
                )
            c.execute(
                f"""
                INSERT INTO {self.table} (job_id, state) VALUES (%s, %s)
                ON CONFLICT (job_id) DO UPDATE
                    SET state = EXCLUDED.state, updated_at = CURRENT_TIMESTAMP
                """,
                (job_id, payload),
            )
            conn.commit()
            self._backoff_until = 0.0
        except Exception as exc:  # noqa: BLE001 — the job carries on in memory
            self._backoff_until = time.monotonic() + BACKOFF_SECONDS
            logger.warning("Could not record generation job %s; other workers won't see it: %s", job_id, exc)
            _rollback(conn)
        finally:
            _close(conn)

    def _load(self, job_id: str) -> Optional[Dict[str, Any]]:
        if not self.persist:
            return None
        conn = None
        try:
            conn = self._conn()
            c = conn.cursor()
            c.execute(f"SELECT state, cancelled FROM {self.table} WHERE job_id = %s", (job_id,))
            row = c.fetchone()
        except Exception as exc:  # noqa: BLE001 — a failed read reads as "not found"
            logger.warning("Could not read generation job %s: %s", job_id, exc)
            _rollback(conn)
            return None
        finally:
            _close(conn)
        if not row:
            return None
        state_raw, cancelled = (row["state"], row["cancelled"]) if hasattr(row, "keys") else (row[0], row[1])
        try:
            state = json.loads(state_raw) if isinstance(state_raw, str) else dict(state_raw or {})
        except ValueError:
            return None
        if cancelled:
            state["cancelled"] = True
        return state

    def _set_cancelled(self, job_id: str) -> bool:
        if not self.persist:
            return False
        conn = None
        try:
            conn = self._conn()
            c = conn.cursor()
            c.execute(f"UPDATE {self.table} SET cancelled = TRUE WHERE job_id = %s", (job_id,))
            conn.commit()
            return (c.rowcount or 0) > 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record Stop for generation job %s: %s", job_id, exc)
            _rollback(conn)
            return False
        finally:
            _close(conn)

    def _read_cancelled(self, job_id: str) -> bool:
        conn = None
        try:
            conn = self._conn()
            c = conn.cursor()
            c.execute(f"SELECT cancelled FROM {self.table} WHERE job_id = %s", (job_id,))
            row = c.fetchone()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not check Stop for generation job %s: %s", job_id, exc)
            _rollback(conn)
            return False
        finally:
            _close(conn)
        if not row:
            return False
        return bool(row["cancelled"] if hasattr(row, "keys") else row[0])

    def _evict_local(self) -> None:
        cutoff = time.monotonic() - LOCAL_KEEP_SECONDS
        with self._lock:
            for job_id in [j for j, at in self._touched.items() if at < cutoff]:
                self._local.pop(job_id, None)
                self._touched.pop(job_id, None)
                self._cancel_checked.pop(job_id, None)


def _rollback(conn) -> None:
    if conn is None:
        return
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001
        pass


def _close(conn) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass
