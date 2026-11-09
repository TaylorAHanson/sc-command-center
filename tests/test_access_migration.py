"""Tests for turning role mappings into access lists at the cutover.

The promise is that the day sharing arrives, the same people keep the same
access. What is pinned here is each old rule as the code enforced it — which
mapping counted as global, that domains matched exactly, that personal views and
agents never followed a domain — and what the report tells an admin changed.
The SQL needs a database and is exercised by hand, not here.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from services import access_migration as am
    from services import consolidation as cons
    from services.access import AGENT, ALL, APP, EVERYONE, GROUP, MANAGE, USE, USER, WIDGET
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_access_migration: {e}")
    sys.exit(0)


def mapping(principal, domain, level):
    return am.Mapping(principal, domain, level)


def grants(obj, *mappings):
    return {k: (e["principal_type"], e["level"]) for k, e in am.grants_for(obj, am.by_domain(mappings)).items()}


def widget(object_id="w1", domain="Supply", created_by="maker@x.com"):
    return {"object_type": WIDGET, "object_id": object_id, "domain": domain, "created_by": created_by}


def view(object_id="v1", domain="Supply", is_global=1, username="system"):
    return {"object_type": APP, "object_id": object_id, "domain": domain, "is_global": is_global, "username": username}


def agent(object_id="a1", visibility="domain", domain="Supply", username="maker@x.com"):
    return {"object_type": AGENT, "object_id": object_id, "visibility": visibility, "domain": domain,
            "username": username}


# ------------------------------------------------------------------ levels and principals

def test_viewer_uses_editor_and_admin_manage():
    assert am.level_of("viewer") == USE
    assert am.level_of("Editor") == MANAGE
    assert am.level_of("admin") == MANAGE
    assert am.level_of("owner") is None and am.level_of(None) is None


def test_unusable_mapping_rows_are_dropped():
    rows = [("planners", "Supply", "viewer"), ("", "Supply", "viewer"), ("x", "Supply", "superuser"),
            {"external_role": "ops", "domain": "Ops", "permission_level": "EDITOR"}]
    assert am.mappings_from(rows) == [mapping("planners", "Supply", "viewer"), mapping("ops", "Ops", "editor")]


def test_only_a_global_alias_at_admin_makes_an_app_admin():
    ms = [mapping("cc-admins", "Global", "admin"), mapping("ops@x.com", "all", "admin"),
          mapping("leads", "Supply", "admin"), mapping("readers", "Global", "viewer")]
    assert am.admins_from(ms) == [("cc-admins", GROUP), ("ops@x.com", USER)]


def test_principal_types_are_inferred():
    g = grants(widget(), mapping("planners", "Supply", "viewer"), mapping("p@x.com", "Supply", "editor"),
               mapping("8f3c2a1e-1111-2222-3333-444455556666", "Supply", "viewer"))
    assert g["planners"] == (GROUP, USE)
    assert g["p@x.com"] == (USER, MANAGE)
    assert g["8f3c2a1e-1111-2222-3333-444455556666"] == (USER, USE)


# ------------------------------------------------------------------ the old rules

def test_a_widget_follows_its_domain_and_its_maker_manages_it():
    g = grants(widget(), mapping("planners", "Supply", "viewer"), mapping("ops", "Ops", "editor"))
    assert g == {"planners": (GROUP, USE), "maker@x.com": (USER, MANAGE)}


def test_an_unset_domain_is_general():
    g = grants(widget(domain=None, created_by="system"), mapping("everyone-ish", "General", "viewer"))
    assert g == {"everyone-ish": (GROUP, USE)}


def test_domains_match_exactly_as_they_did():
    # `domain in domain_permissions` was a dict lookup: "supply" never matched "Supply".
    assert grants(widget(created_by=""), mapping("planners", "supply", "viewer")) == {}


def test_a_placeholder_creator_is_not_an_owner():
    for nobody in ("", "system", "unknown", "dev", None):
        assert grants(widget(created_by=nobody)) == {}


def test_global_views_follow_their_domain_and_record_no_owner():
    g = grants(view(), mapping("planners", "Supply", "viewer"))
    assert g == {"planners": (GROUP, USE)}


def test_personal_views_never_followed_a_domain():
    g = grants(view(is_global=0, username="me@x.com"), mapping("planners", "Supply", "editor"))
    assert g == {"me@x.com": (USER, MANAGE)}


def test_domain_agents_follow_their_domain_and_their_owner_manages():
    g = grants(agent(), mapping("planners", "Supply", "viewer"))
    assert g == {"planners": (GROUP, USE), "maker@x.com": (USER, MANAGE)}


def test_personal_agents_are_their_owners_alone():
    assert grants(agent(visibility="personal"), mapping("planners", "Supply", "editor")) == {
        "maker@x.com": (USER, MANAGE)}


def test_global_agents_are_for_everyone_and_managed_by_admins_only():
    g = grants(agent(visibility="global"), mapping("planners", "Supply", "editor"))
    assert g == {EVERYONE: (ALL, USE)}


def test_global_admins_are_not_listed_on_every_global_item():
    # They manage everything as admins; on each list they would only be noise.
    assert grants(widget(domain="Global", created_by=""), mapping("cc-admins", "Global", "admin")) == {}


def test_a_global_alias_below_admin_still_covers_only_its_literal_domain():
    m = mapping("readers", "Global", "viewer")
    assert grants(widget(domain="Supply", created_by=""), m) == {}
    assert grants(widget(domain="Global", created_by=""), m) == {"readers": (GROUP, USE)}


def test_subscribers_keep_the_views_they_had_and_owners_keep_manage():
    objects = [view(is_global=0, username="me@x.com")]
    subs = [("friend@x.com", "v1"), ("me@x.com", "v1"), ("system", "v1"), ("", "v1")]
    out = am.all_grants(objects, [], subs)
    levels = {k: e["level"] for k, e in out[(APP, "v1")].items()}
    assert levels == {"me@x.com": MANAGE, "friend@x.com": USE}


def test_an_id_filed_differently_in_two_stores_gets_both_and_the_higher_level():
    prod = widget(domain="Supply", created_by="")
    dev = widget(domain="Ops", created_by="")
    ms = [mapping("planners", "Supply", "viewer"), mapping("planners", "Ops", "editor"),
          mapping("ops", "Ops", "viewer")]
    entries = am.all_grants([prod, dev], ms, [])[(WIDGET, "w1")]
    assert {k: e["level"] for k, e in entries.items()} == {"planners": MANAGE, "ops": USE}


def test_objects_nobody_was_granted_are_left_out():
    assert am.all_grants([widget(created_by="")], [], []) == {}


def test_grant_rows_are_stable():
    out = am.all_grants([widget(object_id="w2"), widget(object_id="w1")],
                        [mapping("b", "Supply", "viewer"), mapping("a", "Supply", "editor")], [])
    rows = am.grant_rows(out)
    assert [r[1] for r in rows] == ["w1"] * 3 + ["w2"] * 3
    assert rows[:3] == [(WIDGET, "w1", "maker@x.com", USER, MANAGE), (WIDGET, "w1", "a", GROUP, MANAGE),
                        (WIDGET, "w1", "b", GROUP, USE)]


def test_a_draft_payload_describes_its_object_too():
    d = am.descriptor(AGENT, {"object_id": "a9", "visibility": "personal", "username": "me@x.com"})
    assert d["object_id"] == "a9" and am.owner_of(d) == "me@x.com"


# ------------------------------------------------------------------ the report

def changes(mappings, objects, admins=()):
    return {p["principal"]: p for p in am.principal_changes(mappings, objects, list(admins))}


def test_editors_learn_that_manage_is_more_than_editing():
    out = changes([mapping("planners", "Supply", "editor")], [widget(created_by=""), view()])
    p = out["planners"]
    assert p["principal_type"] == GROUP
    assert p["gained"] == ["Can manage 1 view and 1 widget in Supply: share, publish, archive and delete them, "
                           "not only edit"]
    assert any("New work filed under Supply" in label for label in p["lost"])


def test_viewers_gain_nothing_new_but_lose_new_work():
    p = changes([mapping("planners", "Supply", "viewer")], [widget(created_by="")])["planners"]
    assert p["gained"] == [] and len(p["lost"]) == 1


def test_domain_admins_lose_the_admin_panel():
    p = changes([mapping("leads", "Supply", "admin")], [widget(created_by="")])["leads"]
    assert any("The Admin Panel" in label for label in p["lost"])


def test_app_admins_are_not_listed():
    out = changes([mapping("cc-admins", "Global", "admin"), mapping("cc-admins", "Supply", "editor")],
                  [widget(created_by="")], admins=[("cc-admins", GROUP)])
    assert out == {}


def test_makers_gain_manage_on_what_they_made():
    out = changes([], [widget(), widget(object_id="w2"), agent(), agent(object_id="a2", visibility="personal")])
    assert out["maker@x.com"]["gained"] == ["Can manage the 2 widgets and 1 agent they created, whatever their "
                                            "domain role"]


def test_an_object_seen_in_two_stores_is_counted_once():
    p = changes([mapping("planners", "Supply", "editor")], [widget(created_by=""), widget(created_by="")])["planners"]
    assert "1 widget" in p["gained"][0]


def test_notes_explain_what_the_rules_could_not_carry():
    notes = am.mapping_notes([mapping("readers", "Global", "viewer")], seeded=True, personal_views=4,
                             subscribed_views=1, permissions_off=True)
    text = " ".join(notes)
    assert "only ever covered items filed under the domain 'Global'" in text
    assert "'users'" in text
    assert "1 of 4 personal views" in text
    assert "DISABLE_PERMISSION_CHECKS" in text


def test_users_as_an_admin_is_called_out():
    notes = am.mapping_notes([mapping("users", "Global", "admin")], seeded=False, personal_views=0,
                             subscribed_views=0, permissions_off=False)
    assert any("'users'" in n and "essentially everyone" in n for n in notes)


def test_before_the_cutover_ran_the_report_says_so():
    out = am.build_report({})
    assert out["ran"] is False and out["failed"] is False and out["ran_at"] is None
    assert out["summary"] == {"admins": 0, "grants": 0, "drafts_created": 0, "pins_dropped": 0, "objects": 0}


def test_the_report_joins_both_steps():
    logs = {
        cons.STEP: {"status": cons.DONE, "ran_at": "2026-11-09T10:00:00",
                    "report": {"summary": {"drafts_created": 4, "pins_dropped": 1}, "notes": ["folded"]}},
        am.STEP: {"status": cons.DONE, "ran_at": "2026-11-09T10:00:05",
                  "report": {"summary": {"admins": 1, "grants": 12, "objects": 6},
                             "principals": [{"principal": "p"}], "notes": ["mapped"]}},
    }
    out = am.build_report(logs)
    assert out["ran"] is True and out["failed"] is False and out["ran_at"] == "2026-11-09T10:00:05"
    assert out["summary"] == {"admins": 1, "grants": 12, "drafts_created": 4, "pins_dropped": 1, "objects": 6}
    assert out["principals"] == [{"principal": "p"}] and out["notes"] == ["folded", "mapped"]


def test_a_skipped_fold_still_counts_as_ran():
    logs = {cons.STEP: {"status": cons.SKIPPED, "report": {}}, am.STEP: {"status": cons.DONE, "report": {}}}
    assert am.build_report(logs)["ran"] is True


def test_a_failed_step_is_reported_with_its_error_first():
    logs = {cons.STEP: {"status": cons.FAILED, "error": "RuntimeError: boom", "report": {}},
            am.STEP: {"status": cons.DONE, "report": {"notes": ["mapped"]}}}
    out = am.build_report(logs)
    assert out["failed"] is True and out["ran"] is False
    assert "RuntimeError: boom" in out["notes"][0] and out["notes"][-1] == "mapped"


# ------------------------------------------------------------------ old snapshots

def test_a_snapshot_from_before_sharing_brings_its_access_with_it():
    tables = {
        "role_mappings": {"columns": ["id", "external_role", "domain", "permission_level"],
                          "rows": [[1, "cc-admins", "Global", "admin"], [2, "planners", "Supply", "viewer"]]},
        "widgets": {"columns": ["id", "version", "domain", "created_by", "is_deprecated"],
                    "rows": [["w1", 1, "Ops", "", 0], ["w1", 2, "Supply", "", 0], ["w2", 1, "Supply", "", 1]]},
        "shared_views": {"columns": ["username", "view_id"], "rows": [["friend@x.com", "v1"]]},
    }
    out = am.tables_from_legacy_snapshot(tables)
    perms = out["object_permissions"]
    assert perms["columns"] == ["object_type", "object_id", "principal", "principal_type", "level", "granted_by"]
    assert perms["rows"] == [[APP, "v1", "friend@x.com", USER, USE, "migration"],
                             [WIDGET, "w1", "planners", GROUP, USE, "migration"]]
    assert out["app_admins"]["rows"] == [["cc-admins", GROUP, "migration"]]


def test_a_snapshot_without_role_mappings_converts_to_nothing():
    out = am.tables_from_legacy_snapshot({})
    assert out["object_permissions"]["rows"] == [] and out["app_admins"]["rows"] == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
