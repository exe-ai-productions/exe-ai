"""The server page of the settings, measured in a real browser: once the small
menu of a connected card is open, nothing paints the page black.

The page's content scroller wears a soft mask at its edges (`rollfade.js`).
The menu of a card and its click-away shield used to stand inside that
scroller, and in the app's own window the whole area under the first row of
cards turned black while the menu was open. The browser used for the test
paints it correctly either way (the fault shows only in the program's own
window), so two things are measured here:

* the cause, in the document: no element with `position: fixed` has an
  ancestor that wears a mask — the menu and its click-away shield stand at the
  page's root;
* the result, in the picture: the pixels under the first row of cards are not
  black, the menu is where the card's foot puts it, and the layers go away
  again when the shield is clicked.

`Menueseite.svelte` and `Verbindungen.svelte` are built as shipped, together
with a tiny page of their own, and drawn in headless Chrome. Skipped where
there is no Chrome or no node, like the other browser tests.
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
  import Menueseite from %(page)r
  import Verbindungen from %(connections)r
</script>

<div style="width: 1200px; height: 680px; display: flex; flex-direction: column; position: relative;">
  <Menueseite offen={true} beschriftung="servers">
    {#snippet kopf()}<h2 style="margin: 0; height: 40px;">Servers</h2>{/snippet}
    {#snippet inhalt()}<Verbindungen zuWerkzeugen={() => {}} />{/snippet}
  </Menueseite>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r

// Three servers on file: the page draws a card only for a server that has an entry.
const servers = [{
  name: 'websuche', enabled: true, laeuft: true, type: 'stdio',
  alle_werkzeuge: [{ name: 'search' }, { name: 'fetch' }], allowed_tools: [],
}, {
  name: 'notion', enabled: true, laeuft: true, type: 'http', url: 'https://mcp.notion.com/mcp',
  alle_werkzeuge: [{ name: 'search' }], allowed_tools: [],
}, {
  name: 'github', enabled: true, laeuft: true, type: 'http', url: 'https://api.githubcopilot.com/mcp/',
  alle_werkzeuge: [{ name: 'issues' }], allowed_tools: [],
}, {
  // A server of one's own that wants a sign-in and has none: its card says "not connected", its sheet carries three buttons.
  name: 'atlas', enabled: true, laeuft: false, type: 'http', url: 'http://127.0.0.1:1/mcp', auth: 'oauth',
  alle_werkzeuge: [], allowed_tools: [],
}%(extra)s]
const answers = { '/tools/servers': servers, '/tools/oauth/status': [] }
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
mount(Shell, { target: document.getElementById('wurzel') })
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
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js', cssFileName: 'style' },
  },
})
"""

CASES = r"""
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const rectOf = (node) => {
  const r = node.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height, bottom: r.bottom }
}
for (let k = 0; k < 60 && document.querySelectorAll('.galerie .card').length === 0; k += 1) await wait(100)
await wait(500)
const masked = (node) => {
  const style = getComputedStyle(node)
  return [style.maskImage, style.webkitMaskImage].some((v) => v && v !== 'none')
}
report.cards = document.querySelectorAll('.galerie .card').length
// The setting that makes the case: the page's scroller is masked.
report.scrollerMasked = Array.from(document.querySelectorAll('.inhalt')).some(masked)
const foot = document.querySelector('.galerie .card .state')
report.footFound = Boolean(foot)
foot.click()
await wait(500)
const menu = document.querySelector('.menue')
const shield = document.querySelector('.schirm')
report.menuOpen = Boolean(menu)
report.shieldOpen = Boolean(shield)
const fixedInsideMask = []
for (const node of document.querySelectorAll('*')) {
  if (getComputedStyle(node).position !== 'fixed') continue
  for (let up = node.parentElement; up; up = up.parentElement) {
    if (masked(up)) { fixedInsideMask.push(String(node.className)); break }
  }
}
report.fixedInsideMask = fixedInsideMask
report.menuRect = menu ? rectOf(menu) : null
report.footRect = rectOf(foot)
report.firstRowBottom = Math.max(...Array.from(document.querySelectorAll('.galerie .card')).slice(0, 3).map((n) => n.getBoundingClientRect().bottom))
const frame = document.querySelector('.rechts')
report.frameRect = frame ? rectOf(frame) : null
report.scrollerRect = rectOf(document.querySelector('.inhalt'))
report.viewport = [innerWidth, innerHeight]
// Everything the picture is taken of is on record; the layers go away on a click on the shield.
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
// The click on the shield is made after the picture, by a second call of the harness.
window.__closeShield = async () => {
  document.querySelector('.schirm')?.click()
  await wait(400)
  return {
    menus: document.querySelectorAll('.menue').length,
    shields: document.querySelectorAll('.schirm').length,
    layers: document.querySelectorAll('.menu-layer').length,
  }
}
"""

SHEET_CASES = r"""
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const rect = (node) => {
  const r = node.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }
}
for (let k = 0; k < 60 && document.querySelectorAll('.galerie .card').length === 0; k += 1) await wait(100)
await wait(500)
const measure = async (label, open) => {
  open()
  await wait(700)
  const row = document.querySelector('.knopfzeile')
  const popup = document.querySelector('.popup')
  const buttons = row ? Array.from(row.querySelectorAll('button')) : []
  report[label] = {
    found: Boolean(row && popup),
    names: buttons.map((b) => b.textContent.trim()),
    widths: buttons.map((b) => b.getBoundingClientRect().width),
    heights: buttons.map((b) => b.getBoundingClientRect().height),
    row: row ? rect(row) : null,
    popup: popup ? rect(popup) : null,
    drawn: popup ? [parseFloat(getComputedStyle(popup).width), parseFloat(getComputedStyle(popup).height)] : null,
    columns: document.querySelector('.spalten') ? rect(document.querySelector('.spalten')) : null,
    left: document.querySelector('.spalte') ? rect(document.querySelector('.spalte')) : null,
    leftHasButtons: Boolean(document.querySelector('.spalte .knopfzeile')),
    viewport: [innerWidth, innerHeight],
  }
  const cancel = buttons.find((b) => b.textContent.trim() === 'Cancel' || b.textContent.trim() === 'Abbrechen') || buttons[1]
  cancel?.click()
  await wait(600)
}
const own = () => Array.from(document.querySelectorAll('.galerie .card')).find((c) => c.textContent.includes('atlas')).querySelector('button').click()
await measure('own', own)
await measure('fresh', () => document.querySelector('.tile.own button').click())
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

# The words of every state, in Pearl (`data-modus="hell"`, which also holds
# against a device in its dark scheme) and in Exe (`data-modus="dunkel"`): their
# colour is read from the page, and so are the colours they are to be.
INK_CASES = r"""
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
for (let k = 0; k < 60 && document.querySelectorAll('.galerie .card').length === 0; k += 1) await wait(100)
await wait(500)
const probe = (property, value) => {
  const node = document.createElement('span')
  node.style[property] = value
  document.body.append(node)
  const read = getComputedStyle(node)[property === 'background' ? 'backgroundColor' : property]
  node.remove()
  return read
}
const colour = (node) => (node ? getComputedStyle(node).color : null)
const fill = (node) => (node ? getComputedStyle(node).fill : null)
const state = (name) => document.querySelector(`.galerie .state[data-stand='${name}']`)
const read = async (mode) => {
  document.documentElement.setAttribute('data-modus', mode)
  await wait(400)
  const out = {
    want: {
      rotText: probe('color', 'var(--rot-text)'), gruenText: probe('color', 'var(--gruen-text)'),
      leise: probe('color', 'var(--text-leise)'), still: probe('color', 'var(--text-still)'), rot: probe('color', 'var(--rot)'),
      gruen: probe('color', 'var(--gruen)'),
      gruenSurface: probe('background', 'color-mix(in srgb, var(--gruen) 12%, var(--glass-card))'),
      gruenLine: probe('borderColor', 'color-mix(in srgb, var(--gruen) 28%, transparent)'),
    },
  }
  const lost = document.querySelector('.galerie .lost')
  out.lost = { word: colour(lost?.querySelector('.statetext')), dot: fill(lost?.querySelector('.scheibe')) }
  for (const name of ['verbunden', 'wartet', 'schluessel_fehlt', 'aus']) {
    const foot = state(name)
    const style = foot && getComputedStyle(foot)
    out[name] = foot && {
      word: colour(foot.querySelector('.statetext')), dot: fill(foot.querySelector('.scheibe')),
      surface: style.backgroundColor, line: style.borderTopColor,
    }
  }
  out.heads = Array.from(document.querySelectorAll('.sectionname')).map(colour)
  out.counts = Array.from(document.querySelectorAll('.sectioncount')).map(colour)
  out.headWeights = Array.from(document.querySelectorAll('.sectionname')).map((n) => getComputedStyle(n).fontWeight)
  out.countWeights = Array.from(document.querySelectorAll('.sectioncount')).map((n) => getComputedStyle(n).fontWeight)
  state('verbunden').click()
  await wait(500)
  out.menuState = colour(document.querySelector('.mstand'))
  document.querySelector('.schirm')?.click()
  await wait(400)
  state('schluessel_fehlt').click()
  await wait(500)
  out.menuStateMissingKey = colour(document.querySelector('.mstand'))
  document.querySelector('.schirm')?.click()
  await wait(400)
  return out
}
report.pearl = await read('hell')
report.exe = await read('dunkel')
window.__closeShield = async () => ({})
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

EXTRA_SERVERS = """, {
  name: 'starter', enabled: true, laeuft: false, type: 'stdio',
  alle_werkzeuge: [], allowed_tools: [],
}, {
  name: 'locked', enabled: true, laeuft: false, type: 'stdio', schluessel_gesetzt: false, missing_keys: ['LOCKED_KEY'],
  alle_werkzeuge: [], allowed_tools: [],
}, {
  name: 'asleep', enabled: false, laeuft: false, type: 'stdio',
  alle_werkzeuge: [], allowed_tools: [],
}"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1280px; height: 800px; position: relative; }</style>
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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 120.0) -> dict:
    """Read the page's report over the debug port, take the picture of the
    open menu, then click the shield and read what is left."""
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

        async def call(method: str, **params):
            nonlocal number
            number += 1
            await connection.send(json.dumps({"id": number, "method": method, "params": params}))
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    return response.get("result", {})

        async def value_of(expression: str, wait: bool = False):
            result = await call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=wait)
            return result.get("result", {}).get("value")

        raw = ""
        while time.monotonic() < end and not raw:
            raw = await value_of("document.getElementById('ergebnis')?.textContent || ''")
            if not raw:
                await asyncio.sleep(0.25)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        shot = await call("Page.captureScreenshot", format="png")
        report["picture"] = shot["data"]
        report["after_click"] = await value_of("window.__closeShield()", wait=True)
        return report


def _run_case(cases: str, width: int, extra: str = "") -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-mcp-sheet-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL
            % {
                "page": "../../src/teile/Menueseite.svelte",
                "connections": "../../src/teile/Verbindungen.svelte",
            },
            encoding="utf-8",
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {"global": "../../src/stil/global.css", "extra": extra}, encoding="utf-8"
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
        (folder / "measure.html").write_text(PAGE % {"cases": cases}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                f"--window-size={width},800",
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


@pytest.fixture(scope="module")
def report() -> dict:
    return _run_case(CASES, 1280)


@pytest.fixture(scope="module")
def ink() -> dict:
    return _run_case(INK_CASES, 1280, EXTRA_SERVERS)


@pytest.fixture(scope="module", params=[1280, 720, 375], ids=["1280", "720", "375"])
def sheets(request) -> dict:
    return _run_case(SHEET_CASES, request.param)


def test_the_case_stands_a_masked_scroller_and_an_open_menu(report):
    assert report["cards"] >= 3
    assert report["scrollerMasked"], "the page's scroller must wear the scroll-fade mask for this case"
    assert report["menuOpen"] and report["shieldOpen"]


def test_no_fixed_layer_stands_inside_a_masked_scroller(report):
    assert report["fixedInsideMask"] == []


def test_the_menu_sits_under_the_foot_of_its_card(report):
    menu, foot = report["menuRect"], report["footRect"]
    assert abs(menu["y"] - (foot["bottom"] + 8)) < 2
    assert abs(menu["x"] - foot["x"]) < 2


def test_the_area_under_the_first_row_of_cards_is_not_black(report):
    image_module = pytest.importorskip("PIL.Image")
    picture = image_module.open(io.BytesIO(base64.b64decode(report["picture"]))).convert("RGB")
    scale = picture.width / report["viewport"][0]
    top = int(report["firstRowBottom"] * scale) + 2
    left = int(report["scrollerRect"]["x"] * scale)
    right = int((report["scrollerRect"]["x"] + report["scrollerRect"]["width"]) * scale)
    bottom = int(min(report["scrollerRect"]["bottom"], report["viewport"][1]) * scale)
    black = total = 0
    for y in range(top, bottom, 4):
        for x in range(left, right, 4):
            total += 1
            if max(picture.getpixel((x, y))) <= 6:
                black += 1
    assert total > 100
    assert black / total < 0.02, f"{black} of {total} samples are pure black"


def test_a_click_on_the_shield_takes_both_layers_away(report):
    assert report["after_click"] == {"menus": 0, "shields": 0, "layers": 0}


# --- The button row of the sheet, measured ----------------------------------


def test_the_sheets_of_an_entry_and_of_a_new_address_are_measured(sheets):
    assert sheets["own"]["found"] and sheets["fresh"]["found"]
    assert len(sheets["own"]["names"]) == 3 and len(sheets["fresh"]["names"]) == 2


def test_the_buttons_of_a_sheet_are_equally_wide_and_equally_high(sheets):
    for label in ("own", "fresh"):
        measured = sheets[label]
        assert max(measured["widths"]) - min(measured["widths"]) < 1.0, (label, measured["widths"])
        assert max(measured["heights"]) - min(measured["heights"]) < 1.0, (label, measured["heights"])


def test_from_a_window_of_720_px_every_label_stands_in_one_line(sheets):
    """A button of one line is 34 high; a broken label makes it taller. On a
    phone the sheet is narrower than the row and the labels may break."""
    if sheets["own"]["viewport"][0] < 720:
        pytest.skip("a phone: the labels may break")
    for label in ("own", "fresh"):
        assert max(sheets[label]["heights"]) < 40, (label, sheets[label]["heights"])


def test_the_row_stands_under_both_columns_at_the_right_edge_and_inside_the_sheet(sheets):
    for label in ("own", "fresh"):
        measured = sheets[label]
        row, popup, columns = measured["row"], measured["popup"], measured["columns"]
        assert not measured["leftHasButtons"]
        assert row["y"] >= columns["bottom"] - 1, (label, row, columns)
        assert row["right"] <= popup["right"] + 0.5 and row["x"] >= popup["x"] - 0.5, (label, row, popup)
        assert abs(row["right"] - columns["right"]) < 1.5, (label, row, columns)


def test_the_sheet_keeps_its_size_with_the_row_under_the_columns(sheets):
    """740 wide where the window has room, inside the window where it has not,
    and 520 high, the same for both."""
    for label in ("own", "fresh"):
        width, height = sheets[label]["drawn"]
        assert abs(height - 520) < 1.5, (label, height)
        viewport = sheets[label]["viewport"][0]
        if viewport >= 900:
            assert abs(width - 740) < 1.5, (label, width)
        else:
            assert width > 250, (label, width)
        assert sheets[label]["popup"]["right"] <= viewport, (label, sheets[label]["popup"])
    if sheets["own"]["viewport"][0] >= 720:
        assert sheets["own"]["drawn"] == sheets["fresh"]["drawn"]


# --- The words of a state wear the form made for type -----------------------


@pytest.mark.parametrize("look", ["pearl", "exe"])
def test_every_state_word_wears_the_text_form_of_its_colour(ink, look):
    mode, want = ink[look], ink[look]["want"]
    assert mode["lost"]["word"] == want["rotText"], (look, mode["lost"])
    assert mode["verbunden"]["word"] == want["gruenText"], (look, mode["verbunden"])
    assert mode["wartet"]["word"] == want["gruenText"], (look, mode["wartet"])
    assert mode["schluessel_fehlt"]["word"] == want["rotText"], (look, mode["schluessel_fehlt"])
    assert mode["aus"]["word"] == want["leise"], (look, mode["aus"])
    assert mode["menuState"] == want["gruenText"], look
    assert mode["menuStateMissingKey"] == want["rotText"], look


@pytest.mark.parametrize("look", ["pearl", "exe"])
def test_the_dots_the_surface_and_the_line_keep_the_plain_colour(ink, look):
    mode, want = ink[look], ink[look]["want"]
    assert mode["lost"]["dot"] == want["rot"], (look, mode["lost"])
    assert mode["verbunden"]["dot"] == want["gruen"] and mode["wartet"]["dot"] == want["gruen"], look
    assert mode["schluessel_fehlt"]["dot"] == want["rot"], look
    assert mode["verbunden"]["surface"] == want["gruenSurface"], (look, mode["verbunden"])
    assert mode["verbunden"]["line"] == want["gruenLine"], (look, mode["verbunden"])


def test_the_two_forms_differ_where_the_ground_asks_for_it(ink):
    """Pearl: red and green both need the darker form as type. Exe: only red
    does — green and yellow are the same there, which is why Pearl is measured."""
    assert ink["pearl"]["want"]["rotText"] != ink["pearl"]["want"]["rot"]
    assert ink["pearl"]["want"]["gruenText"] != ink["pearl"]["want"]["gruen"]
    assert ink["exe"]["want"]["rotText"] != ink["exe"]["want"]["rot"]


@pytest.mark.parametrize("look", ["pearl", "exe"])
def test_the_section_heads_are_quiet_and_their_count_stays_still(ink, look):
    mode = ink[look]
    assert len(mode["heads"]) == 2 and set(mode["heads"]) == {mode["want"]["leise"]}, (look, mode["heads"])
    assert mode["counts"] == [mode["want"]["still"]] * 2, (look, mode["counts"])
    assert mode["headWeights"] == ["600"] * 2 and mode["countWeights"] == ["400"] * 2, mode
