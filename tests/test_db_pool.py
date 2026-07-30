"""Tests for the Lakebase connection pool.

No database and no network: a fake connection stands in for psycopg2's, so these
cover the decisions the pool makes — what it reuses, what it throws away, and what
it does with a connection a caller forgot to close.

    PYTHONPATH=server server/venv/bin/python tests/test_db_pool.py

(psycopg2 is imported for its transaction-status constants, so this needs the
server's interpreter rather than a bare python3.)
"""
import gc
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import db_pool  # noqa: E402
from psycopg2.extensions import TRANSACTION_STATUS_IDLE, TRANSACTION_STATUS_INERROR  # noqa: E402


class FakeInfo:
    def __init__(self):
        self.transaction_status = TRANSACTION_STATUS_IDLE


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        self._conn.statements.append(sql)
        if self._conn.fail_on_query:
            raise RuntimeError("server closed the connection unexpectedly")

    def fetchone(self):
        return (1,)

    def close(self):
        pass


class FakeConn:
    """Just enough psycopg2 connection for the pool to reason about."""

    def __init__(self):
        self.closed = 0
        self.statements = []
        self.rollbacks = 0
        self.fail_on_query = False
        self.info = FakeInfo()

    def cursor(self, *a, **kw):
        return FakeCursor(self)

    def rollback(self):
        self.rollbacks += 1
        self.info.transaction_status = TRANSACTION_STATUS_IDLE

    def commit(self):
        pass

    def close(self):
        self.closed = 1


def fresh_pool(env="test-env"):
    """A pool with no history, and a factory that records what it opened."""
    pool = db_pool._EnvPool(env)
    opened = []

    def factory():
        conn = FakeConn()
        opened.append(conn)
        return conn

    return pool, factory, opened


def test_the_second_caller_gets_the_first_callers_connection():
    pool, factory, opened = fresh_pool()
    first = pool.acquire(factory)
    first.close()
    second = pool.acquire(factory)
    assert len(opened) == 1, f"opened {len(opened)} connections, expected to reuse one"
    assert second._entry.conn is opened[0]
    second.close()
    assert pool.stats()["reused"] == 1
    assert pool.stats()["idle"] == 1


def test_connections_held_at_the_same_time_are_separate():
    pool, factory, opened = fresh_pool()
    a = pool.acquire(factory)
    b = pool.acquire(factory)
    assert a._entry.conn is not b._entry.conn
    assert len(opened) == 2
    a.close()
    b.close()
    assert pool.stats()["idle"] == 2


def test_the_proxy_forwards_everything_but_close():
    pool, factory, opened = fresh_pool()
    conn = pool.acquire(factory)
    conn.cursor().execute("SELECT 42")
    assert opened[0].statements == ["SELECT 42"]
    conn.close()
    assert opened[0].closed == 0, "close() must return the connection, not drop it"
    # Idempotent: a call site that closes on both the happy and the error path
    # must not check the connection in twice.
    conn.close()
    assert pool.stats()["idle"] == 1


def test_an_unfinished_transaction_is_rolled_back_before_reuse():
    pool, factory, opened = fresh_pool()
    conn = pool.acquire(factory)
    opened[0].info.transaction_status = TRANSACTION_STATUS_INERROR
    conn.close()
    assert opened[0].rollbacks == 1
    assert pool.stats()["idle"] == 1, "a rolled-back connection is still good"


def test_a_connection_the_caller_never_closed_comes_back_on_collection():
    pool, factory, opened = fresh_pool()

    def borrow_and_fail():
        conn = pool.acquire(factory)
        conn.cursor().execute("SELECT 1")
        raise RuntimeError("the route raised before it could close")

    try:
        borrow_and_fail()
    except RuntimeError:
        pass
    gc.collect()
    stats = pool.stats()
    assert stats["leased"] == 0, f"leaked a lease: {stats}"
    assert stats["idle"] == 1, f"connection was not reclaimed: {stats}"
    assert stats["gc_released"] == 1


def test_a_closed_connection_is_replaced_not_handed_out():
    pool, factory, opened = fresh_pool()
    conn = pool.acquire(factory)
    conn.close()
    opened[0].closed = 1  # the far end went away while it sat idle
    replacement = pool.acquire(factory)
    assert len(opened) == 2
    assert replacement._entry.conn is opened[1]
    replacement.close()


def test_an_idle_connection_is_pinged_and_dropped_if_the_ping_fails():
    pool, factory, opened = fresh_pool()
    conn = pool.acquire(factory)
    conn.close()
    # Pretend it has been sitting for longer than the ping threshold.
    pool._idle[0].idle_since = time.monotonic() - db_pool.PING_AFTER_SECONDS - 1
    opened[0].fail_on_query = True

    replacement = pool.acquire(factory)
    assert opened[0].statements == ["SELECT 1"], "should have been pinged"
    assert opened[0].closed == 1, "a failed ping must close the connection"
    assert replacement._entry.conn is opened[1]
    replacement.close()

    # A connection returned moments ago is handed straight back, no ping.
    again = pool.acquire(factory)
    assert opened[1].statements == [], "a fresh connection needs no ping"
    again.close()


def test_connections_are_retired_once_they_reach_max_age():
    pool, factory, opened = fresh_pool()
    conn = pool.acquire(factory)
    conn.close()
    pool._idle[0].opened_at = time.monotonic() - db_pool.MAX_AGE_SECONDS - 1

    replacement = pool.acquire(factory)
    assert len(opened) == 2, "an over-age connection should be replaced"
    assert opened[0].closed == 1
    replacement.close()


def test_new_credentials_retire_the_connections_opened_under_the_old_ones():
    pool, factory, opened = fresh_pool()
    held = pool.acquire(factory)   # in use across the credential change
    idle = pool.acquire(factory)
    idle.close()

    pool.invalidate()
    assert opened[1].closed == 1, "idle connections should be closed at once"
    assert pool.stats()["idle"] == 0

    held.close()
    assert opened[0].closed == 1, "the in-flight one should be closed on return"
    assert pool.stats()["idle"] == 0

    after = pool.acquire(factory)
    assert after._entry.conn is opened[2]
    after.close()
    assert pool.stats()["idle"] == 1


def test_past_the_size_limit_callers_get_unpooled_connections_rather_than_waiting():
    pool, factory, opened = fresh_pool()
    held = [pool.acquire(factory) for _ in range(db_pool.MAX_SIZE + 3)]
    assert len(opened) == db_pool.MAX_SIZE + 3, "nobody should have been made to wait"
    for conn in held:
        conn.close()
    stats = pool.stats()
    assert stats["overflow"] == 3, "the three past the limit should be marked unpooled"
    assert stats["idle"] == db_pool.MAX_SIZE, "everything within the limit stays warm"
    # Only the three opened past the limit are closed.
    closed = sum(1 for c in opened if c.closed)
    assert closed == 3, f"{closed} closed of {len(opened)}"
    assert stats["discarded"] == 3


def test_a_burst_stays_warm_for_the_next_burst():
    pool, factory, opened = fresh_pool()
    held = [pool.acquire(factory) for _ in range(8)]
    for conn in held:
        conn.close()
    again = [pool.acquire(factory) for _ in range(8)]
    for conn in again:
        conn.close()
    assert len(opened) == 8, f"the second burst reopened connections: {len(opened)}"


def test_connections_left_idle_are_handed_back_but_a_few_stay_warm():
    pool, factory, opened = fresh_pool()
    held = [pool.acquire(factory) for _ in range(6)]
    for conn in held:
        conn.close()
    assert pool.stats()["idle"] == 6

    # An afternoon with no traffic, then one request.
    stale = time.monotonic() - db_pool.IDLE_TIMEOUT_SECONDS - 1
    for entry in pool._idle:
        entry.idle_since = stale
    conn = pool.acquire(factory)
    conn.close()

    idle = pool.stats()["idle"]
    assert idle == db_pool.MIN_IDLE, f"idle={idle}, expected to settle at {db_pool.MIN_IDLE}"
    assert sum(1 for c in opened if c.closed) == 6 - db_pool.MIN_IDLE
    # The ones kept warm are still usable, so the next request pays nothing.
    before = len(opened)
    again = pool.acquire(factory)
    again.close()
    assert len(opened) == before, "a warm connection should have served that"


def test_the_pool_is_safe_under_concurrent_callers():
    pool, factory, opened = fresh_pool()
    errors = []

    def worker():
        try:
            for _ in range(20):
                conn = pool.acquire(factory)
                conn.cursor().execute("SELECT 1")
                conn.close()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent callers hit errors: {errors}"
    stats = pool.stats()
    assert stats["leased"] == 0, f"a lease was not returned: {stats}"
    assert stats["idle"] <= db_pool.MAX_IDLE
    assert len(opened) <= db_pool.MAX_SIZE + 8, f"opened {len(opened)} connections for 8 threads"
    assert stats["reused"] > 0, "with 160 checkouts, some should have been reuses"


def test_pooling_can_be_switched_off():
    calls = []

    def factory():
        conn = FakeConn()
        calls.append(conn)
        return conn

    was = db_pool._enabled
    db_pool._enabled = False
    try:
        conn = db_pool.acquire("dev", factory)
        assert conn is calls[0], "with pooling off the raw connection is returned"
        conn.close()
        assert calls[0].closed == 1, "and close() really closes it"
    finally:
        db_pool._enabled = was


if __name__ == "__main__":
    tests = [
        test_the_second_caller_gets_the_first_callers_connection,
        test_connections_held_at_the_same_time_are_separate,
        test_the_proxy_forwards_everything_but_close,
        test_an_unfinished_transaction_is_rolled_back_before_reuse,
        test_a_connection_the_caller_never_closed_comes_back_on_collection,
        test_a_closed_connection_is_replaced_not_handed_out,
        test_an_idle_connection_is_pinged_and_dropped_if_the_ping_fails,
        test_connections_are_retired_once_they_reach_max_age,
        test_new_credentials_retire_the_connections_opened_under_the_old_ones,
        test_past_the_size_limit_callers_get_unpooled_connections_rather_than_waiting,
        test_a_burst_stays_warm_for_the_next_burst,
        test_connections_left_idle_are_handed_back_but_a_few_stay_warm,
        test_the_pool_is_safe_under_concurrent_callers,
        test_pooling_can_be_switched_off,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
