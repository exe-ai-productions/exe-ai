"""The sentences around a skill's description say what the description is.

Since a description may be 1024 characters long, three sentences that said
"this sentence" or "one line" were wrong, and the slash list let a description
at the limit fill the whole picker. The sentences are the approved ones; the
list shows two lines and an ellipsis.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app import skills
from app.tools import skill

ROOT = Path(__file__).resolve().parent.parent
LIST = (ROOT / "frontend/src/teile/Skillliste.svelte").read_text(encoding="utf-8")


def _catalogue(language: str) -> dict:
    return json.loads((ROOT / "app/locales" / f"{language}.json").read_text(encoding="utf-8"))["skills"]


def test_the_missing_description_sentence_names_the_description():
    assert _catalogue("en")["fehler_beschreibung"] == (
        "'{anzeige}': 'description' is missing. The description appears in the list "
        "and tells the model when to use the skill."
    )
    assert _catalogue("de")["fehler_beschreibung"] == (
        "'{anzeige}': 'description' fehlt. Die Beschreibung erscheint in der Liste "
        "und zeigt dem Modell, wann der Skill anzuwenden ist."
    )


def test_the_template_line_says_what_it_does_and_when_to_use_it():
    assert _catalogue("en")["template_description"] == (
        "description: Describe what this skill does and when to use it."
    )
    assert _catalogue("de")["template_description"] == (
        "description: Was dieser Skill tut und wann er anzuwenden ist."
    )


def test_the_tool_tells_the_model_what_the_description_is_for():
    schreiben = next(w for w in skill.werkzeug_beschreibungen() if w.name == skill.SCHREIBEN)
    text = schreiben.schema["properties"]["description"]["description"]
    assert text == (
        "What the skill does and when it applies, in no more than "
        f"{skills.MAX_BESCHREIBUNG} characters. This description is used to identify "
        "relevant skills."
    )


def test_no_sentence_says_one_line_or_this_sentence_any_more():
    for language in ("en", "de"):
        block = _catalogue(language)
        for key in ("fehler_beschreibung", "template_description"):
            assert not re.search(r"one line|This sentence|einer Zeile|Dieser Satz", block[key]), (language, key)
    assert "One line describing" not in (ROOT / "app/tools/skill.py").read_text(encoding="utf-8")


def test_the_description_in_the_slash_list_stands_two_lines_then_an_ellipsis():
    rule = LIST.split("  .zwas {", 1)[1].split("}", 1)[0]
    assert "-webkit-line-clamp: 2;" in rule and "line-clamp: 2;" in rule
    assert "display: -webkit-box;" in rule and "-webkit-box-orient: vertical;" in rule
    assert "overflow: hidden;" in rule


def test_silence_the_name_stays_a_line_and_the_hint_sentence_stays_gone():
    name = LIST.split("  .zname {", 1)[1].split("}", 1)[0]
    assert "line-clamp" not in name and "<div class=\"zname\">{eintrag.name}</div>" in LIST
    assert "selbst_hinweis" not in _catalogue("en") and "selbst_hinweis" not in _catalogue("de")
