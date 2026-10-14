"""The studio's empty area stands like a fresh one, whichever way it became empty
(`frontend/src/teile/StudioCanvas.svelte`).

The size of a picture counts only while the area shows that very picture. A
load that finishes after the area went empty (the chat was changed, the studio
reopened on a chat without pictures) used to leave the old size behind: the
rail's mask buttons stood live and the surface caught the pointer, so a click
on the picture plaque never reached the file dialog.
"""

from __future__ import annotations

import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = (WURZEL / "frontend/src/teile/StudioCanvas.svelte").read_text(encoding="utf-8")


def _rumpf(name: str) -> str:
    treffer = re.search(rf"\n  function {name}\(.*?\n  \}}\n", QUELLE, re.S)
    assert treffer, f"{name}() not found"
    return treffer.group(0)


def test_the_size_is_derived_from_the_address_it_was_measured_for():
    assert "let natur = $state" not in QUELLE, "the size is a plain state again"
    derived = re.search(r"const natur = \$derived\((.*?)\n  \)\n", QUELLE, re.S)
    assert derived, "the picture's size is no longer derived"
    # Both halves: there is a picture, and it is the one that was measured.
    assert "bildUrl && gemessen.url === bildUrl" in derived.group(1)
    assert "{ w: 0, h: 0 }" in derived.group(1)


def test_a_load_that_ends_after_the_area_left_the_picture_measures_nothing():
    rumpf = _rumpf("bildGeladen")
    guard = rumpf.index("if (!bildUrl || loaded !== bildUrl) return")
    # Before anything is stored or fitted.
    assert guard < rumpf.index("gemessen = {")
    assert guard < rumpf.index("einpassen()")
    assert guard < rumpf.index("maskeHolen()")


def test_a_size_is_stored_with_its_address_and_forgotten_with_the_picture():
    rumpf = _rumpf("bildGeladen")
    assert re.search(r"gemessen = \{ url: loaded, w: knoten\.naturalWidth, h: knoten\.naturalHeight \}", rumpf)
    effect = re.search(r"\$effect\(\(\) => \{\n    if \(!bildUrl\) \{\n(.*?)\n    \}\n  \}\)", QUELLE, re.S)
    assert effect, "the effect that empties the area's state is gone"
    assert "gemessen = { url: '', w: 0, h: 0 }" in effect.group(1)
    assert "maske = null" in effect.group(1)


def test_replacing_a_picture_of_the_same_size_still_keeps_the_view():
    """Silence probe: what the previous picture measured is read before it is
    overwritten, so a finished picture of the same size does not fit again."""
    rumpf = _rumpf("bildGeladen")
    assert rumpf.index("const replaced = { w: gemessen.w, h: gemessen.h }") < rumpf.index("gemessen = {")
    assert "replaced.w === natur.w && replaced.h === natur.h" in rumpf


def test_with_a_picture_the_surface_still_catches_the_pointer_for_hand_and_brush():
    """Silence probe: the catch is still tied to a size, so with a picture
    the hand and the brush work as before."""
    rumpf = _rumpf("fassen")
    assert rumpf.splitlines()[2].strip() == "if (!natur.w || ereignis.button !== 0) return"
    assert "setPointerCapture" in rumpf
