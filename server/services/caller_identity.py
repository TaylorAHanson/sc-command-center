"""Who is calling, resolved once per credential instead of once per request.

Almost every route needs the caller's Databricks username, and the domain-scoped
ones also need their groups: views are owned by username, conversations and
uploads are keyed by it, and role mappings match on group names. Each of those
lookups was a SCIM round trip to the control plane — two on the routes that want
both — which measured at several hundred milliseconds and, once database
connections were pooled, was the largest remaining cost in a page load.

The answer changes when someone's group membership changes, which is rare and not
urgent, so it is cached for a few minutes.

Keyed by a hash of the credential the request arrived with, never by username: two
users hitting the same worker must not be able to see each other's identity. A
client whose credential can't be identified is resolved without caching rather
than sharing a bucket with anyone else.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

TTL_SECONDS = float(os.environ.get("CALLER_IDENTITY_TTL_SECONDS", "300"))


class Identity(NamedTuple):
    username: str
    #: Databricks groups and roles, the names role mappings are matched against.
    entitlements: Tuple[str, ...]


_cache: Dict[str, Tuple[float, Identity]] = {}
_lock = threading.Lock()


def _key_for(host: str, secret: str) -> str:
    return hashlib.sha256(f"{host or ''}\n{secret}".encode("utf-8")).hexdigest()[:32]


def _cache_key(w: Any) -> Optional[str]:
    """A stable key for the credential behind this client, or None if unknown."""
    try:
        config = getattr(w, "config", None)
        # An OBO request carries the user's token; a service-principal client
        # carries a client id. Either identifies the caller; neither is logged.
        secret = getattr(config, "token", None) or getattr(config, "client_id", None)
        if not secret:
            return None
        return _key_for(str(getattr(config, "host", "") or ""), str(secret))
    except Exception:  # noqa: BLE001
        return None


def _scim_me(w: Any) -> Identity:
    """One call for username, groups and roles."""
    data = w.api_client.do("GET", "/api/2.0/preview/scim/v2/Me")
    username = data.get("userName") or ""
    groups = [g.get("display") for g in (data.get("groups") or []) if g.get("display")]
    roles = [r.get("display") for r in (data.get("roles") or []) if r.get("display")]
    return Identity(username or "unknown", tuple(groups + roles))


def _sdk_me(w: Any) -> Identity:
    me = w.current_user.me()
    groups = [g.display for g in (me.groups or []) if g.display]
    roles = [r.display for r in (me.roles or []) if r.display]
    return Identity(me.user_name or "unknown", tuple(groups + roles))


def _fetch(w: Any) -> Identity:
    try:
        return _scim_me(w)
    except Exception as e:  # noqa: BLE001
        logging.info("SCIM Me failed, falling back to the SDK: %s", e)
    try:
        return _sdk_me(w)
    except Exception as e:  # noqa: BLE001
        logging.warning("Could not resolve the caller's identity: %s", e)
        return Identity("unknown", ())


def resolve(w: Any) -> Identity:
    """The caller's username and entitlements, from cache when it is warm."""
    if w is None:
        return Identity("unknown", ())

    key = _cache_key(w)
    now = time.monotonic()
    if key:
        with _lock:
            hit = _cache.get(key)
            if hit and now - hit[0] < TTL_SECONDS:
                return hit[1]

    identity = _fetch(w)
    # Never cache a failure: the next request should try again rather than be told
    # for five minutes that nobody is logged in.
    if key and identity.username != "unknown":
        with _lock:
            _cache[key] = (now, identity)
    return identity


def resolve_for_token(token: Optional[str], client_factory) -> Identity:
    """Same, for callers that hold a raw OBO token rather than a client.

    Keyed identically to ``resolve``, so a request that arrives with a token and
    one that arrives with a client built from it share the one cache entry.
    ``client_factory`` runs only on a miss, so a warm cache does not even build a
    WorkspaceClient.
    """
    key = _key_for(os.environ.get("DATABRICKS_HOST", ""), token) if token else "local"
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < TTL_SECONDS:
            return hit[1]

    identity = _fetch(client_factory())
    if identity.username != "unknown":
        with _lock:
            _cache[key] = (now, identity)
    return identity


def username(w: Any) -> str:
    return resolve(w).username


def entitlements(w: Any) -> List[str]:
    return list(resolve(w).entitlements)


def invalidate() -> None:
    """Forget every cached identity — used by tests and after role changes."""
    with _lock:
        _cache.clear()


def stats() -> Dict[str, Any]:
    with _lock:
        return {"entries": len(_cache), "ttl_seconds": TTL_SECONDS}
