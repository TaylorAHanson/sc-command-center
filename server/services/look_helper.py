"""View settings' "Describe the look": a sentence in, a theme out.

The model only proposes. Its reply is read with the same rules a save applies,
so nothing it says can produce a theme the spec would refuse, and the editor shows
the result for the user to keep or discard before anything is saved.
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from services import app_spec

MAX_DESCRIPTION_CHARS = 1000

_FONT_NOTES = {
    "inter": "neutral, modern sans",
    "manrope": "friendly geometric sans",
    "space-grotesk": "technical, slightly quirky sans",
    "fraunces": "editorial serif",
    "ibm-plex-sans": "corporate, engineered sans",
    "jetbrains-mono": "monospace, for a terminal or data-heavy feel",
}

SYSTEM_PROMPT = f"""You choose the look of a dashboard view from a short description.
The view is a canvas of white cards; you choose what surrounds them.

Reply with one JSON object and nothing else. Every key is optional; leave out
what the description doesn't ask for:

{{
  "primary": "#rrggbb",   // accent: buttons, links, selected tabs. White text sits on it.
  "dark": "#rrggbb",      // dark brand colour: headings, dark panels. White text sits on it.
  "background": {{"kind": "colour", "colour": "#rrggbb"}}
              | {{"kind": "gradient", "from": "#rrggbb", "to": "#rrggbb", "direction": {" | ".join(f'"{d}"' for d in app_spec.GRADIENT_DIRECTIONS)}}},
  "font": {" | ".join(f'"{f}"' for f in app_spec.FONTS)},
  "cards": {{"radius": {" | ".join(f'"{r}"' for r in app_spec.CARD_STYLES["radius"])},
            "depth": {" | ".join(f'"{d}"' for d in app_spec.CARD_STYLES["depth"])},
            "header": {" | ".join(f'"{h}"' for h in app_spec.CARD_STYLES["header"])}}}
}}

Rules:
- "primary" and "dark" must be dark enough for white text on them (a contrast of
  at least {app_spec.MIN_WHITE_CONTRAST:g}:1). Never pick a pale or pastel accent.
- The background sits behind white cards, so it may be light or dark.
- Fonts: {"; ".join(f"{k} — {v}" for k, v in _FONT_NOTES.items())}.
- Cards: "flat" has no edge, "border" a thin line, "shadow" a soft lift.
  "minimal" headers drop the grey bar and capitals.
- If a current look is given, change only what the description asks to change and
  return the whole resulting look.
- No image backgrounds; no other keys; no comments in the JSON."""


def messages(description: str, current: Optional[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """(role, text) pairs for the helper model."""
    text = description.strip()[:MAX_DESCRIPTION_CHARS]
    current_theme = app_spec.read_theme(current)
    user = f"Description: {text}"
    if current_theme:
        user += "\n\nCurrent look:\n" + json.dumps(current_theme)
    return [("system", SYSTEM_PROMPT), ("user", user)]


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)

_LABELS = {"primary": "accent colour", "dark": "dark colour", "background": "background", "font": "font", "cards": "card style"}


def theme_from_reply(reply: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """The theme a reply proposes, and what it proposed that had to be left out."""
    match = _FENCE.search(reply or "")
    candidate = match.group(1) if match else None
    if candidate is None:
        start, end = (reply or "").find("{"), (reply or "").rfind("}")
        candidate = reply[start:end + 1] if 0 <= start < end else None
    try:
        raw = json.loads(candidate) if candidate else None
    except ValueError:
        raw = None
    if not isinstance(raw, dict):
        return None, []
    theme = app_spec.read_theme(raw) or {}
    dropped = []
    for key, label in _LABELS.items():
        asked = raw.get(key) not in (None, "", {})
        if asked and not theme.get(key):
            dropped.append(label)
        elif key == "cards" and isinstance(raw.get(key), dict) and set(raw[key]) - set(theme.get(key) or {}):
            dropped.append("part of the card style")
    return (theme or None), dropped
