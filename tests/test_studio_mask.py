"""The pointer maths of the studio's mask layer
(`frontend/src/teile/StudioCanvas.svelte`, `frontend/src/lib/maske.js`)."""

from __future__ import annotations

import json
import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "frontend/src/teile/StudioCanvas.svelte"


def _rumpf(name: str) -> str:
    """One function's body, from its `function <name>(` to its closing
    brace on the script block's own indent."""
    quelle = QUELLE.read_text()
    treffer = re.search(rf"\n  function {name}\(.*?\n  \}}\n", quelle, re.S)
    assert treffer, f"{name}() not found"
    return treffer.group(0)


def test_the_pointer_on_the_surface_takes_the_zoom_out():
    """The surface steps put `zoom: 1.25` / `1.5` on `#wurzel`
    (`frontend/src/stil/global.css`). Under an ancestor zoom a MEASURED
    rectangle and an absolutely placed child's `left` stop being the same
    unit: a child placed at `left:100px` sits 125 away from its container's
    measured edge at 1.25 and 150 at 1.5.

    `aufDerFlaeche()` feeds a measured distance into the brush ring's
    `left`/`top`, so without dividing the zoom back out the ring is pushed
    off the pointer by (zoom-1) x its distance from the surface's top left
    corner. Since the ring is where the brush paints, that reads as the
    mask painting somewhere the pointer is not.

    The painting itself is never wrong: `aufFlaeche()` in lib/maske.js is a
    pure RATIO of the measured box, and a ratio cancels any zoom. Only the
    ring can drift."""
    rumpf = _rumpf("aufDerFlaeche")
    assert "offsetWidth" in rumpf, (
        "aufDerFlaeche no longer reads the effective zoom back from the element itself "
        "-- the brush ring drifts again on the large/larger steps"
    )
    for achse, kante in (("clientX", "left"), ("clientY", "top")):
        assert re.search(rf"\(ereignis\.{achse} - kasten\.{kante}\) / faktor", rumpf), (
            f"{achse} is no longer divided by the zoom"
        )


def test_the_brush_ring_is_not_zoomed_twice():
    """The ring's size is set in `px` inside the zoomed box, so a scale
    read from a MEASURED rectangle would be applied a second time and draw
    the brush (zoom)x too fat. It is the brush size times the view's own
    zoom and the picture's scale, all layout values."""
    quelle = QUELLE.read_text()
    ring = re.search(r"\{@const d = ([^}]*)\}\s*<div class=\"pinselring\"", quelle)
    assert ring, "the brush ring no longer reads as expected"
    assert ring.group(1) == "groesse * lage.zoom * bereich.s"
    assert "getBoundingClientRect" not in ring.group(1)


def test_das_malen_bleibt_ein_reines_verhaeltnis():
    """The silence half: `aufFlaeche()` must NOT grow a zoom correction.
    It divides by the measured width and multiplies by the picture's, so
    the zoom cancels on its own. A correction here would introduce the
    very error it looks like it is preventing."""
    quelle = (WURZEL / "frontend/src/lib/maske.js").read_text()
    treffer = re.search(r"export function aufFlaeche\(.*?\n\}", quelle, re.S)
    assert treffer, "aufFlaeche() not found"
    rumpf = treffer.group(0)
    assert "offsetWidth" not in rumpf and "faktor" not in rumpf, (
        "aufFlaeche got a zoom correction -- it is a pure "
        "ratio, the zoom cancels itself out there"
    )
    assert "/ kasten.width) * flaeche.width" in rumpf, (
        "aufFlaeche no longer computes as a ratio"
    )


def _body(source: Path, name: str) -> str:
    """One function's body in another file's script block, async or not."""
    found = re.search(rf"\n  (?:async )?function {name}\(.*?\n  \}}\n", source.read_text(encoding="utf-8"), re.S)
    assert found, f"{name}() not found in {source.name}"
    return found.group(0)


def test_the_wheel_over_the_surface_never_reaches_the_page():
    """The generation area never changes size or place. A wheel the surface
    did not take is the page's: with Ctrl or a pinch the browser zooms the
    whole page, area included. So the wheel is stopped before anything can
    return — with no picture in the area too."""
    wheel = _rumpf("radeln")
    assert wheel.index("ereignis.preventDefault()") < wheel.index("return")
    source = QUELLE.read_text(encoding="utf-8")
    assert 'onwheel={radeln}' in source
    # A pinch over what floats on the surface — the tools, the row of
    # pictures, the prompt bar — is stopped by the studio itself; a plain
    # wheel over them is left to them.
    studio = (WURZEL / "frontend/src/teile/ImageStudio.svelte").read_text(encoding="utf-8")
    assert '<div class="studio" onwheel={(e) => { if (e.ctrlKey) e.preventDefault() }}>' in studio
    # The silence check: with a picture the wheel still zooms it about the
    # pointer, by the same step.
    assert "const { x, y } = aufDerFlaeche(ereignis)" in wheel
    assert "zoomen(lage.zoom * Math.exp(-ereignis.deltaY * 0.0016), x, y)" in wheel


def test_fit_and_fill_are_buttons_of_the_tool_rail():
    """ "Fit" shows the whole picture in the middle of the area, "fill"
    covers the area with it. Both are things to do, so they are buttons —
    the last two of the tool rail, "fill" under "fit", resting while there
    is no picture. The zoom list holds percentages only, and the zoom steps
    by one percentage point about the area's middle."""
    source = QUELLE.read_text(encoding="utf-8")
    rail = source.split('<div class="werkzeuge glas" role="toolbar" aria-orientation="vertical"', 1)[1]
    rail = rail.split("</div>", 1)[0]
    fit = ("<button onclick={einpassen} disabled={!natur.w} title={t('maske.ansicht')} "
           "aria-label={t('maske.ansicht')}>")
    fill = ("<button onclick={fill} disabled={!natur.w} title={t('maske.fuellen')} "
            "aria-label={t('maske.fuellen')}>")
    assert rail.index(fit) < rail.index(fill)
    assert rail.rstrip().endswith("</button>") and rail.rindex("<button") == rail.index(fill)
    assert '<MaskenZeichen name="fuellen" groesse={18} />' in rail.split(fill, 1)[1]
    # The list: the steps and where the zoom stands now, nothing else.
    entries = source.split("const zoomEintraege = $derived(", 1)[1].split("\n  )\n", 1)[0]
    assert "[...new Set([...ZOOM_STUFEN, zoomProzent])].sort((a, b) => a - b)" in entries
    assert "maske." not in entries and "'fit'" not in entries and "'fill'" not in entries
    assert "bind:wert={() => zoomProzent, (percent) => zoomAboutCentre(percent / 100)}" in source
    # The silence check: what the two do, and the steps beside the list, are
    # as they were.
    assert "lage = centred(Math.min(gw / natur.w, gh / natur.h))" in _rumpf("einpassen")
    assert "lage = centred(Math.max(gw / natur.w, gh / natur.h))" in _rumpf("fill")
    assert "const zoomStep = (points) => zoomAboutCentre(lage.zoom + points / 100)" in source
    assert "onclick={() => zoomStep(-1)}" in source and "onclick={() => zoomStep(1)}" in source
    for language, text in (("de", "Füllen"), ("en", "Fill")):
        catalogue = json.loads((WURZEL / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        assert catalogue["maske"]["fuellen"] == text


def test_a_picture_off_the_picture_wall_is_laid_on_the_surface():
    """The picture wall drags a picture by its name in a data type of its
    own. The surface takes it as the start picture as it is — it lies in
    the pictures folder already — and only a name of the folder's own
    shape."""
    source = QUELLE.read_text(encoding="utf-8")
    assert "const WALL_PICTURE = 'application/x-exe-bild'" in source
    wall = (WURZEL / "frontend/src/teile/ModulBilder.svelte").read_text(encoding="utf-8")
    assert "setData('application/x-exe-bild', name)" in wall
    dropped = _rumpf("abgelegt")
    assert "ereignis.dataTransfer?.getData(WALL_PICTURE)" in dropped
    assert "if (name) setFromFolder(name)" in dropped
    # The shape of a folder name is the service's own, ending for ending.
    from app.bildfensterwahl import BILDENDUNGEN

    endings = "|".join(e.lstrip(".") for e in BILDENDUNGEN)
    assert f"const FOLDER_NAME = /^[0-9a-f]{{32}}\\.(?:{endings})$/" in source
    by_name = _rumpf("setFromFolder")
    assert "if (!FOLDER_NAME.test(name)) return" in by_name and "startbildWaehlen(name)" in by_name
    assert "bildHochladen" not in by_name
    # The empty area's plaque hands the same on.
    assert "<Bildablage waehlen={setFile} named={setFromFolder} fill />" in source
    plaque = _body(WURZEL / "frontend/src/teile/Bildablage.svelte", "fallenlassen")
    assert "named && ereignis.dataTransfer?.getData('application/x-exe-bild')" in plaque
    # The silence check: a picture file from outside is still uploaded and set.
    assert "else setFile(" in dropped
    upload = _body(QUELLE, "setFile")
    assert "await api.bildHochladen(datei)" in upload and "startbildWaehlen(ergebnis.bild)" in upload


def test_a_file_laid_down_in_the_studio_does_not_hang_on_the_chat_field():
    """The chat field takes every drop in the window. While the studio
    stands in the chat's place, a file laid down goes where it was laid —
    not into the field hidden under it as well."""
    drop = _body(WURZEL / "frontend/src/teile/Eingabeleiste.svelte", "fallenlassen")
    gate = "if (eineSeiteOffen() || studioSichtbar()) return"
    assert gate in drop
    assert drop.index("ereignis.preventDefault()") < drop.index(gate) < drop.index("application/x-exe-bild")
    # The silence check: with the studio shut, a dropped file is attached
    # as before, and so is a picture off the picture wall.
    assert drop.index(gate) < drop.index("anhangSetzen(new File([blob], ausBildwand")
    assert drop.index(gate) < drop.index("for (const datei of [...(ereignis.dataTransfer?.files || [])])")


def test_only_the_open_chat_s_mask_holds_its_layers():
    """A mask layer is as many bytes as four times its picture's pixels.
    Only the open chat's mask keeps its layers: the others give theirs back
    when another chat's values are filled in, and keep the stored mask's
    name and the steps, from which the surface paints the layer again."""
    studio = (WURZEL / "frontend/src/lib/studio.svelte.js").read_text(encoding="utf-8")
    release = studio.split("export function releaseLayers(mask) {", 1)[1].split("\n}\n", 1)[0]
    # Given back at once: a canvas of no size holds no pixels.
    assert "layer.width = 0" in release and "layer.height = 0" in release
    assert "mask.flaeche = null" in release and "mask.grund = null" in release
    # What the layer was is remembered; what it is made of is not touched.
    assert "mask.size = [mask.flaeche.width, mask.flaeche.height]" in release
    assert "verlauf" not in release and "zukunft" not in release and "stored" not in release
    others = studio.split("function releaseOtherMasks(chat) {", 1)[1].split("\n}\n", 1)[0]
    assert "if (owner !== chat) releaseLayers(mask)" in others
    filled = studio.split("export function werteFuellen() {", 1)[1].split("\n}\n", 1)[0]
    assert "releaseOtherMasks(chatanzeige.chatId)" in filled
    # A chat's mask for another picture replaces the old one, whose layers go.
    fetched = studio.split("export function maskeDesChats(chat, bild) {", 1)[1].split("\n}\n", 1)[0]
    assert fetched.index("if (da && da.bild === bild) return da") < fetched.index("if (da) releaseLayers(da)")

    # The surface paints a layer that was given back from what it is made of.
    fetch = _rumpf("maskeHolen")
    assert "const givenBack = !maske.flaeche && Boolean(maske.size) && fits(...maske.size)" in fetch
    assert "if (!givenBack) Object.assign(maske, { stored: werte.maske, verlauf: [], zukunft: [] })" in fetch
    order = [fetch.index(part) for part in (
        "maske.flaeche = malflaeche(natur.w, natur.h)", "if (givenBack) paintLayer()",
        "if (maske.stored) gespeicherteLaden(maske.flaeche, maske.stored)")]
    assert order == sorted(order)
    paint = _rumpf("paintLayer")
    assert "if (maske.grund) maske.flaeche.getContext('2d').drawImage(maske.grund, 0, 0)" in paint
    assert "for (const schritt of maske.verlauf) anwenden(schritt)" in paint
    loaded = _rumpf("gespeicherteLaden")
    assert loaded.index("maske.grund = base") < loaded.index("paintLayer()")
    # The silence check: painting a layer again changes no mask — the mask
    # the chat has stored stays named — while a step back or forward does.
    assert "geaendert()" not in paint and "geaendert()" not in fetch and "geaendert()" not in loaded
    assert "geaendert()" in _rumpf("neuZeichnen")
