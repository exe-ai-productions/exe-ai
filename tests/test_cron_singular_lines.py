"""The two sentences of a schedule that count runs have a singular.

A failure limit of 1 and a single quiet run are one run in both languages:
the page of the schedules says "stopped after 1 failed run", and the program
says "no goal completion report after 1 run". From two on the count stands in
the sentence, word for word as before. Same way as the stop notice
(tests/test_cron_stopp_einzahl.py): one catalogue key of its own with
``_eins``, picked where the count is known.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import cronablauf
from app.i18n import t
from tests.test_cronziel_nachbesserung import eintrag_anlegen

ROOT = Path(__file__).resolve().parent.parent
TASK = "Ins Postfach sehen"


@pytest.fixture
def announced(monkeypatch):
    """Announcements, collected instead of played."""
    calls: list[str] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich, sprache=None: calls.append(text),
    )
    return calls


async def _quiet_runs(repos, runs: int, language: str) -> None:
    entry = eintrag_anlegen(repos, deliver="announce", fehlergrenze=runs)
    for _ in range(runs):
        await cronablauf.ziel_verbuchen(
            repos, entry.id, TASK, bericht=None, erfolgreich=True, sprache=language
        )


@pytest.mark.parametrize(
    ("language", "sentence"),
    [
        ("en", f"{TASK} - no goal completion report after 1 run"),
        ("de", f"{TASK} - nach 1 Lauf keine Meldung über das Erreichen des Ziels"),
    ],
)
async def test_one_quiet_run_is_said_in_the_singular(repos, announced, language, sentence):
    await _quiet_runs(repos, 1, language)

    assert announced == [sentence]


@pytest.mark.parametrize(
    ("language", "sentence"),
    [
        ("en", f"{TASK} - no goal completion report after 2 runs"),
        ("de", f"{TASK} - nach 2 Läufen keine Meldung über das Erreichen des Ziels"),
    ],
)
async def test_silence_two_quiet_runs_keep_the_plural(repos, announced, language, sentence):
    await _quiet_runs(repos, 2, language)

    assert announced == [sentence]


@pytest.mark.parametrize("language", ["en", "de"])
@pytest.mark.parametrize("key", ["cronjobs.ohne_zielmeldung_seit_eins", "cronjobs.angehalten_eins"])
def test_the_singular_has_its_own_catalogue_entry_without_a_count(language, key):
    sentence = t(key, language, aufgabe=TASK)

    assert sentence != key
    assert "{" not in sentence
    assert "1" in sentence


@pytest.mark.parametrize("language", ["en", "de"])
def test_silence_the_plural_of_the_page_is_the_sentence_it_was(language):
    catalogue = json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
    sentence = catalogue["cronjobs"]["angehalten"]

    assert "{n}" in sentence
    assert sentence == {
        "en": "Stopped after {n} failed runs",
        "de": "Nach {n} fehlgeschlagenen Läufen angehalten",
    }[language]
