"""What this deployment can do, given what its admins have set up.

Email, scheduling and hybrid search each depend on something only the
customer's admins can provide: an SES sender identity, an OAuth app integration,
Lakebase Search on the database project. None of that may hold up a release, so
each feature ships able to tell whether its setup exists, and stays off with a
message saying so until it does. The checks live here:

  * the browser asks `GET /api/capabilities` what to show and what to disable;
  * Admin Panel → Settings draws a Setup card from the same answers, with what is
    missing and the exact next step for the customer's admins.

Off until set up never means a safeguard is skipped. A check reports what is
missing; it does not stand in for it.

Checks are registered by hand in `main.py`'s startup. A check may be slow (a
serving-endpoint lookup, a catalog query) and may raise, so results are cached
for a minute and a check that raises reads as unavailable: a broken check costs
one feature, not the page. Saving a setting clears the cache on that worker; the
other worker catches up within the minute.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60.0


class Check(NamedTuple):
    name: str
    label: str
    fn: Callable[[], Dict[str, Any]]


_checks: Dict[str, Check] = {}
_lock = threading.Lock()
_cache: Dict[str, Any] = {"at": 0.0, "results": {}}


def result(available: bool, mode: Optional[str] = None, missing: Iterable[str] = (),
           next_step: str = "") -> Dict[str, Any]:
    """What a check returns.

    `mode` names how the feature is running when it has more than one way to
    (search: `basic` / `keyword` / `hybrid`). `missing` lists what the customer's
    admins have yet to provide, in the order to provide it, and `next_step` is the
    one thing to do now, written for them.
    """
    return {
        "available": bool(available),
        "mode": mode,
        "missing": [str(m) for m in missing if m],
        "next_step": next_step or "",
    }


def register(name: str, label: str, fn: Callable[[], Dict[str, Any]]) -> None:
    """Logs rather than raises on a bad registration, because it runs at startup."""
    if not name or not callable(fn):
        logger.error("Capability %r not registered: it needs a name and a check", name)
        return
    with _lock:
        _checks[name] = Check(name, label or name, fn)
        _cache["at"] = 0.0


def invalidate() -> None:
    with _lock:
        _cache["at"] = 0.0


def _run(check: Check) -> Dict[str, Any]:
    try:
        out = check.fn() or {}
        return result(out.get("available", False), out.get("mode"), out.get("missing") or (),
                      out.get("next_step") or "")
    except Exception as e:  # noqa: BLE001 - a broken check turns off one feature, not the page
        logger.warning("Capability check %s failed: %s", check.name, e)
        return result(False, missing=[f"The check itself failed: {e}"],
                      next_step="See the app's logs for the full error.")


def _results(force: bool = False) -> Dict[str, Dict[str, Any]]:
    now = time.monotonic()
    with _lock:
        if not force and _cache["at"] and now - _cache["at"] < CACHE_SECONDS:
            return dict(_cache["results"])
        checks = list(_checks.values())
    results = {check.name: _run(check) for check in checks}
    with _lock:
        _cache["results"] = results
        _cache["at"] = time.monotonic()
    return dict(results)


def describe(admin: bool, force: bool = False) -> List[Dict[str, Any]]:
    """Every capability in registration order.

    Everyone gets whether each one is available and in what mode, which is all the
    UI needs to hide or disable something. Only admins get what's missing and the
    next step: that names the deployment's setup, which is theirs to act on.
    """
    results = _results(force)
    with _lock:
        checks = list(_checks.values())
    out: List[Dict[str, Any]] = []
    for check in checks:
        res = results.get(check.name) or result(False)
        item = {"name": check.name, "label": check.label, "available": res["available"], "mode": res["mode"]}
        if admin:
            item["missing"] = res["missing"]
            item["next_step"] = res["next_step"]
        out.append(item)
    return out


def get(name: str) -> Dict[str, Any]:
    """One capability's full result, for server-side gates. Unknown names are unavailable."""
    res = _results().get(name)
    return dict(res) if res else result(False, missing=[f"Unknown capability '{name}'"])


def available(name: str) -> bool:
    return bool(get(name)["available"])


def _reset_for_tests() -> None:
    with _lock:
        _checks.clear()
        _cache["at"] = 0.0
        _cache["results"] = {}
