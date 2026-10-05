"""What an app is, independent of where it is stored.

An app is the artifact a user composes and shares: a name, an owner and a domain
(columns on its `dashboard_views` row, exactly as a view had) plus a *spec* — the
tabs, each holding a widget layout, and how the app presents itself. A view is an
app with one tab. Rows written before apps existed have no `spec_json`, and are
read here as that one-tab app rather than migrated: an existing deployment holds
every version of every view anyone ever saved, and rewriting them would mint a new
version of each, and make promotion believe every view in every env had changed.

Two entry points, deliberately different in temperament:

- `read_spec` never raises. It is what every read path uses, including the creator
  leaderboard and promotion, and one malformed row must not take a sidebar or a
  ranking down with it. It keeps whatever widget entries it finds, verbatim.
- `validate_spec` is for writes and refuses anything it would have to guess at.

Nothing here touches the database or the network, so it is tested exhaustively in
`tests/test_app_spec.py`.
"""
import copy
import json
import logging
import re
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# "workspace" renders inside Command Center's sidebar and header, which is how
# every view has always looked; "standalone" renders the app alone. A missing
# value reads as workspace so that no row ever loses the sidebar by omission —
# offering standalone for a new app is the client's choice, made explicitly.
PRESENTATIONS = ("workspace", "standalone")
ASSISTANT = ("on", "off")

MAX_TABS = 50
MAX_NAME_LENGTH = 120
MAX_ID_LENGTH = 64
# Logos and favicons may be stored inline as data URLs, and the spec travels on
# every app read, so an image is bounded by its encoded length.
MAX_IMAGE_CHARS = 256 * 1024

_IMAGE_DATA_URL = re.compile(
    r"^data:image/(png|jpeg|gif|webp|svg\+xml|x-icon|vnd\.microsoft\.icon);base64,[A-Za-z0-9+/=\s]+$"
)
_BRANDING_TEXT = ("title", "assistant_name")
_BRANDING_IMAGES = ("logo", "favicon")


class SpecError(ValueError):
    """A spec submitted for saving that cannot be stored as it stands."""


def pin_value(incoming: Optional[str], previous: Optional[str]) -> Optional[str]:
    """The app-level agent id to store, given what the client sent.

    A save that says nothing about the pin keeps it: every widget move is a full
    PUT, and those must not quietly unpin an app. An empty string is how a client
    says "no agent" — JSON null can't carry that meaning here, since an absent
    field arrives as null too.
    """
    if incoming is None:
        return (previous or "").strip() or None
    return incoming.strip() or None


def _new_id() -> str:
    return str(uuid.uuid4())


def legacy_spec(app_id: str, widgets: Any) -> Dict[str, Any]:
    """The one-tab app a view row stands for.

    The tab takes the app's id, so a link to the view and a link to its only tab
    are the same link, and `widgets_json` stays the first tab's layout.
    """
    return {
        "schema": SCHEMA_VERSION,
        "presentation": "workspace",
        "assistant": "on",
        "branding": None,
        "tabs": [{
            "id": app_id,
            "name": "",
            "widgets": list(widgets) if isinstance(widgets, list) else [],
            "pinned_agent_id": None,
        }],
        "nav": None,
        "theme": None,
        "filters": [],
    }


def _loads(text: Any) -> Any:
    if text is None or text == "":
        return None
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def read_spec(app_id: str, spec_json: Any, widgets_json: Any) -> Dict[str, Any]:
    """The app a stored row describes. Never raises.

    A row with no usable `spec_json` is a view from before apps, or a row a
    future schema wrote in a shape this one can't read; either way its
    `widgets_json` (which every write keeps equal to the first tab) is the
    honest fallback.
    """
    raw = _loads(spec_json)
    if isinstance(raw, dict):
        try:
            return _normalize(raw, app_id, strict=False, new_id=_new_id)
        except Exception:  # noqa: BLE001 - the read path must not fail on one row
            logger.warning("Unreadable spec_json on app %s; reading its widgets_json instead", app_id)
    elif raw is not None:
        logger.warning("spec_json on app %s is not an object; reading its widgets_json instead", app_id)
    return legacy_spec(app_id, _loads(widgets_json))


def validate_spec(raw: Any, app_id: str, new_id: Callable[[], str] = _new_id) -> Dict[str, Any]:
    """The spec to store for a save, or `SpecError` saying what is wrong with it."""
    if not isinstance(raw, dict):
        raise SpecError("An app's spec must be an object.")
    return _normalize(raw, app_id, strict=True, new_id=new_id)


def _choice(raw: Dict[str, Any], key: str, allowed: tuple, strict: bool) -> str:
    value = raw.get(key)
    if value is None:
        return allowed[0]
    if value in allowed:
        return value
    if strict:
        raise SpecError(f"`{key}` must be one of {', '.join(allowed)}.")
    return allowed[0]


def _text(value: Any, field: str, strict: bool, limit: int = MAX_NAME_LENGTH) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        if strict:
            raise SpecError(f"{field} must be text.")
        return ""
    value = value.strip()
    if len(value) > limit:
        if strict:
            raise SpecError(f"{field} is longer than {limit} characters.")
        value = value[:limit]
    return value


def _image(value: Any, field: str, strict: bool) -> Optional[str]:
    if value in (None, ""):
        return None
    ok = (
        isinstance(value, str)
        and len(value) <= MAX_IMAGE_CHARS
        and (value.startswith("https://") or bool(_IMAGE_DATA_URL.match(value)))
    )
    if ok:
        return value
    if strict:
        raise SpecError(
            f"branding.{field} must be an https URL or a base64 image data URL "
            f"of at most {MAX_IMAGE_CHARS // 1024} KB."
        )
    return None


def _branding(value: Any, strict: bool) -> Optional[Dict[str, Optional[str]]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        if strict:
            raise SpecError("`branding` must be an object.")
        return None
    out: Dict[str, Optional[str]] = {}
    for key in _BRANDING_TEXT:
        out[key] = _text(value.get(key), f"branding.{key}", strict) or None
    for key in _BRANDING_IMAGES:
        out[key] = _image(value.get(key), key, strict)
    return out if any(out.values()) else None


def _reserved(raw: Dict[str, Any], key: str, kind: type, strict: bool) -> Any:
    """`nav`, `theme` and `filters` are carried, not yet interpreted."""
    value = raw.get(key)
    empty = [] if kind is list else None
    if value is None:
        return empty
    if isinstance(value, kind):
        return copy.deepcopy(value)
    if strict:
        raise SpecError(f"`{key}` must be {'a list' if kind is list else 'an object'}.")
    return empty


def _tab_id(value: Any, strict: bool, new_id: Callable[[], str], app_id: str) -> str:
    if value is None or value == "":
        return new_id()
    # A view's only tab is named by the view's id, which `/api/views` never
    # limited, so that id is always acceptable however long it is: refusing it
    # would make a view that exists today impossible to save from the apps API.
    if isinstance(value, str) and value.strip() and (len(value.strip()) <= MAX_ID_LENGTH or value.strip() == app_id):
        return value.strip()
    if strict:
        raise SpecError(f"A tab id must be text of at most {MAX_ID_LENGTH} characters.")
    return new_id()


def _normalize(raw: Dict[str, Any], app_id: str, *, strict: bool, new_id: Callable[[], str]) -> Dict[str, Any]:
    schema = raw.get("schema", SCHEMA_VERSION)
    if strict and (not isinstance(schema, int) or schema > SCHEMA_VERSION):
        # Saving through older code would silently drop whatever the newer
        # schema added, so refuse rather than write a lossy version.
        raise SpecError("This app was saved by a newer version of Command Center.")

    tabs_in = raw.get("tabs")
    if not isinstance(tabs_in, list) or not tabs_in:
        if strict:
            raise SpecError("An app needs at least one tab.")
        tabs_in = []
    if strict and len(tabs_in) > MAX_TABS:
        raise SpecError(f"An app may have at most {MAX_TABS} tabs.")

    tabs: List[Dict[str, Any]] = []
    seen_tabs: set = set()
    widget_home: Dict[str, str] = {}
    for position, tab in enumerate(tabs_in[:MAX_TABS], start=1):
        if not isinstance(tab, dict):
            if strict:
                raise SpecError(f"Tab {position} is not an object.")
            continue
        tab_id = _tab_id(tab.get("id"), strict, new_id, app_id)
        if tab_id in seen_tabs:
            if strict:
                raise SpecError(f"Two tabs share the id {tab_id!r}.")
            tab_id = new_id()
        seen_tabs.add(tab_id)

        widgets = tab.get("widgets")
        if widgets is None:
            widgets = []
        if not isinstance(widgets, list):
            if strict:
                raise SpecError(f"Tab {position}'s widgets must be a list.")
            widgets = []
        if strict:
            for widget in widgets:
                if not isinstance(widget, dict):
                    raise SpecError(f"Tab {position} holds a widget that is not an object.")
                # A deep link names a widget instance, not a tab, so an instance
                # id on two tabs would make "open this widget" ambiguous. The same
                # id twice within one tab is left alone: views have always allowed
                # whatever the grid accepted, and refusing it now would break a
                # save that worked yesterday.
                instance = widget.get("i")
                if isinstance(instance, str) and instance:
                    home = widget_home.setdefault(instance, tab_id)
                    if home != tab_id:
                        raise SpecError(f"Widget {instance!r} is placed on more than one tab.")

        pinned = tab.get("pinned_agent_id")
        pinned = (pinned.strip() or None) if isinstance(pinned, str) else None

        tabs.append({
            "id": tab_id,
            "name": _text(tab.get("name"), f"Tab {position}'s name", strict),
            "widgets": copy.deepcopy(widgets),
            "pinned_agent_id": pinned,
        })

    if not tabs:
        # Only reachable when reading; read_spec falls back to widgets_json.
        raise SpecError("No usable tabs.")

    return {
        "schema": SCHEMA_VERSION,
        "presentation": _choice(raw, "presentation", PRESENTATIONS, strict),
        "assistant": _choice(raw, "assistant", ASSISTANT, strict),
        "branding": _branding(raw.get("branding"), strict),
        "tabs": tabs,
        "nav": _reserved(raw, "nav", dict, strict),
        "theme": _reserved(raw, "theme", dict, strict),
        "filters": _reserved(raw, "filters", list, strict),
    }


def dumps(spec: Dict[str, Any]) -> str:
    return json.dumps(spec)


def first_tab_widgets(spec: Dict[str, Any]) -> List[Any]:
    """What `widgets_json` holds: the first tab, so older readers see something true."""
    tabs = spec.get("tabs") or []
    return list(tabs[0].get("widgets") or []) if tabs else []


def with_first_tab_widgets(spec: Dict[str, Any], widgets: List[Any]) -> Dict[str, Any]:
    """The spec after a save that only knows about one tab.

    `/api/views` speaks for a single canvas, and so does a browser still running
    the bundle from before apps. Either saving a multi-tab app must change the tab
    it was looking at and leave the rest alone; replacing the spec with a one-tab
    one would delete every other tab on the next drag.
    """
    out = copy.deepcopy(spec)
    if not out.get("tabs"):
        out["tabs"] = legacy_spec("", [])["tabs"]
    out["tabs"][0]["widgets"] = copy.deepcopy(list(widgets))
    return out


def all_widgets(spec: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Every widget placed on any tab, for checks that apply to the app as a whole."""
    for tab in spec.get("tabs") or []:
        for widget in tab.get("widgets") or []:
            if isinstance(widget, dict):
                yield widget


def compose_spec(
    sources: List[Dict[str, Any]],
    *,
    presentation: Optional[str] = None,
    new_id: Callable[[], str] = _new_id,
) -> Dict[str, Any]:
    """A new app whose tabs are copies of existing apps' tabs, in the order given.

    Each source is `{"name", "pinned_agent_id", "spec"}`. This is how a deployment
    that already has many views folds some of them into one app: the sources are
    copied, never moved, so their links, subscriptions and history are untouched
    and the author can archive them afterwards if they want to.

    Tabs get new ids, since the source's ids still name the source. Widget
    instance ids are kept, so anything keyed on them (a widget's own saved state,
    for instance) still finds it — unless two sources hold the same instance,
    which `duplicateView` copies and older data can produce, and then the later
    copy is re-keyed rather than refused.
    """
    if not sources:
        raise SpecError("Choose at least one view to build the app from.")
    tabs: List[Dict[str, Any]] = []
    seen_widgets: set = set()
    for source in sources:
        source_tabs = (source.get("spec") or {}).get("tabs") or []
        single = len(source_tabs) == 1
        for tab in source_tabs:
            widgets = []
            for widget in tab.get("widgets") or []:
                if not isinstance(widget, dict):
                    continue  # kept verbatim by read_spec, but nothing the grid could ever draw
                widget = copy.deepcopy(widget)
                instance = widget.get("i")
                if isinstance(instance, str) and instance:
                    if instance in seen_widgets:
                        widget["i"] = instance = new_id()
                    seen_widgets.add(instance)
                widgets.append(widget)
            tabs.append({
                "id": new_id(),
                # A view's name lives on the row, not on its only tab.
                "name": (source.get("name") or "") if single else (tab.get("name") or source.get("name") or ""),
                "widgets": widgets,
                # Resolving tab -> app -> default on the source gave this agent,
                # so the copied tab says so explicitly.
                "pinned_agent_id": tab.get("pinned_agent_id") or source.get("pinned_agent_id") or None,
            })
    if len(tabs) > MAX_TABS:
        raise SpecError(f"An app may have at most {MAX_TABS} tabs; these views have {len(tabs)} between them.")
    spec = legacy_spec("", [])
    spec["tabs"] = tabs
    if presentation is not None:
        spec["presentation"] = presentation
    return validate_spec(spec, "", new_id=new_id)


def can_read(app: Dict[str, Any], *, perms: Dict[str, Any]) -> bool:
    """Whether the caller may open this app — exactly the rule views have always had.

    A global app needs a role in its domain (or global admin), as `GET /api/views`
    filters it. A personal app is open to anyone holding its id: that is what a
    share link has always meant, since `POST /api/views/shared/{id}` subscribes any
    caller to any id that exists and the sidebar then shows it. Apps deliberately
    inherit that model unchanged; tightening it is a separate decision, not a side
    effect of introducing apps.

    Unity Catalog, through the caller's OBO token, still decides what each
    widget's queries return.
    """
    if app.get("is_global"):
        if perms.get("is_admin"):
            return True
        return (app.get("domain") or "General") in (perms.get("domain_permissions") or {})
    return True
