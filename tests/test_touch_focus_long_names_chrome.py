"""Touch, focus and long names, measured in a real browser.

Four things stood wrong in the interface and are measured here with the real
components, built as shipped and drawn in headless Chrome, the answers of the
service made up in the page:

* the status strip stood lit over the veil of a dialog and took clicks and
  Tab (the card's veil, the prompt dialog, the log window);
* on a laptop with a touch screen and a touchpad (`any-pointer: coarse` with a
  fine main pointer) the buttons that only show under the pointer were never
  seen by a finger;
* the cross of a reference picture and the context ring were out of reach for
  Tab, and the three dots of a project row had no name;
* a long name ran out of its row, pushed the run number, the duration and the
  tick away, or let a menu out of the window.

Chrome gets the touch screen through `--blink-settings`: the emulation of
the media features `pointer` and `hover` does not exist in the debug
protocol, and making the finger the main pointer would turn the page into the
phone page.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
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
TEILE = FRONTEND / "src" / "teile"

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

TOUCH_AND_TOUCHPAD = (
    "--blink-settings=primaryPointerType=4,availablePointerTypes=6,primaryHoverType=2,availableHoverTypes=3"
)

LONG_TOOL = "mcp__a_very_long_server_name__" + "a_very_long_tool_name_" * 8
LONG_NAME = "a-very-long-name-" * 20

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
        # Pictures of the named places, taken after the page has come to rest.
        report["shots"] = {}
        for name, clip in (report.get("clips") or {}).items():
            number += 1
            await connection.send(json.dumps({"id": number, "method": "Page.captureScreenshot", "params": {
                "format": "png", "clip": {**clip, "scale": 1}}}))
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    report["shots"][name] = response["result"]["data"]
                    break
        return report


def _run_page(
    shell: str, entry: str, cases: str, flags: tuple[str, ...] = (), size: str = "1920,1080",
    extra: dict[str, str] | None = None,
) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-touch-names-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(shell, encoding="utf-8")
        (folder / "entry.js").write_text(entry, encoding="utf-8")
        for name, text in (extra or {}).items():
            (folder / name).write_text(text, encoding="utf-8")
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
        (folder / "measure.html").write_text(PAGE % {"cases": cases, "links": links}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                f"--window-size={size}",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                *flags,
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


# --- The parts: buttons, focus, names ---------------------------------------

PARTS_SHELL = """<script>
  import ContextRing from '../../src/teile/ContextRing.svelte'
  import ProjectRow from '../../src/teile/ProjectRow.svelte'
  import Chatzeile from '../../src/teile/Chatzeile.svelte'
  import Zahlenfeld from '../../src/teile/Zahlenfeld.svelte'
  import Meldungen from '../../src/teile/Meldungen.svelte'
  import Nachricht from '../../src/teile/Nachricht.svelte'
  import DocFolder from '../../src/teile/DocFolder.svelte'
  import StudioDetails from '../../src/teile/StudioDetails.svelte'
  import ModulTerminal from '../../src/teile/ModulTerminal.svelte'
  import FolderChip from '../../src/teile/FolderChip.svelte'
  import Eingabeleiste from '../../src/teile/Eingabeleiste.svelte'
  import Seitenleiste from '../../src/teile/Seitenleiste.svelte'
  import { scene } from './scene.svelte.js'
  let wert = $state(3)
</script>

<div id="ring" style="padding: 8px;"><ContextRing /></div>
<div id="projekt" style="width: 260px;">
  <ProjectRow project={scene.project} open={false} onToggle={() => {}} menu={() => {}} onDropChat={() => {}} />
</div>
<div id="chatzeile" style="width: 260px;"><Chatzeile chat={scene.chat} oeffnen={() => {}} menue={() => {}} /></div>
<div id="zahl" style="width: 200px;"><Zahlenfeld bind:wert min={1} max={9} beschriftung="n" /></div>
<Meldungen />
<div id="meine" style="width: 640px;">
  <Nachricht nachricht={scene.meine} laeuft={false} istLetzte={false} marke={null}
             neuErzeugen={() => {}} neuSenden={() => {}} />
</div>
<div id="antwort" style="width: 640px;">
  <Nachricht nachricht={scene.antwort} laeuft={false} istLetzte={true} marke={null}
             neuErzeugen={() => {}} neuSenden={() => {}} />
</div>
<div id="terminal" style="width: 520px; height: 220px; overflow: auto;"><ModulTerminal /></div>
<div id="ordner" style="width: 340px; height: 300px; position: relative;"><DocFolder /></div>
<div id="details" style="width: 340px;"><StudioDetails /></div>
<div id="seite" style="position: absolute; left: 1500px; top: 0; width: 300px; height: 500px;"><Seitenleiste /></div>
<div id="chip" style="position: absolute; left: 20px; top: 700px;"><FolderChip open={true} onToggle={() => {}} /></div>
<div id="leiste" style="width: 700px; position: absolute; left: 20px; top: 900px;">
  <Eingabeleiste senden={() => {}} abbrechen={() => {}} />
</div>
"""

SCENE_JS = """export const scene = $state({
  project: { id: 'p1', name: 'Project' },
  chat: { id: 'c1', title: 'Chat' },
  meine: { id: 'u1', rolle: 'user', content: 'Hello' },
  antwort: { id: 'a1', rolle: 'assistant', content: '' },
})
"""

PARTS_ENTRY = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import '../../src/stil/global.css'
import '../../src/stil/tiles.css'
import english from '../../../app/locales/en.json'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand } from '../../src/lib/zustand.svelte.js'
import { modellwahl } from '../../src/lib/modelle.svelte.js'
import { melde } from '../../src/lib/meldewesen.svelte.js'
import { werte, auswahl } from '../../src/lib/studio.svelte.js'
import { imageFamilies } from '../../src/lib/imageFamilies.svelte.js'
import { deferQuestion, waitingQuestions } from '../../src/lib/questionbox.svelte.js'

texte.sprache = 'en'
texte.katalog = english
const answer = (body) => new Response(JSON.stringify(body), {
  status: 200, headers: { 'Content-Type': 'application/json' },
})
const DOCK = [{ id: '1', source: 'agent', name: 'notes.txt', type: 'text/plain', size: 5, origin: 'agent', agent: 'x' }]
window.fetch = async (address) => {
  const url = String(address)
  if (url.includes('/doc-folder')) return answer(DOCK)
  if (url.includes('/speicherorte')) return answer([{ name: 'agent_dock', pfad: '/data/dock' }])
  return answer({})
}
window.EventSource = class { addEventListener() {} close() {} }
const LONG_TOOL = %(long_tool)r
const LONG_NAME = %(long_name)r
const call = { aufruf_id: 'c1', name: LONG_TOOL, argumente: { command: 'ls' }, ergebnis: 'ok',
               fehlgeschlagen: false, lauf_nummer: 7, dauer_sekunden: 12 }
const shortCall = { aufruf_id: 'c2', name: 'ping', argumente: {}, ergebnis: 'ok', fehlgeschlagen: false, dauer_sekunden: 2 }
const reply = {
  id: 'a1', rolle: 'assistant', role: 'assistant', content: 'Done.',
  abschnitte: [{ art: 'content', text: 'Working.' }, { art: 'werkzeug', aufruf_id: 'c1' },
               { art: 'werkzeug', aufruf_id: 'c2' }, { art: 'content', text: 'Done.' }],
  werkzeuge: [call, shortCall], stats: {},
}
scene.antwort = reply
scene.meine = { id: 'u1', rolle: 'user', role: 'user', content: 'Hello' }
scene.project = { id: 'p1', name: LONG_NAME }
scene.chat = { id: 'c1', title: 'Chat', working_dirs: ['/Users/a/' + LONG_NAME] }
zustand.chats = [scene.chat]
zustand.projects = [scene.project]
zustand.aktiverChat = 'c1'
zustand.nachrichtenChatId = 'c1'
zustand.nachrichten = [scene.meine, reply]
zustand.modelle = [{ id: 'm1', name: 'long-model-name-'.repeat(4), group: 'cloud', anbieter: 'x', capabilities: {}, context_tokens: 8000 }]
zustand.modellId = 'm1'
modellwahl.geladen = true
werte.ref_bilder = ['reference.png']
auswahl.art = 'edit'
werte.familie = 'many'
imageFamilies.list = [{ name: 'many', many_references: true }]
melde('Hello', 'hinweis', { dauerhaft: true })
zustand.benutzerfrage.c1 = { generationId: 'g1', aufrufId: 'k1', frage: 'Question?', optionen: [], chatId: 'c1' }
deferQuestion('c1', waitingQuestions('c1')[0])
mount(Shell, { target: document.getElementById('wurzel') })
"""

PARTS_CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
for (let k = 0; k < 80 && !(document.querySelector('.chat') && document.querySelector('.project')); k += 1) await wait(100)
await wait(600)
const box = (el) => el && el.getBoundingClientRect().toJSON()
const opacity = (el) => (el ? Number(getComputedStyle(el).opacity) : null)
const visible = (el) => Boolean(el) && getComputedStyle(el).display !== 'none' && opacity(el) === 1
const report = {
  media: {
    anyCoarse: matchMedia('(any-pointer: coarse)').matches,
    pointerFine: matchMedia('(pointer: fine)').matches,
    hoverHover: matchMedia('(hover: hover)').matches,
  },
  buttons: {
    chat: opacity(document.querySelector('#chatzeile .mehr')),
    project: opacity(document.querySelector('#projekt .more')),
    notice: opacity(document.querySelector('.meldung .zu')),
    own: opacity(document.querySelector('#meine .fuss.meine')),
    steps: opacity(document.querySelector('#zahl .treppe')),
    dock: opacity(document.querySelector('#ordner .weg')),
    ref: opacity(document.querySelector('#details .ref .weg')),
  },
  projectMore: (() => {
    const el = document.querySelector('#projekt .more')
    return el && { label: el.getAttribute('aria-label'), title: el.getAttribute('title') }
  })(),
}
/* Focus: what a keyboard can land on, and what then shows. */
const ref = document.querySelector('#details .ref .weg')
if (ref) {
  ref.focus()
  await wait(250)
  report.refFocus = { landed: document.activeElement === ref, opacity: opacity(ref), display: getComputedStyle(ref).display }
}
const ring = document.querySelector('#ring .ring')
if (ring) {
  ring.focus()
  await wait(300)
  const card = ring.querySelector('.card')
  report.ringFocus = {
    landed: document.activeElement === ring,
    cardOpacity: opacity(card),
    cardText: card.textContent.replace(/\s+/g, ' ').trim(),
  }
  ring.blur()
}
/* Names: how they end and whether what stands after them stays in the row. */
document.querySelector('#antwort .block-head')?.click()
for (let k = 0; k < 50 && !document.querySelector('#antwort .aufruf'); k += 1) await wait(100)
await wait(300)
const cut = (el) => Boolean(el) && el.scrollWidth > el.clientWidth + 0.5
const inside = (el, row) => Boolean(el) && el.getBoundingClientRect().right <= row.getBoundingClientRect().right + 0.5
const chatRows = Array.from(document.querySelectorAll('#antwort .aufruf')).map((row) => {
  const name = row.querySelector('.wz-name')
  return {
    cut: cut(name), title: name.getAttribute('title'), numberInside: inside(row.querySelector('.wz-nummer'), row),
    number: row.querySelector('.wz-nummer')?.textContent ?? null,
  }
})
report.chatRows = chatRows
report.terminalRows = Array.from(document.querySelectorAll('#terminal .aufruf')).map((row) => {
  const name = row.querySelector('.name')
  return {
    cut: cut(name), title: name.getAttribute('title'),
    durationInside: inside(row.querySelector('.dauer'), row),
    tickInside: inside(row.querySelector('.ausgang'), row),
  }
})
const chip = document.querySelector('.later-chip')
if (chip) {
  const asker = chip.querySelector('.asker')
  report.laterChip = { cut: cut(asker), title: chip.getAttribute('title'), text: asker?.textContent }
}
const side = document.querySelector('#seite .chat')
if (side) {
  side.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 1800, clientY: 300 }))
  await wait(300)
  document.querySelector('.kontextmenue [aria-haspopup="menu"]')?.click()
  await wait(300)
  const sideMenu = document.querySelector('.kontextmenue')
  const words = Array.from(sideMenu?.querySelectorAll('.wort') ?? [])
  report.sideMenu = sideMenu && {
    right: sideMenu.getBoundingClientRect().right, window: window.innerWidth,
    cutWord: words.some(cut), titles: Array.from(sideMenu.querySelectorAll('button[title]')).map((el) => el.getAttribute('title')),
  }
}
const menu = document.querySelector('#chip .menu')
if (menu) {
  const labels = Array.from(menu.querySelectorAll('.row .label'))
  report.folderMenu = {
    right: menu.getBoundingClientRect().right, window: window.innerWidth,
    cutLabel: labels.some(cut), titles: Array.from(menu.querySelectorAll('.row[title]')).map((el) => el.getAttribute('title')),
  }
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


def _parts(flags: tuple[str, ...] = ()) -> dict:
    entry = PARTS_ENTRY % {"long_tool": LONG_TOOL, "long_name": LONG_NAME}
    return _run_page(PARTS_SHELL, entry, PARTS_CASES, flags, extra={"scene.svelte.js": SCENE_JS})


@pytest.fixture(scope="module")
def mouse() -> dict:
    return _parts()


@pytest.fixture(scope="module")
def touch() -> dict:
    return _parts((TOUCH_AND_TOUCHPAD,))




# --- The status strip under a veil ---------------------------------------------

APP_SHELL = """<script>
  import App from '../../src/App.svelte'
</script>

<App />
"""

APP_ENTRY = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import '../../src/stil/global.css'
import '../../src/stil/tiles.css'
import english from '../../../app/locales/en.json'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand } from '../../src/lib/zustand.svelte.js'
import { oeffneProtokoll } from '../../src/lib/protokollfenster.svelte.js'
import { questionCardStands, waitingQuestions, standingQuestion } from '../../src/lib/questionbox.svelte.js'
window.qcs = { questionCardStands, waitingQuestions, standingQuestion }

window.__errs = []
window.addEventListener('error', (e) => window.__errs.push(String(e.message)))
window.addEventListener('unhandledrejection', (e) => window.__errs.push(String(e.reason && e.reason.stack || e.reason)))
const origError = console.error
console.error = (...a) => { window.__errs.push(a.map(String).join(' ')); origError(...a) }
texte.sprache = 'en'
texte.katalog = english
const answer = (body) => new Response(JSON.stringify(body), {
  status: 200, headers: { 'Content-Type': 'application/json' },
})
const CHAT = { id: 'c1', title: 'Chat', working_dirs: [] }
window.__urls = []
window.fetch = async (address) => {
  const url = String(address)
  window.__urls.push(url)
  if (/[/]chats([?]|$)/.test(url)) return answer([CHAT])
  if (/[/](projects|agents|models|skills|bild[/]familien)([?]|$)/.test(url)) return answer([])
  return answer({})
}
window.EventSource = class { addEventListener() {} close() {} }
zustand.chats = [CHAT]
zustand.aktiverChat = 'c1'
mount(Shell, { target: document.getElementById('wurzel') })
window.zustand = zustand
window.setScene = async (scene) => {
  if (scene === 'card') {
    zustand.benutzerfrage.c1 = { generationId: 'g1', aufrufId: 'k1', frage: 'Question?', optionen: [], chatId: 'c1' }
  } else if (scene === 'prompt') {
    zustand.frage = { text: 'Sure?', eingabe: null, okSchluessel: 'app.ok', danger: false, aufloesen() {} }
  } else if (scene === 'log') {
    oeffneProtokoll('Log')
  }
}
"""

APP_CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
for (let k = 0; k < 80 && !document.querySelector('.fussstreifen'); k += 1) await wait(100)
await wait(500)
await window.setScene(%(scene)r)
await wait(900)
const strip = document.querySelector('.fussstreifen')
const reading = strip.querySelector('.wort') || strip.firstElementChild
const rect = reading.getBoundingClientRect()
const mid = [rect.left + rect.width / 2, rect.top + rect.height / 2]
const stack = document.elementsFromPoint(...mid)
const veil = stack.findIndex((el) => /(^|\s)(schleier|veil)(\s|$)/.test(el.className?.baseVal ?? el.className ?? ''))
const own = stack.findIndex((el) => el === strip || strip.contains(el))
document.getElementById('ergebnis').textContent = JSON.stringify({
  scene: %(scene)r,
  errs: window.__errs.slice(0, 5),
  inert: strip.inert,
  zIndex: getComputedStyle(strip).zIndex,
  topIsStrip: own === 0,
  veilAbove: veil !== -1 && (own === -1 || veil < own),
  clips: { reading: { x: rect.left - 2, y: rect.top - 2, width: rect.width + 4, height: rect.height + 4 } },
})
"""


def _strip(scene: str) -> dict:
    return _run_page(APP_SHELL, APP_ENTRY, APP_CASES % {"scene": scene})


@pytest.fixture(scope="module")
def strip_scenes() -> dict[str, dict]:
    return {scene: _strip(scene) for scene in ("none", "card", "prompt", "log")}


def _brightest(shot: str) -> int:
    """The brightest channel value in a picture: the lit ink of the strip."""
    image = pytest.importorskip("PIL.Image").open(io.BytesIO(base64.b64decode(shot))).convert("RGB")
    return max(max(pixel) for pixel in image.getdata())


@pytest.mark.parametrize("scene", ["card", "prompt", "log"])
def test_the_status_strip_goes_under_the_veil_of_the_card_the_prompt_and_the_log(strip_scenes, scene):
    report = strip_scenes[scene]
    assert report["veilAbove"] and not report["topIsStrip"], report
    assert report["inert"] is True, report
    assert _brightest(report["shots"]["reading"]) < _brightest(strip_scenes["none"]["shots"]["reading"]) - 10, scene


def test_silence_without_a_veil_the_strip_stands_over_the_windows_as_before(strip_scenes):
    report = strip_scenes["none"]
    assert report["topIsStrip"] and report["inert"] is False and report["zIndex"] == "80", report
    scrim = re.search(r"\.schleier\s*\{[^}]*z-index:\s*(\d+)", (TEILE / "Fenster.svelte").read_text())
    assert scrim and int(scrim.group(1)) < 80, "a window's scrim must stay under the strip"


def test_the_touch_screen_is_there_in_the_one_run_and_not_in_the_other(mouse, touch):
    assert touch["media"] == {"anyCoarse": True, "pointerFine": True, "hoverHover": True}, touch["media"]
    assert mouse["media"]["anyCoarse"] is False, mouse["media"]


BUTTONS = ["chat", "project", "notice", "own", "steps", "dock", "ref"]


def test_with_a_touch_screen_the_hover_buttons_stand_in_sight_beside_a_touchpad(touch):
    assert {name: touch["buttons"][name] for name in BUTTONS} == dict.fromkeys(BUTTONS, 1), touch["buttons"]


def test_silence_with_a_mouse_alone_the_hover_buttons_stay_hidden_until_the_pointer_comes(mouse):
    assert {name: mouse["buttons"][name] for name in BUTTONS} == dict.fromkeys(BUTTONS, 0), mouse["buttons"]


def test_every_css_fallback_for_a_screen_without_hover_asks_for_a_touch_screen_too():
    # Three of the ten places (the report rows, the picture tiles, the cloud
    # models) are not drawn in this page; their rules are read from the source.
    for path in sorted(TEILE.glob("*.svelte")):
        for found in re.finditer(r"@media \(hover: none\)([^{]*)\{", path.read_text()):
            assert found.group(1).strip() == ", (any-pointer: coarse)", (path.name, found.group(0))
    for name, selector in (("ModulAgenten", ".bweg"), ("StudioGallery", ".kachel .mehr"), ("ModelleCloud", ".haken")):
        text = (TEILE / f"{name}.svelte").read_text()
        block = re.search(r"@media \(hover: none\), \(any-pointer: coarse\) \{(.*?)\n  \}", text, re.S)
        assert block and selector in block.group(1), (name, selector)
    cloud = (TEILE / "ModelleCloud.svelte").read_text()
    assert re.search(r"\(any-pointer: coarse\) \{\s*\.haken:not\(\.an\) \{ opacity: 0\.3; \}", cloud)


def test_the_cross_of_a_reference_picture_takes_the_keyboard_and_shows_itself(mouse):
    assert mouse["refFocus"] == {"landed": True, "opacity": 1, "display": "flex"}, mouse["refFocus"]


def test_the_context_ring_takes_the_keyboard_and_its_card_shows_the_figures(mouse):
    ring = mouse["ringFocus"]
    assert ring["landed"] and ring["cardOpacity"] == 1 and "8k" in ring["cardText"], ring


def test_the_three_dots_of_a_project_row_are_named_more_in_both_languages(mouse):
    assert mouse["projectMore"] == {"label": "More", "title": "More"}, mouse["projectMore"]
    german = json.loads((ROOT / "app" / "locales" / "de.json").read_text(encoding="utf-8"))
    assert german["app"]["mehr"] == "Mehr"


def test_a_long_tool_name_ends_with_dots_in_the_chat_and_keeps_the_number(mouse):
    long, short = mouse["chatRows"]
    assert long["cut"] and long["numberInside"] and long["number"] == "#7" and long["title"] == LONG_TOOL, long
    assert not short["cut"] and short["title"] == "ping", short


def test_a_long_tool_name_ends_with_dots_in_the_terminal_and_keeps_duration_and_tick(mouse):
    long, short = mouse["terminalRows"]
    assert long["cut"] and long["durationInside"] and long["tickInside"] and long["title"] == LONG_TOOL, long
    assert not short["cut"] and short["tickInside"], short


def test_the_name_of_a_question_pushed_away_ends_with_dots_and_stands_whole_in_the_hint(mouse):
    chip = mouse["laterChip"]
    assert chip["cut"] and chip["text"] in chip["title"], chip


def test_the_folder_menu_ends_at_the_window_edge_and_a_long_name_ends_with_dots(mouse):
    menu = mouse["folderMenu"]
    assert menu["right"] <= menu["window"] and menu["cutLabel"], menu
    assert any(LONG_NAME in title for title in menu["titles"]), menu["titles"]


def test_the_menu_of_the_list_ends_at_the_window_edge_and_a_long_project_name_ends_with_dots(mouse):
    menu = mouse["sideMenu"]
    assert menu["right"] <= menu["window"] and menu["cutWord"], menu
    assert menu["titles"] == [LONG_NAME], menu["titles"]
