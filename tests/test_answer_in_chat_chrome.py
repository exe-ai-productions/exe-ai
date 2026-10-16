"""The answer in the chat, measured in a real browser.

`Nachricht.svelte` is built as it is shipped, together with a tiny page of
its own, and drawn in headless Chrome. The page plays one answer from its
running state to its end and reports what the layout says:

* the last line of text stays where it was when the waiting mark gives way
  to the readings — and so does the height of the answer's line;
* the window of a block shows ten lines at most and scrolls the rest;
* a click on the row of a call asks the terminal tool for exactly that call;
* the row of a call carries no word at its end, and its label names the one
  that nobody sees;
* the text of an answer that was stored stands whole at once;
* a running block is closed only its head, and open its head, thinking and
  calls stand in one colour;
* under a running answer with text only the mark stands — no word, no clock,
  no readings, no buttons — and with no text yet the wait row speaks as it
  always did;
* the readings of a finished answer stand in the quietest text step, the two
  buttons beside them keep theirs;
* the mark at the end of the line never goes away while the answer runs: its
  outer form stands and the line ends inside its stroke, only the inside
  draws itself again and fades;
* once the answer is over, a stored one too and with no readings, the mark
  stands completely drawn and still in the row of the readings, and the
  line ends on it; with less motion asked for everything stands finished.

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
SRC = FRONTEND / "src"

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import Nachricht from %(nachricht)r
  import Wartezeile from %(wartezeile)r
  import { scene } from './scene.svelte.js'
</script>

{#snippet marke(nurMarke = false)}
  <Wartezeile {nurMarke} art="response" text="working" zeit="3 s" beschriftung="working" />
{/snippet}

<div style="width: 640px; margin: 0 auto;">
  {#key scene.again}
    <Nachricht
      nachricht={scene.nachricht}
      laeuft={scene.laeuft}
      istLetzte={true}
      marke={scene.laeuft ? marke : null}
      neuErzeugen={() => {}}
      neuSenden={() => {}}
    />
  {/key}
</div>
"""

SCENE_JS = """export const scene = $state({ nachricht: { id: 'm1', rolle: 'assistant', content: '' }, laeuft: false, again: 0 })
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import { leiste } from %(leiste)r
import { callSelection } from %(selection)r
import { zustand } from %(zustand)r
import %(global)r

window.scene = scene
window.leiste = leiste
window.callSelection = callSelection
window.zustand = zustand
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
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const settle = async () => { await wait(120) }
// Where the line ends against the stroke of the mark's outer form, in pixels
// on the screen: the end of the row's line piece and the top edge of the
// outer form's stroke (its box minus half the stroke as drawn).
const markGeometry = () => {
  const entry = document.querySelector('.ereignis.place')
  const outline = entry && entry.querySelector('.outline')
  if (!entry || !outline) return null
  const piece = getComputedStyle(entry, '::before')
  const lineEnd = entry.getBoundingClientRect().top + parseFloat(piece.top) + parseFloat(piece.height)
  const stroke = parseFloat(getComputedStyle(outline).strokeWidth) * outline.getScreenCTM().a
  const strokeTop = outline.getBoundingClientRect().top - stroke / 2
  return { lineEnd, strokeTop, gap: strokeTop - lineEnd, piece: piece.display }
}
const dashOf = (node) => parseFloat(getComputedStyle(node).strokeDashoffset)
if (location.hash === '#calm') {
  // Less motion asked for (the browser is started with the setting): the
  // mark stands finished, nothing moves.
  scene.laeuft = true
  scene.nachricht = {
    id: 'c1', rolle: 'assistant', content: 'Some text of the running answer.',
    abschnitte: [{ art: 'content', text: 'Some text of the running answer.' }], werkzeuge: [], stats: {},
  }
  await wait(400)
  const row = document.querySelector('.place')
  const mark = row && row.querySelector('.marke')
  document.getElementById('ergebnis').textContent = JSON.stringify({ calm: {
    asked: matchMedia('(prefers-reduced-motion: reduce)').matches,
    mark: Boolean(mark),
    animations: row ? row.getAnimations({ subtree: true }).length : -1,
    drawn: row ? Array.from(row.querySelectorAll('.strich')).map(dashOf) : [],
    inside: row ? Array.from(row.querySelectorAll('.inside')).map((n) => Number(getComputedStyle(n).opacity)) : [],
  } })
  return
}
const calls = (n, extra = {}) => Array.from({ length: n }, (_, k) => ({
  aufruf_id: 'c' + k, name: 'read_file', argumente: { path: '/tmp/file-' + k + '.txt' },
  ergebnis: 'ok', fehlgeschlagen: false, ...extra(k),
}))
const sectionsOf = (n) => [
  { art: 'content', text: 'I look at the files one after another and then tell you what is in them. '.repeat(3) },
  ...Array.from({ length: n }, (_, k) => ({ art: 'werkzeug', aufruf_id: 'c' + k })),
  { art: 'content', text: 'These are the results. The same short word stands in every one of the files. '.repeat(4) },
]
const row = () => document.querySelector('.antwortlinie')
const lastLine = () => {
  const texts = Array.from(document.querySelectorAll('.fliesstext'))
  const last = texts[texts.length - 1]
  const rects = Array.from(last.querySelectorAll('p')).pop()
  const r = document.createRange()
  r.selectNodeContents(rects)
  const list = Array.from(r.getClientRects())
  return list[list.length - 1]
}
const measure = () => ({
  height: row().getBoundingClientRect().height,
  bottom: lastLine().bottom,
  top: lastLine().top,
})

// 1. A running answer with calls and a waiting mark, then its end.
scene.nachricht = {
  id: 'm1', rolle: 'assistant', content: 'x', abschnitte: sectionsOf(3),
  werkzeuge: calls(3, () => ({})), stats: {},
}
scene.laeuft = true
await settle()
// The text of a running answer flows; the end is measured once it has run out.
const textCount = () => {
  const pieces = Array.from(document.querySelectorAll('.fliesstext'))
  return pieces.length ? pieces[pieces.length - 1].textContent.length : 0
}
let tries = 0
while (textCount() < 300 && tries < 150) { await wait(100); tries += 1 }
report.flow = { chars: textCount(), tries }
const running = measure()
report.marke = Boolean(document.querySelector('.place .wartet'))
const visibleOf = (node) => node ? getComputedStyle(node).visibility : null
const waitRow = document.querySelector('.place .wartet')
report.quiet = {
  mark: Boolean(waitRow && waitRow.querySelector('.marke')),
  word: waitRow ? waitRow.textContent.trim() : null,
  dots: waitRow ? waitRow.querySelectorAll('.tupfen').length : -1,
  clock: waitRow ? waitRow.querySelectorAll('.zeit').length : -1,
  rowHeight: waitRow ? waitRow.getBoundingClientRect().height : -1,
  foot: visibleOf(document.querySelector('.fuss')),
  buttons: Array.from(document.querySelectorAll('.fuss .tat')).map((b) => visibleOf(b)),
}
scene.laeuft = false
scene.nachricht = {
  ...scene.nachricht,
  stats: { erstes_token_nach_sekunden: 1.4, prompt_cache_percent: 80, tokens_pro_sekunde: 42 },
}
await settle()
const finished = measure()
report.end = {
  running, finished,
  jumpBottom: Math.abs(finished.bottom - running.bottom),
  jumpHeight: Math.abs(finished.height - running.height),
  numbersInPlace: Boolean(document.querySelector('.place.done .messung')),
  // The running mark is gone; the finished one (`.fertig`) stands in its row.
  markGone: !document.querySelector('.place .wartet:not(.fertig)'),
}
const inkOf = (variable) => {
  const probe = document.createElement('span')
  probe.style.color = 'var(' + variable + ')'
  document.body.appendChild(probe)
  const ink = getComputedStyle(probe).color
  probe.remove()
  return ink
}
const colourOf = (selector) => {
  const node = document.querySelector(selector)
  return node ? getComputedStyle(node).color : null
}
report.readings = {
  quiet: inkOf('--text-neben'),
  still: inkOf('--text-still'),
  number: colourOf('.place.done .zahl'),
  word: colourOf('.place.done .messung'),
  dot: colourOf('.place.done .trenner'),
  buttons: Array.from(document.querySelectorAll('.fuss .tat')).map((b) => getComputedStyle(b).color),
  buttonCount: document.querySelectorAll('.fuss .tat').length,
  foot: visibleOf(document.querySelector('.fuss')),
}

// 2. Fourteen calls: one block, a window of ten lines at most.
scene.nachricht = {
  id: 'm2', rolle: 'assistant', content: 'x', abschnitte: sectionsOf(14),
  werkzeuge: calls(14, () => ({})), stats: {},
}
await settle()
const head = document.querySelector('.block-head')
report.blocks = document.querySelectorAll('.ereignis.block').length
head.click()
await wait(450)
const blockWindow = document.querySelector('.block-window')
// The window slides open; its measure is taken once the slide is over.
for (let k = 0; k < 40 && blockWindow.style.overflow === 'hidden'; k += 1) {
  blockWindow.getAnimations().forEach((a) => a.finish())
  await wait(50)
}
report.blockWindow = {
  rows: blockWindow.querySelectorAll('.aufruf').length,
  height: blockWindow.clientHeight,
  content: blockWindow.scrollHeight,
}

// 3. A click on a row asks the terminal tool for exactly that call.
const third = blockWindow.querySelectorAll('.aufruf')[2]
third.click()
await settle()
report.click = {
  key: callSelection.key,
  modul: leiste.modul,
  offen: leiste.offen,
  counter: callSelection.counter,
}

// 4. The word nobody sees is in the label, and no word stands at the end.
scene.nachricht = {
  id: 'm3', rolle: 'assistant', content: 'x', abschnitte: sectionsOf(2),
  werkzeuge: [
    ...calls(1, () => ({})),
    { aufruf_id: 'c1', name: 'run_command', argumente: { command: 'false' }, ergebnis: 'boom', exit_code: 2, fehlgeschlagen: true },
  ],
  stats: {},
}
await settle()
document.querySelector('.block-head').click()
await settle()
const buttons = Array.from(document.querySelectorAll('.block-window .aufruf'))
report.labels = buttons.map((k) => k.getAttribute('aria-label'))
report.atEnd = buttons.map((k) => k.querySelector('.wz-rechts, .wz-code, .wz-marke, .wz-dauer') !== null)

// 6. A block that runs, closed, is its head and nothing else: no line of
// the newest step under it. Opened and finished, the head, the thinking and
// the calls stand in one colour, with no weight of their own; the answer
// stands in the text colour.
scene.again += 1
scene.laeuft = true
const thoughtSection = { art: 'reasoning', text: 'I read the task and think about the first step. ', seit: 0 }
const stepSections = (n) => [thoughtSection, ...Array.from({ length: n }, (_, k) => ({ art: 'werkzeug', aufruf_id: 'c' + k }))]
scene.nachricht = {
  id: 'm6', rolle: 'assistant', content: 'x', abschnitte: stepSections(2),
  werkzeuge: calls(2, () => ({ ergebnis: null })), reasoning: thoughtSection.text, stats: {},
}
await wait(800)
report.closed = {
  head: document.querySelectorAll('.block-head').length,
  headText: document.querySelector('.block-head')?.textContent.trim() ?? null,
  stepLine: document.querySelectorAll('.newest-step').length,
  window: document.querySelectorAll('.block-window').length,
  thoughts: document.querySelectorAll('.step-thought').length,
  rows: document.querySelectorAll('.aufruf').length,
  lineBelowHead: document.querySelector('.block-head')?.parentElement.children.length ?? -1,
}
scene.again += 1
scene.laeuft = false
scene.nachricht = {
  id: 'm6b', rolle: 'assistant', content: 'x',
  abschnitte: [...stepSections(2), { art: 'content', text: 'The answer stands here.' }],
  werkzeuge: calls(2, () => ({})), reasoning: thoughtSection.text, stats: {},
}
await wait(500)
document.querySelector('.block-head').click()
await wait(600)
const style = (selector) => {
  const node = document.querySelector(selector)
  if (!node) return null
  const css = getComputedStyle(node)
  return { color: css.color, weight: css.fontWeight, opacity: css.opacity }
}
report.colours = {
  head: style('.block-head'),
  thought: style('.step-thought'),
  call: style('.aufruf'),
  name: style('.aufruf .wz-name'),
  answer: style('.fliesstext'),
}

// 6b. Silence: a running answer with no text yet speaks as it always did —
// the mark, the dots, the word, the clock, and the foot in place.
scene.again += 1
scene.laeuft = true
scene.nachricht = { id: 'm6c', rolle: 'assistant', content: '', abschnitte: [], werkzeuge: [], stats: {} }
await settle()
const silentRow = document.querySelector('.place .wartet')
report.noText = {
  mark: Boolean(silentRow && silentRow.querySelector('.marke')),
  word: silentRow ? silentRow.textContent.trim() : null,
  dots: silentRow ? silentRow.querySelectorAll('.tupfen').length : -1,
  clock: silentRow ? silentRow.querySelectorAll('.zeit').length : -1,
  rowHeight: silentRow ? silentRow.getBoundingClientRect().height : -1,
  foot: getComputedStyle(document.querySelector('.fuss')).visibility,
}

// 11. The mark never goes away while the answer runs: over a whole round its
// outer form and the mark itself never drop below full opacity, the outer
// form stands drawn, and the line ends inside its stroke. Only the inside
// fades.
scene.again += 1
scene.laeuft = true
scene.nachricht = {
  id: 'm11', rolle: 'assistant', content: 'Some text of the running answer.',
  abschnitte: [{ art: 'content', text: 'Some text of the running answer.' }], werkzeuge: [], stats: {},
}
await wait(1000)
let lowest = 1
let lowestInside = 1
let sampled = 0
for (let k = 0; k < 40; k += 1) {
  const markNode = document.querySelector('.place .wartet .marke')
  if (!markNode) { sampled += 1; await wait(100); continue }
  const outlines = Array.from(document.querySelectorAll('.place .wartet .outline'))
  lowest = Math.min(lowest, Number(getComputedStyle(markNode).opacity),
    ...outlines.map((node) => Number(getComputedStyle(node).opacity)))
  const inside = document.querySelector('.place .wartet .inside')
  if (inside) lowestInside = Math.min(lowestInside, Number(getComputedStyle(inside).opacity))
  sampled += 1
  await wait(100)
}
report.mark = {
  sampled, lowest, lowestInside,
  drawn: Array.from(document.querySelectorAll('.place .wartet .outline')).map(dashOf),
  geometry: markGeometry(),
}

// 12. Over: the finished mark stands still in the row of the readings, and
// the line ends on it.
scene.laeuft = false
scene.nachricht = {
  ...scene.nachricht,
  stats: { erstes_token_nach_sekunden: 1.4, prompt_cache_percent: 80, tokens_pro_sekunde: 42 },
}
await settle()
const finishedRow = document.querySelector('.place.done')
const finishedMark = finishedRow && finishedRow.querySelector('.wartet.fertig')
report.finished = {
  mark: Boolean(finishedMark && finishedMark.querySelector('.marke')),
  readings: Boolean(finishedMark && finishedMark.querySelector('.messung')),
  running: document.querySelectorAll('.place .wartet:not(.fertig)').length,
  animations: finishedRow ? finishedRow.getAnimations({ subtree: true }).length : -1,
  drawn: finishedRow ? Array.from(finishedRow.querySelectorAll('.strich')).map(dashOf) : [],
  inside: finishedRow ? Array.from(finishedRow.querySelectorAll('.inside')).map((n) => Number(getComputedStyle(n).opacity)) : [],
  geometry: markGeometry(),
}

// 13. A stored answer with no readings has the finished mark as well, and a
// note under it keeps its dot; the line goes on down to the note.
scene.again += 1
scene.laeuft = false
scene.nachricht = {
  id: 'm13', rolle: 'assistant', content: 'A stored answer without any reading.',
  abschnitte: [{ art: 'content', text: 'A stored answer without any reading.' }],
  stats: { abgeschnitten: true },
}
await settle()
const storedRow = document.querySelector('.place.done')
const noteRows = Array.from(document.querySelectorAll('.antwortlinie > .ereignis'))
report.stored13 = {
  mark: Boolean(storedRow && storedRow.querySelector('.wartet.fertig .marke')),
  readings: storedRow ? storedRow.querySelectorAll('.messung').length : -1,
  animations: storedRow ? storedRow.getAnimations({ subtree: true }).length : -1,
  geometry: markGeometry(),
  noteAfterMark: noteRows.length > 0 && noteRows[noteRows.length - 1] !== storedRow
    && Boolean(noteRows[noteRows.length - 1].querySelector('.punkt')),
  continues: storedRow ? getComputedStyle(storedRow, '::after').content !== 'none' : false,
}

// 7. The window opens and closes in 280 ms, over several frames.
scene.laeuft = false
scene.again += 1
scene.nachricht = {
  id: 'm7', rolle: 'assistant', content: 'x', abschnitte: sectionsOf(14),
  werkzeuge: calls(14, () => ({})), stats: {},
}
await wait(1000)
document.querySelector('.block-head').click()
await wait(20)
const blockWindow7 = document.querySelector('.block-window')
// The slide starts one frame after the click (a dummy animation of the delay
// comes first), so the real one is waited for.
const findAnimation = () => blockWindow7.getAnimations().find((a) => a.effect && a.effect.getTiming().duration > 0)
let a7 = findAnimation()
for (let k = 0; k < 60 && !a7; k += 1) { await wait(50); a7 = findAnimation() }
const fields = a7 ? a7.effect.getKeyframes().map((k) => Object.keys(k)).flat() : []
const height = (ms) => { a7.pause(); a7.currentTime = ms; return blockWindow7.getBoundingClientRect().height }
report.unfold = a7 ? {
  duration: a7.effect.getTiming().duration,
  height: !!fields.includes('height'),
  start: height(10), middle: height(140), end: height(278),
} : null

// 8. The thinking text comes in like the answer's: its last stretch flows
// and fades in, in the open window.
scene.again += 1
scene.laeuft = true
const thinking = (t) => ({
  id: 'm8', rolle: 'assistant', content: 'x',
  abschnitte: [{ art: 'reasoning', text: t, seit: 0 }], werkzeuge: [], reasoning: t, stats: {},
})
scene.nachricht = thinking('First')
await wait(300)
document.querySelector('.block-head')?.click()
await wait(400)
const longer = 'First I read the task. Then I think about which steps are needed and check each one before I answer. '.repeat(3)
scene.nachricht = thinking(longer)
await wait(120)
const thought = document.querySelector('.step-thought')
report.thinkText = { spans: thought ? thought.querySelectorAll('.flow-char').length : -1, teil: thought ? thought.textContent.length : -1 }
for (let k = 0; k < 150 && (document.querySelector('.step-thought')?.textContent.length ?? 0) < longer.length; k += 1) await wait(100)
report.thinkText.end = document.querySelector('.step-thought')?.textContent ?? null
report.thinkText.full = longer

// 5. A stored answer stands whole at once: no fading span anywhere. Each
// message is a component of its own in the chat, so this one is a new one.
scene.laeuft = false
scene.again += 1
scene.nachricht = {
  id: 'm4', rolle: 'assistant', content: 'One sentence that is already there and has to scene whole.',
  stats: {},
}
await settle()
report.stored = {
  spans: document.querySelectorAll('.flow-char').length,
  text: document.querySelector('.fliesstext')?.textContent ?? null,
}
// 10. The row of a helper opens the agents with its card picked.
scene.again += 1
scene.laeuft = false
leiste.offen = false
scene.nachricht = {
  id: 'm10', rolle: 'assistant', content: 'x',
  abschnitte: [{ art: 'werkzeug', aufruf_id: 'h1' }, { art: 'content', text: 'Done.' }],
  werkzeuge: [{ aufruf_id: 'h1', name: 'start_job', argumente: { agent: 'helper' }, auftrag_id: 'job-7', ergebnis: 'started', fehlgeschlagen: false }],
  stats: {},
}
await wait(400)
const row10 = document.querySelector('.helper .agent-row')
report.helper = { row: !!row10, transcriptWord: !!document.querySelector('.agent-transcript') }
if (row10) {
  row10.click()
  await wait(400)
  report.helper.modul = leiste.modul
  report.helper.offen = leiste.offen
  report.helper.selected = zustand.auftragAusgewaehlt
}

// 9. Reduced motion: the window opens without a slide.
window.matchMedia = (q) => ({ matches: true, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
scene.again += 1
scene.laeuft = false
scene.nachricht = {
  id: 'm9', rolle: 'assistant', content: 'x', abschnitte: sectionsOf(14),
  werkzeuge: calls(14, () => ({})), stats: {},
}
await wait(600)
document.querySelector('.block-head').click()
await wait(60)
const reducedWindow = document.querySelector('.block-window')
report.reduced = {
  open: Boolean(reducedWindow),
  slides: reducedWindow ? reducedWindow.getAnimations().filter((a) => a.effect && a.effect.getTiming().duration > 0).length : -1,
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>response</title>
<style>body { margin: 0; background: #fff; }</style>
<div id="root"></div><pre id="ergebnis"></pre>
<script>
  // The page's frame clock is a timer: headless Chrome on a machine without
  // a display does not deliver animation frames, and the text of a running
  // answer is let out frame by frame.
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
    """Wait, in the page's own time, until it has written its report, and
    read it over the debug port. The page's animations run on the browser's
    real clock, which a dump at load or a virtual time budget does not give."""
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


def _measure(program: str, folder: Path, address: str, profile: str, flags: list[str]) -> str:
    """One run of the page in a headless Chrome of its own; what it reports."""
    port = _free_port()
    browser = subprocess.Popen(
        [
            program,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-background-networking",
            "--allow-file-access-from-files",
            "--window-size=900,1400",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={folder / profile}",
            *flags,
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
    folder = FRONTEND / "node_modules" / f".harness-answer-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL
            % {
                "nachricht": "../../src/teile/Nachricht.svelte",
                "wartezeile": "../../src/teile/Wartezeile.svelte",
            },
            encoding="utf-8",
        )
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS
            % {
                "leiste": "../../src/lib/arbeitsleiste.svelte.js",
                "selection": "../../src/lib/callSelection.svelte.js",
                "zustand": "../../src/lib/zustand.svelte.js",
                "global": "../../src/stil/global.css",
            },
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [str(FRONTEND / "node_modules" / ".bin" / "vite"), "build", "--config", "vite.config.js"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        page = folder / "measure.html"
        cases = "const { scene, leiste, callSelection, zustand } = window;\n" + CASES
        page.write_text(PAGE % {"cases": cases}, encoding="utf-8")
        raw = _measure(program, folder, page.as_uri(), "profile", [])
        assert raw, "the page reported nothing"
        scene = json.loads(raw)
        assert "failure" not in scene, scene["failure"]
        # The same page once more with less motion asked for, for the one
        # case that cares.
        calm = _measure(program, folder, page.as_uri() + "#calm", "profile-calm",
                        ["--force-prefers-reduced-motion"])
        assert calm, "the page reported nothing with less motion"
        scene.update(json.loads(calm))
        assert "failure" not in scene, scene["failure"]
        return scene
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_at_the_end_the_last_text_line_stays_and_the_answer_stays_as_high(report):
    """The waiting mark gives way to the readings in the same row: nothing
    above it moves — the last line of text and the height of the answer's
    line differ by a pixel at most (without the row it was thirty)."""
    end = report["end"]
    assert report["marke"], "the measurement saw no waiting mark"
    assert report["flow"]["chars"] >= 300, "the text did not run out before the end"
    assert end["markGone"] and end["numbersInPlace"]
    assert end["jumpBottom"] <= 1, end
    assert end["jumpHeight"] <= 1, end


def test_a_block_holds_all_calls_and_its_window_shows_ten_rows_at_most(report):
    assert report["blocks"] == 1
    blockWindow = report["blockWindow"]
    assert blockWindow["rows"] == 14
    assert blockWindow["height"] <= 200
    assert blockWindow["content"] > blockWindow["height"]


def test_a_click_on_a_row_asks_the_terminal_for_exactly_that_call(report):
    click = report["click"]
    assert click["key"] == "m2#2"
    assert click["modul"] == "terminal" and click["offen"] is True
    assert click["counter"] >= 1


def test_the_row_carries_no_word_at_its_end_and_its_label_names_it(report):
    assert report["atEnd"] == [False, False]
    good, bad = report["labels"]
    assert good.startswith("read_file")
    assert bad.startswith("run_command")
    # The exit code is told in the label of the failed call, and in no other.
    assert len(bad.split(", ")) > len(good.split(", "))


def test_a_stored_answer_stands_whole_at_once(report):
    stored = report["stored"]
    assert stored["spans"] == 0
    assert stored["text"] == "One sentence that is already there and has to scene whole."


def test_a_running_block_is_closed_only_its_head_without_the_line_of_the_newest_step(report):
    closed = report["closed"]
    assert closed["head"] == 1
    # The page has no catalogue: the head says its key.
    assert "nachricht.gedankengang" in closed["headText"], closed
    assert closed["stepLine"] == 0
    # Neither the thinking nor the calls are there until the head is clicked.
    assert closed["window"] == 0 and closed["thoughts"] == 0 and closed["rows"] == 0
    # The head's parent holds the dot and the head, no line under it.
    assert closed["lineBelowHead"] <= 2, closed


def test_head_thinking_and_calls_stand_in_one_colour_without_weight_and_the_answer_stays_bright(report):
    colours = report["colours"]
    ink = colours["head"]["color"]
    for part in ("thought", "call", "name"):
        assert colours[part], part
        assert colours[part]["color"] == ink, (part, colours[part], ink)
    # No weight of the sand name, no dimming of the number or the name.
    assert colours["name"]["weight"] in ("400", "normal")
    assert colours["name"]["opacity"] == "1"
    # The answer is the text colour, not the block's.
    assert colours["answer"]["color"] != ink, colours


def test_the_window_unfolds_in_280_ms_over_several_frames(report):
    unfold = report["unfold"]
    assert unfold, "the window opened without an animation"
    assert unfold["duration"] == 280
    assert unfold["height"], "the animation does not move the height"
    assert unfold["start"] < unfold["middle"] < unfold["end"]


def test_the_thinking_text_flows_fades_in_and_stands_whole_at_the_end(report):
    thinkText = report["thinkText"]
    assert thinkText["spans"] > 0, thinkText
    assert thinkText["teil"] < len(thinkText["full"])
    assert thinkText["end"] == thinkText["full"]


def test_with_reduced_motion_the_window_opens_without_a_slide(report):
    reduced = report["reduced"]
    assert reduced["open"] is True
    assert reduced["slides"] == 0


def test_the_helper_row_opens_the_agents_with_its_card(report):
    helper = report["helper"]
    assert helper["row"], "the helper's row is not drawn"
    # No word at its end any more: the whole row is the button.
    assert helper["transcriptWord"] is False
    assert helper["modul"] == "agenten" and helper["offen"] is True
    assert helper["selected"] == "job-7"


def test_under_a_running_text_only_the_mark_stands_in_its_row(report):
    """No word, no dots, no clock, no readings and no buttons while the text
    runs: they would move down with every new line. The row keeps the height
    of its one line, so nothing jumps when the mark gives way at the end."""
    quiet = report["quiet"]
    assert quiet["mark"], quiet
    assert quiet["word"] == "", quiet
    assert quiet["dots"] == 0 and quiet["clock"] == 0, quiet
    assert quiet["rowHeight"] == 20, quiet
    assert quiet["foot"] == "hidden", quiet
    assert quiet["buttons"] and set(quiet["buttons"]) == {"hidden"}, quiet


def test_before_the_first_word_the_wait_row_speaks_as_it_always_did(report):
    """The silence check: with no text the word, the dots and the clock
    stand by the mark and the foot is not hidden."""
    silent = report["noText"]
    assert silent["mark"], silent
    assert "working" in silent["word"] and "3 s" in silent["word"], silent
    assert silent["dots"] == 1 and silent["clock"] == 1, silent
    assert silent["rowHeight"] == 20, silent
    assert silent["foot"] == "visible", silent


def test_the_readings_of_a_finished_answer_stand_in_the_quietest_text_step(report):
    """Number, word and dot in `--text-neben` like the head, the text and the
    calls of the thinking block; copy and regenerate keep their own ink."""
    readings = report["readings"]
    assert readings["quiet"] != readings["still"], "the two steps must differ for this test to mean anything"
    assert readings["number"] == readings["quiet"], readings
    assert readings["word"] == readings["quiet"], readings
    assert readings["dot"] == readings["quiet"], readings
    assert readings["foot"] == "visible", readings
    assert readings["buttonCount"] == 2, readings
    assert set(readings["buttons"]) == {readings["still"]}, readings


def test_the_line_always_reaches_the_mark_and_never_hangs_loose(report):
    """The mark at the end of the line does not go away while the answer
    runs: over a whole round of 3.4 s, measured every 0.1 s, neither the mark
    nor its outer form drops below full opacity (before, the whole mark was
    gone for the last fifth of every round); the outer form stands drawn; and
    the line ends inside its stroke, not above it (before: 0.8 px short).
    Only the inside fades."""
    mark = report["mark"]
    assert mark["sampled"] == 40, mark
    assert mark["lowest"] == 1, mark
    assert mark["lowestInside"] < 0.5, "the inside no longer draws itself again and fades"
    assert mark["drawn"] and all(offset == 0 for offset in mark["drawn"]), mark
    geometry = mark["geometry"]
    assert geometry, "the mark has no outer form"
    assert geometry["piece"] != "none", geometry
    assert geometry["gap"] <= 0.05, geometry


def test_a_finished_answer_keeps_its_mark_still_at_the_end_of_the_line(report):
    """Over: the mark is in the row of the readings, completely drawn, with
    no animation running on it, the readings beside it, the running mark gone,
    and the line ends on its outer form."""
    finished = report["finished"]
    assert finished["mark"] and finished["readings"], finished
    assert finished["running"] == 0, finished
    assert finished["animations"] == 0, finished
    assert finished["drawn"] and all(offset == 0 for offset in finished["drawn"]), finished
    assert finished["inside"] and all(opacity == 1 for opacity in finished["inside"]), finished
    assert finished["geometry"]["gap"] <= 0.05, finished["geometry"]


def test_a_stored_answer_without_readings_has_the_finished_mark_and_a_note_keeps_its_dot(report):
    stored = report["stored13"]
    assert stored["mark"], stored
    assert stored["readings"] == 0, stored
    assert stored["animations"] == 0, stored
    assert stored["geometry"]["gap"] <= 0.05, stored["geometry"]
    assert stored["noteAfterMark"], "the note under the mark lost its dot"
    assert stored["continues"], "the line breaks between the mark and the note"


def test_with_less_motion_asked_for_everything_stands_finished(report):
    calm = report["calm"]
    assert calm["asked"] is True, "the browser did not take the setting"
    assert calm["mark"], calm
    assert calm["animations"] == 0, calm
    assert calm["drawn"] and all(offset == 0 for offset in calm["drawn"]), calm
    assert calm["inside"] and all(opacity == 1 for opacity in calm["inside"]), calm
