"""Tests for the names in links to global views (`services/app_links.py`).

What matters is that a name never stands in for a personal view's id, which is
the only thing keeping a personal view to the people it was shared with, and
that a name once handed out keeps pointing at the same view.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from services import app_links
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_app_links: {e}")
    sys.exit(0)

UUID = "3f2a9c1e-0b5c-4d2e-9f40-4a5b8c6d7e8f"


class Links:
    """`app_links` as Postgres would answer the claim's upsert."""

    def __init__(self, **taken):
        self.rows = dict(taken)
        self._row = None

    def execute(self, sql, params=None):
        slug, app_id = params
        self._row = None
        if self.rows.get(slug, app_id) == app_id:
            self.rows[slug] = app_id
            self._row = (slug,)

    def fetchone(self):
        return self._row


def test_a_name_reads_as_words_joined_by_dashes():
    assert app_links.slugify("  Supply Hub — Q3 Review! ") == "supply-hub-q3-review"
    assert app_links.slugify("Café Opérations") == "cafe-operations"
    assert app_links.slugify("ops_team") == "ops-team"


def test_a_name_with_nothing_to_spell_is_view():
    assert app_links.slugify("!!!") == "view" and app_links.slugify(None) == "view"


def test_a_name_cannot_pose_as_a_personal_views_link():
    # Resolving a personal link reads the id at its end; a global view named so
    # would otherwise answer for someone else's.
    assert app_links.id_in(app_links.slugify(f"Ops {UUID}")) is None
    assert app_links.slugify(UUID) == "view"


def test_a_personal_link_carries_its_id():
    assert app_links.id_in(f"q3-review-{UUID}") == UUID
    assert app_links.id_in(UUID.upper()) == UUID
    assert app_links.id_in("supply-hub") is None


def test_long_names_are_cut_at_a_word():
    slug = app_links.slugify("word " * 40)
    assert len(slug) <= app_links.MAX_LENGTH and not slug.endswith("-")


def test_a_taken_name_gets_the_next_number_and_a_view_keeps_its_own():
    links = Links(ops="other")
    assert app_links.claim(links, "g1", "Ops") == "ops-2"
    assert app_links.claim(links, "g1", "Ops") == "ops-2", "saving again doesn't move it"
    assert app_links.claim(links, "g2", "Ops") == "ops-3"


def test_every_number_taken_falls_back_to_the_id():
    taken = {"ops": "x", **{f"ops-{n}": "x" for n in range(2, app_links.MAX_SUFFIX + 1)}}
    assert app_links.claim(Links(**taken), "g1", "Ops") is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"\n{len(tests)} passed")
