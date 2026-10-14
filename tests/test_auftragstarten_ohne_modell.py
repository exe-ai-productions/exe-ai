"""The window "new task": without a reachable model the start is locked.

The window is Svelte, drawn in a browser; what can be held here is its
source — that the start button is only ready when a model answers, and that
``starten()`` asks the same thing a second time, so a start reached another
way (a key press, a double click) is never sent either.
"""

from __future__ import annotations

import re
from pathlib import Path

QUELLE = Path(__file__).resolve().parent.parent / "frontend/src/teile/AuftragStarten.svelte"


def _text() -> str:
    return QUELLE.read_text(encoding="utf-8")


def test_der_start_ist_ohne_modell_gesperrt():
    treffer = re.search(r"startbar=\{([^}]*)\}", _text())
    assert treffer, "no startbar of the window"
    assert "!keinModell" in treffer.group(1)


def test_starten_fragt_dasselbe_ein_zweites_mal():
    treffer = re.search(r"async function starten\(\) \{(?:\s*//[^\n]*)*\s*if \((.*)\) return", _text())
    assert treffer, "no guard at the head of starten()"
    assert "keinModell" in treffer.group(1)


def test_der_hinweis_steht_weiter_im_fenster():
    """Silence probe: the row that says what is missing, and the way to the
    page that supplies it, stay where they were."""
    quelle = _text()
    assert "t('fehler.kein_modell_verfuegbar')" in quelle
    assert "onclick={modelleOeffnen}" in quelle
