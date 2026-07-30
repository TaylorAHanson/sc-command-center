"""A connection pool for Lakebase/Postgres, sized and aged for OAuth credentials.

Opening a Lakebase connection is expensive — the TCP/TLS/auth handshake alone is
several round trips, measured at roughly 650 ms from outside the workspace and
tens of milliseconds from inside it — while the queries this app runs take one
round trip. Every request used to pay the handshake, so page loads that issue a
few queries spent almost all of their time connecting. Connections are now kept
and handed back out.

Why this rather than ``psycopg2.pool`` or a proxy such as pgbouncer:

- Lakebase passwords are minted OAuth tokens that expire. ``psycopg2.pool`` holds
  one dsn for its lifetime, so once the token behind it expires every *new*
  connection it opens fails. Here each pooled connection carries the credential
  generation it was opened under, and ``invalidate`` retires them together when
  credentials are re-resolved.
- Callers are spread across ~60 sites that open a connection and call ``close()``
  on the happy path only. `PooledConnection` keeps that contract — ``close()``
  returns the connection instead of dropping it — and releases on garbage
  collection too, so the error paths that never reach ``close()`` return their
  connection when CPython drops the last reference, exactly as they do today.
- The pool never blocks. Past its size limit it opens an unpooled connection that
  closes on release: a burst degrades to the old behaviour instead of deadlocking
  behind a queue.

Each uvicorn worker holds its own pool, so the connection ceiling for the
deployment is ``workers × LAKEBASE_POOL_MAX_SIZE``.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from psycopg2.extensions import TRANSACTION_STATUS_IDLE

# How many connections one worker may hold at once. Sized for a burst: a
# dashboard load fires a dozen or so requests together, and sync route handlers
# run in a thread pool, so they arrive genuinely in parallel. Still small enough
# that several workers stay well under a Lakebase instance's connection limit.
MAX_SIZE = int(os.environ.get("LAKEBASE_POOL_MAX_SIZE", "16"))
# Hard ceiling on idle connections; the idle timeout below is what normally
# shrinks the pool, so this only matters if it is configured lower than MAX_SIZE.
MAX_IDLE = int(os.environ.get("LAKEBASE_POOL_MAX_IDLE", str(MAX_SIZE)))
# Idle connections are released after this long, but never below MIN_IDLE. A hard
# idle cap instead of a timeout made repeated bursts churn: each page load opened
# the connections above the cap and closed them again moments later. With a
# timeout, a burst's connections stay warm for the next burst, and a quiet
# afternoon still hands the sessions back — bar the few that keep the next first
# request fast.
IDLE_TIMEOUT_SECONDS = float(os.environ.get("LAKEBASE_POOL_IDLE_TIMEOUT_SECONDS", "300"))
MIN_IDLE = int(os.environ.get("LAKEBASE_POOL_MIN_IDLE", "2"))
# Connections are reopened once they reach this age. Postgres authenticates at
# connect time only, so an expired token does not close a live connection, but
# recycling keeps the pool from accumulating sessions the managed service may
# decide to terminate on its own.
MAX_AGE_SECONDS = float(os.environ.get("LAKEBASE_POOL_MAX_AGE_SECONDS", "1500"))
# A connection idle longer than this is checked with a one-round-trip ping before
# being handed out, since the far end may have gone away without telling us.
PING_AFTER_SECONDS = float(os.environ.get("LAKEBASE_POOL_PING_AFTER_SECONDS", "30"))


class _Entry:
    """A pooled connection and the bookkeeping that decides its fate."""

    __slots__ = ("conn", "opened_at", "idle_since", "generation")

    def __init__(self, conn: Any, generation: int):
        self.conn = conn
        self.opened_at = time.monotonic()
        self.idle_since = self.opened_at
        self.generation = generation


class PooledConnection:
    """Stands in for a psycopg2 connection, returning it to the pool on close.

    Everything except ``close`` is forwarded to the real connection, so callers
    use ``cursor()``, ``commit()``, ``rollback()`` and the rest unchanged.
    """

    __slots__ = ("_entry", "_pool", "_pooled", "_released")

    def __init__(self, entry: _Entry, pool: "_EnvPool", pooled: bool):
        object.__setattr__(self, "_entry", entry)
        object.__setattr__(self, "_pool", pool)
        object.__setattr__(self, "_pooled", pooled)
        object.__setattr__(self, "_released", False)

    # -- the connection interface ------------------------------------------
    def __getattr__(self, name: str) -> Any:
        return getattr(self._entry.conn, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._entry.conn, name, value)

    def close(self) -> None:
        """Return the connection to the pool. Safe to call more than once."""
        self._release(reason="close")

    # -- pool plumbing -----------------------------------------------------
    def _release(self, reason: str) -> None:
        if self._released:
            return
        object.__setattr__(self, "_released", True)
        self._pool.release(self._entry, pooled=self._pooled, reason=reason)

    def __del__(self) -> None:
        # The safety net for call sites that only close on success: when the
        # exception path drops the last reference, the connection comes back.
        try:
            self._release(reason="gc")
        except Exception:  # noqa: BLE001 - never raise from a finalizer
            pass

    def __enter__(self) -> "PooledConnection":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


class _EnvPool:
    """Idle connections for one environment (dev/test/prod)."""

    def __init__(self, env: str):
        self.env = env
        self._lock = threading.Lock()
        self._idle: List[_Entry] = []
        self._leased = 0
        self._generation = 0
        # Counters, surfaced by `stats` and the /api/health endpoint.
        self.opened = 0
        self.reused = 0
        self.discarded = 0
        self.overflow = 0
        self.gc_released = 0

    # -- checkout ----------------------------------------------------------
    def acquire(self, factory: Callable[[], Any]) -> PooledConnection:
        self._reap()
        while True:
            with self._lock:
                entry = self._idle.pop() if self._idle else None
                generation = self._generation
                if entry is None:
                    # Count the lease before releasing the lock so parallel
                    # callers can't all decide there is room for one more.
                    pooled = self._leased + len(self._idle) < MAX_SIZE
                    self._leased += 1
                    if not pooled:
                        self.overflow += 1
                else:
                    self._leased += 1
                    pooled = True

            if entry is None:
                try:
                    conn = factory()
                except Exception:
                    with self._lock:
                        self._leased -= 1
                    raise
                with self._lock:
                    self.opened += 1
                return PooledConnection(_Entry(conn, generation), self, pooled)

            if self._usable(entry, generation):
                with self._lock:
                    self.reused += 1
                return PooledConnection(entry, self, True)

            # Unusable: drop it and look again (or open a fresh one).
            self._discard(entry)
            with self._lock:
                self._leased -= 1

    def _usable(self, entry: _Entry, generation: int) -> bool:
        conn = entry.conn
        if getattr(conn, "closed", 1):
            return False
        if entry.generation != generation:
            return False
        now = time.monotonic()
        if now - entry.opened_at >= MAX_AGE_SECONDS:
            return False
        if now - entry.idle_since < PING_AFTER_SECONDS:
            return True
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            return True
        except Exception as e:  # noqa: BLE001
            logging.info("Discarding idle Lakebase connection for env=%s: %s", self.env, e)
            return False

    # -- checkin -----------------------------------------------------------
    def release(self, entry: _Entry, pooled: bool, reason: str) -> None:
        with self._lock:
            self._leased -= 1
            generation = self._generation
            if reason == "gc":
                self.gc_released += 1

        if reason == "gc":
            logging.debug(
                "Lakebase connection for env=%s returned by garbage collection; "
                "a caller did not close it", self.env,
            )

        keep = pooled and entry.generation == generation and not getattr(entry.conn, "closed", 1)
        if keep:
            keep = self._reset(entry.conn)
        if not keep:
            self._discard(entry)
            return

        entry.idle_since = time.monotonic()
        with self._lock:
            if len(self._idle) >= MAX_IDLE:
                keep = False
            else:
                self._idle.append(entry)
        if not keep:
            self._discard(entry)
        self._reap()

    def _reap(self) -> None:
        """Close connections that have sat unused, keeping a few warm."""
        if IDLE_TIMEOUT_SECONDS <= 0:
            return
        now = time.monotonic()
        with self._lock:
            # Oldest first: `_idle` is used as a stack, so the front is the least
            # recently returned.
            spare = len(self._idle) - MIN_IDLE
            victims = []
            while spare > 0 and self._idle and now - self._idle[0].idle_since >= IDLE_TIMEOUT_SECONDS:
                victims.append(self._idle.pop(0))
                spare -= 1
        for entry in victims:
            self._discard(entry)

    @staticmethod
    def _reset(conn: Any) -> bool:
        """Leave the session clean for the next caller.

        Callers that raise part-way leave an open or aborted transaction behind,
        which would otherwise hold locks and make the next caller's first
        statement fail.
        """
        try:
            if conn.info.transaction_status != TRANSACTION_STATUS_IDLE:
                conn.rollback()
            return True
        except Exception as e:  # noqa: BLE001
            logging.info("Could not reset a Lakebase connection: %s", e)
            return False

    def _discard(self, entry: _Entry) -> None:
        with self._lock:
            self.discarded += 1
        try:
            entry.conn.close()
        except Exception:  # noqa: BLE001
            pass

    # -- lifecycle ---------------------------------------------------------
    def invalidate(self) -> None:
        """Retire every connection opened under the current credentials."""
        with self._lock:
            self._generation += 1
            stale, self._idle = self._idle, []
        for entry in stale:
            self._discard(entry)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "idle": len(self._idle),
                "leased": self._leased,
                "opened": self.opened,
                "reused": self.reused,
                "discarded": self.discarded,
                "overflow": self.overflow,
                "gc_released": self.gc_released,
            }


_pools: Dict[str, _EnvPool] = {}
_pools_lock = threading.Lock()
_enabled = os.environ.get("LAKEBASE_POOL", "1").strip().lower() not in ("0", "false", "no")


def enabled() -> bool:
    """False turns pooling off, for comparing behaviour against a fresh connection."""
    return _enabled


def _pool_for(env: str) -> _EnvPool:
    with _pools_lock:
        pool = _pools.get(env)
        if pool is None:
            pool = _EnvPool(env)
            _pools[env] = pool
        return pool


def acquire(env: str, factory: Callable[[], Any]) -> Any:
    """Hand out a connection for ``env``, opening one with ``factory`` if needed."""
    if not _enabled:
        return factory()
    return _pool_for(env).acquire(factory)


def invalidate(env: Optional[str] = None) -> None:
    """Retire pooled connections for one environment, or all of them."""
    with _pools_lock:
        pools = list(_pools.values()) if env is None else [p for k, p in _pools.items() if k == env]
    for pool in pools:
        pool.invalidate()


def close_all() -> None:
    """Close every idle connection. Called at shutdown."""
    invalidate()


def stats() -> Dict[str, Dict[str, Any]]:
    with _pools_lock:
        pools = dict(_pools)
    return {env: pool.stats() for env, pool in pools.items()}
