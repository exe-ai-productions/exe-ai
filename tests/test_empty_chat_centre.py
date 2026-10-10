"""The empty chat stands on one centre: mark, greeting, date and input.

The centred wordmark draws its sign closer to the lettering than the row in
the header does, and moves right by half the air the last letter leaves, so
its ink — not its box — stands over the middle of the input field. The
greeting keeps sixteen pixels to the mark. The small mark in the header and
the watermark behind the chat stay as they are. Geometry needs a browser to
be measured; what can be held here is that the rules say so. Read off the
source.
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend/src"
WORDMARK = "teile/Wortmarke.svelte"
GREETING = "teile/Begruessungsecke.svelte"


def _style(path: str) -> str:
    """The style rules of a component, without their comments."""
    text = (FRONTEND / path).read_text(encoding="utf-8")
    text = text.split("<style>", 1)[1].split("</style>", 1)[0]
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _rules(path: str) -> list[tuple[str, str]]:
    """Every rule as (selector, declarations), in the order of the sheet."""
    return [
        (" ".join(selector.split()), body)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _style(path))
    ]


def _rule(path: str, selector: str) -> str:
    bodies = [body for name, body in _rules(path) if name == selector]
    assert len(bodies) == 1, (path, selector, len(bodies))
    return bodies[0]


def _uses(path: str) -> list[str]:
    """Every place a file sets the wordmark, as its tag."""
    return re.findall(r"<Wortmarke\b[^>]*>", (FRONTEND / path).read_text(encoding="utf-8"))


def test_the_centred_mark_draws_sign_and_word_together():
    assert "gap: 0.45em;" in _rule(WORDMARK, ".zentriert")


def test_the_centred_mark_moves_right_to_the_centre_of_its_ink():
    shift = re.search(r"transform:\s*translateX\(([^)]*)\)", _rule(WORDMARK, ".zentriert"))
    assert shift, "the centred mark carries no compensation"
    value = shift.group(1).strip()
    # Relative to the type, so it holds at every size — and to the right:
    # the air lies behind the last letter, never before the drawing.
    assert re.fullmatch(r"\d*\.?\d+em", value), value
    assert float(value[:-2]) > 0


def test_the_greeting_keeps_sixteen_pixels_to_the_mark():
    assert "margin-top: 16px;" in _rule(GREETING, ".gruss")


def test_a_mark_in_a_row_keeps_its_gap_and_stands_where_its_box_does():
    base = _rule(WORDMARK, ".marke")
    assert "gap: 0.8em;" in base
    assert "transform" not in base


def test_the_drawing_alone_has_no_gap_and_no_compensation():
    alone = _rule(WORDMARK, ".nurzeichen")
    assert "gap: 0;" in alone and "transform: none;" in alone
    # Same weight as the centred rule: it has to come later to win where
    # both are set.
    order = [selector for selector, _ in _rules(WORDMARK)]
    assert order.index(".zentriert") < order.index(".nurzeichen")


def test_only_the_mark_of_the_empty_chat_is_centred():
    in_the_window = _uses("App.svelte")
    assert sum("zentriert" in tag for tag in in_the_window) == 1
    # The watermark behind the chat is the drawing alone, the mark in the
    # header of the left bar a row: both are set without it.
    watermark = [tag for tag in in_the_window if "mitText={false}" in tag]
    assert watermark and all("zentriert" not in tag for tag in watermark)
    in_the_header = _uses("teile/Seitenleiste.svelte")
    assert in_the_header and all("zentriert" not in tag for tag in in_the_header)
