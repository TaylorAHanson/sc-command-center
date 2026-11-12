"""Tests for the sidebar's list, `GET /api/apps/` (services/working_set.py).

The catalog's own answer (`view_signals.home`) is faked, and so are the content
and settings connections, to pin what the list adds and what it promises:

- light rows only: never a spec, and a payload bounded by the list caps however
  many views the deployment holds;
- a manager sees their draft's name; an archived view leaves at once; a view
  the caller closed stays out of Recent until they open it again;
- until the catalog has finished its first build, or when it can't be read,
  My views still lists the caller's own views, from the source tables;
- everything read is the caller's own.
"""
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from fastapi import HTTPException
    from routes import apps
    from services import access, view_catalog, view_signals, working_set
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_apps_list: {e}")
    sys.exit(0)

ME = access.Caller("Ana@Example.com", ("planners",), False)
OTHER = "bob@example.com"
T0 = datetime(2026, 11, 1, 9, 0)
MANAGE, USE = access.MANAGE, access.USE
KEYS = {"favorites", "favorites_total", "recent", "mine", "mine_total", "new_for_you_count"}


def light(i, *, access_=USE, owner=OTHER, name=None, updated=T0, state=None, favorite=False, description=""):
    """A row as `view_catalog.light` gives it, extras and all."""
    out = {
        "id": i, "link": f"#/app/{i}", "ref": i, "name": name or i.title(), "description": description,
        "owner": owner, "domain": "Finance", "presentation": "workspace", "updated_at": view_catalog.iso(updated),
        "published_at": view_catalog.iso(T0), "viewers_30d": 12, "trend": 0.5, "favorites": 3, "featured": False,
        "featured_position": None, "certified": False, "access": access_, "favorite": favorite, "hidden": False,
        "last_opened_at": view_catalog.iso(T0),
    }
    if state:
        out["state"] = state
    return out


def home(favorites=(), recent=(), mine=(), mine_total=None, new=0):
    return {"favorites": list(favorites), "recent": list(recent), "mine": list(mine),
            "mine_total": len(mine) if mine_total is None else mine_total, "new_for_you_count": new}


class Db:
    """The content and settings schemas, as far as the list reads them."""

    def __init__(self, *, built=True, drafts=None, archived=(), hidden=(), visits=(), favorites=0, grants=(),
                 heads=None, links=None):
        self.built = built
        self.drafts = dict(drafts or {})  # id -> (name, domain, updated_at)
        self.archived = set(archived)
        self.hidden = dict(hidden)  # (username, id) -> closed at
        self.visits = dict(visits)  # (lowercased username, id) -> last opened at
        self.favorites = favorites
        self.grants = list(grants)  # (id, lowercased username, level)
        self.heads = dict(heads or {})  # id -> (name, domain, timestamp)
        self.links = dict(links or {})
        self.statements = []
        self.connections = []

    def conn(self):
        c = FakeConn(self)
        self.connections.append(c)
        return c


class FakeCursor:
    def __init__(self, db):
        self.db, self.description, self._rows = db, None, []

    def _answer(self, columns, rows):
        self.description = [(c,) for c in columns]
        self._rows = [tuple(r) for r in rows]

    def execute(self, sql, params=None):
        db, text = self.db, " ".join(sql.split())
        db.statements.append((text, params))
        if "FROM view_catalog_state" in text:
            self._answer(("value",), [({"built_at": "2026-11-01T09:00:00"} if db.built else {"status": "building"},)])
        elif "FROM object_drafts" in text:
            wanted = params[1]
            self._answer(("id", "name", "domain", "updated_at"),
                         [(i, *d) for i, d in db.drafts.items() if i in wanted])
        elif text.startswith("SELECT id FROM archived_views WHERE id = ANY"):
            self._answer(("id",), [(i,) for i in params[0] if i in db.archived])
        elif "FROM sidebar_hidden h" in text:
            closed = [i for (user, i), at in db.hidden.items()
                      if user == params["user"] and i in params["ids"]
                      and not db.visits.get((params["me"], i), datetime.min) > at]
            self._answer(("app_id",), [(i,) for i in closed])
        elif "COUNT(*) FROM user_favorites" in text:
            self._answer(("n",), [(db.favorites,)])
        elif "FROM object_permissions" in text:
            _type, _ptype, me, level = params
            self._answer(("object_id",), [(i,) for i, user, lvl in db.grants if user == me and lvl == level])
        elif "FROM dashboard_views dv" in text:
            self._answer(("id", "name", "domain", "updated_at"),
                         [(i, *h) for i, h in db.heads.items() if i in params[0]])
        elif "FROM app_links" in text:
            self._answer(("app_id", "slug"), [(i, s) for i, s in db.links.items() if i in params[0]])
        else:
            raise AssertionError(f"unexpected statement: {text[:160]}")

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, db):
        self.db, self.closed = db, False

    def cursor(self):
        return FakeCursor(self.db)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class patched:
    def __init__(self, *triples):
        self.triples, self.saved = triples, []

    def __enter__(self):
        for mod, name, value in self.triples:
            self.saved.append((mod, name, getattr(mod, name)))
            setattr(mod, name, value)
        return self

    def __exit__(self, *exc):
        for mod, name, value in reversed(self.saved):
            setattr(mod, name, value)


def facts_from(acl):
    """`access.acl_facts` over {id: {principal: level}}."""
    def facts(object_type, ids):
        assert object_type == access.APP
        out = {}
        for i in ids:
            if i not in acl:
                continue
            entries = [{"principal": p, "principal_type": "all" if p == "*" else "user", "level": lvl}
                       for p, lvl in acl[i].items()]
            owner = next((p for p, lvl in acl[i].items() if p != "*" and lvl == MANAGE), None)
            out[i] = {"owner": owner, "sharing": access.summary_of(entries, owner)}
        return out
    return facts


def read(db, answer=None, *, ready=True, acl=None, who=ME, home_raises=False):
    """`working_set.read` with the catalog's answer, both schemas and the access list faked."""
    asked = []

    def fake_home(caller):
        asked.append(caller)
        if home_raises:
            raise RuntimeError("view_catalog is locked")
        return answer if answer is not None else home()

    with patched((view_catalog, "_ready", ready), (working_set, "_built", False),
                 (view_signals, "home", fake_home), (view_catalog, "_content", db.conn),
                 (view_catalog, "_settings", db.conn), (access, "acl_facts", facts_from(acl or {}))):
        out = working_set.read(who)
    assert all(c.closed for c in db.connections), "every connection is given back"
    return out, asked


def ids(rows):
    return [r["id"] for r in rows]


# ---------------------------------------------------------------- light rows

def test_the_list_is_light_rows_and_never_a_spec():
    db = Db()
    answer = home(favorites=[light("fav", favorite=True)], recent=[light("seen")],
                  mine=[light("own", access_=MANAGE, owner=ME.username, state="published")], new=4)
    out, asked = read(db, answer, acl={"own": {ME.username: MANAGE}, "seen": {OTHER: MANAGE, "*": USE}})
    assert set(out) == KEYS and asked == [ME]
    for row in out["favorites"] + out["recent"] + out["mine"]:
        assert set(row) <= set(working_set.FIELDS) | {"sharing"}, set(row)
        assert "spec" not in row and "description" not in row and "viewers_30d" not in row
    assert (out["new_for_you_count"], out["mine_total"]) == (4, 1)
    assert out["favorites"][0]["favorite"] is True and out["mine"][0]["state"] == "published"
    assert out["recent"][0]["sharing"] == "everyone" and out["mine"][0]["sharing"] == "private"


def test_the_payload_stays_small_however_many_views_the_deployment_holds():
    long = "A view with a long and descriptive name that someone typed in full " * 2
    answer = home(
        favorites=[light(f"fav-{n:04d}", name=long, description="x" * 4000, favorite=True)
                   for n in range(view_signals.HOME_FAVORITES)],
        recent=[light(f"seen-{n:04d}", name=long, description="x" * 4000) for n in range(view_signals.HOME_RECENT)],
        mine=[light(f"own-{n:04d}", access_=MANAGE, owner=ME.username, name=long, state="draft_only")
              for n in range(view_signals.HOME_MINE)],
        mine_total=10_000, new=9_000)
    db = Db()
    out, _ = read(db, answer)
    size = len(json.dumps(out))
    assert size < 50_000, size
    assert out["mine_total"] == 10_000 and len(out["mine"]) == view_signals.HOME_MINE
    assert not any("dashboard_views" in s for s, _ in db.statements), "the list never reads every view"


def test_with_the_catalog_still_building_my_views_are_capped_too():
    many = [(f"own-{n:05d}", ME.username.lower(), MANAGE) for n in range(5_000)]
    db = Db(built=False, grants=many, heads={i: (f"View {i}", "Finance", T0 + timedelta(minutes=n))
                                             for n, (i, _, _) in enumerate(many)})
    out, _ = read(db, acl={i: {ME.username: MANAGE} for i, _, _ in many})
    assert len(out["mine"]) == view_signals.HOME_MINE and out["mine_total"] == 5_000
    assert out["mine"][0]["id"] == "own-04999", "newest change first"
    assert len(json.dumps(out)) < 50_000


# ---------------------------------------------------------- what it corrects

def test_a_manager_sees_their_draft_name_and_it_orders_my_views():
    later = T0 + timedelta(days=2)
    answer = home(
        mine=[light("older", access_=MANAGE, owner=ME.username, name="Older", updated=T0 + timedelta(days=1)),
              light("live", access_=MANAGE, owner=ME.username, name="Live", state="published_with_draft")],
        recent=[light("theirs", name="Theirs")])
    db = Db(drafts={"live": ("Halfway", "Supply", later), "theirs": ("Their draft", "HR", later)})
    out, _ = read(db, answer)
    assert ids(out["mine"]) == ["live", "older"], "the draft saved since is the newest change"
    assert (out["mine"][0]["name"], out["mine"][0]["domain"]) == ("Halfway", "Supply")
    assert out["recent"][0]["name"] == "Theirs", "someone who can only use a view never sees its draft"
    drafts_read = [p for s, p in db.statements if "FROM object_drafts" in s]
    assert drafts_read == [(access.APP, ["older", "live"])], "only managed rows are looked up"


def test_an_archived_view_leaves_at_once():
    answer = home(favorites=[light("gone", favorite=True)], recent=[light("gone"), light("kept")],
                  mine=[light("gone", access_=MANAGE, owner=ME.username),
                        light("mine", access_=MANAGE, owner=ME.username)], mine_total=7)
    out, _ = read(Db(archived={"gone"}), answer)
    assert ids(out["favorites"]) == [] and ids(out["recent"]) == ["kept"] and ids(out["mine"]) == ["mine"]
    assert out["mine_total"] == 6


def test_a_closed_view_stays_out_of_recent_until_it_is_opened_again():
    answer = home(recent=[light("closed"), light("reopened"), light("open")],
                  favorites=[light("closed", favorite=True)])
    db = Db(hidden={(ME.username, "closed"): T0 + timedelta(hours=1), (ME.username, "reopened"): T0},
            visits={("ana@example.com", "closed"): T0, ("ana@example.com", "reopened"): T0 + timedelta(hours=1)})
    out, _ = read(db, answer)
    assert ids(out["recent"]) == ["reopened", "open"]
    assert ids(out["favorites"]) == ["closed"], "closing takes a view out of Recent, not out of Favorites"
    [(_sql, params)] = [(s, p) for s, p in db.statements if "sidebar_hidden" in s]
    assert params["user"] == ME.username and params["me"] == "ana@example.com"


def test_state_is_only_told_to_managers():
    answer = home(recent=[light("used", state="published_with_draft"),
                          light("managed", access_=MANAGE, state="published_with_draft")])
    out, _ = read(Db(), answer)
    by_id = {r["id"]: r for r in out["recent"]}
    assert "state" not in by_id["used"] and by_id["managed"]["state"] == "published_with_draft"


def test_favorites_total_counts_every_favorite_not_just_those_shown():
    answer = home(favorites=[light(f"f{n}", favorite=True) for n in range(view_signals.HOME_FAVORITES)])
    out, _ = read(Db(favorites=40), answer)
    assert out["favorites_total"] == 40 and len(out["favorites"]) == view_signals.HOME_FAVORITES


# --------------------------------------------------- before the catalog is built

def test_until_the_catalog_is_built_my_views_come_from_the_source_tables():
    me = ME.username.lower()
    db = Db(built=False,
            grants=[("own", me, MANAGE), ("draft", me, MANAGE), ("given", me, MANAGE), ("shelved", me, MANAGE),
                    ("used", me, USE)],
            heads={"own": ("Own", "Finance", T0), "given": ("Given", "HR", T0), "shelved": ("Shelved", "HR", T0)},
            drafts={"draft": ("Sketch", "Supply", T0 + timedelta(hours=2))},
            archived={"shelved"}, links={"own": "own-view"})
    acl = {"own": {ME.username: MANAGE}, "draft": {ME.username: MANAGE}, "shelved": {ME.username: MANAGE},
           "given": {OTHER: MANAGE, ME.username: MANAGE}, "used": {OTHER: MANAGE, ME.username: USE}}
    out, _ = read(db, home(favorites=[light("fav", favorite=True)]), acl=acl)
    assert ids(out["mine"]) == ["draft", "own"], "own views only: not one merely managed, archived or used"
    draft, own = out["mine"]
    assert (draft["name"], draft["state"], draft["ref"]) == ("Sketch", "draft_only", "draft")
    assert (own["ref"], own["state"], own["access"]) == ("own-view", "published", MANAGE)
    assert ids(out["favorites"]) == ["fav"], "what the catalog does know is still shown"
    assert out["mine_total"] == 2


def test_the_build_is_asked_about_once_it_has_finished():
    db = Db()
    with patched((view_catalog, "_ready", True), (working_set, "_built", False),
                 (view_signals, "home", lambda who: home()), (view_catalog, "_content", db.conn),
                 (access, "acl_facts", facts_from({}))):
        working_set.read(ME)
        working_set.read(ME)
    assert sum("view_catalog_state" in s for s, _ in db.statements) == 1


def test_when_the_catalog_cant_be_read_my_views_still_list():
    me = ME.username.lower()
    for ready, raises in ((False, False), (True, True)):
        db = Db(grants=[("own", me, MANAGE)], heads={"own": ("Own", "Finance", T0)})
        out, asked = read(db, ready=ready, home_raises=raises, acl={"own": {ME.username: MANAGE}})
        assert ids(out["mine"]) == ["own"] and out["favorites"] == [] and out["recent"] == []
        assert asked == ([] if not ready else [ME])
        if not ready:
            touched = " ".join(s for s, _ in db.statements)
            for table in ("view_catalog_state", "sidebar_hidden", "user_favorites"):
                assert table not in touched, f"{table} may not exist yet"


# ---------------------------------------------------------- whose list it is

def test_nobody_in_particular_has_no_views_of_their_own():
    db = Db(built=False, grants=[("own", "", MANAGE)])
    out, _ = read(db, who=access.Caller("", (), False))
    assert out["mine"] == [] and not any("object_permissions" in s for s, _ in db.statements)


def test_nothing_at_all_is_an_empty_sidebar():
    db = Db()
    out, _ = read(db)
    assert out == {"favorites": [], "favorites_total": 0, "recent": [], "mine": [], "mine_total": 0,
                   "new_for_you_count": 0}
    assert not any("archived_views" in s for s, _ in db.statements)


def test_the_route_lists_the_callers_working_set():
    seen = []

    def fake_read(who):
        seen.append(who)
        return {"mine": [], "recent": []}

    with patched((access, "caller", lambda w: ME), (working_set, "read", fake_read)):
        assert apps.list_apps(w=None) == {"mine": [], "recent": []}
    assert seen == [ME]


def test_a_list_that_cant_be_read_is_an_error_not_an_empty_sidebar():
    def broken(who):
        raise RuntimeError("connection refused")

    with patched((access, "caller", lambda w: ME), (working_set, "read", broken)):
        try:
            apps.list_apps(w=None)
        except HTTPException as exc:
            assert exc.status_code == 500 and "connection refused" in exc.detail
        else:
            raise AssertionError("an unreadable list was answered")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} passed")
