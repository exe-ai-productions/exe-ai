"""Names that are cut or broken where they should not be, measured in a real browser.

Three places held a name the wrong way:

* a file's name under its tile in the doc folder broke at any letter
  (`notizen/absatz6.t` over `xt`) instead of after a `/`, `-`, `_` or `.`;
* the last character of a path in the folder row stood half cut at its
  right end;
* the model's name in the narrow and the tight form of the input bar was
  held to 58 and 44 px, however much room the row had left.

The real `DocFolder` and the real input bar are built as shipped and drawn
in headless Chrome, the answers of the service made up in the page. The
page reports the lines each name stands in (from the rectangles of its
text), the pixels at the right end of the path row, and the width of the
model's name in the bar at several widths of the row.

Skipped where there is no Chrome or no node, like the other browser tests.
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

SHELL = """<script>
  import DocFolder from '../../src/teile/DocFolder.svelte'
  import Eingabeleiste from '../../src/teile/Eingabeleiste.svelte'
  import Speicherortzeile from '../../src/teile/Speicherortzeile.svelte'
</script>

<div id="ordner" style="width: 340px; position: relative;"><DocFolder /></div>
<div id="kurz" style="width: 340px; padding: 12px 14px; box-sizing: border-box;">
  <Speicherortzeile name="short_place" etikett="Short" />
</div>
<div id="leiste" style="position: relative;"><Eingabeleiste senden={() => {}} abbrechen={() => {}} /></div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import %(tiles)r
import english from %(english)r
import { texte } from %(texts)r
import { zustand } from %(zustand)r
import { modellwahl } from %(models)r

texte.sprache = 'en'
texte.katalog = english
const FILES = %(files)s
const PLACE = %(place)r
const answer = (body) => new Response(JSON.stringify(body), {
  status: 200, headers: { 'Content-Type': 'application/json' },
})
window.fetch = async (address) => {
  const url = String(address)
  if (url.includes('/doc-folder/place')) return answer({ pfad: PLACE })
  if (url.includes('/doc-folder')) return answer(FILES)
  if (url.includes('/speicherorte')) {
    return answer([{ name: 'agent_dock', pfad: PLACE }, { name: 'short_place', pfad: '/Users/a/b' }])
  }
  return answer({})
}
zustand.modelle = [{ id: 'm1', name: 'mimo-v2.5', group: 'cloud', anbieter: 'x', capabilities: {} }]
zustand.modellId = 'm1'
modellwahl.geladen = true
mount(Shell, { target: document.getElementById('wurzel'), props: {} })
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

CASES = r"""
const BAR_WIDTHS = %(bar_widths)s
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
for (let k = 0; k < 80 && !(document.querySelector('.tilewall .name') && document.querySelector('.bar-row') && document.querySelector('.ordnerzeile .pfad span') && document.querySelector('#kurz .pfad span') && document.querySelector('#kurz .pfad span').textContent); k += 1) await wait(100)
await wait(500)
/* The lines a name stands in: its characters grouped by the top of their
   rectangles, only those the box shows (a clamped name hides the rest). */
const linesOf = (box) => {
  const frame = box.getBoundingClientRect()
  const rows = new Map()
  const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT)
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    for (let at = 0; at < node.data.length; at += 1) {
      const range = document.createRange()
      range.setStart(node, at)
      range.setEnd(node, at + 1)
      const rect = range.getClientRects()[0]
      if (!rect || rect.width === 0) continue
      if (rect.top < frame.top - 1 || rect.bottom > frame.bottom + 1) continue
      const key = Math.round(rect.top)
      rows.set(key, (rows.get(key) || '') + node.data[at])
    }
  }
  return [...rows.entries()].sort((a, b) => a[0] - b[0]).map((row) => row[1])
}
const pathBox = document.querySelector('.ordnerzeile .pfad')
const pathSpan = pathBox.querySelector('span')
const shortBox = document.querySelector('#kurz .pfad')
const shortSpan = shortBox.querySelector('span')
const report = {
  scale: window.devicePixelRatio,
  tiles: [...document.querySelectorAll('.tilewall .name')].map((el) => ({
    width: el.getBoundingClientRect().width,
    text: el.textContent,
    title: el.getAttribute('title'),
    lines: linesOf(el),
    clamped: el.scrollHeight > el.clientHeight + 1,
  })),
  path: {
    box: pathBox.getBoundingClientRect().toJSON(),
    span: pathSpan.getBoundingClientRect().toJSON(),
    clientWidth: pathBox.clientWidth, scrollWidth: pathBox.scrollWidth,
    text: pathSpan.textContent,
  },
  short: {
    box: shortBox.getBoundingClientRect().toJSON(),
    span: shortSpan.getBoundingClientRect().toJSON(),
    text: shortSpan.textContent,
    cut: shortBox.scrollWidth > shortBox.clientWidth + 0.5,
  },
  bar: {},
}
const leiste = document.getElementById('leiste')
for (const width of BAR_WIDTHS) {
  leiste.style.width = `${width}px`
  await wait(700)
  const row = document.querySelector('.bar-row')
  const name = document.querySelector('.bar-row .part .name')
  const tops = [...row.children].map((child) => Math.round(child.getBoundingClientRect().top))
  report.bar[width] = {
    state: row.className.replace(/svelte-\S+/, '').trim(),
    name: name.textContent,
    nameWidth: name.clientWidth,
    later: await (async () => { await wait(300); return name.clientWidth })(),
    nameNeeds: name.scrollWidth,
    cut: name.scrollWidth > name.clientWidth + 0.5,
    oneLine: new Set(tops).size === 1,
    rowHeight: row.getBoundingClientRect().height,
    rowOverflow: row.scrollWidth > row.clientWidth + 1,
    lamps: Boolean(document.querySelector('.bar-row .part .lamps') && getComputedStyle(document.querySelector('.bar-row .part .lamps')).display !== 'none'),
    free: row.clientWidth - [...row.children].reduce((sum, child) => sum + child.getBoundingClientRect().width, 0),
  }
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
%(links)s
<style>html { --stufenfaktor: 1; } html, body { margin: 0; } #wurzel { width: 1280px; position: relative; }</style>
</head><body>
<div id="wurzel"></div>
<pre id="ergebnis" style="display: none"></pre>
<script src="out/entry.js"></script>
<script>
  window.addEventListener('load', async () => {
    try {
      %(cases)s
    } catch (failure) {
      document.getElementById('ergebnis').textContent = JSON.stringify({ failure: String(failure && failure.stack || failure) })
    }
  })
</script>
</body></html>
"""

BAR_WIDTHS = [1000, 602, 555, 524, 493, 477, 461, 446, 430, 415, 384, 352]
NAMES = ["notizen/absatz6.txt", "projekt-bericht.md", "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz.txt", "kurz.md"]
PLACE = "C:\\\\Benutzer\\\\Arbeit\\\\Dokumente\\\\Ablage\\\\Projekte\\\\Wochenberichte\\\\Quartal\\\\W"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 120.0) -> dict:
    """Read the page's report over the debug port."""
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
    async with websockets.connect(address, max_size=32 * 1024 * 1024) as connection:
        number = 0

        async def value_of(expression: str):
            nonlocal number
            number += 1
            await connection.send(
                json.dumps({"id": number, "method": "Runtime.evaluate",
                            "params": {"expression": expression, "returnByValue": True}})
            )
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    return response.get("result", {}).get("result", {}).get("value")

        raw = ""
        while time.monotonic() < end and not raw:
            raw = await value_of("document.getElementById('ergebnis')?.textContent || ''")
            if not raw:
                await asyncio.sleep(0.25)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        box = report["path"]["box"]
        await connection.send(json.dumps({"id": 9000, "method": "Page.captureScreenshot", "params": {
            "format": "png", "clip": {"x": box["left"], "y": box["top"], "width": box["width"],
                                       "height": box["height"], "scale": 1}}}))
        while True:
            response = json.loads(await connection.recv())
            if response.get("id") == 9000:
                report["pathShot"] = response["result"]["data"]
                break
        return report


def _run_case(scale: float = 1.0) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-names-wrap-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        files = [{"id": str(n), "source": "dock", "name": name, "type": "text/plain", "size": 10,
                  "origin": "user"} for n, name in enumerate(NAMES)]
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "tiles": "../../src/stil/tiles.css",
                "english": "../../../app/locales/en.json",
                "zustand": "../../src/lib/zustand.svelte.js",
                "texts": "../../src/lib/texte.svelte.js",
                "models": "../../src/lib/modelle.svelte.js",
                "files": json.dumps(files),
                "place": PLACE,
            },
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        links = "\n".join(
            f'<link rel="stylesheet" href="out/{sheet.name}">' for sheet in sorted((folder / "out").glob("*.css"))
        )
        assert links, "the build emitted no stylesheet"
        (folder / "measure.html").write_text(PAGE % {"cases": CASES % {"bar_widths": json.dumps(BAR_WIDTHS)}, "links": links}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1920,1080",
                f"--force-device-scale-factor={scale}",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri(),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return asyncio.run(_drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _ink_gap(shot: str, scale: float) -> float:
    """CSS pixels between the last drawn pixel of the path row and its right edge."""
    image = pytest.importorskip("PIL.Image").open(io.BytesIO(base64.b64decode(shot))).convert("RGB")
    width, height = image.size
    pixels = image.load()
    colours = [pixels[x, y] for x in range(width) for y in range(height)]
    ground = max(set(colours), key=colours.count)
    last = -1
    for x in range(width):
        for y in range(height):
            if max(abs(a - b) for a, b in zip(pixels[x, y], ground, strict=True)) > 24:
                last = max(last, x)
    return (width - 1 - last) / scale


@pytest.fixture(scope="module")
def report() -> dict:
    return _run_case(1.0)


@pytest.fixture(scope="module")
def scaled() -> dict:
    return _run_case(1.5)


def _tile(report: dict, name: str) -> dict:
    return next(tile for tile in report["tiles"] if tile["title"] == name)


def test_a_file_name_breaks_after_a_slash_and_stands_whole_in_two_lines(report):
    tile = _tile(report, "notizen/absatz6.txt")
    assert tile["lines"] == ["notizen/", "absatz6.txt"], tile


def test_a_file_name_breaks_after_a_hyphen(report):
    tile = _tile(report, "projekt-bericht.md")
    assert tile["lines"] == ["projekt-", "bericht.md"], tile


def test_a_name_without_a_separator_breaks_inside_and_ends_with_dots_with_the_whole_name_in_the_title(report):
    long = "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz.txt"
    tile = _tile(report, long)
    assert len(tile["lines"]) == 2 and tile["clamped"], tile
    assert tile["text"] == long and tile["title"] == long, tile


def test_silence_a_short_name_stands_in_one_line_and_every_name_is_unchanged(report):
    assert _tile(report, "kurz.md")["lines"] == ["kurz.md"]
    for tile in report["tiles"]:
        assert tile["text"] == tile["title"], tile


def _ink_gap(shot: str, scale: float) -> float:
    """CSS pixels between the last drawn pixel of the path row and its right edge."""
    image = pytest.importorskip("PIL.Image").open(io.BytesIO(base64.b64decode(shot))).convert("RGB")
    width, height = image.size
    pixels = image.load()
    colours = [pixels[x, y] for x in range(width) for y in range(height)]
    ground = max(set(colours), key=colours.count)
    last = -1
    for x in range(width):
        for y in range(height):
            if max(abs(a - b) for a, b in zip(pixels[x, y], ground, strict=True)) > 24:
                last = max(last, x)
    return (width - 1 - last) / scale


def test_the_last_character_of_a_path_does_not_touch_the_edge_of_its_row(report, scaled):
    # A path that ends in a wide letter; the row cuts it at the front with
    # dots and the end of the path keeps a pixel of air, at both scales.
    for run, scale in ((report, 1.0), (scaled, 1.5)):
        assert run["path"]["span"]["left"] < run["path"]["box"]["left"], "the path is not longer than its row"
        assert _ink_gap(run["pathShot"], scale) >= 1.0, (scale, _ink_gap(run["pathShot"], scale))


def test_silence_a_short_path_stands_whole_without_dots(report):
    short = report["short"]
    assert not short["cut"], short
    assert short["span"]["left"] >= short["box"]["left"] - 0.5, short
    assert short["text"] == "/Users/a/b", short


@pytest.fixture(scope="module")
def bar(report) -> dict[int, dict]:
    return {int(width): state for width, state in report["bar"].items()}


def test_the_bar_stays_in_one_line_at_every_width(bar):
    for width, state in bar.items():
        assert state["oneLine"] and not state["rowOverflow"], (width, state)
        # Measured again after a moment: the bar has come to rest and does not go on re-measuring.
        assert state["later"] == state["nameWidth"], (width, state)


def test_the_narrow_form_keeps_the_whole_name_and_its_lamps(bar):
    narrow = [state for state in bar.values() if "narrow" in state["state"] and "tight" not in state["state"]]
    assert narrow, bar
    for state in narrow:
        assert not state["cut"] and state["lamps"], state


def test_the_tight_form_takes_the_lamps_and_keeps_the_name_whole_while_it_fits(bar):
    tight = [state for state in bar.values() if "tight" in state["state"]]
    assert any(not state["cut"] for state in tight), bar
    for state in tight:
        assert not state["lamps"], state


def test_a_name_is_cut_only_as_far_as_the_row_demands(bar):
    cut = [state for state in bar.values() if state["cut"]]
    assert cut, "no width of the sweep cuts the name"
    for state in cut:
        assert "tight" in state["state"] and state["free"] < 3, state


def test_silence_the_full_form_is_as_before(bar):
    full = bar[1000]
    assert full["state"] == "bar-row" and full["lamps"] and not full["cut"], full
