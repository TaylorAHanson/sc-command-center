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
  * **Script hosts stay in step with `src/hooks/useScript.ts`.** The runtime
    refuses to load an off-allowlist script and this refuses to store one; the
    two must agree, or an author is told their widget saved and then watches it
    fail to load. Same arrangement as `creator_stats.py` and `creators.ts`.
    Reach is a little wider: a widget may also name a Databricks App an admin
    has listed (`widget_app_hosts` in `settings_store`), so it can embed or call
    it. An entry is one app's host or one workspace (`*-<workspace-id>.…`), never
    a `*.databricksapps.com` wildcard, because that domain is shared by every
    Databricks customer. They are not script
    sources — `useScript` and CSP `script-src` still refuse them. The list is
    read at review time, so changing it needs no redeploy.
"""

from __future__ import annotations

import re
from typing import FrozenSet, Iterable, List, Optional, Set, Tuple

#: CDN hosts a widget may load a library from. Keep in step with
#: ALLOWED_SCRIPT_HOSTS in `src/hooks/useScript.ts` and the CDN rule in
#: `routes/agent_instructions.md`.
ALLOWED_HOSTS = frozenset({
    "cdn.jsdelivr.net",
    "code.highcharts.com",
    "unpkg.com",
    "cdnjs.cloudflare.com",
})

_DATABRICKS_APP_SUFFIX = ".databricksapps.com"


def approved_app_hosts() -> FrozenSet[str]:
    """Databricks Apps an admin has listed. Empty if the setting can't be read:
    a failure must narrow what widgets may reach, never widen it."""
    try:
        from services.settings_store import get_host_list_setting

        return frozenset(get_host_list_setting("widget_app_hosts"))
    except Exception:  # noqa: BLE001
        return frozenset()


def _resolve(app_hosts: Optional[Iterable[str]]) -> FrozenSet[str]:
    if app_hosts is None:
        return approved_app_hosts()
    return frozenset(h.lower() for h in app_hosts)


_APP_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def _in_workspace(host: str, pattern: str) -> bool:
    """`host` is one app in the workspace `*-<id>.<region>.databricksapps.com`.

    The app name must be a single label: Databricks puts the workspace ID last
    in the first label, so another workspace's app named `x-<our id>` gets a
    host ending in its own ID, and a dot before the name is not an app at all.
    """
    tail = pattern[1:]
    if not host.endswith(tail):
        return False
    return bool(_APP_NAME.match(host[: -len(tail)]))


def host_is_allowed(host: str, app_hosts: Optional[Iterable[str]] = None) -> bool:
    """Whether an absolute-URL host may appear in stored widget code."""
    name = (host or "").lower()
    if not name:
        return False
    if name in ALLOWED_HOSTS:
        return True
    approved = _resolve(app_hosts)
    if name in approved:
        return True
    return any(p.startswith("*-") and _in_workspace(name, p) for p in approved)


def csp_app_hosts(app_hosts: Optional[Iterable[str]] = None) -> List[str]:
    """The approved apps the CSP can name. A host-source wildcard replaces whole
    leftmost labels, so `*-<id>.…` has no CSP form: workspace entries are left
    out, which still lets them be framed (`frame-src https:`) but not fetched."""
    return sorted(h for h in _resolve(app_hosts) if "*" not in h)


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

# The host ends where a browser's URL parser ends it. A backslash counts: the
# parser treats it as `/`, so `https://evil.example\@cdn.jsdelivr.net` goes to
# evil.example, and reading on to the `@` would approve it. A raw `\` also
# starts any JS escape (`\u0040` is `@`), which ends the host the same way.
_URL = re.compile(r"https?://([^/\\?#\s'\"`)]+)", re.IGNORECASE)


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


def offending_hosts(code: str, app_hosts: Optional[Iterable[str]] = None) -> Set[str]:
    """Hosts referenced by absolute URLs in the code that are not allowlisted.

    Deliberately covers every absolute URL rather than only `useScript` calls:
    a widget that `fetch`es map topology from a CDN is doing the same thing as
    one that loads a script from it, and relative `/api/...` paths — which is how
    a widget is supposed to reach its own backend — have no host to object to.
    """
    approved = _resolve(app_hosts)
    _, literals = _scan(code)
    found: Set[str] = set()
    for literal in literals:
        for match in _URL.finditer(literal):
            host = match.group(1).split("@")[-1].split(":")[0].lower()
            if host and not host_is_allowed(host, approved):
                found.add(host)
    return found


def _reach_refusal(hosts: Set[str], app_hosts: FrozenSet[str]) -> str:
    message = (
        "Widgets may only reach this app (a relative /api/... path), an approved CDN "
        f"({', '.join(sorted(ALLOWED_HOSTS))})"
    )
    if app_hosts:
        message += f", or an approved Databricks App ({', '.join(sorted(app_hosts))})"
    message += f". Found: {', '.join(sorted(hosts))}."
    if any(h.endswith(_DATABRICKS_APP_SUFFIX) for h in hosts):
        message += (" A global admin can approve a Databricks App under Admin Panel → Settings"
                    " → Databricks Apps widgets may embed or call.")
    return message


def review_widget_code(code: str, app_hosts: Optional[Iterable[str]] = None) -> List[str]:
    """Blocking problems with a widget's TSX. Empty means it may be stored."""
    problems: List[str] = []
    if not (code or "").strip():
        return problems

    approved = _resolve(app_hosts)

    stripped, _ = _scan(code)
    lowered = stripped.lower()
    for construct, advice in BANNED_CONSTRUCTS:
        if construct.lower() in lowered:
            problems.append(f"`{construct}` is not allowed in widget code. {advice}")

    hosts = offending_hosts(code, approved)
    if hosts:
        problems.append(_reach_refusal(hosts, approved))
    return problems


def review_widget(
    code: str,
    data_source: str = "",
    data_source_type: str = "none",
    is_executable: bool = False,
    app_hosts: Optional[Iterable[str]] = None,
) -> List[str]:
    """Every blocking problem with a widget about to be stored.

    The data-source rule is the one that matters most for audit: a SQL source
    that writes turns the widget into something that changes data, and only an
    executable widget routes its controls through the confirmation prompt that
    records who approved the change and why. Publishing a writing widget that is
    not executable would produce exactly the untracked modification the
    confirmation exists to prevent.
    """
    problems = review_widget_code(code, app_hosts=app_hosts)

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
