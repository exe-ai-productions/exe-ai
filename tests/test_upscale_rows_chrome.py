"""The rows of the enlarging in the studio's details column, in a real browser.

``StudioDetails.svelte`` is built as shipped and drawn in headless Chrome with
the picture service made up in the page: three upscaler files (a x4 one, a x2
one, one whose factor the service could not read). The rows "Repeats" and
"Tile size" start at 1 and 128, and the row "Final size" tells where the
enlarging ends before the press: the picture's width and height times the
factor to the power of the repeats, only the factor with no picture in the
area, and a word instead when the factor is not known. The two numbers the
draw takes are clamped the way the service reads them. Skipped where there is
no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import test_studio_generate_stays_chrome as page

ROOT = page.ROOT
FRONTEND = page.FRONTEND

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import StudioDetails from '../../src/teile/StudioDetails.svelte'
</script>

<div id="frame" style="width: 420px; height: 1400px; position: relative; display: flex; flex-direction: column;">
  <StudioDetails />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { werte, bildmass, listenLaden, upscaleWerte } from %(studio)r

const answers = {
  '/bild/modelle': {
    programm_da: true, modelle: ['model-a'], standardmodell: 'model-a', families: {}, sampler: [], scheduler: [],
    loras: [], sizes: {},
    upscalers: ['x2.pth', 'x4.pth', 'unknown.pth'],
    upscaler_scales: { 'x2.pth': 2, 'x4.pth': 4 },
  },
  '/bild/familien': [],
  '/bild/vorgaben': { family: '', breite: 1024, hoehe: 1024, schritte: 8, cfg: 1 },
  '/bilder': { bilder: [] },
  '/settings/resolved/bildfenster': { wert: { modell: 'model-a', prompt: '' } },
}
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
document.documentElement.dataset.modus = 'hell'
window.__studio = { werte, bildmass, listenLaden, upscaleWerte }
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const { werte, bildmass, listenLaden, upscaleWerte } = window.__studio
const row = (key) => document.querySelector(`.zeile[data-suche="${key}"]`)
for (let k = 0; k < 100 && !row('bild.upscale_final_size'); k += 1) await wait(100)
await listenLaden()
await wait(500)

const text = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : null)
const labels = () => Array.from(document.querySelectorAll('.zeile[data-suche^="bild.upscale"], .zeile[data-suche="bild.upscaler"]'))
  .map((r) => r.dataset.suche)
const field = (key) => row(key)?.querySelector('input')?.value ?? null
const final = () => text(row('bild.upscale_final_size')?.querySelector('.endgroesse'))
const settle = () => wait(150)
const report = {}

report.order = labels()
report.defaults = { repeats: field('bild.upscale_repeats'), tile: field('bild.upscale_tile_size') }

// No picture in the area: only the factor over all runs.
werte.upscale_model = 'x4.pth'
bildmass.w = 0
bildmass.h = 0
await settle()
report.noPicture = { one: final() }
werte.upscale_repeats = 2
await settle()
report.noPicture.two = final()

// A picture of 1024 pixels.
bildmass.w = 1024
bildmass.h = 1024
werte.upscale_repeats = 1
await settle()
report.picture = { x4: final() }
werte.upscale_model = 'x2.pth'
werte.upscale_repeats = 2
await settle()
report.picture.x2twice = final()

// A picture that is not square keeps its proportions.
bildmass.w = 1000
bildmass.h = 500
werte.upscale_model = 'x4.pth'
werte.upscale_repeats = 1
await settle()
report.picture.wide = final()

// A file whose factor the service could not read.
werte.upscale_model = 'unknown.pth'
await settle()
report.unknown = final()

// What the draw takes is clamped the way the service reads it.
const clamp = {}
for (const [repeats, tile] of [[1, 128], [4, 1], [5, 0], [0, -3], ['', ''], [2.7, 256.9], ['3', '64']]) {
  werte.upscale_repeats = repeats
  werte.upscale_tile_size = tile
  clamp[`${repeats}|${tile}`] = upscaleWerte()
}
report.clamp = clamp

document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    """The page built once and read once."""
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-upscale-rows-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {"global": "../../src/stil/global.css", "studio": "../../src/lib/studio.svelte.js"},
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(page.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(page.PAGE % {"cases": CASES}, encoding="utf-8")
        port = page._free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1000,1400",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri(),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return asyncio.run(page._drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_the_rows_stand_under_the_upscaler_in_this_order(report):
    assert report["order"] == [
        "bild.upscaler", "bild.upscale_repeats", "bild.upscale_tile_size", "bild.upscale_final_size",
    ], report


def test_the_rows_start_at_the_start_values_of_sd_cpp(report):
    assert report["defaults"] == {"repeats": "1", "tile": "128"}, report


def test_the_final_size_is_the_picture_times_the_factor_to_the_power_of_the_repeats(report):
    assert report["picture"]["x4"] == "4096 × 4096", report
    assert report["picture"]["x2twice"] == "4096 × 4096", report
    assert report["picture"]["wide"] == "4000 × 2000", report


def test_with_no_picture_only_the_factor_over_all_runs_is_told(report):
    assert report["noPicture"] == {"one": "×4", "two": "×16"}, report


def test_a_factor_that_is_not_known_is_a_word_not_a_size(report):
    assert report["unknown"] == "bild.upscale_faktor_unbekannt", report


def test_the_numbers_of_the_draw_are_clamped_the_way_the_service_reads_them(report):
    clamp = report["clamp"]
    assert clamp["1|128"] == {"upscale_repeats": 1, "upscale_tile_size": 128}, report
    assert clamp["4|1"] == {"upscale_repeats": 4, "upscale_tile_size": 1}, report
    # Out of the range or empty: the start value.
    assert clamp["5|0"] == {"upscale_repeats": 1, "upscale_tile_size": 128}, report
    assert clamp["0|-3"] == {"upscale_repeats": 1, "upscale_tile_size": 128}, report
    assert clamp["|"] == {"upscale_repeats": 1, "upscale_tile_size": 128}, report
    assert clamp["2.7|256.9"] == {"upscale_repeats": 2, "upscale_tile_size": 256}, report
    assert clamp["3|64"] == {"upscale_repeats": 3, "upscale_tile_size": 64}, report
