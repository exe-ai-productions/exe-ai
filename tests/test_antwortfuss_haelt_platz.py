"""The foot of an answer keeps its place across a round border, and the red
"stopped before anything came" line stands only when nothing came.

Both live in `frontend/src/teile/Nachricht.svelte` as derived values; they
are lifted out of the file by their real text and run in node.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.test_hausregeln import _node, _stueck

MESSAGE = Path(__file__).resolve().parent.parent / "frontend/src/teile/Nachricht.svelte"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def _foot(steps: list[dict]) -> list[dict]:
    """The row of readings the foot draws after each step. A step names
    whether the answer runs and which readings it carries now; the memory of
    the last row lives across the steps, as it does in the component."""
    kept = _stueck(
        MESSAGE,
        r"  let zuletztGemessen = \[\]\n  (const fussMessungen = \$derived\.by\(.*?\n  \}\)\n)",
        "fussMessungen",
    )
    kept = kept.split("\n", 1)[1].strip()
    haelt = _stueck(
        MESSAGE, r"  const messungenHaelt = \$derived\(.*?\)\n", "messungenHaelt"
    ).strip()
    return _node(f"""
let zuletztGemessen = []
const schritt = (laeuft, messungen) => {{
  const $derived = Object.assign((wert) => wert, {{ by: (fn) => fn() }})
  {kept}
  {haelt}
  return {{ fuss: fussMessungen, haelt: messungenHaelt }}
}}
const ergebnis = {json.dumps(steps)}.map((s) => schritt(s.laeuft, s.messungen))
console.log(JSON.stringify(ergebnis))
""")


def _row(nachricht: dict, teile: list[dict], laeuft: bool, laufzustand: str,
         dokumentKarten: list | None = None, abgeschnitten: bool = False,
         abgelehnt: bool = False) -> bool:
    kam = _stueck(MESSAGE, r"  const etwasKam = \$derived\(.*?\n  \)\n", "etwasKam")
    leer = _stueck(MESSAGE, r"  const leereAntwort = \$derived\(.*?\n  \)\n", "leereAntwort")
    got = _node(f"""
const $derived = (wert) => wert
const nachricht = {json.dumps(nachricht)}
const teile = {json.dumps(teile)}
const dokumentKarten = {json.dumps(dokumentKarten or [])}
const hatInhalt = Boolean((nachricht.content || '').trim())
const laeuft = {json.dumps(laeuft)}
const laufzustand = {json.dumps(laufzustand)}
const abgeschnitten = {json.dumps(abgeschnitten)}
const abgelehnt = {json.dumps(abgelehnt)}
{kam}
{leer}
console.log(JSON.stringify({{ leereAntwort }}))
""")
    return got["leereAntwort"]


READING = [{"zahl": "31", "wort": "TPS", "titel": None}]
OTHER = [{"zahl": "12 %", "wort": "Cache", "titel": None}]


@needs_node
def test_the_row_stays_invisible_at_a_round_border_and_is_back_with_the_next_reading():
    got = _foot(
        [
            {"laeuft": True, "messungen": []},  # before the first reading
            {"laeuft": True, "messungen": READING},  # a reading
            {"laeuft": True, "messungen": []},  # the round border
            {"laeuft": True, "messungen": OTHER},  # the next reading
        ]
    )
    assert got[0] == {"fuss": [], "haelt": False}
    assert got[1] == {"fuss": READING, "haelt": False}
    # Same width as the last reading, drawn invisible.
    assert got[2] == {"fuss": READING, "haelt": True}
    # With the new reading the new number stands, and it is shown.
    assert got[3] == {"fuss": OTHER, "haelt": False}


@needs_node
def test_a_finished_answer_shows_what_was_measured_and_nothing_else():
    got = _foot(
        [
            {"laeuft": True, "messungen": READING},
            {"laeuft": False, "messungen": []},  # finished, nothing measured
            {"laeuft": False, "messungen": OTHER},  # finished, measured
        ]
    )
    assert got[1] == {"fuss": [], "haelt": False}
    assert got[2] == {"fuss": OTHER, "haelt": False}


@needs_node
def test_a_new_run_does_not_inherit_the_row_of_the_one_before():
    got = _foot(
        [
            {"laeuft": True, "messungen": READING},
            {"laeuft": False, "messungen": READING},
            {"laeuft": True, "messungen": []},
        ]
    )
    assert got[2] == {"fuss": [], "haelt": False}


@needs_node
def test_a_stopped_answer_with_a_tool_row_and_no_text_has_no_red_line():
    nachricht = {"content": "", "reasoning": ""}
    teile = [{"art": "werkzeug"}]
    assert _row(nachricht, teile, laeuft=False, laufzustand="abgebrochen") is False


@needs_node
def test_a_stopped_answer_with_only_thinking_has_no_red_line():
    nachricht = {"content": "", "reasoning": "let me see"}
    teile = [{"art": "reasoning", "text": "let me see"}]
    assert _row(nachricht, teile, laeuft=False, laufzustand="abgebrochen") is False


@needs_node
def test_a_stopped_answer_with_a_file_or_a_picture_has_no_red_line():
    nachricht = {"content": "", "reasoning": ""}
    assert _row(nachricht, [], False, "abgebrochen", dokumentKarten=[{"id": "d"}]) is False
    assert _row({**nachricht, "bild": "x.png"}, [], False, "abgebrochen") is False


@needs_node
def test_a_stopped_answer_with_nothing_at_all_keeps_its_red_line():
    nachricht = {"content": "", "reasoning": ""}
    assert _row(nachricht, [], laeuft=False, laufzustand="abgebrochen") is True
    # A trailing blank section, as a live answer keeps it, is nothing either.
    blank = [{"art": "content", "text": "  "}]
    assert _row(nachricht, blank, laeuft=False, laufzustand="abgebrochen") is True


@needs_node
def test_failed_and_silent_answers_keep_their_line_as_before():
    nachricht = {"content": "", "reasoning": ""}
    teile = [{"art": "werkzeug"}]
    assert _row(nachricht, teile, laeuft=False, laufzustand="fehler") is True
    assert _row(nachricht, teile, laeuft=False, laufzustand="fertig") is True


@needs_node
def test_a_declined_answer_has_no_red_silent_line_of_its_own():
    """The line that says the model declined stands in its place."""
    nachricht = {"content": "", "reasoning": ""}
    assert _row(nachricht, [], False, "fertig", abgelehnt=True) is False
    assert _row(nachricht, [], False, "fertig", abgelehnt=False) is True


@needs_node
def test_an_image_answer_a_running_answer_and_a_cut_off_one_have_no_red_line():
    nachricht = {"content": "", "reasoning": ""}
    assert _row({**nachricht, "bild": "x.png"}, [], False, "fertig") is False
    assert _row(nachricht, [], laeuft=True, laufzustand="laeuft") is False
    assert _row(nachricht, [], False, "fertig", abgeschnitten=True) is False
    # An answer with text never had one.
    assert _row({"content": "hi"}, [], False, "fertig") is False


def test_the_foot_is_bound_to_the_run_and_the_wait_row_keeps_its_rule():
    """The foot is quiet for every running answer — with text and before its
    first word — and for no other: finished, stopped and failed ones show the
    buttons. The wait row keeps its own rule (it still speaks before the
    first word). Real behaviour is measured in a browser
    (`test_a_running_answer_without_text_shows_no_button_...`); this guards
    the binding."""
    source = MESSAGE.read_text(encoding="utf-8")
    assert '<div class="fuss" class:ruhig={laeuft}>' in source, "the foot is no longer quiet while the run goes"
    assert "const markeRuhig = $derived(laeuft && hatInhalt)" in source, "the wait row's rule changed"
