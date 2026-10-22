"""The two dark looks carry no drawing: a flat frame, nothing on it.

Exe and Dark Matter once carried one drawing each on the frame (cubes, a net
of stars). Only Moune carries drawings now (tests/test_drawing_names.py);
what stays of these two looks is the flat frame of one colour, the three
stops kept for the user's own gradient, and the see-through glass over it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "frontend" / "src" / "stil" / "global.css"
APP = ROOT / "frontend" / "src" / "App.svelte"
FIELD = ROOT / "frontend" / "src" / "teile" / "Vektorfeld.svelte"
DRAWING = ROOT / "frontend" / "src" / "stil" / "exe" / "01_wuerfel.svg"
NET = ROOT / "frontend" / "src" / "stil" / "darkmatter" / "01_sternnetz.svg"

EXE = ":root[data-eigen='dunkel'],\n:root[data-modus='dunkel']"
AUTO = ":root:not([data-modus='hell'], [data-modus='snow'], [data-eigen='hell'])"
DARK_MATTER = ":root[data-modus='darkmatter']"
FRAME = "#353634"
DARK_MATTER_FRAME = "#1a0b3a"


def _rule(selector: str) -> str:
    sheet = SHEET.read_text(encoding="utf-8")
    start = sheet.index(selector + " {")
    return sheet[start:sheet.index("}", start)]


def _value(selector: str, name: str) -> str | None:
    hit = re.search(rf"^\s*{re.escape(name)}: (.+);$", _rule(selector), re.MULTILINE)
    return hit.group(1) if hit else None


def test_the_exe_frame_is_one_flat_colour_in_both_of_its_rules():
    for selector in (EXE, AUTO):
        assert _value(selector, "--frame") == FRAME, selector


def test_the_three_stops_stay_for_the_users_own_gradient():
    """The flat frame takes nothing from the look of the user's own gradient,
    which starts from the stops the Exe rule names."""
    for selector in (EXE, AUTO):
        rule = _rule(selector)
        assert len(re.findall(r"--rahmen-vorgabe-\d+: #", rule)) == 3, selector


def test_the_dark_matter_frame_is_one_flat_colour():
    assert _value(DARK_MATTER, "--frame") == DARK_MATTER_FRAME


def test_none_of_the_four_looks_without_drawings_names_an_ink_for_them():
    """The ink the vector field reads belongs to the one look that carries
    drawings; the others name none."""
    sheet = SHEET.read_text(encoding="utf-8")
    declared = re.findall(r"^\s*--vek: [^;]+;$", sheet, re.MULTILINE)
    assert len(declared) == 1, declared
    for selector in (EXE, AUTO, DARK_MATTER):
        assert _value(selector, "--vek") is None, selector


def test_no_drawing_stands_on_the_frame_of_the_dark_looks():
    app = APP.read_text(encoding="utf-8")
    start = app.index('<div class="fenster">')
    block = app[start:app.index('<div class="rumpf"', start)]
    assert block.count("<Vektorfeld") == 1, "a drawing on the frame beside Moune's"
    assert "{#if moune}\n    <Vektorfeld art=\"gras\" />\n  {/if}" in block
    for name in ("wuerfel", "sternnetz"):
        assert f'art="{name}"' not in app
        assert name not in FIELD.read_text(encoding="utf-8")
    assert "const exe = " not in app and "const darkmatter = " not in app
    # The sheets themselves are gone from the repository.
    assert not DRAWING.exists() and not NET.exists()
