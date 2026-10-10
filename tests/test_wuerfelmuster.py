"""The drawings of the two dark looks: cubes for Exe, a net of stars for
Dark Matter, on the frame, under the side rails.

The frame of each look is one flat colour instead of a gradient, and on it
lies one drawing, mounted the way Moune's grass is: the first layer of the
window, behind everything that stands on the frame. The rails, the chat
tile and the input bar are left exactly as they were — they carry no drawing
of their own. Both sheets are written by a script, their ink follows the
look, and both show at the same weight. Exe's cubes are solid: their faces
carry the frame's colour and hide what stands behind. Dark Matter's net is
lines with a four-pointed star at every knot.
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
AUTO = ":root:not([data-modus='hell'], [data-eigen='hell'])"
DARK_MATTER = ":root[data-modus='darkmatter']"
FRAME = "#353634"
INK = "#d0d0cc"
DARK_MATTER_FRAME = "#1a0b3a"
DARK_MATTER_INK = "#b18cff"
# The weight of both drawings: a texture of the ground, not a picture.
WEIGHT = "0.18"


def _rule(selector: str) -> str:
    sheet = SHEET.read_text(encoding="utf-8")
    start = sheet.index(selector + " {")
    return sheet[start:sheet.index("}", start)]


def _value(selector: str, name: str) -> str | None:
    hit = re.search(rf"^\s*{re.escape(name)}: (.+);$", _rule(selector), re.MULTILINE)
    return hit.group(1) if hit else None


def _frame_block() -> str:
    """The frame's own drawings in the window, from its opening to the first
    thing that stands on it."""
    app = APP.read_text(encoding="utf-8")
    start = app.index('<div class="fenster">')
    return app[start:app.index('<div class="rumpf"', start)]


def test_the_exe_frame_is_one_flat_colour_in_both_of_its_rules():
    for selector in (EXE, AUTO):
        assert _value(selector, "--frame") == FRAME, selector
        assert _value(selector, "--vek") == INK, selector


def test_the_three_stops_stay_for_the_users_own_gradient():
    """The flat frame takes nothing from the look of the user's own gradient,
    which starts from the stops the Exe rule names."""
    for selector in (EXE, AUTO):
        rule = _rule(selector)
        assert len(re.findall(r"--rahmen-vorgabe-\d+: #", rule)) == 3, selector


def test_the_cubes_lie_on_the_frame_for_exe_and_the_net_for_dark_matter():
    block = _frame_block()
    assert '{:else if exe}\n    <Vektorfeld art="wuerfel" />\n  {:else if darkmatter}\n    <Vektorfeld art="sternnetz" />' in block
    assert block.count("<Vektorfeld") == 5, "a drawing on the frame no test here knows"
    app = APP.read_text(encoding="utf-8")
    assert app.count('art="wuerfel"') == 1, "the cubes are mounted on a second surface"
    assert app.count('art="sternnetz"') == 1, "the net is mounted on a second surface"


def test_exe_is_the_dark_look_and_the_dark_half_of_auto_and_dark_matter_itself():
    app = APP.read_text(encoding="utf-8")
    assert "const exe = $derived(modus === 'dunkel' || (modus === 'auto' && geraet.dunkel))" in app
    assert "const darkmatter = $derived(modus === 'darkmatter')" in app


def test_the_rails_and_the_input_bar_of_exe_carry_no_drawing():
    """The silence check: what stands on the frame is left as it is."""
    app = APP.read_text(encoding="utf-8")
    for name in ("leistenZeichnung", "eingabeZeichnung"):
        line = re.search(rf"const {name} = \$derived\((.+)\)", app).group(1)
        assert "exe" not in line, f"{name} draws on an Exe surface"
        assert "darkmatter" not in line, f"{name} draws on a Dark Matter surface"


def test_the_field_shows_both_drawings_at_the_one_weight_of_the_design():
    field = FIELD.read_text(encoding="utf-8")
    assert "import wuerfel from '../stil/exe/01_wuerfel.svg?raw'" in field
    assert "import sternnetz from '../stil/darkmatter/01_sternnetz.svg?raw'" in field
    assert f"wuerfel: {{ roh: wuerfel, deckkraft: {WEIGHT} }}," in field
    assert f"sternnetz: {{ roh: sternnetz, deckkraft: {WEIGHT} }}," in field


def test_the_sheet_fills_the_frame_from_its_feet_and_takes_its_ink_from_the_look():
    sheet = DRAWING.read_text(encoding="utf-8")
    assert 'viewBox="0 0 1600 1000"' in sheet
    assert 'preserveAspectRatio="xMidYMax slice"' in sheet
    assert 'stroke="currentColor"' in sheet
    assert not re.search(r'stroke="#', sheet), "a line carries a colour of its own"
    # The faces of a cube wear the frame's colour; every other path is bare.
    fills = set(re.findall(r'fill="([^"]+)"', sheet))
    assert fills == {"none", "var(--frame, #353634)"}, fills
    assert sheet.count("<path") > 60, "the stairs are missing"


def test_the_dark_matter_frame_is_one_flat_colour_in_the_looks_ink():
    assert _value(DARK_MATTER, "--frame") == DARK_MATTER_FRAME
    assert _value(DARK_MATTER, "--vek") == DARK_MATTER_INK


def test_the_net_covers_the_frame_and_takes_its_ink_from_the_look():
    sheet = NET.read_text(encoding="utf-8")
    assert 'viewBox="0 0 1600 1000"' in sheet
    assert 'preserveAspectRatio="xMidYMid slice"' in sheet
    assert 'stroke="currentColor"' in sheet
    assert not re.search(r'stroke="#', sheet), "a line carries a colour of its own"
    # The lines are bare; the stars are filled in the same ink.
    assert set(re.findall(r'fill="([^"]+)"', sheet)) == {"none", "currentColor"}
    assert sheet.count(" Z") > 100, "the stars are missing"
