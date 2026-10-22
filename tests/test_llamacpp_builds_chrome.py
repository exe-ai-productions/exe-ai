"""The builds of the server program in a real browser: on a Mac four greyed,
locked rows with their size; on Windows the installed build green with a tick
and the others with their size and the download button of a file row — as
large as the button of a file row drawn beside them in the same run; and the
way back to the tested build under a fold that stands only when there is one.

The real section (`LlamaCppSection.svelte`) is built as it ships, with only
the service's answers replaced (`lib/api.js` by a stand-in) and the real
German texts put in. Skipped where there is no Chrome or no node, like the
other browser tests.
"""

from __future__ import annotations

import asyncio
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

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

ENTRY_JS = """import { mount, unmount, createRawSnippet } from 'svelte'
import Section from '../src/teile/LlamaCppSection.svelte'
import Serverabschnitt from '../src/teile/Serverabschnitt.svelte'
import DownloadRow from '../src/teile/DownloadRow.svelte'
import { texte } from '../src/lib/texte.svelte.js'
import katalog from '../../app/locales/de.json'
import '../src/stil/global.css'

texte.katalog = katalog
let handle = null
window.draw = (auskunft) => {
  if (handle) unmount(handle)
  document.getElementById('root').textContent = ''
  handle = mount(Section, { target: document.getElementById('root'), props: { auskunft } })
}
// A name in the card of another section, drawn beside this one.
mount(Serverabschnitt, {
  target: document.getElementById('other'),
  props: { titel: 'other', children: createRawSnippet(() => ({ render: () => '<div class="zeile"><span class="name">cpu</span></div>' })) },
})
// The button of a file row of the catalogue, drawn beside the section.
mount(DownloadRow, { target: document.getElementById('ref'), props: { status: 'neu' } })
"""

# Every call answers with what `window.answers` holds under its name, and
# records its name and its arguments.
API_STUB = """export const setSessionKey = () => {}
export const sitzungNeuLaden = () => {}
export const spracheMerken = () => {}
export const rememberStatusText = () => {}
export const bootMessage = (failure) => String(failure)
export const allPages = async () => []
export async function* antwortStrom() {}
export async function* zusehenStrom() {}
export class ApiFehler extends Error {}
export const api = new Proxy({}, {
  get: (_, name) => async (...args) => {
    ;(window.calls ||= []).push([name, ...args])
    const answer = (window.answers || {})[name]
    return JSON.parse(JSON.stringify(answer === undefined ? {} : answer))
  },
})
"""

CASES = r"""
const report = { errors: [] }
window.addEventListener('error', (event) => report.errors.push(String(event.message)))
window.addEventListener('unhandledrejection', (event) => report.errors.push(String(event.reason && event.reason.message || event.reason)))
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const until = async (test, what, limit = 20000) => {
  const end = Date.now() + limit
  while (Date.now() < end) {
    try { if (test()) return true } catch (_) {}
    await wait(100)
  }
  throw new Error('timed out waiting for ' + what)
}

const FOUR = [
  { variante: 'cpu', groesse: 19398918 },
  { variante: 'cuda12', groesse: 264478423 + 391443627 },
  { variante: 'vulkan', groesse: 33337769 },
  { variante: 'rocm', groesse: 256958369 },
]
window.answers = { serverProgrammStand: { fertig: true, fehler: false, anteil: 1 } }

const colour = (value) => {
  const probe = document.createElement('span')
  probe.style.color = value
  document.body.appendChild(probe)
  const out = getComputedStyle(probe).color
  probe.remove()
  return out
}
const box = (node) => {
  if (!node) return null
  const r = node.getBoundingClientRect()
  return { w: r.width, h: r.height, left: r.left, right: r.right }
}
const reference = box(document.querySelector('#ref .sign-button'))
report.reference = reference
report.otherCard = (() => {
  const name = document.querySelector('#other .zeile .name')
  return name ? [getComputedStyle(name).fontWeight, getComputedStyle(name).fontSize] : null
})()
report.green = colour('var(--gruen)')

const cardRows = () => [...document.querySelectorAll('#root .karte > .zeile')]
const describe = (row) => {
  const size = row.querySelector('.groesse')
  const button = row.querySelector('.sign-button')
  const own = row.querySelector('.zeichenknopf')
  const mark = row.querySelector('.da')
  const name = row.querySelector('.name')
  return {
    name: name ? name.textContent.trim() : null,
    nameOpacity: name ? getComputedStyle(name).opacity : null,
    nameType: name ? [getComputedStyle(name).fontWeight, getComputedStyle(name).fontSize] : null,
    sizeType: size ? [getComputedStyle(size).fontWeight, getComputedStyle(size).fontSize] : null,
    markType: mark ? [getComputedStyle(mark).fontWeight, getComputedStyle(mark).fontSize] : null,
    foldType: row.matches('.klappzeile')
      ? [getComputedStyle(row.querySelector('.klapptext')).fontWeight, getComputedStyle(row.querySelector('.klapptext')).fontSize]
      : null,
    size: size ? size.textContent.trim() : null,
    sizeBeforeButton: size && button ? box(size).right <= box(button).left : null,
    button: button ? { ...box(button), disabled: button.disabled } : null,
    own: own ? { ...box(own), label: own.getAttribute('aria-label'), title: own.getAttribute('title') } : null,
    installed: mark ? mark.textContent.replace(/\s+/g, ' ').trim() : null,
    tick: mark ? Boolean(mark.querySelector('svg')) : false,
    colour: mark ? getComputedStyle(mark).color : null,
    text: row.textContent.replace(/\s+/g, ' ').trim(),
    height: row.getBoundingClientRect().height,
  }
}
const scene = async (auskunft, answer, rows) => {
  window.answers.serverProgrammVarianten = answer
  window.draw(auskunft)
  await until(() => cardRows().length >= rows, rows + ' rows')
  await wait(300)
  return cardRows().map(describe)
}
const mac = { varianten: [], installiert: null, unavailable: FOUR }
const windows = { varianten: FOUR, installiert: 'cpu', unavailable: [] }
const none = { varianten: [], installiert: null, unavailable: [] }

// A Mac: the four builds, greyed and locked.
report.mac = await scene({ programm: '/opt/llama-server', version: 'b11429', updatable: false, restorable: false }, mac, 5)

// Windows with no program yet: the list is the way to fetch one.
report.windows = await scene({ programm: null, version: null, updatable: false, restorable: false }, windows, 5)
window.calls = []
const vulkan = cardRows()[3].querySelector('.sign-button')
vulkan.click()
await until(() => window.calls.some((call) => call[0] === 'serverProgrammHolen'), 'the fetch of a build')
report.pressed = window.calls.filter((call) => call[0] === 'serverProgrammHolen')

// A program that can go back: the fold is open, with its one row.
report.fold = await scene({ programm: '/opt/llama-server', version: 'b11429', updatable: true, restorable: true }, windows, 7)
report.foldButton = (() => {
  const button = document.querySelector('.karte > .klappzeile')
  return button ? { open: button.getAttribute('aria-expanded'), text: button.textContent.trim(), height: button.getBoundingClientRect().height } : null
})()
window.calls = []
document.querySelector('.zeichenknopf').click()
await until(() => window.calls.some((call) => call[0] === 'serverProgramRestore'), 'the way back')
report.restoredBy = window.calls.filter((call) => call[0] === 'serverProgramRestore').length
document.querySelector('.karte > .klappzeile').click()
await wait(200)
report.folded = cardRows().map(describe)
report.foldedState = document.querySelector('.karte > .klappzeile').getAttribute('aria-expanded')

// A Mac with a build to go back to: the greyed rows, then the fold.
report.macFold = await scene({ programm: '/opt/llama-server', version: 'b11429', updatable: false, restorable: true }, mac, 7)

// Nothing to go back to: no fold at all.
report.noFold = await scene({ programm: '/opt/llama-server', version: 'b11429', updatable: true, restorable: false }, windows, 5)
report.noFoldNode = Boolean(document.querySelector('.klappzeile'))

// A system with no builds to list and nothing to go back to: the version row alone.
report.alone = await scene({ programm: '/usr/bin/llama-server', version: 'b11429', updatable: false, restorable: false }, none, 1)
report.aloneFold = Boolean(document.querySelector('.klappzeile'))

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>builds</title>
<style>body { margin: 0; background: #1c1c1a; } #root { width: 1050px; padding: 16px; }</style>
<div id="root"></div><div id="other" style="width: 1050px; padding: 16px"></div><div id="ref" style="padding:16px"></div><pre id="ergebnis"></pre>
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

VITE_CONFIG = """import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { fileURLToPath } from 'node:url'

const stub = fileURLToPath(new URL('./api_stub.js', import.meta.url))

export default defineConfig({
  plugins: [svelte({ compilerOptions: { css: 'injected' } })],
  logLevel: 'error',
  resolve: { alias: [{ find: /^(?:\\.|.*\\/lib)\\/api\\.js$/, replacement: stub }] },
  build: {
    outDir: 'out',
    emptyOutDir: true,
    minify: false,
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js' },
  },
})
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _read_result(port: int, limit: float = 240.0) -> str:
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
            await asyncio.sleep(0.5)
    return ""


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / f".harness-builds-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "api_stub.js").write_text(API_STUB, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=300,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2500:]
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1200,1000", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", page.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            raw = asyncio.run(_read_result(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
        assert raw, "the page reported nothing"
        result = json.loads(raw)
        assert "failure" not in result, result["failure"]
        return result
    finally:
        shutil.rmtree(folder, ignore_errors=True)


SIZES = {"cpu": "19 MB", "cuda12": "626 MB", "vulkan": "32 MB", "rocm": "245 MB"}


def test_the_page_ran_without_a_script_error(report):
    assert report["errors"] == []


def test_a_mac_lists_the_four_builds_greyed_and_locked_with_their_size(report):
    builds = report["mac"][1:]
    assert [b["name"] for b in builds] == list(SIZES)
    for build in builds:
        assert build["size"] == SIZES[build["name"]]
        assert build["sizeBeforeButton"] is True
        assert build["button"]["disabled"] is True
        # Dimmed: the name and the size stand back, the button is dimmed by its own lock.
        assert build["nameOpacity"] == "0.4"
        # No word: not even for the build that runs, the version row names it.
        assert build["installed"] is None
    assert report["mac"][0]["text"].startswith("Version")


def test_the_download_button_is_the_size_of_the_button_of_a_file_row(report):
    """The button of a build is the file row's own, so it is as large as the
    one drawn beside the section in the same run — no number of its own."""
    reference = report["reference"]
    assert reference["w"] > 0
    for rows in (report["mac"][1:], report["windows"][2:]):
        for build in rows:
            assert (build["button"]["w"], build["button"]["h"]) == (reference["w"], reference["h"])


def test_windows_draws_the_installed_build_green_with_a_tick_and_the_rest_with_a_size(report):
    cpu, *others = report["windows"][1:]
    assert cpu["name"] == "cpu"
    assert cpu["installed"] == "Installiert"
    assert cpu["tick"] is True
    assert cpu["colour"] == report["green"]
    assert cpu["size"] is None and cpu["button"] is None
    assert [b["name"] for b in others] == ["cuda12", "vulkan", "rocm"]
    for build in others:
        assert build["size"] == SIZES[build["name"]]
        assert build["sizeBeforeButton"] is True
        assert build["button"]["disabled"] is False
        assert build["nameOpacity"] == "1"


def test_a_press_on_a_build_fetches_that_build(report):
    assert report["pressed"] == [["serverProgrammHolen", "vulkan"]]


def test_the_rows_keep_the_height_of_a_row_of_the_card(report):
    heights = {row["height"] for row in report["windows"][1:]}
    assert len(heights) == 1


def test_the_way_back_stands_under_an_open_fold_with_a_34_px_sign_button(report):
    assert report["foldButton"] == {"open": "true", "text": "Erweitert", "height": 44.0}
    rows = report["fold"]
    # The version row, four builds, the fold, the one row.
    assert [r["name"] for r in rows[1:5]] == ["cpu", "cuda12", "vulkan", "rocm"]
    back = rows[6]
    assert back["name"] == "Getestete Version wiederherstellen"
    assert (back["own"]["w"], back["own"]["h"]) == (34, 34)
    assert back["own"]["label"] == back["own"]["title"] == "Getestete Version wiederherstellen"
    # It is no longer a button of the version row.
    assert "Getestete Version wiederherstellen" not in rows[0]["text"]
    assert report["restoredBy"] == 1


def test_a_press_on_the_fold_closes_it(report):
    assert report["foldedState"] == "false"
    assert not any(r["name"] == "Getestete Version wiederherstellen" for r in report["folded"])


def test_a_mac_with_a_build_to_go_back_to_shows_the_fold_under_the_greyed_rows(report):
    rows = report["macFold"]
    assert [r["name"] for r in rows[1:5]] == ["cpu", "cuda12", "vulkan", "rocm"]
    assert rows[6]["name"] == "Getestete Version wiederherstellen"


def test_silence_without_a_build_to_go_back_to_there_is_no_fold(report):
    assert report["noFoldNode"] is False
    assert all(r["name"] != "Getestete Version wiederherstellen" for r in report["noFold"])
    assert re.fullmatch(r"Version.*", report["noFold"][0]["text"])


def test_silence_a_system_with_nothing_to_list_shows_the_version_row_alone(report):
    assert len(report["alone"]) == 1
    assert report["aloneFold"] is False


SEMI_BOLD = ["600", "13px"]


def test_the_names_of_the_builds_and_the_version_line_are_semi_bold_13(report):
    for rows in (report["mac"], report["windows"], report["fold"]):
        # The version line first, then the builds.
        assert rows[0]["nameType"] == SEMI_BOLD
    for build in report["mac"][1:] + report["windows"][1:]:
        assert build["nameType"] == SEMI_BOLD, build["name"]


def test_the_way_back_is_named_in_semi_bold_13(report):
    back = report["fold"][6]
    assert back["name"] == "Getestete Version wiederherstellen"
    assert back["nameType"] == SEMI_BOLD


def test_silence_the_sizes_the_installed_word_and_the_fold_keep_their_type(report):
    for build in report["windows"][2:]:
        assert build["sizeType"] == ["400", "12px"]
    assert report["windows"][1]["markType"] == ["400", "13px"]
    assert report["fold"][5]["foldType"] == SEMI_BOLD


def test_silence_a_name_in_the_card_of_another_section_stays_regular(report):
    assert report["otherCard"] == ["400", "13px"]


def test_silence_the_builds_a_mac_cannot_run_stay_dimmed(report):
    assert all(build["nameOpacity"] == "0.4" for build in report["mac"][1:])
