"""Reading and writing apps in `dashboard_views`.

Apps live in the table views always lived in, under the view's own id, so that
`shared_views`, `archived_views`, every `#/view/<id>` and `?shared_view=` link and
every action-log reference keeps pointing at the same thing. `/api/apps` writes
through `save_version` here, so there is one answer to who may change an app and
one shape of row that results.

Every write stores `spec_json` and keeps `widgets_json` equal to the first tab.
That second copy is for rollback: code from before apps reads only
`widgets_json`, so a deployment rolled back after apps shipped still shows each
app's first tab rather than an empty canvas.

The functions take a cursor and leave committing to the caller, so a route can
check, write and commit in one transaction.
"""
import re
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from routes.roles import require_domain_editor
from services import app_spec

# Custom widgets are stored under UUID ids; built-in types (iframe, etc.) have no row.
_CUSTOM_WIDGET_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

HEAD_COLUMNS = (
    "id", "version", "name", "domain", "username", "is_global",
    "widgets_json", "spec_json", "is_locked", "pinned_agent_id", "timestamp",
)


def fetch_rows(c) -> List[Dict[str, Any]]:
    names = [d[0] for d in c.description]
    return [dict(zip(names, row)) for row in c.fetchall()]


def head(c, app_id: str) -> Optional[Dict[str, Any]]:
    """The newest version of an app, or None. Versions are per env, like everything here."""
    c.execute(
        f"SELECT {', '.join(HEAD_COLUMNS)} FROM dashboard_views "
        "WHERE id = %s ORDER BY version DESC LIMIT 1",
        (app_id,),
    )
    row = c.fetchone()
    return dict(zip([d[0] for d in c.description], row)) if row else None


def spec_of(row: Dict[str, Any]) -> Dict[str, Any]:
    return app_spec.read_spec(row.get("id") or "", row.get("spec_json"), row.get("widgets_json"))


def is_subscribed(c, username: str, app_id: str) -> bool:
    c.execute("SELECT 1 FROM shared_views WHERE username = %s AND view_id = %s", (username, app_id))
    return c.fetchone() is not None


def is_archived(c, app_id: str) -> bool:
    c.execute("SELECT 1 FROM archived_views WHERE id = %s", (app_id,))
    return c.fetchone() is not None


def insert_version(
    c,
    *,
    app_id: str,
    version: int,
    name: str,
    domain: Optional[str],
    username: str,
    is_global: bool,
    is_locked: bool,
    pinned_agent_id: Optional[str],
    spec: Dict[str, Any],
) -> None:
    c.execute(
        """
        INSERT INTO dashboard_views
            (id, version, name, domain, username, is_global, widgets_json, spec_json, is_locked, pinned_agent_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            app_id, version, name, domain, username, int(bool(is_global)),
            app_spec.dumps(app_spec.first_tab_widgets(spec)), app_spec.dumps(spec),
            int(bool(is_locked)), pinned_agent_id,
        ),
    )


# Arranging a view is a burst of saves (every drag, resize, tab rename and
# setting is a full PUT), and each used to be a version, so a view's history was
# mostly noise. A save to a personal app within this long of its last one
# replaces that version instead. Global apps keep one version per save: their
# versions are what View Promotion copies and rolls back to, several editors
# share them, and their rows don't record which editor saved.
COALESCE_SECONDS = 300


def replace_recent_version(
    c,
    *,
    app_id: str,
    version: int,
    name: str,
    domain: Optional[str],
    username: str,
    is_locked: bool,
    pinned_agent_id: Optional[str],
    spec: Dict[str, Any],
) -> bool:
    """Overwrite `version` if it is personal and saved within the window; say whether it was.

    The age is judged by the database's clock, which wrote the timestamp.
    """
    c.execute(
        """
        UPDATE dashboard_views
        SET name = %s, domain = %s, username = %s, widgets_json = %s, spec_json = %s,
            is_locked = %s, pinned_agent_id = %s, timestamp = CURRENT_TIMESTAMP
        WHERE id = %s AND version = %s AND is_global = 0
          AND timestamp > CURRENT_TIMESTAMP - make_interval(secs => %s)
        """,
        (
            name, domain, username, app_spec.dumps(app_spec.first_tab_widgets(spec)), app_spec.dumps(spec),
            int(bool(is_locked)), pinned_agent_id, app_id, version, COALESCE_SECONDS,
        ),
    )
    return c.rowcount == 1


def is_custom_widget(widget_id: Any) -> bool:
    return isinstance(widget_id, str) and bool(_CUSTOM_WIDGET_ID.match(widget_id))


def custom_widget_ids(spec: Dict[str, Any]) -> List[str]:
    """The stored widgets an app places, each once, sorted; built-in types have no row."""
    ids, _ = app_spec.placed_widgets(spec)
    return sorted(i for i in ids if is_custom_widget(i))


def widget_heads(c, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """The current (newest live) version of each widget that exists, by id."""
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


def require_certified_widgets(c, spec: Dict[str, Any], env: str) -> None:
    """Block a global app holding widgets nobody has certified, when configured to.

    A global app is the one place in this app where one person's work lands on
    everyone else's screen without them choosing it, so it is the place worth
    gating on review. Off by default — see the setting's own note: certification
    happens during promotion to production, so requiring it everywhere would make
    global apps impossible to create in dev and test.

    Every tab counts. Checking only the first would let an uncertified widget onto
    everyone's screen one tab over.

    Only widgets present in the `widgets` table are considered. Built-in widget
    types ship with the app and are reviewed by the act of being in the repo;
    they have no row here and are not something an author can introduce.
    """
    from services.settings_store import get_bool_setting

    if not get_bool_setting("require_certified_for_global_views"):
        return

    ids = custom_widget_ids(spec)
    if not ids:
        return

    heads = widget_heads(c, ids)
    uncertified: List[str] = [
        heads[wid]["name"] if wid in heads else f"unknown widget ({wid})"
        for wid in ids
        if not (wid in heads and heads[wid]["is_certified"])
    ]

    if uncertified:
        raise HTTPException(
            status_code=400,
            detail=(
                "A view shared with everyone may only contain certified widgets. "
                f"Not yet certified: {', '.join(sorted(uncertified))}."
            ),
        )


def require_may_edit(w, env: str, existing: Dict[str, Any], username: str) -> None:
    """Personal apps by their owner, global ones by an editor of their domain."""
    if existing["is_global"]:
        require_domain_editor(w, existing.get("domain") or "General", env)
    elif existing["username"] != username:
        raise HTTPException(status_code=403, detail="You can only edit your own views")


def save_version(
    c,
    w,
    env: str,
    app_id: str,
    username: str,
    *,
    name: Optional[str] = None,
    domain: Optional[str] = None,
    is_global: Optional[bool] = None,
    is_locked: Optional[bool] = None,
    pinned_agent_id: Optional[str] = None,
    spec: Optional[Dict[str, Any]] = None,
) -> int:
    """Write the next version of an app, or fold the save into a recent personal
    one (`COALESCE_SECONDS`), and return the version it landed in. Raises HTTPException.

    Fields left as None keep their current value; `spec` replaces the whole spec.
    """
    existing = head(c, app_id)
    if not existing:
        raise HTTPException(status_code=404, detail="View not found")
    require_may_edit(w, env, existing, username)

    new_name = name if name is not None else existing["name"]
    new_domain = domain if domain is not None else existing["domain"]
    new_global = is_global if is_global is not None else bool(existing["is_global"])
    new_locked = is_locked if is_locked is not None else bool(existing["is_locked"])
    new_pin = app_spec.pin_value(pinned_agent_id, existing.get("pinned_agent_id"))

    # The check above was against what the app is now. Making it global, or
    # moving a global app to another domain, puts it in front of that domain's
    # users, which needs the same right as creating it there.
    if new_global and (not existing["is_global"] or (new_domain or "General") != (existing["domain"] or "General")):
        require_domain_editor(w, new_domain or "General", env)

    if spec is not None:
        try:
            new_spec = app_spec.validate_spec(spec, app_id)
        except app_spec.SpecError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        new_spec = spec_of(existing)

    # Checked on update too, and against the resulting spec rather than the
    # submitted one: an app that passed at creation must not become a way to put
    # an uncertified widget in front of everyone by editing it later.
    if new_global:
        require_certified_widgets(c, new_spec, env)

    if not new_global and replace_recent_version(
        c,
        app_id=app_id,
        version=existing["version"],
        name=new_name,
        domain=new_domain,
        username=username,
        is_locked=new_locked,
        pinned_agent_id=new_pin,
        spec=new_spec,
    ):
        return existing["version"]

    new_version = existing["version"] + 1
    insert_version(
        c,
        app_id=app_id,
        version=new_version,
        name=new_name,
        domain=new_domain,
        username="system" if new_global else username,
        is_global=new_global,
        is_locked=new_locked,
        pinned_agent_id=new_pin,
        spec=new_spec,
    )
    return new_version
