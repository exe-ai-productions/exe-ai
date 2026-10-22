"""The arrow of the input bar, locked because the chat's model is off, says
why: its title and its accessible name carry the sentence the model choice
beside it already has. As the stop button, and with the model on, it says
what it always said.

The derived value and the three attributes are lifted out of
`Eingabeleiste.svelte` by their real text and run in node.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.test_hausregeln import _node, _stueck
from tests.fensterquelle import BAR_SOURCE

BAR = BAR_SOURCE

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def _arrow(
    stoppt: bool,
    modell_aus: bool,
    text: str = "Hallo",
    frage: bool = False,
    versteckt: bool = False,
) -> dict:
    gesperrt = _stueck(
        BAR, r"  const gesperrtDurchModell = \$derived\(.*?\n  \)\n", "gesperrtDurchModell"
    ).strip()
    regel = _stueck(
        BAR, r"  function antwortetOffeneFrage\(inhalt\) \{.*?\n  \}\n", "antwortetOffeneFrage"
    ).strip()
    muster = r"          disabled=\{(?P<d>.*?)\}\n          title=\{(?P<t>.*?)\}\n          aria-label=\{(?P<a>.*?)\}\n"
    import re

    treffer = re.search(muster, BAR.read_text(encoding="utf-8"), re.S)
    assert treffer, "the attributes of the arrow"
    return _node(f"""
const $derived = (wert) => wert
const t = (schluessel) => schluessel
const stoppt = {json.dumps(stoppt)}
const chosenModelOff = () => {json.dumps(modell_aus)}
const text = {json.dumps(text)}
const zustand = {{ aktiverChat: 'c', benutzerfrage: {{ c: {json.dumps(frage)} }} }}
const questionHidden = () => {json.dumps(versteckt)}
{regel}
{gesperrt}
console.log(JSON.stringify({{
  disabled: Boolean({treffer['d']}),
  title: {treffer['t']},
  label: {treffer['a']},
}}))
""")


@needs_node
def test_a_locked_arrow_names_the_reason_in_title_and_label():
    got = _arrow(stoppt=False, modell_aus=True)
    assert got == {
        "disabled": True,
        "title": "fehler.modell_deaktiviert",
        "label": "fehler.modell_deaktiviert",
    }


@needs_node
def test_an_open_arrow_says_send_as_before():
    got = _arrow(stoppt=False, modell_aus=False)
    assert got == {"disabled": False, "title": "eingabe.senden", "label": "eingabe.senden"}


@needs_node
def test_the_stop_button_stays_open_and_says_stop_even_with_the_model_off():
    got = _arrow(stoppt=True, modell_aus=True)
    assert got == {
        "disabled": False,
        "title": "eingabe.abbrechen_tipp",
        "label": "eingabe.abbrechen",
    }
    got = _arrow(stoppt=True, modell_aus=False)
    assert got["title"] == "eingabe.abbrechen_tipp"
    assert got["label"] == "eingabe.abbrechen"


@needs_node
def test_words_that_answer_an_open_question_pass_the_arrow_as_they_pass_enter():
    """The model is off, a run waits on a question: Enter sends the words as
    the answer, and the arrow is open too."""
    got = _arrow(stoppt=False, modell_aus=True, text="Blau", frage=True)
    assert got["disabled"] is False
    assert got["title"] == "eingabe.senden"
    assert got["label"] == "eingabe.senden"


@needs_node
def test_the_arrow_stays_locked_where_enter_sends_nothing():
    # No question open: locked, with its reason, as before.
    got = _arrow(stoppt=False, modell_aus=True, text="Blau", frage=False)
    assert got["disabled"] is True and got["label"] == "fehler.modell_deaktiviert"
    # A question open but pushed away with "later": the words are no answer.
    got = _arrow(stoppt=False, modell_aus=True, text="Blau", frage=True, versteckt=True)
    assert got["disabled"] is True
    # Only an attachment, no words: a new send, which Enter turns down too.
    got = _arrow(stoppt=False, modell_aus=True, text="", frage=True)
    assert got["disabled"] is True
    # The model on: open as always.
    assert _arrow(stoppt=False, modell_aus=False, text="", frage=True)["disabled"] is False


def test_enter_and_the_arrow_read_one_rule_for_the_open_question():
    source = BAR.read_text(encoding="utf-8")
    assert "const answersQuestion = antwortetOffeneFrage(inhalt)" in source
    assert "!stoppt && chosenModelOff() && !antwortetOffeneFrage(text.trim())" in source
