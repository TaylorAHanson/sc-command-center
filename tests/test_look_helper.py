"""Tests for "Describe the look": what the model is told, and what of its reply is kept."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import app_spec  # noqa: E402
from services.look_helper import MAX_DESCRIPTION_CHARS, SYSTEM_PROMPT, messages, theme_from_reply  # noqa: E402


def test_the_prompt_names_every_choice_the_spec_accepts():
    for value in (*app_spec.FONTS, *app_spec.GRADIENT_DIRECTIONS, *app_spec.CARD_STYLES["radius"],
                  *app_spec.CARD_STYLES["depth"], *app_spec.CARD_STYLES["header"]):
        assert f'"{value}"' in SYSTEM_PROMPT, value
    assert "white text" in SYSTEM_PROMPT


def test_the_current_look_goes_with_the_description_and_long_text_is_cut():
    sent = messages("x" * (MAX_DESCRIPTION_CHARS + 50), {"dark": "#1e293b", "font": "nonsense"})
    assert sent[0][0] == "system"
    assert sent[1][1].count("x") == MAX_DESCRIPTION_CHARS
    assert '"dark": "#1e293b"' in sent[1][1] and "nonsense" not in sent[1][1]
    assert "Current look" not in messages("calm", None)[1][1]


def test_a_reply_is_read_with_the_spec_rules():
    theme, dropped = theme_from_reply(
        'Here you go:\n```json\n{"dark": "#0B1220", "font": "space-grotesk", '
        '"background": {"kind": "gradient", "from": "#0b1220", "to": "#1e3a8a", "direction": "to-br"}}\n```'
    )
    assert theme == {"primary": None, "dark": "#0b1220", "font": "space-grotesk",
                     "background": {"kind": "gradient", "from": "#0b1220", "to": "#1e3a8a", "direction": "to-br"}}
    assert dropped == []
    assert theme_from_reply('{"cards": {"radius": "xl"}}')[0] == {"primary": None, "dark": None, "cards": {"radius": "xl"}}


def test_what_could_not_be_drawn_is_named_not_kept():
    theme, dropped = theme_from_reply('{"primary": "#ffe4e1", "dark": "#1e293b", "font": "comic-sans", "cards": {"radius": "xl", "depth": "glow"}}')
    assert theme == {"primary": None, "dark": "#1e293b", "cards": {"radius": "xl"}}
    assert dropped == ["accent colour", "font", "part of the card style"]


def test_a_reply_with_no_look_in_it_gives_nothing():
    for reply in ("", "I can't help with that.", "{not json}", "[1, 2]", '{"primary": "#ffffff"}'):
        assert theme_from_reply(reply)[0] is None, reply


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
            passed += 1
    print(f"\n{passed} passed")
