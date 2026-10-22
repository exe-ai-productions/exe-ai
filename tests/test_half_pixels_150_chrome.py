"""Half pixels on a scaled display: the dots stand on the answer's line, and the
ring round today is sharp, measured in the screenshots of a real browser.

`Nachricht.svelte` and `ScheduleCalendar.svelte` are built as shipped and drawn
in headless Chrome started with `--force-device-scale-factor` 1, 1.5 and 2 (the
emulation of a device ratio paints the line over three half-lit columns and is
not the display a scaled desktop has). The page is shown at four start points a
quarter of a CSS pixel apart, and each is photographed and read pixel by pixel:

* the centre of the dot of a state (an answer cut off at its ceiling: red, no
  breathing) lies on the centre of the line, at most 0.3 device pixels beside it
  at every scale and every start point; the ring of the answer next to it keeps
  its place; from the edge of the disc to the text stand 13 CSS pixels;
* the middle row through the left edge of the ring round today holds no pixel
  whose lightness is more than an eighth of the full range away from both the
  ring and the ground, at 100 % and 150 %; at 200 % the ring is as thick as it
  was (three device pixels).

Skipped where there is no Chrome, no node, or no Pillow, like the other browser
tests.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SCALES = (1.0, 1.5, 2.0)
OFFSETS = (0.0, 0.25, 0.5, 0.75)

SHELL = """<script>
  import Nachricht from '../../src/teile/Nachricht.svelte'
  import ScheduleCalendar from '../../src/teile/ScheduleCalendar.svelte'
  import { scene } from './scene.svelte.js'
</script>

<div style="position: relative; left: {scene.offset}px; top: {scene.offset}px; display: flex; gap: 40px; padding: 24px;">
  <div style="width: 560px;">
    <Nachricht
      nachricht={scene.nachricht}
      laeuft={false}
      istLetzte={true}
      marke={null}
      neuErzeugen={() => {}}
      neuSenden={() => {}}
    />
  </div>
  <div style="width: 760px;">
    <ScheduleCalendar kalender={scene.kalender} gross={true} />
  </div>
</div>
"""

SCENE_JS = """const first = new Date(Date.UTC(2026, 8, 28))
const grid = Array.from({ length: 42 }, (_, k) => new Date(first.getTime() + k * 86400000).toISOString().slice(0, 10))

export const scene = $state({
  offset: 0,
  nachricht: {
    id: 'm1', rolle: 'assistant',
    content: 'The first paragraph says what was found in the files.\\n\\nThe second paragraph says what is left to do, '
      + 'and it runs over a second line so that the line of the answer is long enough to be measured.\\n\\nThe third one ends it.',
    abschnitte: [], werkzeuge: [], stats: { abgeschnitten: true },
  },
  kalender: {
    title: 'October 2026',
    weekdayShort: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    weekdayHeads: ['M', 'T', 'W', 'T', 'F', 'S', 'S'],
    grid, shaped: {}, shownMonth: '2026-10', chosen: '2026-10-14', today: '2026-10-20',
    choose() {}, toToday() {}, step() {},
  },
})
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import '../../src/stil/global.css'

window.scene = scene
mount(Shell, { target: document.getElementById('root') })
"""

VITE_CONFIG = """import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte({ compilerOptions: { css: 'injected' } })],
  logLevel: 'error',
  build: {
    outDir: 'out',
    emptyOutDir: true,
    minify: false,
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js' },
  },
})
"""

# The page answers `show(offset)` with the places of the parts it is asked
# about, in CSS pixels; the screenshot is taken by the driver after that.
CASES = r"""
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const rect = (node) => {
  if (!node) return null
  const r = node.getBoundingClientRect()
  return { left: r.left, top: r.top, right: r.right, bottom: r.bottom }
}
window.show = async (offset) => {
  window.scene.offset = offset
  await wait(400)
  const entries = Array.from(document.querySelectorAll('.antwortlinie > .ereignis'))
  const state = document.querySelector('.antwortlinie .punkt .lp .scheibe')
  const ring = document.querySelector('.antwortlinie .punkt .ring')
  const text = document.querySelector('.antwortlinie .fliesstext p')
  const hint = document.querySelector('.antwortlinie .hinweis')
  const first = entries[0]
  const piece = getComputedStyle(first, '::before')
  return {
    dpr: window.devicePixelRatio,
    width: window.innerWidth,
    entries: entries.length,
    lineLeft: first.getBoundingClientRect().left + parseFloat(piece.left),
    lineWidth: parseFloat(piece.width),
    disc: rect(state), ring: rect(ring), text: rect(text), hint: rect(hint),
    today: rect(document.querySelector('.tag.heutig .n')),
    todayBorder: document.querySelector('.tag.heutig .n') && getComputedStyle(document.querySelector('.tag.heutig .n')).borderTopWidth,
  }
}
window.ready = true
"""

PAGE = """<!doctype html><meta charset=utf-8><title>half pixels</title>
<style>body { margin: 0; background: var(--bg); }</style>
<div id="root"></div>
<script>
  window.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now()), 16)
  window.cancelAnimationFrame = (id) => clearTimeout(id)
</script>
<link rel="stylesheet" href="out/exe-ai-terminal-frontend.css">
<script src="out/entry.js"></script>
<script>
  window.addEventListener('load', async () => {
    try {
      %(cases)s
    } catch (failure) {
      window.failure = String(failure && failure.stack || failure)
    }
  })
</script>
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 120.0) -> list[dict]:
    """For each start point: the places the page reports, and its screenshot."""
    websockets = pytest.importorskip("websockets")
    end = time.monotonic() + limit
    address = None
    while time.monotonic() < end and address is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as response:
                for page in json.load(response):
                    if page.get("type") == "page" and "measure.html" in page.get("url", ""):
                        address = page["webSocketDebuggerUrl"]
        except OSError:
            pass
        if address is None:
            await asyncio.sleep(0.2)
    assert address, "Chrome did not open the page"
    result: list[dict] = []
    async with websockets.connect(address, max_size=64 * 1024 * 1024) as connection:
        number = 0

        async def call(method: str, params: dict) -> dict:
            nonlocal number
            number += 1
            await connection.send(json.dumps({"id": number, "method": method, "params": params}))
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    return response

        async def read(expression: str):
            answer = await call("Runtime.evaluate", {
                "expression": expression, "returnByValue": True, "awaitPromise": True,
            })
            return answer.get("result", {}).get("result", {}).get("value")

        while time.monotonic() < end and not await read("window.ready === true || Boolean(window.failure)"):
            await asyncio.sleep(0.25)
        failure = await read("window.failure || ''")
        assert not failure, failure
        for offset in OFFSETS:
            places = await read(f"window.show({offset})")
            assert places, "the page reported nothing"
            shot = await call("Page.captureScreenshot", {"format": "png"})
            places["png"] = base64.b64decode(shot["result"]["data"])
            places["offset"] = offset
            result.append(places)
    return result


def _run_chrome(program: str, folder: Path, scale: float) -> list[dict]:
    port = _free_port()
    browser = subprocess.Popen(
        [
            program, "--headless=new", "--disable-gpu", "--no-first-run",
            "--disable-background-networking", "--allow-file-access-from-files",
            "--window-size=1920,1080", f"--force-device-scale-factor={scale}",
            f"--remote-debugging-port={port}", f"--user-data-dir={folder / f'profile-{scale}'}",
            (folder / "measure.html").as_uri(),
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        return asyncio.run(_drive(port))
    finally:
        prozessstopp.beenden(browser, frist=5)


class _Shot:
    """A screenshot read in CSS pixel coordinates."""

    def __init__(self, png: bytes, css_width: float):
        from PIL import Image

        self.image = Image.open(io.BytesIO(png)).convert("RGB")
        self.scale = self.image.width / css_width
        self.pixels = self.image.load()

    def lightness(self, x: int, y: int) -> float:
        r, g, b = self.pixels[x, y]
        return (299 * r + 587 * g + 114 * b) / 1000

    def distance(self, x: int, y: int, ground: tuple[int, int, int]) -> float:
        r, g, b = self.pixels[x, y]
        return (abs(r - ground[0]) + abs(g - ground[1]) + abs(b - ground[2])) / 3

    def centre_x(self, left: float, right: float, top: float, bottom: float,
                 ground: tuple[int, int, int]) -> float:
        """Where the ink in the box lies, from its left, in CSS pixels."""
        x0, x1 = int(left * self.scale), int(right * self.scale) + 1
        y0, y1 = int(top * self.scale), int(bottom * self.scale) + 1
        weight = moment = 0.0
        for y in range(y0, y1):
            for x in range(x0, x1):
                w = self.distance(x, y, ground)
                weight += w
                moment += w * (x + 0.5)
        assert weight > 0, "no ink in the box"
        return moment / weight / self.scale

    def ground_at(self, x: float, y: float) -> tuple[int, int, int]:
        return self.pixels[int(x * self.scale), int(y * self.scale)]


def _middle(box: dict) -> float:
    return (box["top"] + box["bottom"]) / 2


def _dot_error(places: dict) -> dict:
    """Device pixels between the centre of the dot of a state and the centre
    of the line, and of the ring of the answer and the line."""
    shot = _Shot(places["png"], places["width"])
    scale = shot.scale
    disc, ring = places["disc"], places["ring"]
    line_left, line_width = places["lineLeft"], places["lineWidth"]
    between = (_middle(ring) + _middle(disc)) / 2
    ground = shot.ground_at(line_left - 8, between)
    # The line, in a row between the two signs: the whole width round it.
    line = shot.centre_x(line_left - 3, line_left + line_width + 3, between - 4, between + 4, ground)
    # The dot: the rows through its middle, where it covers the line.
    middle = _middle(disc)
    dot = shot.centre_x(disc["left"] - 2, disc["right"] + 2, middle - 1.5, middle + 1.5, ground)
    ring_middle = _middle(ring)
    ring_x = shot.centre_x(ring["left"] - 2, ring["right"] + 2, ring_middle - 1.5, ring_middle + 1.5, ground)
    return {
        "dot": abs(dot - line) * scale,
        "ring": abs(ring_x - line) * scale,
        "air": places["hint"]["left"] - disc["right"],
        "text_air": places["text"]["left"] - ring["right"],
    }


def _edge(places: dict) -> dict:
    """The middle row through the left edge of the ring round today: how far
    its softest pixel lies from both the ring and the ground, in lightness out
    of 255, and how many device pixels the ring is thick."""
    shot = _Shot(places["png"], places["width"])
    today = places["today"]
    y = int(_middle(today) * shot.scale)
    x_start = int((today["left"] - 3) * shot.scale)
    x_end = int((today["left"] + 4.5) * shot.scale)
    ground = shot.lightness(int((today["left"] - 3) * shot.scale), y)
    row = [shot.lightness(x, y) for x in range(x_start, x_end)]
    ring = min(row, key=lambda v: -abs(v - ground))
    soft = max(min(abs(v - ring), abs(v - ground)) for v in row)
    thickness = 0
    for v in row:
        if abs(v - ring) <= 255 / 8:
            thickness += 1
        elif thickness:
            break
    return {"soft": soft, "thickness": thickness, "contrast": abs(ring - ground)}


@pytest.fixture(scope="module")
def runs() -> dict[float, list[dict]]:
    pytest.importorskip("PIL")
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-halfpixel-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        return {scale: _run_chrome(program, folder, scale) for scale in SCALES}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_the_page_is_drawn_at_the_asked_scale(runs):
    for scale, places in runs.items():
        assert all(abs(p["dpr"] - scale) < 1e-6 for p in places)
        assert all(p["entries"] >= 2 and p["disc"] and p["ring"] and p["today"] for p in places)


@pytest.mark.parametrize("scale", SCALES)
def test_the_dot_of_a_state_sits_on_the_middle_of_the_line(runs, scale):
    for places in runs[scale]:
        error = _dot_error(places)
        assert error["dot"] <= 0.3, (scale, places["offset"], error)


@pytest.mark.parametrize("scale", SCALES)
def test_the_ring_of_the_answer_keeps_its_place_on_the_line(runs, scale):
    for places in runs[scale]:
        error = _dot_error(places)
        assert error["ring"] <= 0.6, (scale, places["offset"], error)


def test_from_the_edge_of_the_dot_to_the_text_stand_thirteen_pixels(runs):
    for places in runs[1.0]:
        error = _dot_error(places)
        assert abs(error["air"] - 13) <= 0.25, error
        assert abs(error["text_air"] - 13) <= 0.25, error


@pytest.mark.parametrize("scale", (1.0, 1.5))
def test_the_ring_round_today_has_no_half_lit_edge(runs, scale):
    for places in runs[scale]:
        edge = _edge(places)
        assert edge["contrast"] > 60, edge
        assert edge["soft"] <= 255 / 8, (scale, places["offset"], edge)


def test_the_ring_round_today_is_as_thick_as_it_was_at_double_scale(runs):
    for places in runs[2.0]:
        edge = _edge(places)
        assert edge["contrast"] > 60, edge
        assert edge["thickness"] == 3, (places["offset"], edge)
        assert edge["soft"] <= 255 / 8, edge


@pytest.mark.parametrize("scale", SCALES)
def test_the_ring_leaves_the_size_of_the_number_as_it_was(runs, scale):
    """A border on the number itself would add its width to every two-digit
    day; the ring is a layer of its own and the number keeps its box."""
    for places in runs[scale]:
        today = places["today"]
        assert today["right"] - today["left"] <= 25.4, today
        assert today["bottom"] - today["top"] == 24, today
