"""The studio opens with the hand and with the mask off, and a mask that is
switched off goes nowhere.

The switch "Mask" is `surface.maskOn` (`frontend/src/lib/studio.svelte.js`),
kept by the drawing surface (`frontend/src/teile/StudioCanvas.svelte`). Off,
the mask is not shown, is not part of the request the studio sends, and is
not one of the things "auto" goes by; on, it is shown and acts. The drawing
module and the studio's values run for real in node (the harness of
`tests/studio_test_run.py`); the surface is read off its source.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.studio_test_run import needs_node
from tests.studio_test_run import run as _run

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
CANVAS = (FRONTEND / "src/teile/StudioCanvas.svelte").read_text(encoding="utf-8")
STUDIO = (FRONTEND / "src/lib/studio.svelte.js").read_text(encoding="utf-8")

# A picture lies in the area and the next press draws from it; the surface's
# hand-over names a mask file the way a painted mask would.
SETUP = """
    stubs.mounted()
    await settled()
    studio.werte.prompt = 'a cat on a roof'
    studio.werte.modell = 'picture-model'
    studio.werte.startbild = 'in.png'
    studio.auswahl.art = 'img2img'
    studio.leinwand.ausgeben = async (name, withMask) => ({
      startbild: 'cut.png', maske: withMask ? 'painted.png' : null, place: null,
    })
"""


def _wish_mask(switch: str, stored: str = "") -> str:
    """The mask the request names when the press is made with the switch as
    given and `stored` as the mask the studio holds."""
    report = _run(
        f"""{SETUP}
    studio.werte.maske = {stored!r}
    studio.surface.maskOn = {switch}
    await draw.studioZeichnen()
    await settled()
    return {{ maske: wishes[0].maske }}
"""
    )
    return report["maske"]


@needs_node
def test_a_mask_switched_off_is_not_part_of_the_request():
    assert _wish_mask("false") is None


@needs_node
def test_a_mask_switched_on_goes_with_the_request():
    """Silence probe: on, the painted mask goes as it did."""
    assert _wish_mask("true") == "painted.png"


@needs_node
def test_the_mask_a_chat_stored_goes_only_when_the_switch_is_on():
    """The surface hands over no mask of its own here, the studio holds one:
    off it goes nowhere, on it goes as before."""
    report = _run(
        """
    stubs.mounted()
    await settled()
    studio.werte.prompt = 'a cat on a roof'
    studio.werte.modell = 'picture-model'
    studio.werte.startbild = 'in.png'
    studio.auswahl.art = 'img2img'
    studio.leinwand.ausgeben = async () => ({ startbild: 'cut.png', maske: null, place: null })
    studio.werte.maske = 'stored.png'
    studio.surface.maskOn = false
    await draw.studioZeichnen()
    await settled()
    const off = wishes[0].maske
    studio.surface.maskOn = true
    await draw.studioZeichnen()
    await settled()
    return { off, on: wishes[1].maske }
    """
    )
    assert report == {"off": None, "on": "stored.png"}


@needs_node
def test_auto_counts_a_mask_only_while_the_switch_is_on():
    """A mask is painted on the picture in the area: "auto" draws from the
    picture then. With the switch off it draws from the text."""
    report = _run(
        """
    stubs.mounted()
    await settled()
    studio.werte.startbild = 'in.png'
    studio.auswahl.art = 'auto'
    studio.werte.staerke = 1
    studio.surface.masked = true
    studio.surface.maskOn = false
    const off = studio.autoKind()?.value ?? null
    studio.surface.maskOn = true
    const on = studio.autoKind()?.value ?? null
    return { off, on }
    """
    )
    assert report["on"] == "img2img"
    assert report["off"] != "img2img"


def test_the_surface_opens_with_the_hand_and_the_switch_off():
    assert "let werkzeug = $state('hand')" in CANVAS
    assert "export const surface = $state({ masked: false, maskOn: false })" in STUDIO
    # The switch is the studio's state, not one of the surface alone.
    assert "maskeSichtbar" not in CANVAS
    assert re.search(r"<Schalter an=\{surface\.maskOn\} onschalten=\{\(an\) => \(surface\.maskOn = an\)\}", CANVAS)
    assert "style:opacity={surface.maskOn ? toenung : 0}" in CANVAS


def test_a_picture_laid_into_the_area_chooses_the_hand_and_switches_the_mask_off():
    """The area's picture is told by its name: a name that is new, and only
    that, takes the tools back to the hand and the mask to off."""
    effect = re.search(
        r"let eingelegt = ''\n  \$effect\(\(\) => \{\n(.*?)\n  \}\)\n", CANVAS, re.S
    )
    assert effect, "the effect that follows the picture of the area is gone"
    body = effect.group(1)
    assert "const name = werte.startbild" in body
    assert "if (name && name !== eingelegt)" in body
    assert "werkzeug = 'hand'" in body
    assert "surface.maskOn = false" in body


def test_the_switch_goes_back_to_off_when_the_surface_goes():
    """Its own effect, so the reset runs only when the surface is taken
    down, not with every change of what the other effect reads."""
    assert "$effect(() => () => {\n    surface.maskOn = false\n  })" in CANVAS


def test_the_hand_over_to_the_service_takes_the_mask_only_while_it_is_on():
    assert "if (mitMaske && surface.maskOn && maske?.flaeche && bemalt(maske.flaeche))" in CANVAS
    # A change of the switch is a change of what the last hand-over was made of.
    assert re.search(r"natur, stand, surface\.maskOn,\n", CANVAS)
