"""Reading and writing apps: published versions in `dashboard_views`, the draft in `object_drafts`.

Apps live in the table views always lived in, under the view's own id, so that
`archived_views`, `app_links`, every `#/view/<id>` and `?shared_view=` link and
every action-log reference keeps pointing at the same thing. The rows there are
published versions; managers change an app's draft (`services/drafts.py`) and
Publish makes it the next version. An app that has never been published is a
draft and nothing else, so "does this app exist" asks both places.

Every draft stores `spec_json` and keeps `widgets_json` equal to the first tab,
and publishing copies both. That second copy is for rollback: code from before
apps reads only `widgets_json`, so a deployment rolled back after apps shipped
still shows each app's first tab rather than an empty canvas.

The functions take a cursor and leave committing to the caller, so a route can
check, write and commit in one transaction.
"""
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import HTTPException

from services import app_links, app_spec, drafts

logger = logging.getLogger(__name__)

APP = drafts.APP

# Custom widgets are stored under UUID ids; built-in types (iframe, etc.) have no row.
_CUSTOM_WIDGET_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

HEAD_COLUMNS = (
    "id", "version", "name", "domain", "username", "is_global",
    "widgets_json", "spec_json", "is_locked", "pinned_agent_id", "timestamp",
)

# What an app's draft holds besides the columns publishing stamps; see drafts.NOT_PAYLOAD.
PAYLOAD_COLUMNS = ("name", "domain", "username", "is_global", "widgets_json", "spec_json",
                   "is_locked", "pinned_agent_id")


def fetch_rows(c) -> List[Dict[str, Any]]:
    names = [d[0] for d in c.description]
    return [dict(zip(names, row)) for row in c.fetchall()]


def head(c, app_id: str) -> Optional[Dict[str, Any]]:
    """The newest published version of an app, or None."""
    c.execute(
        f"SELECT {', '.join(HEAD_COLUMNS)} FROM dashboard_views "
        "WHERE id = %s ORDER BY version DESC LIMIT 1",
        (app_id,),
    )
    row = c.fetchone()
    return dict(zip([d[0] for d in c.description], row)) if row else None


def exists(c, app_id: str) -> bool:
    """Published, or a draft that never has been."""
    return head(c, app_id) is not None or drafts.read(c, APP, app_id) is not None


def resolve_ref(c, ref: str) -> Optional[str]:
    """The id of the app a link names: its id, its link name, or `<name>-<id>`.

    Whether the caller may open it is not decided here: the route asks the access
    list next, and a caller without Can use gets the same 404 as for a ref that
    named nothing.
    """
    if not ref:
        return None
    if exists(c, ref):
        return ref
    named = app_links.owner(c, ref)
    if named and exists(c, named):
        return named
    embedded = app_links.id_in(ref)
    if embedded and exists(c, embedded):
        return embedded
    return None


def claim_link(c, app_id: str, name: str) -> None:
    """Give a published app its link name, without letting a failure here fail the publish.

    In a savepoint so an error (the table missing on a deployment whose startup
    couldn't build it) rolls back only this; the app's links then carry its id.
    """
    c.execute("SAVEPOINT app_link")
    try:
        app_links.claim(c, app_id, name)
        c.execute("RELEASE SAVEPOINT app_link")
    except Exception as e:  # noqa: BLE001
        c.execute("ROLLBACK TO SAVEPOINT app_link")
        logger.warning("Couldn't give app %s a link name: %s", app_id, e)


def spec_of(row: Dict[str, Any]) -> Dict[str, Any]:
    return app_spec.read_spec(row.get("id") or "", row.get("spec_json"), row.get("widgets_json"))


def is_archived(c, app_id: str) -> bool:
    c.execute("SELECT 1 FROM archived_views WHERE id = %s", (app_id,))
    return c.fetchone() is not None


def archived_ids(c) -> Set[str]:
    c.execute("SELECT id FROM archived_views")
    return {str(r[0] if not hasattr(r, "keys") else r["id"]) for r in c.fetchall() or []}


def hidden_ids(c, username: str) -> Set[str]:
    """Views shared with this person that they closed in their sidebar."""
    c.execute("SELECT app_id FROM sidebar_hidden WHERE username = %s", (username,))
    return {str(r[0] if not hasattr(r, "keys") else r["app_id"]) for r in c.fetchall() or []}


def payload(*, name: str, domain: Optional[str], username: str, is_locked: bool,
            pinned_agent_id: Optional[str], spec: Dict[str, Any], is_global: bool = False) -> Dict[str, Any]:
    return {
        "name": name,
        "domain": domain,
        "username": username,
        # Nothing reads this for access any more; publishing sets it so that code
        # from before sharing, after a rollback, lists a widely shared view to its
        # domain rather than to nobody.
        "is_global": int(bool(is_global)),
        "widgets_json": app_spec.dumps(app_spec.first_tab_widgets(spec)),
        "spec_json": app_spec.dumps(spec),
        "is_locked": int(bool(is_locked)),
        "pinned_agent_id": pinned_agent_id,
    }


def create_draft(c, *, app_id: str, name: str, domain: Optional[str], username: str,
                 is_locked: bool, pinned_agent_id: Optional[str], spec: Dict[str, Any]) -> None:
    """A new app: a draft with nothing published behind it."""
    if exists(c, app_id):
        raise HTTPException(status_code=409, detail="An app with this id already exists.")
    drafts.save(
        c, APP, app_id,
        payload(name=name, domain=domain, username=username, is_locked=is_locked,
                pinned_agent_id=pinned_agent_id, spec=spec),
        username, base_version=None,
    )


def draft_payload(c, app_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
    """What the next save starts from — the draft, else the newest published version — and that version."""
    published = drafts.latest(c, APP, app_id)
    held = drafts.read(c, APP, app_id)
    version = int(published["version"]) if published else None
    if held is not None:
        return dict(held.get("payload") or {}), version
    if published is not None:
        return {k: v for k, v in drafts.payload_of(published).items() if k in PAYLOAD_COLUMNS}, version
    return None, None


def save_draft(
    c,
    app_id: str,
    username: str,
    *,
    name: Optional[str] = None,
    domain: Optional[str] = None,
    is_locked: Optional[bool] = None,
    pinned_agent_id: Optional[str] = None,
    spec: Optional[Dict[str, Any]] = None,
) -> str:
    """Write the app's draft in place and return its state. The caller has checked Can manage.

    Fields left as None keep their current value; `spec` replaces the whole spec.
    Every save lands in the one draft, so arranging a view (a burst of full PUTs)
    adds no versions; publishing is what makes one.
    """
    current, version = draft_payload(c, app_id)
    if current is None:
        raise HTTPException(status_code=404, detail="View not found")

    if spec is not None:
        try:
            new_spec = app_spec.validate_spec(spec, app_id)
        except app_spec.SpecError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        new_spec = spec_of({"id": app_id, **current})

    drafts.save(c, APP, app_id, payload(
        name=name if name is not None else current.get("name") or "",
        domain=domain if domain is not None else current.get("domain"),
        # The creator, kept: the access list says who may edit, not this column.
        username=current.get("username") or username,
        is_locked=is_locked if is_locked is not None else bool(current.get("is_locked")),
        pinned_agent_id=app_spec.pin_value(pinned_agent_id, current.get("pinned_agent_id")),
        spec=new_spec,
        is_global=bool(current.get("is_global")),
    ), username)
    return drafts.state_of(True, version)


def is_custom_widget(widget_id: Any) -> bool:
    return isinstance(widget_id, str) and bool(_CUSTOM_WIDGET_ID.match(widget_id))


def custom_widget_ids(spec: Dict[str, Any]) -> List[str]:
    """The stored widgets an app places, each once, sorted; built-in types have no row."""
    ids, _ = app_spec.placed_widgets(spec)
    return sorted(i for i in ids if is_custom_widget(i))


def pinned_agent_ids(row: Dict[str, Any], spec: Dict[str, Any]) -> List[str]:
    """The agents an app pins, at app level or on a tab, each once."""
    pins = [row.get("pinned_agent_id")] + [t.get("pinned_agent_id") for t in spec.get("tabs") or []]
    return list(dict.fromkeys(p for p in pins if p and p != "default"))


def widget_heads(c, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """The current (newest live) published version of each widget that has one, by id."""
    if not ids:
        return {}
    c.execute(
        """
        SELECT w.id, w.version, w.name, w.domain, COALESCE(w.is_certified, 0) AS is_certified
          FROM widgets w
          INNER JOIN (
                SELECT id, MAX(version) AS version
                  FROM widgets
                 WHERE is_deprecated = 0
                   AND id = ANY(%s)
                 GROUP BY id
               ) latest ON w.id = latest.id AND w.version = latest.version
        """,
        (list(ids),),
    )
    return {str(r["id"]): r for r in fetch_rows(c)}


def certified_required() -> bool:
    """Whether views shared beyond their owner may hold only certified widgets.

    Off by default. A widely shared view is where one person's work lands on other
    people's screens, so it is the place an organisation may want to gate on review.
    """
    from services.settings_store import get_bool_setting

    return get_bool_setting("require_certified_for_global_views")


def uncertified_widgets(c, spec: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(id, name) of each widget the app places whose current published version isn't certified.

    Every tab counts: checking only the first would let an uncertified widget onto
    people's screens one tab over. A widget never published counts as uncertified;
    publishing it alongside the view doesn't help, since a new version starts
    uncertified. Built-in widget types ship with the app and are reviewed by being
    in the repo; they have no row and are not something an author can introduce.
    """
    ids = custom_widget_ids(spec)
    if not ids:
        return []
    heads = widget_heads(c, ids)
    missing = [wid for wid in ids if wid not in heads]
    held = drafts.drafts(c, drafts.WIDGET, missing) if missing else {}
    out: List[Tuple[str, str]] = []
    for wid in ids:
        if wid in heads and heads[wid]["is_certified"]:
            continue
        name = (heads.get(wid) or {}).get("name") or ((held.get(wid) or {}).get("payload") or {}).get("name")
        out.append((wid, name or f"unknown widget ({wid})"))
    return out


def certification_problem(c, spec: Dict[str, Any], shared_beyond_owner: bool) -> Optional[str]:
    """Why publishing this spec would be refused under the certified-widgets setting, else None."""
    if not shared_beyond_owner or not certified_required():
        return None
    names = sorted(name for _, name in uncertified_widgets(c, spec))
    if not names:
        return None
    return ("A view shared beyond its owner may only contain certified widgets. "
            f"Not yet certified: {', '.join(names)}.")
