"""The check for a newer build says so when the release list cannot be read,
in the section "llama.cpp" every server window carries and in the picture
server's window, and the footer's
name for the skip-layers field is the field's own.

Checked at the source of both, since there is no Svelte runtime
harness here; the service's answer is tested with its routes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
FENSTER = {
    "llama.cpp section": WURZEL / "frontend/src/teile/LlamaCppSection.svelte",
    "picture server": WURZEL / "frontend/src/teile/Bildserver.svelte",
}


def _text(language: str, key: str):
    node = json.loads((WURZEL / f"app/locales/{language}.json").read_text(encoding="utf-8"))
    for part in key.split("."):
        node = node[part]
    return node


def test_both_say_it_at_the_top_when_the_list_was_not_readable():
    for name, path in FENSTER.items():
        quelle = path.read_text(encoding="utf-8")
        said = re.search(
            r"\.unreadable\)\s*melde\(t\('bildserver\.updates_nicht_pruefbar'\), 'fehler'\)",
            quelle,
        )
        assert said, f"the {name} shows no message for an unreadable list"
        # Said with the answer the newest check got, not one it replaced.
        assert re.search(r"if \((lauf|run) === (pruefLauf|checkRun)\) \{\s*"
                         r"(aktualisierung|updateAnswer) = (antwort|answer)", quelle), name


def test_the_sentence_is_one_text_in_both_languages():
    assert _text("en", "bildserver.updates_nicht_pruefbar") == "Could not check for updates."
    assert _text("de", "bildserver.updates_nicht_pruefbar") == "Updates ließen sich nicht prüfen."


def test_the_skip_layers_field_carries_the_name_of_the_option():
    """The footer names the control that sends a picture to sd-cli by the
    field's label; "Layers" alone said nothing without the field."""
    assert _text("en", "bild.skip_layers") == "Skip layers"
    assert _text("de", "bild.skip_layers") == "Übersprungene Ebenen"
    # The footer says the field's own label, so the two cannot drift apart.
    assert _text("en", "studio.bildserver_pausiert").format(
        control=_text("en", "bild.skip_layers")
    ) == "Image server pauses for Skip layers"
    assert _text("de", "studio.bildserver_pausiert").format(
        control=_text("de", "bild.skip_layers")
    ) == "Bild-Server pausiert für Übersprungene Ebenen"
