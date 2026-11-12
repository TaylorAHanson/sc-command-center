"""Tests for the background job runner (services/background.py).

Both uvicorn workers run the same loop, so what matters is the decision each
makes on its turn: skip a job the other worker holds, skip one that ran recently
enough, run one that's due, and record a failure without letting it escape. A
fake connection is enough to pin each of those, the way test_db_pool does.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from services import background
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_background: {e}")
    sys.exit(0)


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._next = None

    def execute(self, sql, params=None):
        text = " ".join(sql.split())
        self.conn.statements.append((text, params))
        if text.startswith("SELECT pg_try_advisory_lock"):
            self._next = (self.conn.lock_free,)
        elif text.startswith("INSERT INTO background_jobs"):
            self._next = ("job",) if self.conn.due else None
        else:
            self._next = None

    def fetchone(self):
        return self._next


class FakeConn:
    def __init__(self, lock_free=True, due=True):
        self.lock_free = lock_free
        self.due = due
        self.statements = []
        self.commits = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def sql(self, prefix):
        return [s for s in self.statements if s[0].startswith(prefix)]


def _job(fn=None, every=60):
    calls = []

    def default():
        calls.append(1)

    return background.Job("reconcile", every, fn or default), calls


def test_a_job_the_other_worker_holds_is_skipped():
    job, calls = _job()
    conn = FakeConn(lock_free=False)
    assert background.run_job(job, conn) == "busy"
    assert calls == []
    # Nothing was claimed, so the other worker's run is the only one recorded.
    assert conn.sql("INSERT INTO background_jobs") == []


def test_a_job_that_ran_recently_is_not_run_again():
    job, calls = _job()
    conn = FakeConn(due=False)
    assert background.run_job(job, conn) == "not_due"
    assert calls == []
    assert conn.sql("SELECT pg_advisory_unlock"), "the lock must be released even when nothing ran"


def test_a_due_job_runs_once_and_is_recorded():
    job, calls = _job()
    conn = FakeConn()
    assert background.run_job(job, conn) == "ran"
    assert calls == [1]
    update = conn.sql("UPDATE background_jobs")
    assert update and update[0][1][0] == "ok" and update[0][1][-1] == "reconcile"
    assert conn.sql("SELECT pg_advisory_unlock")


def test_the_claim_carries_the_interval():
    job, _ = _job(every=900)
    conn = FakeConn()
    background.run_job(job, conn)
    claim = conn.sql("INSERT INTO background_jobs")[0]
    assert claim[1] == ("reconcile", 900.0)


def test_a_failing_job_is_recorded_not_raised():
    def boom():
        raise RuntimeError("catalog unreachable")

    job, _ = _job(fn=boom)
    conn = FakeConn()
    assert background.run_job(job, conn) == "failed"
    status, error = conn.sql("UPDATE background_jobs")[0][1][:2]
    assert status == "failed" and "catalog unreachable" in error
    assert conn.sql("SELECT pg_advisory_unlock")


def test_lock_keys_are_stable_signed_64_bit_and_distinct():
    a, b = background.lock_key("reconcile"), background.lock_key("rollup")
    assert a == background.lock_key("reconcile")
    assert a != b
    for key in (a, b):
        assert -(2 ** 63) <= key < 2 ** 63


def test_next_check_backs_off_less_when_the_job_was_busy():
    # A job another worker is running, or that couldn't be checked, is looked at
    # again soon; one that ran or wasn't due waits its full interval.
    assert background.next_check("busy", 3600, 100.0) == 130.0
    assert background.next_check("error", 3600, 100.0) == 130.0
    assert background.next_check("ran", 3600, 100.0) == 3700.0
    assert background.next_check("not_due", 10, 100.0) == 110.0


def test_registration_never_raises():
    background._reset_for_tests()
    background.register("too-often", 1, lambda: None)
    background.register("", 60, lambda: None)
    background.register("no-fn", 60, None)
    assert background.jobs() == []
    background.register("ok", 60, lambda: None)
    assert [j.name for j in background.jobs()] == ["ok"]
    background._reset_for_tests()


def test_start_respects_the_kill_switch():
    background._reset_for_tests()
    os.environ["BACKGROUND_JOBS"] = "0"
    try:
        background.start()
        assert background._started is False
    finally:
        del os.environ["BACKGROUND_JOBS"]
        background._reset_for_tests()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
