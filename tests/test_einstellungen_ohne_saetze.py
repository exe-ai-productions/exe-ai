"""Settings › Skills and › Tools carry no explaining, sub or empty sentence:
an empty list shows nothing, and a row stands with its label and its value
alone. The eight texts that stood there are gone from the three files and
from both catalogues; what states a cause or describes a tool stays."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEILE = ROOT / "frontend" / "src" / "teile"
FILES = {
    "Skillmaske.svelte": TEILE / "Skillmaske.svelte",
    "Werkzeuge.svelte": TEILE / "Werkzeuge.svelte",
    "SystemPrompt.svelte": TEILE / "SystemPrompt.svelte",
}
GONE = (
    ("skills", "wieviele"),
    ("skills", "selbst_hinweis"),
    ("skills", "keine"),
    ("werkzeuge", "keine_quelle"),
    ("werkzeuge", "fragt_vorher_hinweis"),
    ("werkzeuge", "fragt_nicht_hinweis"),
    ("werkzeuge", "eingebaut_hinweis"),
    ("werkzeuge", "keine"),
)


def _catalogue(language: str) -> dict:
    return json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("language", ["de", "en"])
def test_the_eight_sentences_are_in_neither_catalogue(language: str):
    catalogue = _catalogue(language)
    for group, key in GONE:
        assert key not in catalogue[group], f"{group}.{key} in {language}"


def test_no_file_reads_the_eight_sentences_or_draws_their_style():
    for name, path in FILES.items():
        source = path.read_text(encoding="utf-8")
        for group, key in GONE:
            assert f"'{group}.{key}'" not in source, f"{group}.{key} in {name}"
        assert "regelhinweis" not in source, name
    skills = FILES["Skillmaske.svelte"].read_text(encoding="utf-8")
    assert 'class="hinweis"' not in skills and 'class="leer"' not in skills
    tools = FILES["Werkzeuge.svelte"].read_text(encoding="utf-8")
    assert 'class="leer"' not in tools and "eingebaut_hinweis" not in tools


def test_what_states_a_cause_or_describes_a_tool_stays():
    """The silence probe: the line that names why tools are off, the short
    description of each built-in tool and the head line of the built-in
    source are not among the eight."""
    for language in ("de", "en"):
        werkzeuge = _catalogue(language)["werkzeuge"]
        assert "abgeschaltet" in werkzeuge
        assert "eingebaut_unter" in werkzeuge
        assert werkzeuge["eingebaut_satz"]
    prompt = FILES["SystemPrompt.svelte"].read_text(encoding="utf-8")
    assert "t('werkzeuge.abgeschaltet')" in prompt
    tools = FILES["Werkzeuge.svelte"].read_text(encoding="utf-8")
    assert "t(`werkzeuge.eingebaut_satz.${werkzeug.name}`)" in tools
    assert "t('werkzeuge.eingebaut_unter')" in tools
    # "Asks first" still stands with its label and its yes or no.
    assert "t('werkzeuge.fragt_vorher')" in tools
    assert "t(gewaehltesWerkzeug.needs_confirmation ? 'app.ja' : 'app.nein')" in tools


def test_an_empty_list_shows_nothing_and_a_tool_without_a_live_list_stays_quiet():
    """The empty branches are gone, not replaced: no element is drawn for no
    list; the live list of the tool file draws a line only for the state
    "off"."""
    prompt = FILES["SystemPrompt.svelte"].read_text(encoding="utf-8")
    live = prompt.split("t('werkzeuge.live')", 1)[1].split("{#if istGedaechtnis}", 1)[0]
    assert "{#if lese && !lese.aktiv}" in live
    assert "{:else if lese}" in live
    assert live.count('class="leseleer"') == 1
