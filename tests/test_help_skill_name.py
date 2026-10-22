"""The shipped skill that explains the program is named `help`, like the other
shipped skills, which all carry English names.

The folder of a skill gives its name, so `skills/help/` is what the user types
after the slash. The manual (English and German page) names it where it lists
the shipped skills and where it says how to ask about the program; its own
address stays `/help/`.
"""

from __future__ import annotations

from pathlib import Path

from app import skills

ROOT = Path(__file__).resolve().parent.parent
SHIPPED = ROOT / "skills"
PAGES = {
    "en": ROOT / "static" / "help" / "index.html",
    "de": ROOT / "static" / "help" / "de" / "index.html",
}
# Where each page names the skill: in the list of the shipped skills and in the
# sentence about asking the assistant. (The CLI's own `/help` stands elsewhere.)
NAMED = {
    "en": (
        "<code>/handoff</code>, <code>/help</code> and <code>/image-generator</code>",
        "Use <code>/help</code> to ask questions about the app.",
    ),
    "de": (
        "<code>/handoff</code>, <code>/help</code> und <code>/image-generator</code>",
        "Mit <code>/help</code> beantwortet er Fragen zum Programm.",
    ),
}


def test_the_shipped_help_skill_is_named_help(tmp_path):
    assert (SHIPPED / "help" / "SKILL.md").is_file()
    assert not (SHIPPED / "hilfe").exists()
    # An empty folder of the user's own: only the shipped skills are there.
    loaded = skills.skills_laden(SHIPPED, tmp_path / "own")
    assert "help" in loaded and "hilfe" not in loaded
    assert loaded["help"].eigen is False


def test_the_text_of_the_skill_names_no_slash_hilfe():
    text = (SHIPPED / "help" / "SKILL.md").read_text(encoding="utf-8")
    assert "/hilfe" not in text
    assert "/handoff, /help and /image-generator" in text


def test_the_manual_names_the_skill_help_in_both_languages():
    for language, page in PAGES.items():
        html = page.read_text(encoding="utf-8")
        # The address of the manual itself, `/help/`, stays; the skill's old name does not.
        assert "<code>/hilfe</code>" not in html, language
        for place in NAMED[language]:
            assert html.count(place) == 1, (language, place)


def test_silence_the_other_shipped_skills_keep_their_names_and_the_manual_its_address():
    loaded = skills.skills_laden(SHIPPED, Path("/nonexistent-own-skills-folder"))
    for name in ("cleanup", "cronjob", "grill-me", "handoff", "image-generator"):
        assert name in loaded, name
    # The switch between the two pages still points at the address of the manual.
    assert 'href="/help/de/?sprache=de"' in PAGES["en"].read_text(encoding="utf-8")
    assert 'href="/help/?sprache=en"' in PAGES["de"].read_text(encoding="utf-8")
