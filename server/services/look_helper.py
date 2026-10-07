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

Reply with one JSON object and nothing else. Always include "primary" and "dark";
the other keys are optional, so leave out what the description doesn't ask for:

{{
  "primary": "#rrggbb",   // accent: buttons, links, selected tabs. White text sits on it.
  "dark": "#rrggbb",      // dark brand color: headings, dark panels. White text sits on it.
  "background": {{"kind": "colour", "colour": "#rrggbb"}}
              | {{"kind": "gradient", "from": "#rrggbb", "to": "#rrggbb", "direction": {" | ".join(f'"{d}"' for d in app_spec.GRADIENT_DIRECTIONS)}}},
  "font": {" | ".join(f'"{f}"' for f in app_spec.FONTS)},
  "bars": {" | ".join(f'"{b}"' for b in app_spec.BARS)},
  "cards": {{"radius": {" | ".join(f'"{r}"' for r in app_spec.CARD_STYLES["radius"])},
            "depth": {" | ".join(f'"{d}"' for d in app_spec.CARD_STYLES["depth"])},
            "header": {" | ".join(f'"{h}"' for h in app_spec.CARD_STYLES["header"])},
            "spacing": {" | ".join(f'"{s}"' for s in app_spec.CARD_STYLES["spacing"])}}}
}}

Rules:
- "primary" and "dark" must be dark enough for white text on them (a contrast of
  at least {app_spec.MIN_WHITE_CONTRAST:g}:1). Where the look's natural accent is bright
  (cyan on navy, gold on brown), give the deepest shade of it that still carries
  white text rather than leaving the accent out.
- The background is everything under the header: tabs, filters, and the white
  cards and assistant messages, so it may be light or dark.
- Fonts: {"; ".join(f"{k} — {v}" for k, v in _FONT_NOTES.items())}.
- Cards: "flat" has no edge, "border" a thin line, "shadow" a soft lift.
  "minimal" headers drop the gray bar and capitals; "none" leaves the title off
  entirely, for cards whose content names itself; "accent" and "dark" put the
  title in white on a bar of that color. "spacing" is the gap between cards.
- "bars": "dark" draws the header in the dark color with white text, for a bold,
  branded look; "light" (the default) keeps it white.
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

_LABELS = {"primary": "accent color", "dark": "dark color", "background": "background", "font": "font",
           "bars": "header color", "cards": "card style"}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def deepened(colour: Any) -> Any:
    """`colour` darkened, keeping its hue, until white text reads on it.

    Models often answer "bright cyan on navy" with the bright cyan, which a save
    would refuse; the shade that passes is closer to what was asked for than no
    accent at all. Anything that isn't a #rrggbb string comes back unchanged.
    """
    if not isinstance(colour, str) or not _HEX.match(colour):
        return colour
    rgb = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
    for step in range(20):
        shade = "#" + "".join(f"{round(c * (1 - 0.05 * step)):02x}" for c in rgb)
        if app_spec.white_text_contrast(shade) >= app_spec.MIN_WHITE_CONTRAST:
            return shade
    return colour


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
    raw = {**raw, **{key: deepened(raw.get(key)) for key in app_spec.THEME_COLOURS if key in raw}}
    theme = app_spec.read_theme(raw) or {}
    dropped = []
    for key, label in _LABELS.items():
        asked = raw.get(key) not in (None, "", {})
        if asked and not theme.get(key):
            dropped.append(label)
        elif key == "cards" and isinstance(raw.get(key), dict) and set(raw[key]) - set(theme.get(key) or {}):
            dropped.append("part of the card style")
    return (theme or None), dropped
