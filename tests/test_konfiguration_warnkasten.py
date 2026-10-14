"""Settings › Configuration: the warning box of a broken file names the file.

The page of `config.yaml` (and of the credentials file) used to fall into the
sentence made for an agent, "This agent is not available", because the box
told only the tools file apart. Read off the source, the way the other
interface tests do.
"""

from __future__ import annotations

import json
from pathlib import Path

HUELLE_PFAD = Path(__file__).resolve().parent.parent / "frontend/src/teile/SystemPrompt.svelte"
HUELLE = HUELLE_PFAD.read_text(encoding="utf-8")
LOCALES = Path(__file__).resolve().parent.parent / "app/locales"


def _box() -> str:
    """The warning box: from its condition to its closing tag."""
    return HUELLE.split("{#if kaputt || unlesbar}", 1)[1].split("{/if}", 1)[0]


def test_the_box_of_a_file_page_names_the_file_not_an_agent():
    box = _box()
    assert "t(istTools || istDatei ? 'werkzeuge.kaputt' : 'agenten.kaputt'" in box
    # Both file pages, and no other page, are `istDatei`.
    flag = HUELLE.split("const istDatei = $derived(", 1)[1].split(")\n", 1)[0]
    assert flag == "art === 'konfiguration' || art === 'zugangsdaten'"


def test_the_agent_page_and_the_tools_file_keep_their_sentences():
    """The silence probe: the agent editor still falls to the agent sentence,
    the tools file keeps the file sentence, and the catalogues are unchanged."""
    box = _box()
    assert "'agenten.kaputt'" in box and "'werkzeuge.kaputt'" in box
    assert box.count("t(") == 1
    for language, file_sentence, agent_sentence in (
        ("de", "Fehlerhafte Datei: {grund}", "Dieser Agent ist nicht verfügbar:"),
        ("en", "Invalid file: {grund}", "This agent is unavailable:"),
    ):
        catalogue = json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))
        assert catalogue["werkzeuge"]["kaputt"] == file_sentence
        assert catalogue["agenten"]["kaputt"].startswith(agent_sentence)
