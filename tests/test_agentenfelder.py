"""Field-wise agent editing: the form must never lose what it does not show.

The guard this file exists for: a file carrying EVERY field — including the
ones the form has no control for, plus comments and an unknown key — goes
through a form save and comes back complete. A form that rebuilt the file
from its own controls would fail exactly here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import agentenfelder
from app.agenten import agent_aus_text

# A full path of this system: a POSIX path is not one on Windows, where the
# agent file is refused for it ("'folders' needs full paths").
CODE = str(Path(Path.cwd().anchor, "Users", "wer", "code"))

VOLL = f"""---
# the model this agent computes on
model: mana
tools:
  - web_search
  - read_file
folders:
  - {CODE}
max_rounds: 12
max_minutes: 7
max_tokens: 16000
schedule: "08:00"
schedule_task: "Sort the inbox"
permissions:
  run_command: nein
zukunftsfeld: bleibt
---

You research things.
"""


def test_waechter_kein_feld_geht_verloren():
    """The core guard: a full file through the form path stays complete."""
    neu = agentenfelder.felder_anwenden(
        VOLL,
        {
            "max_rounds": 20,
            "tools": ["web_search", "search_files"],
        },
    )
    agent = agent_aus_text("voll", neu)
    assert agent.runden == 20
    assert agent.werkzeuge == ["web_search", "search_files"]
    # Everything the form did not touch is still there, value for value.
    assert agent.ordner == [CODE]
    assert agent.minuten == 7
    assert agent.max_tokens == 16000
    assert agent.berechtigungen == {"run_command": "nein"}
    # The retired keys — ``schedule``/``schedule_task`` and
    # ``model`` — are no longer form fields, which makes them the
    # sharpest case for this guard: the form does not know them, and they
    # still have to come out of a form save word for word.
    assert "model: mana" in neu
    assert 'schedule: "08:00"' in neu
    assert 'schedule_task: "Sort the inbox"' in neu
    assert agent.prompt == "You research things."
    # The parts the parser does not carry survive as text: the comment and
    # the field this program version does not know.
    assert "# the model this agent computes on" in neu
    assert "zukunftsfeld: bleibt" in neu


def test_leere_feldliste_aendert_nichts():
    assert agentenfelder.felder_anwenden(VOLL, {}) == VOLL


def test_none_entfernt_ein_feld():
    neu = agentenfelder.felder_anwenden(VOLL, {"max_tokens": None})
    assert "max_tokens" not in neu
    agent = agent_aus_text("voll", neu)
    assert agent.max_tokens is None
    assert "model: mana" in neu


def test_fehlendes_feld_wird_angehaengt():
    text = "---\nmodel: mana\n---\n\nPrompt.\n"
    neu = agentenfelder.felder_anwenden(text, {"max_rounds": 5})
    agent = agent_aus_text("neu", neu)
    assert agent.runden == 5
    assert "model: mana" in neu


def test_prompt_ersetzt_nur_den_rumpf():
    neu = agentenfelder.felder_anwenden(VOLL, {}, prompt="New prompt.")
    agent = agent_aus_text("voll", neu)
    assert agent.prompt == "New prompt."
    assert agent.berechtigungen == {"run_command": "nein"}


def test_leere_werkzeugliste_bleibt_leer():
    """`tools: []` and no tools key mean different things — both round-trip."""
    neu = agentenfelder.felder_anwenden(VOLL, {"tools": []})
    assert agent_aus_text("voll", neu).werkzeuge == []
    ohne = agentenfelder.felder_anwenden(VOLL, {"tools": None})
    assert agent_aus_text("voll", ohne).werkzeuge is None


def test_sonderzeichen_im_pfad_ueberleben():
    text = "---\nmodel: mana\n---\n\nPrompt.\n"
    pfad = str(Path(Path.cwd().anchor, "Volumes", "Data Disk", "Projects: with a colon"))
    neu = agentenfelder.felder_anwenden(text, {"folders": [pfad]})
    assert agent_aus_text("neu", neu).ordner == [pfad]


def test_neu_bauen_schreibt_nur_gesagtes():
    text = agentenfelder.neu_bauen({"tools": ["web_search"]}, "Do research.")
    agent = agent_aus_text("frisch", text)
    assert agent.werkzeuge == ["web_search"]
    assert "model" not in text


def test_ohne_kopfteil_wird_abgelehnt():
    with pytest.raises(agentenfelder.KopfteilKaputt):
        agentenfelder.felder_anwenden("kein kopf", {"max_rounds": 5})


def test_model_ist_kein_formularfeld_mehr():
    """Which model a run uses is the one field's word or the start
    window's, never a line in the agent file. The form cannot write one, and
    the refusal is the same one any other non-form field gets."""
    assert "model" not in agentenfelder.FORMULAR_FELDER
    with pytest.raises(ValueError):
        agentenfelder.felder_anwenden(VOLL, {"model": "kea"})


def test_unbekanntes_formularfeld_wird_abgelehnt():
    with pytest.raises(ValueError):
        agentenfelder.felder_anwenden(VOLL, {"permissions": {}})


def test_max_command_seconds_ist_formularfaehig():
    """The form could set every shell time limit but this one by hand-editing
    the file — now it goes through the same named-field path as the rest."""
    neu = agentenfelder.felder_anwenden(VOLL, {"max_command_seconds": 600})
    agent = agent_aus_text("voll", neu)
    assert agent.befehlssekunden == 600


def test_farbe_ist_formularfaehig():
    """The colour is picked in the mask, so it travels the same named-field
    path as the folders and the limits beside it."""
    neu = agentenfelder.felder_anwenden(VOLL, {"color": "#b04f96"})
    assert agent_aus_text("voll", neu).farbe == "#b04f96"


def test_farbe_laesst_sich_wieder_abwaehlen():
    """None removes a field — which is how "no colour" gets back into a file
    that already had one."""
    mit = agentenfelder.felder_anwenden(VOLL, {"color": "#b04f96"})
    ohne = agentenfelder.felder_anwenden(mit, {"color": None})
    assert agent_aus_text("voll", ohne).farbe is None
