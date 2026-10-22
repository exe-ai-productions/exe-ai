"""The studio's brush bar and the two rows over the generation area never lie on
something else, measured in a real browser.

`ImageStudio.svelte` is built as shipped and drawn in headless Chrome with the
answers of the service made up in the page: a picture in the area, a row of
three pictures. The surface has the width a window leaves it — 775 px is a
1440 px window with both columns open, 435 px a 1100 px one — in German and in
English, with the brush and the eraser.

* From 880 px of surface the brush bar stands at the top between the tools
  and the zoom; below that in a row of its own under the zoom, the row of
  pictures under it. Nothing of the bar lies over the zoom, the row of
  pictures, the rows of the area or "···"; its switch can be clicked in the
  middle; the bar never reaches out of its glass.
* Below that width the area keeps the second row free, with the hand chosen
  too, so it stays where it is when the tool changes.
* Both rows over the area end at its right edge, the area's own row 8 px
  before "···"; too long, only the label ends with "…" and the sign and the
  size stay whole. A wide area keeps the row whole.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import struct
import subprocess
import zlib
from urllib.parse import quote
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import test_studio_generate_stays_chrome as page

FRONTEND = page.FRONTEND
ROOT = page.ROOT

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]


def _picture() -> str:
    """A plain 64 x 64 picture as an address of its own."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + b"\xcc\xcc\xcc" * 64 for _ in range(64))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode()


SHELL = """<script>
  import ImageStudio from '../../src/teile/ImageStudio.svelte'

  const q = JSON.parse(new URLSearchParams(location.search).get('s'))
</script>

<div id="frame" style="width: {q.w}px; height: {q.h}px; position: relative; display: flex;">
  <ImageStudio zeichnen={() => {}} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import german from %(german)r
import english from %(english)r
import { texte } from %(texts)r
import { api } from %(api)r
import { werte } from %(studio)r

const q = JSON.parse(new URLSearchParams(location.search).get('s'))
texte.sprache = q.lang
texte.katalog = q.lang === 'de' ? german : english
api.bildAdresse = () => %(picture)r
const names = ['a', 'b', 'c'].map((c) => c.repeat(32) + '.png')
const answers = {
  '/bild/modelle': {
    programm_da: true, modelle: ['model-a'], standardmodell: 'model-a', families: {}, sampler: [], scheduler: [],
    loras: [], sizes: {},
  },
  '/bild/familien': [],
  '/bild/vorgaben': { family: '', breite: q.areaW, hoehe: q.areaH, schritte: 8, cfg: 1 },
  '/bilder': { bilder: names },
  '/settings/resolved/bildfenster': { wert: { modell: 'model-a', prompt: 'a cat' } },
}
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
document.documentElement.dataset.modus = 'hell'
werte.breite = q.areaW
werte.hoehe = q.areaH
werte.startbild = q.picture ? 'a-picture.png' : ''
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const q = JSON.parse(new URLSearchParams(location.search).get('s'))
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const cut = (el) => {
  if (!el) return null
  const r = el.getBoundingClientRect()
  return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }
}
const surfaceEl = () => document.querySelector('.studio > .flaeche')
const tools = () => [...document.querySelectorAll('.werkzeuge > button')].slice(0, 3)
for (let k = 0; k < 100 && !(surfaceEl() && document.querySelector('.leiste .kachel.bild')); k += 1) await wait(100)
if (q.picture) for (let k = 0; k < 100 && !document.querySelector('.bild img')?.naturalWidth; k += 1) await wait(100)
await wait(500)

const slide = async (index, value) => {
  const input = document.querySelectorAll('.pinselleiste input[type=range]')[index]
  input.value = String(value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
  await wait(100)
}
const snapshot = () => {
  const surface = surfaceEl()
  const origin = surface.getBoundingClientRect()
  const bar = document.querySelector('.pinselleiste')
  // The picture's row stands above the area's own: the lower one is the area's.
  const rows = [...document.querySelectorAll('.studio > .flaeche > .bereichsname')]
    .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top)
  const areaRow = rows[rows.length - 1]
  const pictureRow = rows.length > 1 ? rows[0] : null
  const word = areaRow?.querySelector('.wort') ?? areaRow?.querySelector(':scope > span')
  const size = areaRow?.querySelector('.mass') ?? word
  const sign = areaRow?.querySelector('svg')
  const toggle = bar?.querySelector('[role=switch]')
  let reach = null
  if (toggle) {
    const r = toggle.getBoundingClientRect()
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
    reach = Boolean(hit && (hit === toggle || toggle.contains(hit)))
  }
  return {
    surface: { w: origin.width, h: origin.height, l: origin.left, t: origin.top },
    area: cut(document.querySelector('.studio .bereich')),
    bar: cut(bar),
    barScroll: bar ? { scroll: bar.scrollWidth, client: bar.clientWidth } : null,
    toggleReach: reach,
    zoom: cut(document.querySelector('.flaeche > .zoom')),
    tools: cut(document.querySelector('.werkzeuge')),
    head: cut(document.querySelector('.gallery .kopf')),
    gallery: cut(document.querySelector('.gallery')),
    galleryUnder: document.querySelector('.gallery')?.classList.contains('unter') ?? null,
    areaRow: cut(areaRow),
    pictureRow: cut(pictureRow),
    word: cut(word),
    wordScroll: word ? { scroll: word.scrollWidth, client: word.clientWidth } : null,
    size: cut(size),
    sizeText: size?.textContent ?? null,
    sign: cut(sign),
    more: cut(document.querySelector('.bereichsmenue .mehr')),
    moreWrap: cut(document.querySelector('.bereichsmenue')),
  }
}

const report = { q, hand: snapshot() }
// The tool of the scenario, then the widest values the bar can take.
tools()[q.tool === 'pinsel' ? 1 : 2].click()
await wait(400)
if (q.widest) {
  await slide(0, 118)
  await slide(1, 8)
}
await wait(200)
report.tool = snapshot()
report.sliderTexts = [...document.querySelectorAll('.pinselleiste .zahl')].map((el) => el.textContent.trim())

document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

# (id, surface width, surface height, language, tool, area w, area h, widest values)
SCENARIOS = {
    "de_eraser_775": dict(w=775, h=860, lang="de", tool="radierer", areaW=1024, areaH=1024),
    "en_brush_775": dict(w=775, h=860, lang="en", tool="pinsel", areaW=1024, areaH=1024),
    "de_eraser_879": dict(w=879, h=860, lang="de", tool="radierer", areaW=1024, areaH=1024),
    "de_eraser_880": dict(w=880, h=860, lang="de", tool="radierer", areaW=1024, areaH=1024, widest=True),
    "en_brush_935": dict(w=935, h=860, lang="en", tool="pinsel", areaW=1024, areaH=1024),
    "de_eraser_435": dict(w=435, h=860, lang="de", tool="radierer", areaW=1024, areaH=1024),
    "en_brush_435": dict(w=435, h=860, lang="en", tool="pinsel", areaW=1024, areaH=1024),
    "de_eraser_1100": dict(w=1100, h=860, lang="de", tool="radierer", areaW=1024, areaH=1024),
}


@pytest.fixture(scope="module")
def reports() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-brush-bar-rows-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS
            % {
                "global": "../../src/stil/global.css",
                "german": str(ROOT / "app" / "locales" / "de.json"),
                "english": str(ROOT / "app" / "locales" / "en.json"),
                "texts": "../../src/lib/texte.svelte.js",
                "api": "../../src/lib/api.js",
                "studio": "../../src/lib/studio.svelte.js",
                "picture": _picture(),
            },
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(page.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(page.PAGE % {"cases": CASES}, encoding="utf-8")
        out: dict = {}
        for name, scenario in SCENARIOS.items():
            scenario = {"picture": True, **scenario}
            port = page._free_port()
            browser = subprocess.Popen(
                [
                    program, "--headless=new", "--no-first-run", "--disable-background-networking",
                    "--allow-file-access-from-files", "--window-size=1920,1080",
                    f"--remote-debugging-port={port}", f"--user-data-dir={folder / ('profile-' + name)}",
                    (folder / "measure.html").as_uri() + "?s=" + quote(json.dumps(scenario)),
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            try:
                out[name] = asyncio.run(page._drive(port))
            finally:
                prozessstopp.beenden(browser, frist=5)
        return out
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _over(a: dict, b: dict) -> bool:
    """Whether two rectangles share area."""
    return a["l"] < b["r"] - 0.5 and b["l"] < a["r"] - 0.5 and a["t"] < b["b"] - 0.5 and b["t"] < a["b"] - 0.5


def _bar_clear(shot: dict) -> list[str]:
    """What the bar lies over, by name."""
    bar = shot["bar"]
    names = ["zoom", "head", "gallery", "areaRow", "pictureRow", "more", "tools"]
    return [name for name in names if shot[name] and _over(bar, shot[name])]


WIDE = ["en_brush_935", "de_eraser_880", "de_eraser_1100"]
NARROW = ["de_eraser_775", "en_brush_775", "de_eraser_879", "de_eraser_435", "en_brush_435"]


@pytest.mark.parametrize("name", WIDE)
def test_a_wide_surface_has_the_bar_at_the_top_beside_the_zoom(reports, name):
    shot = reports[name]["tool"]
    assert shot["galleryUnder"] is False, shot
    assert abs(shot["bar"]["t"] - shot["zoom"]["t"]) < 1.5, shot
    assert shot["bar"]["r"] <= shot["zoom"]["l"] + 0.5, shot
    assert shot["bar"]["l"] >= shot["tools"]["r"] - 0.5, shot
    assert _bar_clear(shot) == [], (name, _bar_clear(shot), shot)


@pytest.mark.parametrize("name", NARROW)
def test_a_narrow_surface_has_the_bar_in_a_row_under_the_zoom_and_the_pictures_under_it(reports, name):
    shot = reports[name]["tool"]
    assert shot["galleryUnder"] is True, shot
    assert shot["bar"]["t"] >= shot["zoom"]["b"] - 0.5, shot
    assert shot["head"]["t"] >= shot["bar"]["b"] - 0.5, shot
    assert _bar_clear(shot) == [], (name, _bar_clear(shot), shot)
    # The row of the area's resolution stands under the bar, not behind it.
    assert shot["pictureRow"]["t"] >= shot["bar"]["b"] - 0.5, shot


@pytest.mark.parametrize("name", WIDE + NARROW)
def test_the_bar_stays_in_its_glass_and_its_switch_can_be_clicked(reports, name):
    shot = reports[name]["tool"]
    assert shot["barScroll"]["scroll"] <= shot["barScroll"]["client"] + 1, shot
    assert shot["toggleReach"] is True, shot
    assert shot["bar"]["l"] >= shot["surface"]["l"] - 0.5, shot
    assert shot["bar"]["r"] <= shot["surface"]["l"] + shot["surface"]["w"] + 0.5, shot


def test_the_widest_bar_fits_at_the_limit(reports):
    """The limit is what the widest bar needs: German, the eraser, a size of
    three digits and a tint with two decimals."""
    report = reports["de_eraser_880"]
    assert report["sliderTexts"] == ["240", "0,55"] or report["sliderTexts"] == ["240", "0.55"], report
    shot = report["tool"]
    assert shot["bar"]["w"] <= 622.5, shot["bar"]
    assert shot["barScroll"]["scroll"] <= shot["barScroll"]["client"] + 1, shot


@pytest.mark.parametrize("name", NARROW)
def test_the_area_keeps_the_second_row_free_and_stays_when_the_tool_changes(reports, name):
    report = reports[name]
    for shot in (report["hand"], report["tool"]):
        # 122 for its rows plus the 40 px of the second row.
        assert shot["area"]["t"] - shot["surface"]["t"] >= 162 - 0.5, shot
    assert report["hand"]["area"] == report["tool"]["area"], report


@pytest.mark.parametrize("name", WIDE)
def test_a_wide_surface_leaves_the_area_where_it_stood(reports, name):
    """Silence probe: from the limit on the area keeps the room of 122 px."""
    report = reports[name]
    assert report["tool"]["area"]["t"] - report["tool"]["surface"]["t"] >= 122 - 0.5, report
    assert report["hand"]["area"] == report["tool"]["area"], report


# --- the rows over the area ------------------------------------------------


@pytest.mark.parametrize("name", ["de_eraser_435", "en_brush_435"])
def test_the_rows_end_at_the_areas_edge_and_the_label_gives_way_before_the_menu(reports, name):
    shot = reports[name]["tool"]
    area, row, more = shot["area"], shot["areaRow"], shot["more"]
    assert area["w"] < 293, area
    assert row["r"] <= more["l"] - 8 + 0.5, shot
    assert row["r"] <= area["r"] + 0.5, shot
    assert shot["pictureRow"]["r"] <= area["r"] + 0.5, shot
    # Only the label is cut: it ends with "…", sign and size are whole.
    assert shot["wordScroll"]["scroll"] > shot["wordScroll"]["client"], shot
    assert shot["sign"]["l"] >= row["l"] - 0.5 and shot["sign"]["r"] <= row["r"] + 0.5, shot
    assert shot["size"]["l"] >= shot["word"]["r"] - 0.5 and shot["size"]["r"] <= row["r"] + 0.5, shot
    assert shot["sizeText"].strip() == "· 1024 × 1024", shot
    assert not _over(row, more), shot


@pytest.mark.parametrize("name", ["de_eraser_435", "en_brush_435"])
def test_the_rows_do_not_go_under_the_row_of_pictures(reports, name):
    shot = reports[name]["tool"]
    for key in ("areaRow", "pictureRow"):
        assert not _over(shot[key], shot["gallery"]), (key, shot)
        assert not _over(shot[key], shot["head"]), (key, shot)


@pytest.mark.parametrize("name", ["de_eraser_1100", "de_eraser_880", "en_brush_935"])
def test_a_wide_area_keeps_its_row_whole(reports, name):
    """Silence probe: nothing is cut, the row is as wide as its content."""
    shot = reports[name]["tool"]
    assert shot["wordScroll"]["scroll"] <= shot["wordScroll"]["client"], shot
    assert shot["areaRow"]["w"] <= shot["area"]["w"] + 0.5, shot
