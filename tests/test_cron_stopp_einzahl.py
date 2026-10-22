"""The sentence a schedule is stopped with names how many runs failed
(app/cronablauf.py): one failed run has a sentence of its own, from two on
the count stands in it, in both languages.
"""

from __future__ import annotations

import pytest

from app import cronablauf
from app.i18n import t

TASK = "Check the inbox"


@pytest.fixture
def announced(monkeypatch):
    """Announcements, collected instead of played."""
    calls: list[str] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich, sprache=None: calls.append(text),
    )
    return calls


async def _stop_after(repos, runs: int, language: str) -> str:
    entry = repos.cronjobs.erstellen(
        agent="a", task=TASK, zeitplan="*/15 * * * *", herkunft="chat",
        deliver="announce", fehlergrenze=runs,
    )
    for _ in range(runs):
        await cronablauf.ausgang_verbuchen(
            repos, entry.id, TASK, erfolgreich=False, sprache=language
        )
    return entry.id


@pytest.mark.parametrize(
    ("language", "sentence"),
    [
        ("en", f"{TASK} - stopped after 1 failed run"),
        ("de", f"{TASK} - nach 1 fehlgeschlagenen Lauf gestoppt"),
    ],
)
async def test_one_failed_run_is_said_in_the_singular(repos, announced, language, sentence):
    await _stop_after(repos, 1, language)

    assert announced == [sentence]


@pytest.mark.parametrize(
    ("language", "sentence"),
    [
        ("en", f"{TASK} - stopped after 2 failed runs"),
        ("de", f"{TASK} - nach 2 fehlgeschlagenen Läufen gestoppt"),
    ],
)
async def test_silence_two_failed_runs_keep_the_plural(repos, announced, language, sentence):
    await _stop_after(repos, 2, language)

    assert announced == [sentence]


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_singular_has_its_own_catalogue_entry_without_a_count(language):
    sentence = t("cronjobs.nach_fehlversuchen_gestoppt_eins", language, aufgabe=TASK)

    assert sentence != "cronjobs.nach_fehlversuchen_gestoppt_eins"
    assert "{" not in sentence
    assert "1" in sentence
