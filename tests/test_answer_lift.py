"""The one swap between thinking and answer, as the drawn stretches see it.

`liftAnswer` is lifted out of `frontend/src/App.svelte` and run in node, the
way `tests/test_laufmarke.py` runs the waiting mark: the shapes it has to
survive are not obvious from the template, and one earlier version got two of
them wrong. The stretch that becomes the answer is NOT simply the last one —
thinking that a later round continued lands in the SAME stretch, because the
pieces are appended to the one before them, and a run that wrote one bare line
break leaves a content stretch standing behind the thinking.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "frontend/src/App.svelte"


def _lift_answer() -> str:
    treffer = re.search(r"\n  function liftAnswer\(.*?\n  \}\n", QUELLE.read_text(), re.S)
    assert treffer, "liftAnswer() not found in App.svelte"
    return treffer.group(0)


def _lift(strecken: list, content: str, reasoning: str) -> list:
    """The stretches the bubble shows after the swap, read out of node."""
    skript = (
        _lift_answer()
        + f"""
const strecken = {json.dumps(strecken)};
console.log(JSON.stringify(
  liftAnswer(strecken, {json.dumps(content)}, {json.dumps(reasoning)})
));
"""
    )
    lauf = subprocess.run(["node", "-e", skript], capture_output=True, text=True)
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_two_rounds_in_one_stretch_are_cut_apart():
    """Thinking that a second round continued is ONE stretch here.

    The pieces are appended to the stretch before them, so the cut has to
    happen inside it: what was thought first stays thinking, and the answer
    is drawn after it. Cutting the whole stretch away would lose the
    deliberation the tool round was about.
    """
    strecken = [{"art": "reasoning", "text": "erst schauen| 1 |"}]

    assert _lift(strecken, "| 1 |", "erst schauen") == [
        {"art": "reasoning", "text": "erst schauen"},
        {"art": "content", "text": "| 1 |"},
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_the_tool_rows_keep_their_place_and_their_call_id():
    strecken = [
        {"art": "reasoning", "text": "erst schauen", "seit": 1},
        {"art": "werkzeug", "aufruf_id": "a1", "seit": 2},
        {"art": "reasoning", "text": "| 1 |", "seit": 3},
    ]

    assert _lift(strecken, "| 1 |", "erst schauen") == [
        {"art": "reasoning", "text": "erst schauen", "seit": 1},
        {"art": "werkzeug", "aufruf_id": "a1", "seit": 2},
        {"art": "content", "text": "| 1 |"},
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_a_bare_line_break_stays_where_it_was_written():
    """A run that wrote one bare line break leaves a content stretch behind.

    The answer may not land in it — that stretch is what the model wrote,
    while the answer is the thought it ended on. It draws nothing (the view
    wants text there), so the answer simply stands after it.
    """
    strecken = [{"art": "reasoning", "text": "| 1 |"}, {"art": "content", "text": "\n"}]

    assert _lift(strecken, "| 1 |", "") == [
        {"art": "content", "text": "\n"},
        {"art": "content", "text": "| 1 |"},
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_a_stretch_the_swap_emptied_out_steps_aside():
    """The thinking that changed sides leaves nothing behind.

    An empty thinking stretch would still draw its head ("Gedankengang"),
    with nothing under it — so it is dropped, and the answer is all that
    remains.
    """
    strecken = [{"art": "reasoning", "text": "| 1 |", "seit": 1}]

    assert _lift(strecken, "| 1 |", "") == [{"art": "content", "text": "| 1 |"}]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_what_the_swap_did_not_touch_stands_unchanged():
    """A tool stretch and a reach of thinking that stayed thinking are handed
    back as they were — including the `seit` the view times a stretch with."""
    strecken = [
        {"art": "werkzeug", "aufruf_id": "a1", "seit": 2},
        {"art": "reasoning", "text": "erst schauen", "seit": 3},
        {"art": "reasoning", "text": "| 1 |", "seit": 4},
    ]

    assert _lift(strecken, "| 1 |", "erst schauen") == [
        {"art": "werkzeug", "aufruf_id": "a1", "seit": 2},
        {"art": "reasoning", "text": "erst schauen", "seit": 3},
        {"art": "content", "text": "| 1 |"},
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_a_sentence_before_the_tool_stands_once():
    """An earlier round wrote a sentence before its tool call; the closing
    round only thought. The row's answer is the sentence and the lifted
    thought — the sentence already stands drawn, so only the thought is
    drawn after the tool row, and the sentence stands once."""
    strecken = [
        {"art": "reasoning", "text": "erst schauen", "seit": 1},
        {"art": "content", "text": "Ich schaue nach.\n", "seit": 2},
        {"art": "werkzeug", "aufruf_id": "a1", "seit": 3},
        {"art": "reasoning", "text": "| 1 |", "seit": 4},
    ]

    assert _lift(strecken, "Ich schaue nach.\n| 1 |", "erst schauen") == [
        {"art": "reasoning", "text": "erst schauen", "seit": 1},
        {"art": "content", "text": "Ich schaue nach.\n", "seit": 2},
        {"art": "werkzeug", "aufruf_id": "a1", "seit": 3},
        {"art": "content", "text": "| 1 |"},
    ]
