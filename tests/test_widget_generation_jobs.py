"""Standalone tests for Widget Studio's job store.

The app runs two uvicorn workers, and the studio's polls and its Stop can reach
either one. Each test here builds two stores over one fake table — two workers
over one Lakebase — and checks what the other worker can see and do: read a
job's progress, stop it, and not be undone by the running worker's next write.
And, because the table is only a copy, that a database outage costs visibility
and never the generation.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import generation_jobs as gj  # noqa: E402
from services.generation_jobs import JobStore  # noqa: E402


class FakeTable:
    """The one table both workers share. `down` makes every statement fail."""

    def __init__(self):
        self.rows = {}
        self.down = False
        self.statements = 0


class FakeCursor:
    def __init__(self, table):
        self.table = table
        self.rowcount = 0
        self._result = None

    def execute(self, sql, params=()):
        self.table.statements += 1
        if self.table.down:
            raise RuntimeError("connection refused")
        verb = sql.split()[0].upper()
        if verb == "DELETE":
            return
        if verb == "INSERT":
            job_id, state = params
            row = self.table.rows.setdefault(job_id, {"cancelled": False})
            row["state"] = state  # never touches `cancelled`, like the real upsert
            return
        if verb == "UPDATE":
            (job_id,) = params
            row = self.table.rows.get(job_id)
            self.rowcount = 1 if row else 0
            if row:
                row["cancelled"] = True
            return
        if verb == "SELECT":
            (job_id,) = params
            row = self.table.rows.get(job_id)
            if row is None:
                self._result = None
            elif "state" in sql.split("FROM")[0]:
                self._result = {"state": row["state"], "cancelled": row["cancelled"]}
            else:
                self._result = {"cancelled": row["cancelled"]}
            return
        raise AssertionError(f"unexpected statement: {sql}")

    def fetchone(self):
        return self._result


class FakeConn:
    def __init__(self, table):
        self.table = table

    def cursor(self):
        return FakeCursor(self.table)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def workers():
    """Two stores over one table, with no throttle on Stop checks."""
    table = FakeTable()
    a, b = JobStore(), JobStore()
    a._conn = b._conn = lambda: FakeConn(table)
    return table, a, b


def with_cancel_poll(seconds, fn):
    before = gj.CANCEL_POLL_SECONDS
    gj.CANCEL_POLL_SECONDS = seconds
    try:
        fn()
    finally:
        gj.CANCEL_POLL_SECONDS = before


def test_a_poll_on_the_other_worker_sees_the_job_and_its_progress():
    table, running, other = workers()
    running.create("j1", {"status": "pending", "trace": []})
    running.update("j1", status="running", stage_index=1)
    running["j1"]["trace"].append("planned it")
    running.save("j1")

    seen = other.snapshot("j1")
    assert seen["status"] == "running" and seen["stage_index"] == 1
    assert seen["trace"] == ["planned it"]
    assert other.snapshot("nobody") is None


def test_stop_received_by_the_other_worker_reaches_the_running_job():
    def run():
        table, running, other = workers()
        running.create("j1", {"status": "running"})
        assert not running.is_cancelled("j1")

        answer = other.cancel("j1")
        assert answer is not None and answer["cancelled"] is True
        assert running.is_cancelled("j1")
        assert other.cancel("nobody") is None

    with_cancel_poll(0.0, run)


def test_a_progress_write_does_not_undo_a_stop():
    def run():
        table, running, other = workers()
        running.create("j1", {"status": "running"})
        other.cancel("j1")
        # The running worker hasn't noticed yet and writes progress over the row.
        running.update("j1", stage_index=2)
        assert table.rows["j1"]["cancelled"] is True
        assert running.is_cancelled("j1")
        assert other.snapshot("j1")["cancelled"] is True

    with_cancel_poll(0.0, run)


def test_checking_for_a_stop_is_throttled():
    def run():
        table, running, _ = workers()
        running.create("j1", {"status": "running"})
        before = table.statements
        for _ in range(20):
            running.is_cancelled("j1")
        assert table.statements - before == 1

    with_cancel_poll(60.0, run)


def test_a_stop_on_the_running_worker_needs_no_database():
    table, running, _ = workers()
    running.create("j1", {"status": "running"})
    table.down = True
    assert running.cancel("j1")["cancelled"] is True
    assert running.is_cancelled("j1")


def test_an_outage_costs_visibility_not_the_generation():
    table, running, other = workers()
    table.down = True
    running.create("j1", {"status": "pending"})
    running.update("j1", status="running")
    assert running["j1"]["status"] == "running"
    assert other.snapshot("j1") is None

    # Intermediate writes back off rather than each paying for the failure...
    failed_at = table.statements
    running.update("j1", stage_index=1)
    assert table.statements == failed_at

    # ...but the settled state is always attempted, since a poll is waiting on it.
    table.down = False
    running.replace("j1", {"status": "completed", "result": {"code": "x"}}, final=True)
    assert other.snapshot("j1")["status"] == "completed"


def test_what_is_stored_is_json_and_leaves_the_flag_to_its_column():
    table, running, _ = workers()
    running.create("j1", {"status": "running", "cancelled": True, "odd": {1, 2}})
    stored = json.loads(table.rows["j1"]["state"])
    assert "cancelled" not in stored
    assert stored["status"] == "running"


def test_switched_off_it_is_a_plain_dict():
    store = JobStore()
    store.persist = False
    store._conn = lambda: (_ for _ in ()).throw(AssertionError("must not touch the database"))
    store["j1"] = {"status": "pending"}
    store["j1"]["cancelled"] = True
    assert "j1" in store and store.get("j1")["status"] == "pending"
    assert store.is_cancelled("j1")
    assert store.snapshot("missing") is None
    assert store.cancel("missing") is None


if __name__ == "__main__":
    tests = [
        test_a_poll_on_the_other_worker_sees_the_job_and_its_progress,
        test_stop_received_by_the_other_worker_reaches_the_running_job,
        test_a_progress_write_does_not_undo_a_stop,
        test_checking_for_a_stop_is_throttled,
        test_a_stop_on_the_running_worker_needs_no_database,
        test_an_outage_costs_visibility_not_the_generation,
        test_what_is_stored_is_json_and_leaves_the_flag_to_its_column,
        test_switched_off_it_is_a_plain_dict,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
