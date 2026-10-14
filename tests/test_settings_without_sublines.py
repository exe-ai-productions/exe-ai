"""The settings pages carry no explanatory line under their rows: a row
stands with its label alone, and the twelve sentences that used to sit
under the rows are gone from the component and from both catalogues."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = (ROOT / "frontend" / "src" / "teile" / "SystemPrompt.svelte").read_text(encoding="utf-8")
CATALOGUES = {
    language: json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
    for language in ("de", "en")
}

# The sentence keys that sat under a row, by section.
REMOVED = {
    "einstellungen": ["sprache_hinweis", "auto_hinweis", "codefarben_hinweis", "blase_hinweis"],
    "gedaechtnis": ["an_lokal_hinweis", "an_cloud_hinweis"],
    "bildschutz": ["hinweis"],
    "editor": [
        "werkzeugrunden_unter", "befehlszeit_unter", "kontextkomprimierung_unter",
        "anrede_unter", "anrede_schalter_unter",
    ],
}

# The labels of the same twelve rows, which stay.
LABELS = {
    "einstellungen": ["sprache", "erscheinungsbild", "codefarben", "blase"],
    "gedaechtnis": ["an_lokal", "an_cloud"],
    "bildschutz": ["titel"],
    "editor": [
        "werkzeugrunden_titel", "befehlszeit_titel", "kontextkomprimierung_titel",
        "anrede_titel", "anrede_schalter",
    ],
}


def test_the_component_has_no_line_under_a_row():
    assert 'class="hinweis"' not in COMPONENT
    assert ".hinweis {" not in COMPONENT


def test_the_twelve_sentences_are_gone_from_both_catalogues():
    for language, catalogue in CATALOGUES.items():
        for section, keys in REMOVED.items():
            for key in keys:
                assert key not in catalogue[section], f"{language}: {section}.{key}"


def test_the_twelve_labels_stay_in_both_catalogues_and_in_the_component():
    """Silence probe: only the sentences under the rows went, the rows keep
    their labels."""
    for language, catalogue in CATALOGUES.items():
        for section, keys in LABELS.items():
            for key in keys:
                assert catalogue[section][key], f"{language}: {section}.{key}"
    for section, keys in LABELS.items():
        for key in keys:
            assert f"t('{section}.{key}')" in COMPONENT, f"{section}.{key}"


def test_the_context_compaction_field_keeps_its_limit():
    assert "bind:wert={verdichtungSchwelle} min={0} max={85} ganzzahlig" in COMPONENT
