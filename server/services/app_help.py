"""What the chat agent knows about the Command Center application itself.

Users ask the assistant about the app they are standing in — "what's a widget",
"why can't I see the Finance views", "how do I get this into prod" — and an agent
that only knows how to query data answers those badly. Knowledge is split in two
rather than picking one approach:

  * ``APP_PRIMER`` goes into every system prompt (see ``agent_runtime``). It is
    deliberately short: the vocabulary and the handful of rules the agent must
    never get wrong, on the assumption it may answer without calling any tool.
  * ``app_help(question)`` reads ``app_guide.md`` on demand. Step-by-step
    procedures (mapping a role, promoting a view) are too long to spend prompt
    tokens on every turn and are only occasionally asked about.

Keeping the detail in a markdown file also means it can be edited alongside the
user guide without touching Python.
"""

from __future__ import annotations

import math
import os
import re
import threading
from typing import Dict, List, Tuple

# Kept tight on purpose — this is paid for on every single turn of every agent.
APP_PRIMER = """You are embedded in the **Command Center**, a configurable dashboard application running as a Databricks App. Users can ask you about the app itself; know the basics and be accurate about them:

- A **widget** is one tile on the dashboard — a chart, table, form, embedded page, or a button that performs an action. Users add widgets from the **Widget Library** (sidebar, or the `w` key) by dragging them onto the grid, then move and resize them.
- A **view** is a named tab holding a layout of widgets. Users own their own views; **Global Views** are shared templates that can be copied into My Views to edit. **Lock** freezes a layout, **Share** copies a link to it.
- **Widget Studio** (sidebar) is where widgets are created — an agent generates the code from a description. **Agent Studio** is where the assistants offered in this chat are authored.
- A **domain** (Finance, Supply Chain, …) groups widgets, global views, and saved agents for access control. Each user holds **Viewer**, **Editor**, or **Admin** on a domain, granted by mapping their Databricks group to it. Permissions are additive — the highest level a user is mapped to wins. Domain admins manage this in the **Admin Panel → Access Management**; a blocked user should ask a domain admin to map a group they belong to.
- Work moves **Dev → Test → Prod** by promotion, which is admin-only. Saving a widget in Dev increments its version.
- The **User Guide** and **Release Notes** are in the sidebar under Resources.

For anything beyond these basics — exact steps, promotion rules, agent authoring, widget configuration options — call the `app_help` tool instead of guessing, and say plainly when something is outside what you know about the app."""

_GUIDE_PATH = os.path.join(os.path.dirname(__file__), "app_guide.md")
_MAX_SECTIONS = 3
_MAX_CHARS = 6000

# Words that appear in almost every question and would match almost every
# section, drowning out the terms that actually discriminate.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "about", "from", "into", "this", "that", "these", "those", "it",
    "its", "is", "are", "was", "were", "be", "been", "do", "does", "did", "how",
    "what", "why", "when", "where", "who", "which", "can", "could", "should",
    "would", "will", "i", "me", "my", "you", "your", "we", "our", "us", "they",
    "them", "there", "here", "get", "got", "use", "used", "using", "work",
    "works", "working", "tell", "explain", "mean", "means", "app", "command",
    "center", "please", "help",
}

_lock = threading.Lock()
_cache: Dict[str, object] = {"mtime": None, "sections": []}


def _load_sections() -> List[Tuple[str, str]]:
    """[(title, body)] parsed from the guide, one entry per `##` heading.

    Re-read when the file changes so editing the guide during a dev session
    takes effect without a restart.
    """
    try:
        mtime = os.path.getmtime(_GUIDE_PATH)
    except OSError:
        return []

    with _lock:
        if _cache["mtime"] == mtime:
            return _cache["sections"]  # type: ignore[return-value]

    try:
        with open(_GUIDE_PATH, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return []

    # The authoring conventions at the top live in an HTML comment.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    sections: List[Tuple[str, str]] = []
    for match in re.finditer(r"^##\s+(.+?)\s*$(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL):
        title = match.group(1).strip()
        body = match.group(2).strip()
        if title and body:
            sections.append((title, body))

    with _lock:
        _cache["mtime"] = mtime
        _cache["sections"] = sections
    return sections


def topics() -> List[str]:
    """Section titles, used to advertise coverage in the tool description."""
    return [title for title, _ in _load_sections()]


def _tokens(question: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", (question or "").lower())
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS]


def _variants(token: str) -> List[str]:
    """Substrings that count as a hit for this token.

    Includes a plural/singular twin ("roles" finds "role") and, for longer words,
    a truncated stem so a question's verb form finds the guide's ("certify" finds
    "certified", "promote" finds "promoting"). Crude on purpose — scores are only
    ever compared against each other.
    """
    forms = [token]
    if token.endswith("s") and len(token) > 3:
        forms.append(token[:-1])
    else:
        forms.append(token + "s")
    if len(token) >= 7:
        forms.append(token[:-2])
    return forms


def _weights(sections: List[Tuple[str, str]], tokens: List[str]) -> Dict[str, float]:
    """Rarity weight per token, roughly inverse document frequency.

    Needed because the guide is about widgets throughout: unweighted, "how do I
    get my widget into prod" is decided by "widget" (present in half the
    sections) and the promotion section never surfaces. The rare term in a
    question is the one that says what it is really about.
    """
    total = max(len(sections), 1)
    weights: Dict[str, float] = {}
    for token in tokens:
        forms = _variants(token)
        containing = sum(
            1 for title, body in sections
            if any(f in title.lower() or f in body.lower() for f in forms)
        )
        weights[token] = math.log(1 + total / max(containing, 1))
    return weights


def _score(title: str, body: str, tokens: List[str], weights: Dict[str, float]) -> float:
    title_l = title.lower()
    body_l = body.lower()
    score = 0.0
    for token in tokens:
        forms = _variants(token)
        weight = weights.get(token, 1.0)
        if any(f in title_l for f in forms):
            # Modest, because half the guide's titles contain "widget": a title
            # match should not by itself beat a body that answers the question.
            score += 3 * weight
        # Count the shortest form only — the others are substrings of the text it
        # already matched, so summing them would just double-count.
        hits = body_l.count(min(forms, key=len))
        if hits:
            # Capped: a long section repeating a common word should not outrank a
            # short section that is actually about the thing being asked.
            score += min(hits, 4) * weight
    return score


def app_help(question: str = "") -> str:
    """Return the guide sections most relevant to ``question`` as markdown."""
    sections = _load_sections()
    if not sections:
        return (
            "The application guide is unavailable. Answer from the basics you "
            "already have, and say that you cannot look up further detail."
        )

    tokens = _tokens(question)
    weights = _weights(sections, tokens)
    scored = sorted(
        ((_score(t, b, tokens, weights), t, b) for t, b in sections),
        key=lambda triple: triple[0],
        reverse=True,
    )
    picked = [(t, b) for score, t, b in scored[:_MAX_SECTIONS] if score > 0]

    if not picked:
        return (
            "No section of the application guide matched that. Available topics: "
            + "; ".join(topics())
            + ". Call this tool again naming one of them, or tell the user this "
            "is not something the guide covers."
        )

    out: List[str] = []
    budget = _MAX_CHARS
    for title, body in picked:
        block = f"## {title}\n{body}"
        if len(block) > budget:
            block = block[:budget].rstrip() + "\n…(truncated)"
        out.append(block)
        budget -= len(block)
        if budget <= 200:
            break
    return "\n\n".join(out)


def app_help_tool_spec() -> Dict[str, object]:
    """OpenAI tool spec. Lists the real section titles so the model knows the
    shape of what it can ask for rather than guessing at topics."""
    available = ", ".join(topics()) or "the Command Center application"
    return {
        "type": "function",
        "function": {
            "name": "app_help",
            "description": (
                "Look up how the Command Center application itself works — widgets, views, "
                "the Widget Library, Widget Studio, Agent Studio, domains, roles and "
                "permissions, requesting access, environments and promotion. Use this before "
                "answering any question about using or administering the app, rather than "
                "relying on assumptions. Covers: " + available
            )[:1024],
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The user's question about the app, or a topic name.",
                    }
                },
                "required": ["question"],
            },
        },
    }
