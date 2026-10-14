"""Every card and every quiet button in the right rail is glass.

The rail has no ground of its own: its tools lie on the look's gradient or
drawing. What stands in it carries the glass tokens of the look instead of
the flat raised grounds — `--glass-card` with `--glass-card-line` for a
card, `--glass-button` with `--glass-button-edge` for a button or a chip,
`--glass-hover` under the pointer, `--glass-dropdown` for what floats, and
the house's field outline for a field. Three things stay what they are: the
paper a document is shown on, the code ground of an unfolded tool call, and
a state's own colour, which is mixed over the glass. Read off the source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend/src"

# The tools of the rail, the parts they share, and the wall of tiles.
FILES = [
    "teile/ModulAgenten.svelte", "teile/ModulTerminal.svelte", "teile/ModulVorschau.svelte",
    "teile/DocFolder.svelte", "teile/Agentenverlauf.svelte",
    "teile/Speicherortzeile.svelte", "stil/tiles.css",
]
FLAT = ("var(--bg-erhoben)", "var(--bg-hoch)", "var(--bg)")
# What may keep a flat ground, and why: the page of the preview is paper —
# it shows a document, and the look must not run under its text.
PAPER = {("teile/ModulVorschau.svelte", ".seite")}


def _style(path: str) -> str:
    """The style rules of a file, without their comments."""
    text = (FRONTEND / path).read_text(encoding="utf-8")
    if path.endswith(".svelte"):
        text = text.split("<style>", 1)[1].split("</style>", 1)[0]
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _rules(path: str) -> list[tuple[str, str]]:
    """Every rule as (selector, declarations), the innermost ones of a
    nested block included."""
    return [
        (" ".join(selector.split()), body)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _style(path))
    ]


def _rule(path: str, selector: str) -> str:
    """The declarations of every rule with exactly this selector, joined."""
    bodies = [body for name, body in _rules(path) if name == selector]
    assert bodies, (path, selector)
    return "\n".join(bodies)


@pytest.mark.parametrize("path", FILES)
def test_no_flat_ground_is_left_in_the_rail(path):
    for selector, body in _rules(path):
        if (path, selector) in PAPER:
            continue
        for token in FLAT:
            assert token not in body, (path, selector, token)


@pytest.mark.parametrize(
    ("path", "selector"),
    [
        ("teile/ModulAgenten.svelte", ".karte"),
        ("teile/ModulTerminal.svelte", ".lauf"),
        ("teile/ModulTerminal.svelte", ".output"),
        ("teile/ModulVorschau.svelte", ".quelle"),
        ("teile/Agentenverlauf.svelte", ".roh"),
    ],
)
def test_a_card_is_card_glass_with_its_fine_line(path, selector):
    body = _rule(path, selector)
    assert "background: var(--glass-card);" in body
    assert "box-shadow: inset 0 0 0 1px var(--glass-card-line);" in body


def test_a_tile_of_the_wall_is_card_glass():
    """The tiles of the pictures and of the doc folder share one rule; the
    line is the border the tile always had, now in the card's colour, and
    the shadow that lifts it stays."""
    body = _rule("stil/tiles.css", ".tilewall .kachel")
    assert "background: var(--glass-card);" in body
    assert "border: 1px solid var(--glass-card-line);" in body
    assert "box-shadow: 0 6px 16px rgb(0 0 0 / 0.3);" in body
    # Schweigeprobe: a file with nothing to preview still has no tile at all.
    bare = _rule("teile/DocFolder.svelte", ".tilewall .kachel.nurzeichen")
    assert "background: none;" in bare and "border-color: transparent;" in bare


@pytest.mark.parametrize(
    ("path", "selector", "edge"),
    [
        ("teile/ModulAgenten.svelte", ".datei-chip", "box-shadow: inset 0 0 0 1px var(--glass-button-edge);"),
        ("teile/ModulTerminal.svelte", ".stop", "box-shadow: inset 0 0 0 1px var(--glass-button-edge);"),
        ("teile/Speicherortzeile.svelte", ".ordnerknopf", "box-shadow: inset 0 0 0 1px var(--glass-button-edge);"),
        ("teile/ModulVorschau.svelte", ".zeichenknopf", "border: 1px solid var(--glass-button-edge);"),
        ("teile/DocFolder.svelte", ".modul.dropTarget", "box-shadow: inset 0 0 0 1px var(--glass-button-edge);"),
    ],
)
def test_a_button_or_chip_is_button_glass_with_its_edge(path, selector, edge):
    """A button that had a border keeps it in the edge's colour, so it stays
    as large as it was; one without a border draws the edge inside."""
    body = _rule(path, selector)
    assert "background: var(--glass-button);" in body
    assert edge in body


def test_a_tab_is_an_outline_and_the_shown_one_is_filled():
    tab = _rule("teile/ModulVorschau.svelte", ".reiter-eintrag")
    assert "border: 1px solid var(--glass-button-edge);" in tab
    assert "background: none;" in tab
    assert "background: var(--glass-button);" in _rule("teile/ModulVorschau.svelte", ".reiter-eintrag.aktiv")


@pytest.mark.parametrize(
    ("path", "selector"),
    [
        ("teile/ModulVorschau.svelte", ".adresse"),
    ],
)
def test_a_field_is_glass_with_the_field_outline(path, selector):
    body = _rule(path, selector)
    assert "background: var(--glass-button);" in body
    assert "border: 1px solid var(--feldstrich);" in body


@pytest.mark.parametrize(
    ("path", "selector"),
    [
        ("teile/ModulTerminal.svelte", ".aufruf:hover"),
        ("teile/ModulTerminal.svelte", ".befehl:hover"),
        ("teile/ModulTerminal.svelte", ".stop:hover"),
        ("teile/ModulTerminal.svelte", ".copy:hover"),
        ("teile/ModulVorschau.svelte", ".reiter-eintrag:hover"),
        ("teile/ModulVorschau.svelte", ".zeichenknopf:hover"),
        ("teile/Speicherortzeile.svelte", ".ordnerknopf:hover"),
    ],
)
def test_under_the_pointer_lies_hover_glass(path, selector):
    assert "background: var(--glass-hover);" in _rule(path, selector)


@pytest.mark.parametrize(
    ("path", "selector"),
    [
        ("teile/ModulTerminal.svelte", ".runter"),
        ("teile/DocFolder.svelte", ".weg"),
    ],
)
def test_what_floats_is_dense_glass(path, selector):
    body = _rule(path, selector)
    assert "background: var(--glass-dropdown);" in body
    assert "var(--glass-button-edge)" in body


def test_a_state_is_mixed_over_the_glass_it_lies_on():
    pressed = _rule("teile/ModulVorschau.svelte", ".zeichenknopf.gedrueckt")
    assert "background: color-mix(in srgb, var(--blau) 12%, var(--glass-button));" in pressed
    stop = _rule("teile/ModulAgenten.svelte", ".stopp:hover")
    assert "color-mix(in srgb, var(--rot) 14%, var(--glass-button))" in stop


def test_the_ring_of_a_sentence_has_no_ground_and_the_line_leaves_it_a_gap():
    """The transcript's line was one stroke with rings that covered it by a
    ground of their own. On glass a ground is a plate: the line is drawn row
    by row, and the row of a sentence leaves the ring's nine pixels out."""
    path = "teile/Agentenverlauf.svelte"
    selectors = [selector for selector, _ in _rules(path)]
    assert ".verlauf::before" not in selectors
    assert "background" not in _rule(path, ".ring")
    piece = _rule(path, ".vzeile::before")
    assert "top: var(--line-top);" in piece and "bottom: var(--line-bottom);" in piece
    assert "background: var(--linie-stark);" in piece
    gap = _rule(path, ".vzeile:has(> .vpunkt > .ring)::before")
    assert "transparent calc(6px - var(--line-top))" in gap
    assert "transparent calc(15px - var(--line-top))" in gap
    # The first piece begins inside its dot, the last ends above the edge.
    assert "--line-top: 8px;" in _rule(path, ".vzeile:first-child")
    assert "--line-bottom: 8px;" in _rule(path, ".vzeile:last-child")


def test_paper_code_and_the_browsers_page_stay_what_they_are():
    """Schweigeprobe: the three grounds the rule leaves alone."""
    page = _rule("teile/ModulVorschau.svelte", ".seite")
    assert "background: var(--bg-hoch);" in page
    assert "background: #fff;" in _rule("teile/ModulVorschau.svelte", ".rahmen")
    assert "background: var(--code-grund);" in _rule("teile/ModulTerminal.svelte", ".aufruf-text")


def test_the_parts_that_were_glass_already_are_not_touched_by_the_rule():
    """Schweigeprobe: the calendar and the day's runs next door carried the
    glass before; they still name it and still hold no flat ground."""
    for path in ("teile/ScheduleCalendar.svelte", "teile/ScheduleDayRuns.svelte"):
        css = _style(path)
        assert "background: var(--glass-card);" in css, path
        assert "box-shadow: inset 0 0 0 1px var(--glass-card-line);" in css, path
        for token in FLAT:
            assert token not in css, (path, token)
    # The cron job module draws nothing of its own: it has no style block.
    assert "<style>" not in (FRONTEND / "teile/ModulCronjobs.svelte").read_text(encoding="utf-8")
