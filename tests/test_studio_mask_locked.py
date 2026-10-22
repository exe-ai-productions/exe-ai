"""A mask that is switched off is locked, not hidden and kept painting.

The switch "Mask" is `surface.maskOn` (`frontend/src/lib/studio.svelte.js`).
Off, the brush and the eraser leave no mark, their ring on the surface is
gone, and invert and clear rest; what was painted before stays and shows when
the switch goes on. The rule is `frontend/src/lib/maskLock.js`, run here
in node; the surface that asks it is read off its source
(`frontend/src/teile/StudioCanvas.svelte`) — the pixels themselves are
painted by the browser's canvas, which node does not have.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
RULE = FRONTEND / "src/lib/maskLock.js"
CANVAS = (FRONTEND / "src/teile/StudioCanvas.svelte").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _rule(expression: str):
    """Evaluates ``expression`` in node with the rule's two functions in
    scope, and returns what it gives, read as JSON."""
    program = (
        f"import {{ paintAllowed, layerChangeable }} from {RULE.as_uri()!r};"
        f"console.log(JSON.stringify({expression}));"
    )
    done = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert done.returncode == 0, done.stderr[-1500:]
    return json.loads(done.stdout)


@needs_node
@pytest.mark.parametrize("tool", ["pinsel", "radierer"])
def test_brush_and_eraser_paint_only_with_the_switch_on(tool):
    assert _rule(f"paintAllowed({tool!r}, false)") is False
    assert _rule(f"paintAllowed({tool!r}, true)") is True


@needs_node
def test_the_hand_never_paints_whatever_the_switch_says():
    """Silence probe: the hand is no painting tool, on or off."""
    assert _rule("[paintAllowed('hand', true), paintAllowed('hand', false)]") == [False, False]


@needs_node
def test_invert_and_clear_need_a_picture_and_the_switch_on():
    assert _rule("layerChangeable(false, 800)") is False
    assert _rule("layerChangeable(true, 0)") is False
    assert _rule("layerChangeable(true, 800)") is True


def test_the_surface_asks_the_rule_before_it_paints_and_before_it_changes_the_layer():
    # What the rule is asked with: the tool and the switch, the switch and the picture.
    assert "const mayPaint = $derived(paintAllowed(werkzeug, surface.maskOn))" in CANVAS
    assert "const layerFree = $derived(layerChangeable(surface.maskOn, natur.w))" in CANVAS
    # The press: no stroke is begun, so no pixel and no step for "back".
    press = re.search(r"\n  function fassen\(ereignis\) \{.*?\n  \}\n", CANVAS, re.S)
    assert press and "if (!mayPaint || !maske?.flaeche) return" in press.group(0)
    assert "if (!malt || !maske?.flaeche) return" not in press.group(0)
    # Invert and clear.
    whole = re.search(r"\n  function ganzeMaske\(art\) \{.*?\n  \}\n", CANVAS, re.S)
    assert whole and "if (!layerFree || !maske?.flaeche) return" in whole.group(0)


def test_a_stroke_under_a_switch_that_goes_off_ends_as_one_step():
    move = re.search(r"\n  function ziehen\(ereignis\) \{.*?\n  \}\n", CANVAS, re.S)
    assert move
    body = move.group(0)
    assert "if (!mayPaint) {" in body
    # Drawn so far is one step, the rest leaves no mark.
    assert body.index("if (!mayPaint) {") < body.index("strich(maske.flaeche")
    assert "merken(laufenderStrich)" in body.split("if (!mayPaint) {", 1)[1].split("}", 1)[0]


def test_the_ring_and_the_painting_cursor_go_with_the_lock():
    assert "{#if zeiger && mayPaint && !schiebend && natur.w}" in CANVAS
    assert "class:malt={mayPaint && !schiebend && natur.w}" in CANVAS


def test_the_buttons_rest_with_the_switch_and_keep_their_label():
    rail = CANVAS.split('<div class="werkzeuge glas" role="toolbar"', 1)[1].split("</div>", 1)[0]
    assert "<button onclick={() => ganzeMaske('umkehren')} disabled={!layerFree} " in rail
    assert "<button onclick={() => ganzeMaske('leeren')} disabled={!layerFree || !etwasGemalt}" in rail
    # The labels are the ones they had.
    assert "title={t('maske.umkehren')}" in rail and "title={t('maske.leeren')}" in rail


def test_the_bar_with_the_switch_still_stands_while_the_brush_is_picked_and_the_mask_is_off():
    """The switch is reached from the bar of the brush and the eraser, which
    stands whatever the switch says: a locked tool would leave no way to turn
    the mask on."""
    assert "const malt = $derived(werkzeug === 'pinsel' || werkzeug === 'radierer')" in CANVAS
    assert "{#if malt}\n    <div class=\"oben\" class:zeile={brushRow}>" in CANVAS
    assert re.search(r"<Schalter an=\{surface\.maskOn\} onschalten=\{\(an\) => \(surface\.maskOn = an\)\}", CANVAS)


def test_a_mask_painted_before_stays_whatever_the_switch_says():
    """Silence probe: the switch changes what is shown and what goes with
    the request, never the layer itself — nothing in the switch's handlers
    touches the strokes."""
    handler = re.search(r"onschalten=\{\(an\) => \(surface\.maskOn = an\)\}", CANVAS)
    assert handler
    assert "style:opacity={surface.maskOn ? toenung : 0}" in CANVAS
