"""The picture studio of the phone: its own surface, its own mask page, and the
fingers on a picture.

Two kinds of test. The shape of the files (what the studio page holds and no
longer holds, the four fields in one row, the mask page's tools and its
primitives, the reader's gestures, the desktop studio left alone) is read from
the sources. The decisions are tried in Node, with no window around them: the
gesture tracker (`pictureGestures.js`), the row of pictures (`pager.js`) and
the sizes (`format.js`) are pure modules, so pointer positions and times go in
and what happened comes out.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"
STUDIO = SRC / "phone/studio"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="no Node on this machine",
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run(driver: str) -> dict:
    """Run a driver in Node from the frontend folder and hand back the JSON
    its last line printed."""
    script = FRONTEND / f"phonestudio-{os.getpid()}.check.mjs"
    script.write_text(driver, encoding="utf-8")
    try:
        run = subprocess.run(
            ["node", script.name], cwd=FRONTEND, capture_output=True, text=True, encoding="utf-8", timeout=60
        )
    finally:
        script.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


# --- The gesture decisions ----------------------------------------------------

GESTURES = """
import { startGestures, NEUTRAL, ZOOM_MAX } from './src/lib/pictureGestures.js'

const box = { left: 0, top: 0, width: 400, height: 800 }
const stage = () => ({ w: 400, h: 800 })
const natural = () => ({ w: 1200, h: 2400 })
const shown = () => ({ w: 400, h: 800 })
const kinds = (list) => list.map((effect) => effect.kind)
const make = (extra = {}) => startGestures({ stageSize: stage, natural, shown, ...extra })

function pinch(tracker, from, to) {
  tracker.down(1, 200 - from, 400, 0, box)
  tracker.down(2, 200 + from, 400, 0, box)
  const out = tracker.move(2, 200 + to, 400)
  tracker.up(2, 200 + to, 400, 50)
  tracker.up(1, 200 - from, 400, 60)
  return out
}

const report = {}

// Two fingers pull apart: the picture grows, and never past the limit.
{
  const tracker = make()
  const out = pinch(tracker, 40, 80)
  report.pinchZoom = tracker.view.zoom
  const far = make()
  pinch(far, 20, 190)
  report.pinchMax = far.view.zoom
  report.pinchLimit = ZOOM_MAX
  report.pinchEffect = kinds(out)
}

// Two fingers together again: back to the whole picture, in the middle.
{
  const tracker = make()
  tracker.down(1, 160, 400, 0, box)
  tracker.down(2, 240, 400, 0, box)
  tracker.move(2, 320, 400)
  tracker.move(2, 240, 400)
  report.pinchBack = tracker.view
}

// A double tap goes to the picture's own size, and a second one fits it again.
{
  const tracker = make()
  tracker.down(1, 200, 400, 0, box)
  const firstTap = tracker.up(1, 200, 400, 80)
  tracker.down(1, 202, 401, 160, box)
  const second = tracker.up(1, 202, 401, 230)
  report.firstTap = kinds(firstTap)
  report.second = kinds(second)
  report.doubleZoom = tracker.view.zoom
  tracker.down(1, 200, 400, 1000, box)
  tracker.up(1, 200, 400, 1060)
  tracker.down(1, 200, 400, 1120, box)
  tracker.up(1, 200, 400, 1180)
  report.doubleBack = tracker.view
}

// Two taps far apart in time stay two taps.
{
  const tracker = make()
  tracker.down(1, 200, 400, 0, box)
  tracker.up(1, 200, 400, 60)
  tracker.down(1, 200, 400, 900, box)
  report.slowTaps = kinds(tracker.up(1, 200, 400, 960))
}

// A finger held still is a long press; one that moved is not.
{
  const tracker = make()
  tracker.down(1, 200, 400, 0, box)
  report.holdStill = kinds(tracker.hold())
  report.holdTwice = kinds(tracker.hold())
  report.afterLong = kinds(tracker.up(1, 200, 400, 900))
  const moved = make()
  moved.down(1, 200, 400, 0, box)
  moved.move(1, 260, 400)
  report.holdMoved = kinds(moved.hold())
  const two = make()
  two.down(1, 150, 400, 0, box)
  two.down(2, 250, 400, 0, box)
  report.holdTwoFingers = kinds(two.hold())
}

// A swipe to the side steps, a swipe down closes — where the page asks for it.
{
  const reader = make({ swipe: true })
  reader.down(1, 320, 400, 0, box)
  reader.move(1, 200, 405)
  report.swipeLeft = reader.up(1, 100, 410, 180)
  reader.down(1, 80, 400, 300, box)
  reader.move(1, 200, 400)
  report.swipeRight = reader.up(1, 320, 400, 480)
  reader.down(1, 200, 300, 600, box)
  reader.move(1, 205, 420)
  report.swipeDown = kinds(reader.up(1, 210, 520, 780))
  reader.down(1, 200, 300, 900, box)
  reader.move(1, 205, 420)
  report.slowDown = kinds(reader.up(1, 200, 560, 2200))
  const quiet = make({ swipe: false })
  quiet.down(1, 320, 400, 0, box)
  quiet.move(1, 200, 400)
  report.swipeOff = kinds(quiet.up(1, 100, 400, 180))
  const zoomed = make({ swipe: true })
  pinch(zoomed, 40, 120)
  zoomed.down(1, 320, 400, 2000, box)
  zoomed.move(1, 200, 400)
  report.swipeZoomed = kinds(zoomed.up(1, 100, 400, 2180))
}

// One finger moves a zoomed picture, and not beyond its edge.
{
  const tracker = make()
  pinch(tracker, 40, 120)
  const zoom = tracker.view.zoom
  tracker.down(1, 200, 400, 5000, box)
  tracker.move(1, 260, 430)
  report.dragMoved = tracker.view.x > 0 && tracker.view.y > 0
  for (let step = 0; step < 40; step += 1) tracker.move(1, 260 + step * 40, 430)
  const edge = ((zoom - 1) * 400) / 2
  report.dragEdge = Math.abs(tracker.view.x - edge) < 0.001
  report.dragZoomKept = tracker.view.zoom === zoom
}

// The mask page: one finger paints, a second one voids the stroke, two never paint.
{
  const tracker = make({ paint: true })
  report.paintStart = kinds(tracker.down(1, 100, 200, 0, box))
  report.paintMove = kinds(tracker.move(1, 120, 220))
  report.paintEnd = kinds(tracker.up(1, 130, 230, 100))
  const two = make({ paint: true })
  two.down(1, 100, 200, 0, box)
  report.paintCancel = kinds(two.down(2, 300, 200, 10, box))
  report.paintTwoMove = kinds(two.move(2, 340, 200))
  report.paintTwoMoved = two.view.zoom > 1
  report.paintHold = kinds(make({ paint: true }).hold())
}

// A reset puts the view back; a cancel clears the fingers.
{
  const tracker = make()
  pinch(tracker, 40, 100)
  report.resetView = tracker.reset()[0].view
  tracker.down(1, 10, 10, 0, box)
  tracker.cancel()
  report.cancelled = tracker.touching
  report.neutral = NEUTRAL
}

console.log(JSON.stringify(report))
"""


@needs_node
def test_gestures_decide_what_the_fingers_mean():
    report = _run(GESTURES)

    # Two fingers: the picture grows and stops at the limit.
    assert 1 < report["pinchZoom"] <= report["pinchLimit"]
    assert report["pinchMax"] == report["pinchLimit"]
    assert report["pinchEffect"] == ["view"]
    assert report["pinchBack"] == {"zoom": 1, "x": 0, "y": 0}

    # A double tap: own size, then fitted again.
    assert report["firstTap"] == ["tap"]
    assert report["second"] == ["double"]
    assert report["doubleZoom"] == pytest.approx(3.0)
    assert report["doubleBack"] == {"zoom": 1, "x": 0, "y": 0}
    assert report["slowTaps"] == ["tap"]

    # A long press only where one finger stays put.
    assert report["holdStill"] == ["long"]
    assert report["holdTwice"] == []
    assert report["afterLong"] == []
    assert report["holdMoved"] == []
    assert report["holdTwoFingers"] == []

    # Swipes: sideways steps, down closes, none where the page does not ask,
    # none on a zoomed picture, none when it takes too long.
    assert [effect["kind"] for effect in report["swipeLeft"]] == ["swipe"]
    assert report["swipeLeft"][0]["step"] == 1
    assert report["swipeRight"][0]["step"] == -1
    assert report["swipeDown"] == ["swipe-down"]
    assert report["slowDown"] == []
    assert report["swipeOff"] == []
    assert report["swipeZoomed"] == []

    # A zoomed picture follows one finger, and stops at its edge.
    assert report["dragMoved"] is True
    assert report["dragEdge"] is True
    assert report["dragZoomKept"] is True

    # The mask page paints with one finger and never with two.
    assert report["paintStart"] == ["paint-start"]
    assert report["paintMove"] == ["paint-move"]
    assert report["paintEnd"] == ["paint-end"]
    assert report["paintCancel"] == ["paint-cancel"]
    assert report["paintTwoMove"] == ["view"]
    assert report["paintTwoMoved"] is True
    assert report["paintHold"] == []

    assert report["resetView"] == {"zoom": 1, "x": 0, "y": 0}
    assert report["cancelled"] is False


# --- The row of pictures and the sizes ---------------------------------------

LISTS = """
import { pagesOf, tilesOf, shownIndex, pageAt, dotsOf } from './src/phone/studio/pager.js'
import { FORMATS, formatPair, chosenFormat, longEdge, sizeLabel, sameShape, fitInto } from './src/phone/studio/format.js'

const report = {}
const names = ['c.png', 'b.png', 'a.png']
const running = { id: 7 }
const waiting = [{ id: 8 }, { id: 9 }]

report.pagesAll = pagesOf({ running, original: 'a.png', names }).map((page) => page.key)
report.pagesNone = pagesOf({ running: null, original: '', names: [] })
report.tilesAll = tilesOf({ running, waiting, original: 'a.png', names }).map((tile) => tile.key)
report.tilesOriginal = tilesOf({ running: null, waiting: [], original: 'a.png', names })
  .map((tile) => [tile.key, Boolean(tile.original)])

const pages = pagesOf({ running: null, original: '', names })
report.shownArea = shownIndex(pages, 'b.png')
report.shownNone = shownIndex(pages, '')
report.shownRunning = shownIndex(pagesOf({ running, original: '', names }), '')
report.shownMissing = shownIndex(pages, 'zzz.png')
report.heldPages = pagesOf({ running: null, held: 'chat.png', original: '', names }).map((page) => page.key)
report.heldInList = pagesOf({ running: null, held: 'b.png', original: '', names }).map((page) => page.key)
report.heldIsOriginal = pagesOf({ running: null, held: 'a.png', original: 'a.png', names }).map((page) => page.key)
report.heldTiles = tilesOf({ running, waiting, held: 'chat.png', original: '', names }).map((tile) => tile.key)
report.heldShown = shownIndex(pagesOf({ running: null, held: 'chat.png', original: '', names }), 'chat.png')
report.shownEmpty = shownIndex([], 'a.png')
report.pageAt = [pageAt(0, 300, 3), pageAt(160, 300, 3), pageAt(9000, 300, 3), pageAt(10, 0, 3), pageAt(10, 300, 0)]
report.dots = [dotsOf(1, 0), dotsOf(5, 2), dotsOf(30, 0), dotsOf(30, 15), dotsOf(30, 29)]

report.pairs = FORMATS.map((format) => formatPair(format, 512))
report.chosen = [chosenFormat(512, 512), chosenFormat(384, 512), chosenFormat(500, 512), chosenFormat(0, 0)]
report.longEdge = [longEdge(0, 384, 512), longEdge(512, 64, 64), longEdge(0, 0, 0), longEdge(0, 500, 100)]
report.label = sizeLabel(384, 512)
report.same = [sameShape(1024, 1536, 512, 768), sameShape(1024, 1024, 512, 768)]
report.fit = fitInto(1000, 500, 400, 400)

console.log(JSON.stringify(report))
"""


@needs_node
def test_the_row_of_pictures_and_the_sizes():
    report = _run(LISTS)

    # The picture drawing now first, then the original, then the drawn ones —
    # the original once, though it is among the drawn ones as well.
    assert report["pagesAll"] == ["run:7", "pic:a.png", "pic:c.png", "pic:b.png"]
    assert report["pagesNone"] == []
    # The waiting ones have a tile and no page, and stand behind the running one.
    assert report["tilesAll"] == ["run:7", "wait:8", "wait:9", "pic:a.png", "pic:c.png", "pic:b.png"]
    assert report["tilesOriginal"][0] == ["pic:a.png", True]
    assert report["tilesOriginal"][1] == ["pic:c.png", False]

    assert report["shownArea"] == 1
    # No picture in the area: the picture drawing now is on show, else the
    # surface is empty (as where the picture was taken out of the area).
    assert report["shownNone"] == -1
    assert report["shownRunning"] == 0
    assert report["shownMissing"] == -1
    # A picture chosen from the chat or a folder has its page and its tile,
    # first among the finished ones; one the studio holds has no second.
    assert report["heldPages"] == ["pic:chat.png", "pic:c.png", "pic:b.png", "pic:a.png"]
    assert report["heldInList"] == ["pic:c.png", "pic:b.png", "pic:a.png"]
    assert report["heldIsOriginal"] == ["pic:a.png", "pic:c.png", "pic:b.png"]
    assert report["heldTiles"] == ["run:7", "wait:8", "wait:9", "pic:chat.png", "pic:c.png", "pic:b.png", "pic:a.png"]
    assert report["heldShown"] == 0
    assert report["shownEmpty"] == -1
    assert report["pageAt"] == [0, 1, 2, 0, 0]
    assert report["dots"] == [
        {"dots": 0, "at": -1},
        {"dots": 5, "at": 2},
        {"dots": 7, "at": 0},
        {"dots": 7, "at": 3},
        {"dots": 7, "at": 6},
    ]

    # A tile sets the long edge and works the short one out on the grid of 64.
    assert report["pairs"] == [
        [512, 512], [384, 512], [512, 384], [384, 512], [512, 384], [320, 512], [512, 320],
    ]
    assert report["chosen"] == [[1, 1], [3, 4], None, None]
    assert report["longEdge"] == [512, 512, 0, 512]
    assert report["label"] == "384 × 512"
    assert report["same"] == [True, False]
    assert report["fit"]["zoom"] == pytest.approx(0.4)
    assert report["fit"]["x"] == pytest.approx(0)
    assert report["fit"]["y"] == pytest.approx(100)


# --- The studio page ----------------------------------------------------------


def test_the_studio_page_has_a_surface_of_its_own():
    page = _source(SRC / "phone/pages/Studio.svelte")

    # No desktop studio inside the phone page.
    assert "import ImageStudio" not in page and "<ImageStudio" not in page
    assert "import StudioCanvas" not in page and "<StudioCanvas" not in page
    # The surface, the strip, the foot, the mask page.
    for part in ("Area", "Strip", "Compose", "Mask", "PictureSheet", "InfoSheet"):
        assert re.search(rf"import {part} from '\.\./studio/{part}\.svelte'", page), part
    # The fine settings stand under a sign at the right end of the head.
    assert "headRightSet" in page
    assert "StudioBasics" in page and "StudioDetails" in page


def test_the_foot_has_four_equal_fields_and_one_line():
    foot = _source(STUDIO / "Compose.svelte")

    chips = re.findall(r'<button class="chip"', foot)
    assert len(chips) == 4
    assert "grid-template-columns: repeat(4, 1fr)" in foot
    # Each field opens exactly the choice it names; the mask opens its page.
    for sheet in ("'size'", "'style'", "'negative'"):
        assert f"sheet = {sheet}" in foot
    assert "onmask?.()" in foot
    # The one line: the picture, the prompt, improve, draw.
    for name in ("chooseFile", "bind:value={werte.prompt}", "improve", "studioZeichnen"):
        assert name in foot


def test_the_mask_page_has_its_tools_and_the_desktop_primitives():
    page = _source(STUDIO / "Mask.svelte")

    # The same primitives the desktop mask is made of, the same place it writes to.
    assert "from '../../lib/maske.js'" in page
    assert "werte.maske" in page
    assert "surface.maskOn" in page and "surface.masked" in page
    # Four tools with words, one brush slider, undo and redo, Cancel and Done.
    for tool in ("pinsel", "radierer", "umkehren", "leeren"):
        assert f"'{tool}'" in page, tool
    for word in ("maske.pinsel", "maske.radierer", "maske.umkehren", "maske.leeren"):
        assert word in page, word
    assert 'aria-orientation="vertical"' in page
    assert "SubHead" in page and "backText=" in page and "right={{" in page
    # One finger paints, two fingers move and zoom.
    assert "paint" in page and "use:gestures" in page


def test_the_reader_hears_the_fingers():
    reader = _source(SRC / "teile/Bildschau.svelte")
    action = _source(SRC / "lib/pictureGesturesAction.js")
    gestures = _source(SRC / "lib/pictureGestures.js")

    assert "use:gestures" in reader
    assert "swipe: true" in reader
    assert "onswipedown: closeReader" in reader
    assert "openPictureMenu" in reader
    assert "<PictureSheet reader={true} />" in reader
    # Two fingers, a double tap, a long press, a swipe down.
    for effect in ("pinchView", "doubleTapView", "LONG_TIME", "swipedDown"):
        assert effect in gestures
    # A mouse keeps the browser's own clicks and drags.
    assert "event.pointerType !== 'mouse'" in action


def test_a_touch_that_begins_on_a_video_is_the_videos_own():
    action = _source(SRC / "lib/pictureGesturesAction.js")
    reader = _source(SRC / "teile/Bildschau.svelte")

    assert "closest?.('video')" in action
    assert "!fingerOnly(event) || onVideo(event)" in action
    # The ground around a video hears the swipes: the stage stands round it.
    assert re.search(r'<div class="stage"[^>]*use:gestures[^>]*>\s*(<!--.*?-->\s*)*<video', reader, re.S)


def test_the_picture_menu_has_the_desktop_entries():
    sheet = _source(STUDIO / "PictureSheet.svelte")
    desktop = _source(SRC / "teile/StudioPictureMenu.svelte")

    for action in ("alsEingabe", "zuVideo", "infosZeigen", "nachbessern", "hochskalieren"):
        assert action in sheet, action
        assert action in desktop, action
    assert "bildEntfernen" in sheet
    # A long-pressed picture of the reader leaves it for the studio.
    assert "closeReader()" in sheet and "pageOpen('studio')" in sheet


# --- The desktop is left as it was -------------------------------------------


@pytest.mark.parametrize("name", ["ImageStudio.svelte", "StudioCanvas.svelte", "StudioGallery.svelte"])
def test_the_desktop_studio_does_not_know_the_phone_parts(name):
    source = _source(SRC / "teile" / name)

    for word in ("pictureGestures", "pictureMenu", "phone/studio", "headRightSet"):
        assert word not in source, f"{name} mentions {word}"


def test_the_head_and_the_sheet_stay_as_they_were_without_the_new_parts():
    frame = _source(SRC / "phone/PageFrame.svelte")
    sheet = _source(SRC / "phone/Sheet.svelte")
    head = _source(SRC / "phone/head.svelte.js")

    # An inner page with neither a word nor a button draws the arrow and no
    # right end; a sheet without a layer keeps its old height.
    assert "{#if inner?.backText}" in frame and "{:else}" in frame
    assert "{#if right}" in frame
    assert "layer = 40" in sheet
    assert "right: null" in head


def test_the_sign_at_the_right_end_goes_with_the_page_that_set_it():
    head = _source(SRC / "phone/head.svelte.js")

    # The store hands back a proxy of what was put in, so what stands there is
    # told by a copy kept outside it — never by comparing with the store.
    assert "rightEntry === entry" in head
    assert "head.right === entry" not in head
