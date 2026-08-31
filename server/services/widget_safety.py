"""What a widget may contain, checked when it is saved rather than when it runs.

Widget code is written by a model from a natural-language prompt, and can also
be typed into the editor or imported from a file. The generation contract in
`routes/agent_instructions.md` already forbids most of what is checked here, but
a prompt is advice: it does not apply to hand-edited or imported code, and a
model that ignores it produces a widget nobody notices is unusual until it is on
someone's dashboard. This module is the enforcement, and it runs on every path
that writes to the `widgets` table.

Two things worth knowing before changing it:

  * **Comments are stripped with a scanner, not a regex.** A naive `//.*$` sweep
    deletes the rest of the line from inside `'https://cdn.jsdelivr.net/...'`,
    which is how a checker like this ends up reporting nonsense about the most
    common line in a charting widget. `_scan` tracks string, template and comment
    state in one pass so neither can be mistaken for the other.
  * **The host allowlist is duplicated in `src/hooks/useScript.ts`.** The runtime
    refuses to load an off-allowlist script and this refuses to store one; the
    two must agree, or an author is told their widget saved and then watches it
    fail to load. Same arrangement as `creator_stats.py` and `creators.ts`.
"""

from __future__ import annotations

import re
from typing import List, Set, Tuple

#: Hosts a widget may reference. Keep in step with ALLOWED_SCRIPT_HOSTS in
#: `src/hooks/useScript.ts` and the CDN rule in `routes/agent_instructions.md`.
ALLOWED_HOSTS = frozenset({
    "cdn.jsdelivr.net",
    "code.highcharts.com",
    "unpkg.com",
    "cdnjs.cloudflare.com",
})

#: Constructs that execute text as code or write markup straight into the DOM.
#: Each maps to what the author should do instead, because a refusal that does
#: not say what to do next just gets worked around.
BANNED_CONSTRUCTS: Tuple[Tuple[str, str], ...] = (
    ("eval(", "Evaluates text as code. Compute the value in the component instead."),
    ("new Function(", "Compiles text into code. Write the function directly."),
    ("document.write(", "Rewrites the whole document. Render through React instead."),
    (".innerHTML", "Injects unescaped markup. Render the value as JSX text instead."),
    ("dangerouslySetInnerHTML", "Injects unescaped markup. Render the value as JSX text instead."),
    ("importScripts(", "Loads code outside the runtime's control. Use useScript() instead."),
)

_URL = re.compile(r"https?://([^/\s'\"`)]+)", re.IGNORECASE)


def _scan(code: str) -> Tuple[str, List[str]]:
    """`(code with comments and string bodies blanked, string literals found)`.

    One pass, because the states are mutually exclusive: a `//` inside a string
    starts no comment, and a quote inside a comment starts no string.
    """
    out: List[str] = []
    literals: List[str] = []
    i, n = 0, len(code or "")
    quote = ""          # active string delimiter, "" when not in a string
    current: List[str] = []
    comment = ""        # "line" | "block" | ""

    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ""

        if comment == "line":
            if ch == "\n":
                comment = ""
                out.append(ch)
            i += 1
            continue
        if comment == "block":
            if ch == "*" and nxt == "/":
                comment = ""
                i += 2
                continue
            i += 1
            continue

        if quote:
            if ch == "\\":
                current.append(code[i:i + 2])
                i += 2
                continue
            if ch == quote:
                literals.append("".join(current))
                current = []
                quote = ""
                out.append(" ")
                i += 1
                continue
            current.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "/":
            comment = "line"
            i += 2
            continue
        if ch == "/" and nxt == "*":
            comment = "block"
            i += 2
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue

        out.append(ch)
        i += 1

    if current:
        literals.append("".join(current))
    return "".join(out), literals


def offending_hosts(code: str) -> Set[str]:
    """Hosts referenced by absolute URLs in the code that are not allowlisted.

    Deliberately covers every absolute URL rather than only `useScript` calls:
    a widget that `fetch`es map topology from a CDN is doing the same thing as
    one that loads a script from it, and relative `/api/...` paths — which is how
    a widget is supposed to reach its own backend — have no host to object to.
    """
    _, literals = _scan(code)
    found: Set[str] = set()
    for literal in literals:
        for match in _URL.finditer(literal):
            host = match.group(1).split("@")[-1].split(":")[0].lower()
            if host and host not in ALLOWED_HOSTS:
                found.add(host)
    return found


def review_widget_code(code: str) -> List[str]:
    """Blocking problems with a widget's TSX. Empty means it may be stored."""
    problems: List[str] = []
    if not (code or "").strip():
        return problems

    stripped, _ = _scan(code)
    lowered = stripped.lower()
    for construct, advice in BANNED_CONSTRUCTS:
        if construct.lower() in lowered:
            problems.append(f"`{construct}` is not allowed in widget code. {advice}")

    hosts = offending_hosts(code)
    if hosts:
        problems.append(
            "Widgets may only reach this app (a relative /api/... path) or an approved CDN "
            f"({', '.join(sorted(ALLOWED_HOSTS))}). Found: {', '.join(sorted(hosts))}."
        )
    return problems


def review_widget(
    code: str,
    data_source: str = "",
    data_source_type: str = "none",
    is_executable: bool = False,
) -> List[str]:
    """Every blocking problem with a widget about to be stored.

    The data-source rule is the one that matters most for audit: a SQL source
    that writes turns the widget into something that changes data, and only an
    executable widget routes its controls through the confirmation prompt that
    records who approved the change and why. Publishing a writing widget that is
    not executable would produce exactly the untracked modification the
    confirmation exists to prevent.
    """
    problems = review_widget_code(code)

    if (data_source_type or "").lower() == "sql" and (data_source or "").strip() and not is_executable:
        from services.sql_safety import classify_statement

        kind, verb = classify_statement(data_source)
        if kind == "write":
            problems.append(
                f"This widget's SQL data source changes data"
                + (f" (`{verb.upper()}`)" if verb else "")
                + ". Tick \"Executable\" so its controls require a confirmation and a written "
                  "reason, which is what records who made the change."
            )
    return problems
