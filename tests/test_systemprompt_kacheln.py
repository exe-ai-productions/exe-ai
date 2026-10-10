"""The schedules tile must open without a file fetch.

``laden()`` in SystemPrompt.svelte reached its final ``else`` branch for any
art missing from ``OHNE_DATEI`` and called ``api.agentDatei('')`` — an empty
name the backend rejects. The schedules tile has no file of its own, same as
tools and skills, but was left out of that list, so a click on it always
failed and, worse, reported itself as an agent problem through the catch-all
in ``meldeschluessel()``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "frontend/src/teile/SystemPrompt.svelte"


def _ohne_datei():
    text = QUELLE.read_text(encoding="utf-8")
    zeile = re.search(r"const OHNE_DATEI = \[(.*?)\]", text).group(1)
    return {stueck.strip().strip("'") for stueck in zeile.split(",")}


def test_cronjobs_loest_keinen_dateiabruf_aus():
    assert "cronjobs" in _ohne_datei()


def test_cronjobs_hat_einen_eigenen_meldetext():
    text = QUELLE.read_text(encoding="utf-8")
    assert "if (welche === 'cronjobs') return `cronjobs.${fall}`" in text


def test_auffangfall_redet_nicht_mehr_von_agenten():
    text = QUELLE.read_text(encoding="utf-8")
    treffer = re.search(r"function meldeschluessel.*?\n  \}", text, re.S).group(0)
    assert "return `editor.${fall}`" in treffer
    assert "agenten.${fall}" not in treffer.replace(
        "if (welche === 'agent') return `agenten.${fall}`", ""
    )


def test_gescheitertes_laden_nennt_die_kachel_die_gerade_scheiterte():
    """``art`` only updates once the request succeeds — the catch must name
    the tile that was being switched TO, not the one still showing."""
    text = QUELLE.read_text(encoding="utf-8")
    assert "meldeschluessel('nicht_geladen', neueArt)" in text
    assert "meldeschluessel('nicht_geladen')" not in text


def test_katalog_kennt_die_neuen_schluessel():
    for datei in ("de.json", "en.json"):
        katalog = json.loads((WURZEL / "app/locales" / datei).read_text(encoding="utf-8"))
        assert "nicht_geladen" in katalog["cronjobs"]
        assert "nicht_geladen" in katalog["editor"]
