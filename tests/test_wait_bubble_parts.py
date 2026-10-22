"""The parts of a waiting bubble, the hint on a touch screen, and one word once.

`Warteblasen.svelte` and `Nachricht.svelte` are built as they are shipped,
together with a tiny page of their own, and drawn in headless Chrome. The page
reports what the layout says:

* a waiting message with a picture, a document and an instruction stands in
  the same parts as the sent one — the picture's frame, the document's card,
  the instruction's pill, no line of names — and its text stands at the same
  place as the sent one's;
* on a screen with no pointer a tap on the word "In der Warteschlange" opens
  the sentence that says what the bubble is, a tap beside it closes it, and
  the block keeps its height; with a pointer the tap opens nothing;
* an answer stopped before anything came says "abgebrochen" once, on its
  line; one stopped with text in it says it in its foot.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
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
  import Nachricht from %(nachricht)r
  import Warteblasen from %(warteblasen)r
  import { scene } from './scene.svelte.js'
</script>

<div class="spur" style="width: 640px; margin: 0 auto; display: flex; flex-direction: column; gap: 40px;">
  <div class="davor">Above</div>
  {#if scene.mode === 'waiting'}
    <Warteblasen takeBack={() => {}} />
  {:else if scene.mode === 'gesendet'}
    <div><Nachricht nachricht={scene.nachricht} istLetzteFrage={true} neuSenden={() => {}} /></div>
  {:else}
    {#key scene.again}
      <div><Nachricht nachricht={scene.antwort} neuErzeugen={() => {}} /></div>
    {/key}
  {/if}
</div>
<style>
  .spur > :global(div) { display: flex; flex-direction: column; min-width: 0; }
</style>
"""

SCENE_JS = """export const scene = $state({ mode: 'waiting', again: 0, nachricht: null, antwort: null })
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import { einreihen } from %(queue)r
import { zustand } from %(zustand)r
import { skills } from %(skills)r
import { nameUpload } from %(preview)r
import %(global)r

window.scene = scene
window.einreihen = einreihen
window.zustand = zustand
window.skills = skills
window.nameUpload = nameUpload
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

CASES = r"""
const { scene, einreihen, zustand, skills, nameUpload } = window
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const report = {}

const textTop = (el) => {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => (node.textContent.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
  })
  const node = walker.nextNode()
  if (!node) return null
  const range = document.createRange()
  range.selectNodeContents(node)
  return range.getClientRects()[0].top
}
// The attachments stand above the bubble in the block of the message, so the
// parts are counted over the whole block; the place and the text are the bubble's.
const parts = (bubble) => ({
  frames: bubble.parentElement.querySelectorAll('.bildrahmen').length,
  cards: bubble.parentElement.querySelectorAll('.dok-reihe .dok-zeile').length,
  pill: bubble.querySelectorAll('.skillpille').length,
  names: bubble.parentElement.querySelectorAll('.anhang').length,
  top: bubble.getBoundingClientRect().top,
  height: bubble.getBoundingClientRect().height,
  width: bubble.getBoundingClientRect().width,
  textTop: textTop(bubble.querySelector('.skillpille') || bubble),
})

zustand.aktiverChat = 'c1'
skills.liste = [{ name: 'summary' }]
const dokument = { id: 'd1', name: 'notes.md', typ: 'md', seiten: null, groesse: 1200 }
const entry = {
  inhalt: '/summary the pictures and the notes',
  bilder: ['picture-one.png'],
  dokumente: [dokument],
}
einreihen('c1', entry)
await wait(400)
const waiting = document.querySelector('.von-mir.waiting')
report.waiting = parts(waiting)
report.waitingOpacity = parseFloat(getComputedStyle(waiting).opacity)

// The same message, sent: the shape the send gives it.
scene.nachricht = {
  id: 'eigen-x', role: 'user', content: entry.inhalt,
  bild: 'picture-one.png', anhaenge: null, dokument, dokumente: null,
}
scene.mode = 'gesendet'
await wait(400)
report.sent = parts(document.querySelector('.von-mir:not(.waiting)'))

// A message with a skill and a text only: no pictures, no cards — the pill.
scene.mode = 'waiting'
zustand.aktiverChat = 'c2'
einreihen('c2', { inhalt: '/summary only words' })
await wait(300)
report.skillOnly = parts(document.querySelector('.von-mir.waiting'))

// A picture still to be uploaded is the file itself: its bubble shows the
// file by an address of its own, and the picture is drawn.
const canvas = document.createElement('canvas')
canvas.width = 40; canvas.height = 30
const pen = canvas.getContext('2d'); pen.fillStyle = '#c33'; pen.fillRect(0, 0, 40, 30)
const file = await new Promise((resolve) => canvas.toBlob((b) => resolve(new File([b], 'local.png', { type: 'image/png' })), 'image/png'))
zustand.aktiverChat = 'c3'
einreihen('c3', { inhalt: 'a file not uploaded yet', bilder: [file] })
await wait(500)
const local = document.querySelector('.attachment-block.waiting img.bildanhang')
report.local = {
  found: Boolean(local),
  blob: Boolean(local && local.src.startsWith('blob:')),
  drawn: Boolean(local && local.complete && local.naturalWidth > 0),
}
// The message goes: the service names the upload, the waiting bubble leaves
// and the sent one shows the very same picture, from the same address and
// already drawn in its first frame, so nothing is fetched or decoded twice.
const waitingSrc = local.src
nameUpload('up-1.png', file)
scene.nachricht = {
  id: 'eigen-y', role: 'user', content: 'a file not uploaded yet',
  bild: 'up-1.png', anhaenge: null, dokument: null, dokumente: null,
}
scene.mode = 'gesendet'
await wait(40)
const swapped = document.querySelector('.attachment-block:not(.waiting) img.bildanhang')
report.swap = {
  found: Boolean(swapped),
  same: Boolean(swapped && swapped.src === waitingSrc),
  drawn: Boolean(swapped && swapped.complete && swapped.naturalWidth > 0),
}
scene.mode = 'waiting'
zustand.aktiverChat = 'c2'
await wait(300)

// 2. The hint on a screen with no pointer.
const realMatch = window.matchMedia.bind(window)
const row = () => document.querySelector('.zeile')
const block = () => row().parentElement.parentElement
report.hint = { heightBefore: block().getBoundingClientRect().height, closedAtFirst: !document.querySelector('.hint') }
const word = document.querySelector('.marke')
// with a pointer: the tap opens nothing
window.matchMedia = (q) => (q.includes('hover: none') ? { matches: false, media: q } : realMatch(q))
word.click()
await wait(100)
report.hint.withPointer = Boolean(document.querySelector('.hint'))
// without one: the tap opens the sentence
window.matchMedia = (q) => (q.includes('hover: none') ? { matches: true, media: q } : realMatch(q))
word.click()
await wait(100)
const hint = document.querySelector('.hint')
report.hint.open = Boolean(hint)
report.hint.text = hint ? hint.textContent.trim() : null
report.hint.expanded = word.getAttribute('aria-expanded')
report.hint.heightOpen = block().getBoundingClientRect().height
if (hint) {
  const h = hint.getBoundingClientRect(), r = row().getBoundingClientRect()
  report.hint.below = h.top >= r.bottom - 1
  report.hint.insideWidth = h.right <= window.innerWidth && h.left >= 0
}
// a tap beside it closes it
document.querySelector('.davor').dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
await wait(100)
report.hint.closedByOutside = !document.querySelector('.hint')
// a tap on the word again opens it, and again closes it
word.click(); await wait(60)
const openAgain = Boolean(document.querySelector('.hint'))
word.click(); await wait(60)
report.hint.toggle = [openAgain, Boolean(document.querySelector('.hint'))]
window.matchMedia = realMatch

// 3. "abgebrochen" once.
const stopped = (id, content, extra = {}) => ({
  id, rolle: 'assistant', content, abschnitte: content ? [{ art: 'content', text: content }] : [],
  werkzeuge: [], stats: {}, zustand: 'abgebrochen', ...extra,
})
const foot = () => {
  const f = document.querySelector('.fuss')
  return f ? f.textContent : ''
}
scene.mode = 'antwort'
scene.antwort = stopped('a1', '')
scene.again += 1
await wait(500)
const said = (key) => document.getElementById('root').textContent.split(key).length - 1
report.emptyStopped = {
  line: said('nachricht.abgebrochen_leer'),
  short: said('nachricht.abgebrochen_kurz'),
  sentence: said('nachricht.stopped_hint'),
  buttons: document.querySelectorAll('.fuss .tat').length,
}
scene.antwort = stopped('a2', 'Some words that came before the stop. And a second sentence of them.')
scene.again += 1
await wait(500)
report.textStopped = {
  line: said('nachricht.abgebrochen_leer'),
  short: said('nachricht.abgebrochen_kurz'),
  sentence: said('nachricht.stopped_hint'),
  inFoot: foot().includes('nachricht.stopped_hint'),
}
scene.antwort = { ...stopped('a3', 'An answer that ran to its end.'), zustand: 'fertig' }
scene.again += 1
await wait(500)
report.finished = {
  short: said('nachricht.abgebrochen_kurz'),
  sentence: said('nachricht.stopped_hint'),
}

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>parts</title>
<style>body { margin: 0; background: #fff; }</style>
<div id="root"></div><pre id="ergebnis"></pre>
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
      document.getElementById('ergebnis').textContent = JSON.stringify({ failure: String(failure && failure.stack || failure) })
    }
  })
</script>
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _read_result(port: int, limit: float = 120.0) -> str:
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
    async with websockets.connect(address, max_size=16 * 1024 * 1024) as connection:
        number = 0
        while time.monotonic() < end:
            number += 1
            await connection.send(json.dumps({
                "id": number,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.getElementById('ergebnis')?.textContent || ''",
                           "returnByValue": True},
            }))
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    break
            value = response.get("result", {}).get("result", {}).get("value", "")
            if value:
                return value
            await asyncio.sleep(0.25)
    return ""


def _measure(program: str, folder: Path, address: str) -> str:
    port = _free_port()
    browser = subprocess.Popen(
        [
            program,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-background-networking",
            "--allow-file-access-from-files",
            "--window-size=900,1000",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={folder / 'profile'}",
            address,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        return asyncio.run(_read_result(port))
    finally:
        prozessstopp.beenden(browser, frist=5)


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-parts-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL
            % {
                "nachricht": "../../src/teile/Nachricht.svelte",
                "warteblasen": "../../src/teile/Warteblasen.svelte",
            },
            encoding="utf-8",
        )
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS
            % {
                "queue": "../../src/lib/warteschlange.svelte.js",
                "preview": "../../src/lib/picturePreview.js",
                "zustand": "../../src/lib/zustand.svelte.js",
                "skills": "../../src/lib/skills.svelte.js",
                "global": "../../src/stil/global.css",
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
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        raw = _measure(program, folder, page.as_uri())
        assert raw, "the page reported nothing"
        scene = json.loads(raw)
        assert "failure" not in scene, scene["failure"]
        return scene
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_a_waiting_message_stands_in_the_parts_of_the_sent_one(report):
    """The picture's frame, the document's card and the instruction's pill
    stand in the waiting bubble as in the sent one; no line of names."""
    waiting, sent = report["waiting"], report["sent"]
    assert waiting["frames"] == sent["frames"] == 1, (waiting, sent)
    assert waiting["cards"] == sent["cards"] == 1, (waiting, sent)
    assert waiting["names"] == 0, waiting
    # the document and the picture take the text; the pill stands in a message
    # of words only
    assert report["skillOnly"]["pill"] == 1, report["skillOnly"]
    assert report["skillOnly"]["names"] == 0 and report["skillOnly"]["frames"] == 0


def test_a_picture_that_is_not_uploaded_yet_is_shown_from_the_file_itself(report):
    local = report["local"]
    assert local["found"] is True, local
    assert local["blob"] is True and local["drawn"] is True, local


def test_the_waiting_bubble_has_the_size_and_place_of_the_sent_one_so_nothing_jumps(report):
    waiting, sent = report["waiting"], report["sent"]
    assert abs(waiting["width"] - sent["width"]) <= 0.5, (waiting, sent)
    assert abs(waiting["height"] - sent["height"]) <= 0.5, (waiting, sent)
    assert abs(waiting["top"] - sent["top"]) <= 0.5, (waiting, sent)
    assert abs(waiting["textTop"] - sent["textTop"]) <= 0.5, (waiting, sent)
    assert abs(report["waitingOpacity"] - 0.6) < 0.01, report["waitingOpacity"]


def test_a_tap_on_the_word_opens_the_sentence_where_there_is_no_pointer(report):
    hint = report["hint"]
    assert hint["closedAtFirst"] is True, hint
    assert hint["open"] is True and hint["text"] == "warteschlange.erklaerung", hint
    assert hint["expanded"] == "true", hint
    assert hint["below"] is True and hint["insideWidth"] is True, hint
    # it stands over what follows: the block keeps its height
    assert abs(hint["heightOpen"] - hint["heightBefore"]) <= 0.5, hint
    assert hint["closedByOutside"] is True, hint
    assert hint["toggle"] == [True, False], hint


def test_silence_with_a_pointer_the_tap_opens_nothing(report):
    assert report["hint"]["withPointer"] is False, report["hint"]


def test_an_answer_stopped_before_anything_came_says_stopped_once(report):
    empty = report["emptyStopped"]
    assert empty["line"] == 1, empty
    assert empty["short"] == 0 and empty["sentence"] == 0, empty
    # copy and generate again stay
    assert empty["buttons"] >= 1, empty


def test_an_answer_stopped_with_text_in_it_says_a_whole_sentence_in_its_foot(report):
    text = report["textStopped"]
    assert text["line"] == 0, text
    assert text["sentence"] == 1 and text["inFoot"] is True, text
    # The short word is no longer the hint of the page (the CLI keeps it).
    assert text["short"] == 0, text


def test_silence_a_finished_answer_has_no_hint(report):
    assert report["finished"] == {"short": 0, "sentence": 0}, report["finished"]


def test_the_sent_picture_is_the_one_the_waiting_bubble_drew_not_a_second_fetch(report):
    swap = report["swap"]
    assert swap["found"] is True, swap
    assert swap["same"] is True and swap["drawn"] is True, swap
