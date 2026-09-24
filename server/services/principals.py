"""Checking a role-mapping name against the workspace before it is saved.

A role mapping grants a domain to whoever holds `external_role`, and that name is
compared — exactly, case included — with the caller's Databricks groups and their
username (`routes/roles._get_user_permissions`, fed by `caller_identity`, which
reads SCIM's display names). Until this existed it was a free-text box, so a typo,
a stray space or `Supply-Chain-Admins` for `supply-chain-admins` saved without
complaint and then matched nobody, ever. Nothing reported it: the people it was
meant for simply didn't get the access, and the admin had no way to see why.

So a name is looked up before it is stored, in the same place the match will look:

  * `group` / `user` — an exact match. Saved.
  * `mismatch` — SCIM found it, but spelt differently (SCIM filters ignore case;
    the permission check does not). Refused, with the spelling that will work.
  * `unknown` — nothing by that name. Refused, with the reason.
  * `unverified` — the lookup itself failed (no SCIM access, network). Saved as
    typed, and said so. Refusing here would make role mappings uneditable during
    an outage, and an admin who cannot fix access control is the worse failure.

The lookups run on the caller's OBO client. Listing groups is not something the
app needs its own identity for, and a global admin of this app who cannot see a
group in SCIM is being told something true about the workspace.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SCIM = "/api/2.0/preview/scim/v2"

#: Suggestions per kind. A typeahead that returns a thousand groups is a select
#: box nobody can use; the filter narrows as the admin types.
SEARCH_LIMIT = 20

#: Domain names that mean "every domain" to the permission check. They are
#: meaningful as a mapping's domain without being taxonomy entries.
GLOBAL_DOMAINS = ("global", "all", "app")


def filter_literal(text: str) -> str:
    """`text` made safe to sit between double quotes in a SCIM filter.

    SCIM has no escape for a quote inside a string literal that every server
    honours, and no group or username legitimately contains one, so both quotes
    and backslashes are dropped rather than escaped. Leaving them in would let a
    typed value close the literal and extend the filter.
    """
    return "".join(ch for ch in (text or "") if ch not in '"\\').strip()


def classify(name: str, groups: List[str], users: List[str]) -> Dict[str, Any]:
    """The verdict on `name`, given the SCIM names that matched it loosely."""
    wanted = (name or "").strip()
    if not wanted:
        return {"status": "unknown", "name": wanted, "detail": "Enter a Databricks group or user."}
    if wanted in groups:
        return {"status": "group", "name": wanted, "detail": "Databricks group"}
    if wanted in users:
        return {"status": "user", "name": wanted, "detail": "Databricks user"}
    for kind, names in (("group", groups), ("user", users)):
        for candidate in names:
            if candidate.lower() == wanted.lower():
                return {
                    "status": "mismatch",
                    "name": wanted,
                    "suggestion": candidate,
                    "kind": kind,
                    "detail": (
                        f"The {kind} is spelled '{candidate}'. Role mappings match names "
                        "exactly, so this one would never apply."
                    ),
                }
    return {
        "status": "unknown",
        "name": wanted,
        "detail": (
            f"No Databricks group or user named '{wanted}' in this workspace. A mapping "
            "matches a user's Databricks groups or their username, so this one would "
            "never apply."
        ),
    }


def _scim_names(w: Any, resource: str, attribute: str, scim_filter: str, count: int) -> List[str]:
    params: Dict[str, Any] = {"attributes": attribute, "count": count, "startIndex": 1}
    if scim_filter:
        params["filter"] = scim_filter
    data = w.api_client.do("GET", f"{SCIM}/{resource}", query=params) or {}
    names = []
    for item in data.get("Resources") or []:
        value = item.get(attribute)
        if isinstance(value, str) and value:
            names.append(value)
    return names


def search(w: Any, query: str, limit: int = SEARCH_LIMIT) -> Dict[str, Any]:
    """Groups and users whose names contain `query`, for the typeahead."""
    q = filter_literal(query)
    limit = max(1, min(int(limit or SEARCH_LIMIT), 50))
    try:
        groups = _scim_names(w, "Groups", "displayName",
                             f'displayName co "{q}"' if q else "", limit)
        # Users only once something is typed: an unfiltered user list is the
        # whole directory in arbitrary order, which helps nobody pick a name.
        users = _scim_names(w, "Users", "userName", f'userName co "{q}"', limit) if q else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("SCIM principal search failed: %s", exc)
        return {"groups": [], "users": [], "available": False, "error": str(exc)}
    return {"groups": sorted(groups, key=str.lower), "users": sorted(users, key=str.lower),
            "available": True}


def check(w: Any, name: str) -> Dict[str, Any]:
    """Whether a mapping naming `name` would ever match anyone."""
    wanted = (name or "").strip()
    literal = filter_literal(wanted)
    if not wanted:
        return classify(wanted, [], [])
    if literal != wanted:
        # Quotes and backslashes can't be searched for, and no SCIM name has them.
        return classify(wanted, [], [])
    try:
        # `co`, not `eq`, for groups: Databricks compares group `eq` case-sensitively,
        # which would report `Admins` as unknown when the useful answer is that the
        # group is spelled `admins`. `co` ignores case and `classify` does the exact
        # comparison. User `eq` already ignores case.
        groups = _scim_names(w, "Groups", "displayName", f'displayName co "{literal}"', SEARCH_LIMIT)
        users = [] if wanted in groups else _scim_names(w, "Users", "userName", f'userName eq "{literal}"', 5)
    except Exception as exc:  # noqa: BLE001
        logger.warning("SCIM principal check failed for a role mapping: %s", exc)
        return {
            "status": "unverified",
            "name": wanted,
            "detail": "Couldn't check this name against Databricks; it will be saved as typed.",
        }
    return classify(wanted, groups, users)


def is_blocking(verdict: Dict[str, Any]) -> bool:
    """Whether a save must be refused on this verdict."""
    return verdict.get("status") in ("mismatch", "unknown")
