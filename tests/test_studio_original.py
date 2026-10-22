"""The studio's row of pictures: the room it keeps free, and the original.

* The generation area leaves the room of the row's bar on the right and as
  much on the left, so it never slides under the bar (`lib/studioArea.js`).
* The picture that last came from outside — a file, one off the picture
  folder — is the studio's original: its tile stays on top of the row and a
  click lays it in the area again, with no mask (`pictureFromOutside` in
  `lib/studio.svelte.js`, `lib/studioRow.js`, `StudioGallery.svelte`).

The studio's own modules run for real in node (`studio_test_run.py`); the
geometry and the row's content are plain modules and run as they are.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app import bildfensterwahl

from tests.studio_test_run import FRONTEND, LIB, needs_node, run

GALLERY = FRONTEND / "src/teile/StudioGallery.svelte"
CANVAS = FRONTEND / "src/teile/StudioCanvas.svelte"
NAME = "a" * 32 + ".png"


def _plain(tmp_path: Path, module: str, script: str):
    """Runs `script` in node with a plain module of the studio imported as
    `m`: the file is copied to `.mjs`, so no package setting is needed."""
    copy = tmp_path / "module.mjs"
    copy.write_text((LIB / module).read_text(encoding="utf-8"), encoding="utf-8")
    done = subprocess.run(
        ["node", "--input-type=module", "-e",
         f"import * as m from {json.dumps(copy.as_uri())}\n{script}"],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


# --- the room the area leaves ------------------------------------------

SURFACES = [(700, 700), (940, 780), (1100, 880)]
# From this width the bar of the brush stands at the top between the tools and
# the zoom; below it the area keeps a second row free (`lib/studioArea.js`).
WIDE_FROM = 880
SECOND_ROW = 40
SHAPES = {"1:1": (1024, 1024), "2:3": (1024, 1536), "1024x2048": (1024, 2048), "16:9": (1344, 768)}


@needs_node
def test_the_area_keeps_the_rows_room_on_both_sides(tmp_path: Path):
    """Right and left edge of the area stand at least 102 px from the
    surface's border, in every shape and surface — with 70 the 16:9 area of
    the narrow surfaces stood 70 px away and went under the bar."""
    cases = _plain(tmp_path, "studioArea.js", f"""
      const out = []
      for (const [fw, fh] of {json.dumps(SURFACES)})
        for (const [name, [gw, gh]] of Object.entries({json.dumps(SHAPES)})) {{
          const a = m.fitArea(fw, fh, gw, gh)
          out.push({{ name, fw, fh, left: a.x, right: fw - a.x - a.w }})
        }}
      console.log(JSON.stringify(out))
    """)
    assert len(cases) == len(SURFACES) * len(SHAPES)
    for case in cases:
        assert case["left"] >= 102 - 1e-6, case
        assert case["right"] >= 102 - 1e-6, case
    # The bar is 14 to 90 px from the border: nothing of the area under it.
    assert all(case["right"] > 90 for case in cases)


@needs_node
def test_an_area_that_hangs_on_the_height_keeps_its_size(tmp_path: Path):
    """Silence probe: from the width the bar of the brush fits at the top,
    where the room on the sides was not what limited the area, the new room
    changes nothing — same size, same place."""
    kept = _plain(tmp_path, "studioArea.js", f"""
      const old = (fw, fh, gw, gh) => {{
        const s = Math.max(0.01, Math.min((fw - 2 * 70) / gw, (fh - 122 - 274) / gh))
        return {{ w: gw * s, h: gh * s, x: (fw - gw * s) / 2,
                  y: 122 + Math.max(0, (fh - 122 - 274 - gh * s) / 2) }}
      }}
      const out = []
      for (const [fw, fh] of {json.dumps(SURFACES)})
        for (const [name, [gw, gh]] of Object.entries({json.dumps(SHAPES)})) {{
          if (fw < {WIDE_FROM}) continue
          const heightBound = (fh - 396) / gh <= (fw - 204) / gw
          const a = m.fitArea(fw, fh, gw, gh), b = old(fw, fh, gw, gh)
          out.push({{ name, fw, heightBound, same: a.w === b.w && a.h === b.h && a.x === b.x && a.y === b.y }})
        }}
      console.log(JSON.stringify(out))
    """)
    bound = [case for case in kept if case["heightBound"]]
    assert bound, "no case hangs on the height"
    assert all(case["same"] for case in bound), bound


@needs_node
def test_below_the_limit_the_area_keeps_the_second_row_free_in_every_shape(tmp_path: Path):
    """The area stands at least TOP_ROOM + 40 px from the top and 102 px from
    the sides on a surface narrower than the bar needs, whatever the shape;
    from the limit on it is the 122 px of before, the limit itself included."""
    cases = _plain(tmp_path, "studioArea.js", f"""
      const out = []
      for (const fw of [435, 700, 775, {WIDE_FROM - 1}, {WIDE_FROM}, {WIDE_FROM + 1}, 935])
        for (const fh of [640, 860, 1000])
          for (const [name, [gw, gh]] of Object.entries({json.dumps(SHAPES)})) {{
            const a = m.fitArea(fw, fh, gw, gh)
            out.push({{ name, fw, fh, top: a.y, left: a.x, right: fw - a.x - a.w, bottom: fh - a.y - a.h,
                        room: m.TOP_ROOM, row: m.BRUSH_ROW_ROOM, above: m.brushBarAbove(fw) }})
          }}
      console.log(JSON.stringify(out))
    """)
    assert cases[0]["room"] == 122 and cases[0]["row"] == SECOND_ROW
    for case in cases:
        assert case["above"] is (case["fw"] >= WIDE_FROM), case
        assert case["top"] >= 122 + (0 if case["above"] else SECOND_ROW) - 1e-6, case
        assert case["left"] >= 102 - 1e-6 and case["right"] >= 102 - 1e-6, case
        assert case["bottom"] >= 274 - 1e-6, case


def test_the_row_of_pictures_and_the_canvas_share_the_one_limit():
    """The gallery steps down by what the canvas tells (`surface.brushRow`);
    neither file keeps a window width of its own for it."""
    gallery = GALLERY.read_text(encoding="utf-8")
    canvas = CANVAS.read_text(encoding="utf-8")
    assert "class:unter={surface.brushRow}" in gallery
    assert "brushBarAbove(fw)" in canvas
    assert "@media (max-width: 720px)" not in gallery
    assert "@media (max-width: 720px)" not in canvas


def test_the_canvas_takes_its_room_from_the_one_module():
    source = CANVAS.read_text(encoding="utf-8")
    assert "fitArea(fw, fh, gw, gh)" in source
    assert "RAND_SEITE" not in source


# --- the original -------------------------------------------------------


@needs_node
def test_the_original_stays_when_a_finished_picture_comes_in():
    """(1) A file in the area, then a drawn picture arrives: the area shows
    the drawn one, the original stays and keeps its tile on top."""
    report = run("""
    service.studioList = ['old.png']
    stubs.mounted()
    await studio.newestIntoArea()
    await settled()
    studio.pictureFromOutside('file.png')
    stubs.changed()
    const first = { area: studio.werte.startbild, original: studio.werte.original }
    studio.drawAsked()
    service.studioList = ['drawn.png', 'old.png']
    await studio.newestIntoArea()
    await settled()
    return { first, area: studio.werte.startbild, original: studio.werte.original }
    """)
    assert report["first"] == {"area": "file.png", "original": "file.png"}
    assert report["area"] == "drawn.png"
    assert report["original"] == "file.png"


@needs_node
def test_a_click_on_the_original_lays_it_in_the_area_with_no_mask():
    """(2) Another picture stands in the area with a mask; the original's
    click is `startbildWaehlen(original)`: the area shows it, the mask is
    empty."""
    report = run("""
    stubs.mounted()
    await settled()
    studio.pictureFromOutside('file.png')
    studio.startbildWaehlen('other.png')
    studio.werte.maske = 'mask.png'
    studio.startbildWaehlen(studio.werte.original)
    return { area: studio.werte.startbild, mask: studio.werte.maske, original: studio.werte.original }
    """)
    assert report == {"area": "file.png", "mask": "", "original": "file.png"}
    # The tile does exactly that.
    source = GALLERY.read_text(encoding="utf-8")
    assert "onclick={() => startbildWaehlen(original)}" in source


@needs_node
def test_drawing_and_other_clicks_never_change_the_original():
    """(3) A click on another picture, a picture laid in from the row, the
    area emptied, a draw: the original is the one from outside still."""
    report = run("""
    service.studioList = ['old.png']
    stubs.mounted()
    await studio.newestIntoArea()
    await settled()
    studio.pictureFromOutside('file.png')
    studio.startbildWaehlen('other.png')
    const afterClick = studio.werte.original
    studio.emptyArea()
    const afterEmpty = studio.werte.original
    studio.drawAsked()
    service.studioList = ['drawn.png', 'old.png']
    await studio.newestIntoArea()
    await settled()
    return { afterClick, afterEmpty, afterDraw: studio.werte.original }
    """)
    assert report == {"afterClick": "file.png", "afterEmpty": "file.png", "afterDraw": "file.png"}


@needs_node
def test_the_next_picture_from_outside_takes_the_originals_place():
    """(4) A second file, then one off the picture folder: each replaces
    the one before."""
    report = run("""
    stubs.mounted()
    await settled()
    studio.pictureFromOutside('first.png')
    studio.pictureFromOutside('second.png')
    const second = studio.werte.original
    studio.pictureFromOutside('folder.png')
    return { second, third: studio.werte.original, area: studio.werte.startbild }
    """)
    assert report == {"second": "second.png", "third": "folder.png", "area": "folder.png"}
    canvas = CANVAS.read_text(encoding="utf-8")
    # The three ways in from outside all name the original.
    assert "pictureFromOutside(ergebnis.bild)" in canvas
    assert "pictureFromOutside(name)" in canvas
    details = (FRONTEND / "src/teile/StudioDetails.svelte").read_text(encoding="utf-8")
    assert "pictureFromOutside(name)" in details


@needs_node
def test_shut_the_row_keeps_the_original_and_one_tile(tmp_path: Path):
    """(5) Open: the original, then every picture. Shut: the original and
    one tile — the picture drawing now, which stands above, or else the
    newest. The original is never shown twice."""
    rows = _plain(tmp_path, "studioRow.js", """
      const names = ['n3.png', 'n2.png', 'n1.png']
      console.log(JSON.stringify({
        open: m.rowPictures({ original: 'o.png', names, open: true, running: false }),
        shut: m.rowPictures({ original: 'o.png', names, open: false, running: false }),
        shutRunning: m.rowPictures({ original: 'o.png', names, open: false, running: true }),
        twice: m.rowPictures({ original: 'n3.png', names, open: false, running: false }),
        none: m.rowPictures({ original: '', names: [], open: false, running: false }),
      }))
    """)
    assert rows["open"] == {"original": "o.png", "pictures": ["n3.png", "n2.png", "n1.png"]}
    assert rows["shut"] == {"original": "o.png", "pictures": ["n3.png"]}
    assert rows["shutRunning"] == {"original": "o.png", "pictures": []}
    assert rows["twice"] == {"original": "n3.png", "pictures": ["n2.png"]}
    # Silence probe: no picture from outside, no tile.
    assert rows["none"] == {"original": "", "pictures": []}


@needs_node
def test_the_original_is_stored_and_comes_back_after_a_restart():
    """(6) It is written with the studio's values; a studio that reads the
    store again has it — also when the file was chosen before the store
    arrived."""
    written = run("""
    stubs.mounted()
    await settled()
    studio.pictureFromOutside('file.png')
    stubs.changed()
    await flushed()
    return { stored: service.stores.global.bildfenster }
    """)
    assert written["stored"]["original"] == "file.png"
    assert written["stored"]["startbild"] == "file.png"

    again = run("""
    service.stores.global = { bildfenster: { startbild: 'drawn.png', original: 'file.png' } }
    stubs.mounted()
    await speicher.readStudioStore()
    stubs.mounted()
    await settled()
    return { original: studio.werte.original, area: studio.werte.startbild }
    """)
    assert again == {"original": "file.png", "area": "drawn.png"}

    early = run("""
    service.stores.global = { bildfenster: { original: 'old.png' } }
    stubs.mounted()
    studio.pictureFromOutside('early.png')
    await speicher.readStudioStore()
    stubs.mounted()
    await settled()
    await flushed()
    return { original: studio.werte.original, stored: service.stores.global.bildfenster.original }
    """)
    assert early == {"original": "early.png", "stored": "early.png"}


@needs_node
def test_a_studio_without_a_picture_from_outside_has_no_original_and_writes_none():
    """Silence probe: nothing came from outside — the value is empty and
    drawing and clicking write no `original`."""
    report = run("""
    service.studioList = ['drawn.png']
    stubs.mounted()
    await studio.newestIntoArea()
    await settled()
    studio.startbildWaehlen('other.png')
    stubs.changed()
    await flushed()
    return { original: studio.werte.original, stored: service.stores.global?.bildfenster ?? {} }
    """)
    assert report["original"] == ""
    assert not report["stored"].get("original")


# --- the service keeps it ----------------------------------------------


def test_the_service_keeps_the_original_and_protects_its_file():
    """The studio's store takes `original` as a picture's name — a name of
    the folder's own shape only — and the picture's file is held, so no
    cleaning takes it away."""
    kept = bildfensterwahl.wahl_pruefen({"startbild": NAME, "original": NAME})
    assert kept == {"startbild": NAME, "original": NAME}
    # No name of the folder's shape: dropped, like any picture field.
    assert "original" not in (bildfensterwahl.wahl_pruefen({"original": "../etc/passwd"}) or {})
    assert NAME in bildfensterwahl.held_pictures({"original": NAME})
