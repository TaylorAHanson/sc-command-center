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
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

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
_BRANDING_TEXT = ("title",)
_BRANDING_IMAGES = ("logo", "favicon")

NAV_STYLES = ("tabs", "sidebar")

# A page tab is one widget drawn edge to edge instead of a grid of cards, so it
# has room for exactly one.
TAB_LAYOUTS = ("canvas", "page")

# The theme recolours the `brand-blue` and `brand-navy` classes, which the app and
# generated widgets alike put white text on (buttons, badges, the sidebar), and
# which widgetLint treats as dark backgrounds. So a theme colour must keep white
# text readable; 3:1 is what Command Center's own blue manages.
THEME_COLOURS = ("primary", "dark")
MIN_WHITE_CONTRAST = 3.0
_HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")

# The rest of a look. Fonts are bundled with the app (the CSP allows no font
# host), so a theme may only name one of these; `src/fonts.ts` holds the files.
GRADIENT_DIRECTIONS = ("to-b", "to-r", "to-br", "to-tr")
BACKGROUND_FITS = ("cover", "tile")
FONTS = ("inter", "manrope", "space-grotesk", "fraunces", "ibm-plex-sans", "jetbrains-mono")
CARD_STYLES = {
    "radius": ("none", "sm", "md", "lg", "xl"),
    "depth": ("flat", "border", "shadow"),
    "header": ("bar", "minimal", "none"),
}

# A filter's choice lands in the dashboard variables under its key, which widget
# code reads as `data.variables.<key>`, so the key must be a plain identifier.
MAX_FILTERS = 10
MAX_FILTER_OPTIONS = 100
_FILTER_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


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
            "layout": "canvas",
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


def _nav(value: Any, strict: bool) -> Optional[Dict[str, str]]:
    """How the tabs are laid out. Tabs across the top is no nav at all."""
    if value is None:
        return None
    if not isinstance(value, dict):
        if strict:
            raise SpecError("`nav` must be an object.")
        return None
    style = value.get("style")
    if style in (None, NAV_STYLES[0]):
        return None
    if style in NAV_STYLES:
        return {"style": style}
    if strict:
        raise SpecError(f"`nav.style` must be one of {', '.join(NAV_STYLES)}.")
    return None


def white_text_contrast(colour: str) -> float:
    """WCAG contrast ratio of white text on a `#rrggbb` colour."""
    def channel(hex_pair: str) -> float:
        c = int(hex_pair, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(colour[i:i + 2]) for i in (1, 3, 5))
    return 1.05 / (0.2126 * r + 0.7152 * g + 0.0722 * b + 0.05)


def _hex(value: Any) -> Optional[str]:
    return value.lower() if isinstance(value, str) and _HEX_COLOUR.match(value) else None


def _background(value: Any) -> Optional[Dict[str, str]]:
    """A canvas background, or None if `value` isn't one. Any colour will do:
    it is drawn behind white cards, never under white text."""
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    if kind == "colour":
        colour = _hex(value.get("colour"))
        return {"kind": "colour", "colour": colour} if colour else None
    if kind == "gradient":
        start, end = _hex(value.get("from")), _hex(value.get("to"))
        direction = value.get("direction") or GRADIENT_DIRECTIONS[0]
        if start and end and direction in GRADIENT_DIRECTIONS:
            return {"kind": "gradient", "from": start, "to": end, "direction": direction}
        return None
    if kind == "image":
        url = value.get("url")
        fit = value.get("fit") or BACKGROUND_FITS[0]
        ok = (
            isinstance(url, str)
            and len(url) <= MAX_IMAGE_CHARS
            and (url.startswith("https://") or bool(_IMAGE_DATA_URL.match(url)))
        )
        return {"kind": "image", "url": url, "fit": fit} if ok and fit in BACKGROUND_FITS else None
    return None


def _cards(value: Any, where: str, strict: bool) -> Optional[Dict[str, str]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        if strict:
            raise SpecError(f"{where}.cards must be an object.")
        return None
    out: Dict[str, str] = {}
    for key, allowed in CARD_STYLES.items():
        choice = value.get(key)
        if choice in (None, ""):
            continue
        if choice in allowed:
            out[key] = choice
        elif strict:
            raise SpecError(f"{where}.cards.{key} must be one of {', '.join(allowed)}.")
    return out or None


def read_theme(value: Any) -> Optional[Dict[str, Any]]:
    """A theme with whatever couldn't be drawn left out, as a read does."""
    return _theme(value, strict=False)


def _theme(value: Any, strict: bool, where: str = "theme") -> Optional[Dict[str, Any]]:
    """An app's look. `primary` and `dark` are always present, and the
    rest only when set, so a theme from before backgrounds reads back unchanged."""
    if value is None:
        return None
    if not isinstance(value, dict):
        if strict:
            raise SpecError(f"`{where}` must be an object.")
        return None
    out: Dict[str, Any] = {}
    for key in THEME_COLOURS:
        colour = value.get(key)
        if colour in (None, ""):
            out[key] = None
        elif isinstance(colour, str) and _HEX_COLOUR.match(colour) and white_text_contrast(colour) >= MIN_WHITE_CONTRAST:
            out[key] = colour.lower()
        elif strict:
            raise SpecError(
                f"{where}.{key} must be a #rrggbb color dark enough to carry white text "
                f"(a contrast of at least {MIN_WHITE_CONTRAST:g}:1)."
            )
        else:
            out[key] = None

    raw_background = value.get("background")
    if raw_background not in (None, ""):
        background = _background(raw_background)
        if background:
            out["background"] = background
        elif strict:
            raise SpecError(
                f"{where}.background must be a color, a two-color gradient "
                f"({', '.join(GRADIENT_DIRECTIONS)}), or an https or base64 image "
                f"of at most {MAX_IMAGE_CHARS // 1024} KB ({', '.join(BACKGROUND_FITS)})."
            )

    font = value.get("font")
    if font not in (None, ""):
        if font in FONTS:
            out["font"] = font
        elif strict:
            raise SpecError(f"{where}.font must be one of {', '.join(FONTS)}.")

    cards = _cards(value.get("cards"), where, strict)
    if cards:
        out["cards"] = cards
    return out if any(out.values()) else None


def _filter(value: Any, position: int) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise SpecError(f"Filter {position} is not an object.")
    key = value.get("key")
    if not isinstance(key, str) or not _FILTER_KEY.match(key):
        raise SpecError(
            f"Filter {position}'s key must be letters, digits and underscores, "
            "not starting with a digit, at most 64 characters."
        )
    label = _text(value.get("label"), f"Filter {position}'s label", True) or key
    options_in = value.get("options")
    if not isinstance(options_in, list) or not options_in:
        raise SpecError(f"Filter {position} needs at least one option.")
    if len(options_in) > MAX_FILTER_OPTIONS:
        raise SpecError(f"Filter {position} may have at most {MAX_FILTER_OPTIONS} options.")
    options: List[str] = []
    for option in options_in:
        text = _text(option, f"Filter {position}'s options", True)
        if not text:
            raise SpecError(f"Filter {position} has an empty option.")
        if text in options:
            raise SpecError(f"Filter {position} lists {text!r} twice.")
        options.append(text)
    default = value.get("default")
    if default in (None, ""):
        default = None
    elif not isinstance(default, str) or default.strip() not in options:
        raise SpecError(f"Filter {position}'s default must be one of its options.")
    else:
        default = default.strip()
    return {"key": key, "label": label, "options": options, "default": default}


def _filters(value: Any, strict: bool) -> List[Dict[str, Any]]:
    """The view's own filter bar. Reading drops a filter it can't use whole."""
    if value is None:
        return []
    if not isinstance(value, list):
        if strict:
            raise SpecError("`filters` must be a list.")
        return []
    if strict and len(value) > MAX_FILTERS:
        raise SpecError(f"A view may have at most {MAX_FILTERS} filters.")
    out: List[Dict[str, Any]] = []
    keys: set = set()
    for position, item in enumerate(value, start=1):
        try:
            one = _filter(item, position)
            if one["key"] in keys:
                raise SpecError(f"Two filters set the variable {one['key']!r}.")
        except SpecError:
            if strict:
                raise
            continue
        keys.add(one["key"])
        out.append(one)
        if len(out) == MAX_FILTERS:
            break
    return out


def _tab_id(value: Any, strict: bool, new_id: Callable[[], str], app_id: str) -> str:
    if value is None or value == "":
        return new_id()
    # A view's only tab is named by the view's id, which views never limited,
    # so that id is always acceptable however long it is: refusing it
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

        layout = tab.get("layout")
        if layout is None:
            layout = TAB_LAYOUTS[0]
        elif layout not in TAB_LAYOUTS:
            if strict:
                raise SpecError(f"Tab {position}'s layout must be one of {', '.join(TAB_LAYOUTS)}.")
            layout = TAB_LAYOUTS[0]
        if layout == "page" and len(widgets) > 1:
            if strict:
                raise SpecError(f"Tab {position} is a page, which holds one widget.")
            widgets = widgets[:1]

        entry = {
            "id": tab_id,
            "name": _text(tab.get("name"), f"Tab {position}'s name", strict),
            "layout": layout,
            "widgets": copy.deepcopy(widgets),
            "pinned_agent_id": pinned,
        }
        tabs.append(entry)

    if not tabs:
        # Only reachable when reading; read_spec falls back to widgets_json.
        raise SpecError("No usable tabs.")

    return {
        "schema": SCHEMA_VERSION,
        "presentation": _choice(raw, "presentation", PRESENTATIONS, strict),
        "assistant": _choice(raw, "assistant", ASSISTANT, strict),
        "branding": _branding(raw.get("branding"), strict),
        "tabs": tabs,
        "nav": _nav(raw.get("nav"), strict),
        "theme": _theme(raw.get("theme"), strict),
        "filters": _filters(raw.get("filters"), strict),
    }


def dumps(spec: Dict[str, Any]) -> str:
    return json.dumps(spec)


def first_tab_widgets(spec: Dict[str, Any]) -> List[Any]:
    """What `widgets_json` holds: the first tab, so older readers see something true."""
    tabs = spec.get("tabs") or []
    return list(tabs[0].get("widgets") or []) if tabs else []


def all_widgets(spec: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Every widget placed on any tab, for checks that apply to the app as a whole."""
    for tab in spec.get("tabs") or []:
        for widget in tab.get("widgets") or []:
            if isinstance(widget, dict):
                yield widget


def placed_widgets(spec: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """The widget ids an app's tabs place, and the `id@version` of each one pinned.

    A placed widget renders its current version unless `props._version` pins an
    older one, which is what the browser looks up as `id@version`. Ids come out
    in the order they first appear, each once.
    """
    ids: Dict[str, None] = {}
    pinned: Dict[str, None] = {}
    for widget in all_widgets(spec):
        widget_id = widget.get("type")
        if not isinstance(widget_id, str) or not widget_id:
            continue
        ids[widget_id] = None
        props = widget.get("props")
        version = props.get("_version") if isinstance(props, dict) else None
        if isinstance(version, str) and version.strip().isdigit():
            version = int(version.strip())
        if isinstance(version, int) and not isinstance(version, bool) and version > 0:
            pinned[f"{widget_id}@{version}"] = None
    return list(ids), list(pinned)


def retarget_links(props: Dict[str, Any], tab_ids: Dict[Any, str]) -> Dict[str, Any]:
    """A widget's settings with its tab links (`{"tab": id}`) moved onto a copy's tab ids.

    Mirrors `retargetLinks` in `src/store/appSpec.ts`, which does the same when a
    view is duplicated in the browser.
    """
    out = {}
    for key, value in props.items():
        if isinstance(value, dict) and isinstance(value.get("tab"), str) and value["tab"] in tab_ids:
            value = {"tab": tab_ids[value["tab"]]}
        out[key] = value
    return out


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
        # A link reaches only its own view's tabs, so each source maps its own.
        tab_ids = {t.get("id"): new_id() for t in source_tabs if isinstance(t, dict)}
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
                if isinstance(widget.get("props"), dict):
                    widget["props"] = retarget_links(widget["props"], tab_ids)
                widgets.append(widget)
            tabs.append({
                "id": tab_ids.get(tab.get("id")) or new_id(),
                # A view's name lives on the row, not on its only tab.
                "name": (source.get("name") or "") if single else (tab.get("name") or source.get("name") or ""),
                "layout": tab.get("layout") or TAB_LAYOUTS[0],
                "widgets": widgets,
                # Resolving tab -> app -> default on the source gave this agent,
                # so the copied tab says so explicitly.
                "pinned_agent_id": tab.get("pinned_agent_id") or source.get("pinned_agent_id") or None,
            })
    if len(tabs) > MAX_TABS:
        raise SpecError(f"An app may have at most {MAX_TABS} tabs; these views have {len(tabs)} between them.")
    # The copied widgets may read variables their view's filter bar set, so the
    # app keeps those filters; where two views filter the same key, the first wins.
    filters: List[Dict[str, Any]] = []
    for source in sources:
        for one in (source.get("spec") or {}).get("filters") or []:
            if isinstance(one, dict) and one.get("key") not in {f["key"] for f in filters}:
                filters.append(copy.deepcopy(one))
    if len(filters) > MAX_FILTERS:
        raise SpecError(f"An app may have at most {MAX_FILTERS} filters; these views have {len(filters)} between them.")
    spec = legacy_spec("", [])
    spec["tabs"] = tabs
    spec["filters"] = filters
    # A view has one look, so the app takes the first source's that has one.
    spec["theme"] = next((read_theme(s["spec"]["theme"]) for s in sources if (s.get("spec") or {}).get("theme")), None)
    if presentation is not None:
        spec["presentation"] = presentation
    return validate_spec(spec, "", new_id=new_id)


def can_read(app: Dict[str, Any], *, perms: Dict[str, Any]) -> bool:
    """Whether the caller may open this app — exactly the rule views have always had.

    A global app needs a role in its domain (or global admin), as the views list
    always filtered it. A personal app is open to anyone holding its id: that is
    what a share link has always meant, since opening one subscribes any caller to
    any id that exists and the sidebar then shows it. Apps deliberately
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
