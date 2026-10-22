"""Under an answer the user stopped after text had come stands a whole sentence,
not the one short word — and only there: the command line and the results of
jobs keep the short word.

The browser run of the page (the sentence stands in the foot of an answer
stopped with text, not under an empty one, not under a finished one) is in
``tests/test_wait_bubble_parts.py``; this file reads the catalogue and the
places that name the two keys.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.i18n import t

ROOT = Path(__file__).resolve().parent.parent
HINT = "nachricht.stopped_hint"
SHORT = "nachricht.abgebrochen_kurz"


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_hint_is_a_whole_sentence_and_the_short_word_stays(language):
    hint = t(HINT, language)
    assert hint != HINT, "the key is missing from the catalogue"
    assert hint.rstrip().endswith("."), hint
    assert len(hint.split()) >= 6, hint
    # The short word of the command line and of the job results is untouched.
    assert t(SHORT, language) == {"en": "stopped", "de": "abgebrochen"}[language]


@pytest.mark.parametrize("language, sentence", [
    ("en", "This answer was stopped. Send a message to continue."),
    ("de", "Die Antwort wurde angehalten. Zum Fortsetzen bitte eine Nachricht senden."),
])
def test_the_sentence_is_neutral_about_who_stopped_the_answer(language, sentence):
    """A restart of the service also ends an answer that was still running, so the
    sentence may not say that the user stopped it."""
    assert t(HINT, language) == sentence
    first = t(HINT, language).split(".")[0].lower()
    assert " you " not in f" {first} " and " du " not in f" {first} " and "hast" not in first


def test_the_two_languages_say_it_differently():
    assert t(HINT, "en") != t(HINT, "de")


def test_the_page_takes_the_hint_after_a_stop_and_not_the_short_word():
    source = (ROOT / "frontend" / "src" / "teile" / "Nachricht.svelte").read_text(encoding="utf-8")
    line = next(row for row in source.splitlines() if "laufzustand === 'abgebrochen' && !leereAntwort" in row)
    assert HINT in line and SHORT not in line, line
    assert SHORT not in source


@pytest.mark.parametrize("place", [
    "cli/render.py", "app/api/v1/generierung.py", "app/api/v1/auftraege.py",
])
def test_silence_the_command_line_and_the_job_results_keep_the_short_word(place):
    source = (ROOT / place).read_text(encoding="utf-8")
    assert SHORT in source
    assert not re.search(r"stopped_hint", source)
