"""A tap on the line of a call, on the phone page: the terminal as a sheet.

`Nachricht.svelte` and `TerminalSheet.svelte` are built as they are shipped,
together with a tiny page of their own, and drawn in headless Chrome. The
page marks its root as the phone page does, opens the block of an answer,
taps the third call and reports what stands there:

* the terminal stands as a sheet over the chat, the call that was tapped
  stands in it unfolded and marked, and the desktop's column stays shut;
* the rows of the open block are 44 px high on the phone page, and a
  little more than 19 px on the desktop's;
* the sheet closes with a tap on the veil, with the key, and with the head
  pulled down; the focus goes back to the row that was tapped;
* the same tap on the desktop page opens the column, not the sheet
  (`moduleShow('terminal')`).

Skipped where there is no Chrome or no node, like the other browser tests.
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
SRC = FRONTEND / "src"

needs_chrome = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
    reason="no node or no frontend dependencies on this machine",
)

SHELL = """<script>
  import Nachricht from %(nachricht)r
  import TerminalSheet from %(sheet)r
  import { scene } from './scene.svelte.js'
</script>

<div style="width: 390px; margin: 0 auto;">
  <Nachricht nachricht={scene.nachricht} istLetzte={true} neuErzeugen={() => {}} neuSenden={() => {}} />
</div>
<TerminalSheet />
"""

SCENE_JS = """export const scene = $state({ nachricht: { id: 'm2', rolle: 'assistant', content: '' } })
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import { leiste } from %(leiste)r
import { callSelection, terminalSheet } from %(selection)r
import { zustand } from %(zustand)r
import %(global)r

window.scene = scene
window.leiste = leiste
window.callSelection = callSelection
window.terminalSheet = terminalSheet
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
const { scene, leiste, callSelection, terminalSheet, zustand } = window
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const report = {}
const calls = (n) => Array.from({ length: n }, (_, k) => ({
  aufruf_id: 'c' + k, name: 'read_file', argumente: { path: '/tmp/file-' + k + '.txt' },
  ergebnis: 'ok', fehlgeschlagen: false,
}))
const sectionsOf = (n) => [
  { art: 'content', text: 'I look at the files one after another and then tell you what is in them. ' },
  ...Array.from({ length: n }, (_, k) => ({ art: 'werkzeug', aufruf_id: 'c' + k })),
  { art: 'content', text: 'These are the results.' },
]
const message = {
  id: 'm2', rolle: 'assistant', content: 'x', abschnitte: sectionsOf(14), werkzeuge: calls(14), stats: {},
}
zustand.aktiverChat = 'c1'
zustand.nachrichtenChatId = 'c1'
zustand.nachrichten = [message]
scene.nachricht = message
await wait(300)

const openBlock = async () => {
  const head = document.querySelector('.block-head')
  if (head && !document.querySelector('.block-window')) head.click()
  await wait(450)
  const win = document.querySelector('.block-window')
  for (let k = 0; k < 40 && win.style.overflow === 'hidden'; k += 1) {
    win.getAnimations().forEach((a) => a.finish())
    await wait(50)
  }
  return win
}
const dialog = () => document.querySelector('[role=dialog]')
const pointer = (target, type, y) =>
  target.dispatchEvent(new PointerEvent(type, { bubbles: true, clientY: y, pointerId: 1 }))
const closed = async () => {
  for (let k = 0; k < 40 && dialog(); k += 1) {
    document.getAnimations().forEach((a) => a.finish())
    await wait(50)
  }
  return !dialog()
}

// 1. The desktop page: the tap opens the column, no sheet, rows as before.
let win = await openBlock()
const desktopRow = win.querySelectorAll('.aufruf')[2]
report.desktop = { rowHeight: desktopRow.getBoundingClientRect().height }
desktopRow.click()
await wait(200)
report.desktop.sheet = terminalSheet.open
report.desktop.dialog = Boolean(dialog())
report.desktop.modul = leiste.modul
report.desktop.offen = leiste.offen
leiste.offen = false
callSelection.key = null

// 2. The phone page: the tap raises the sheet at this very call.
document.documentElement.setAttribute('data-phone', '')
await wait(100)
const row = win.querySelectorAll('.aufruf')[2]
report.phone = { rowHeight: row.getBoundingClientRect().height }
row.click()
await wait(500)
const sheet = dialog()
report.phone.sheet = terminalSheet.open
report.phone.dialog = Boolean(sheet)
report.phone.label = sheet ? sheet.getAttribute('aria-label') : null
report.phone.head = sheet ? sheet.querySelector('.head').textContent.trim() : null
report.phone.offen = leiste.offen
report.phone.markedKey = sheet?.querySelector('.werkzeugblock.selected .aufruf')?.getAttribute('data-key') ?? null
report.phone.markedOpen = Boolean(sheet?.querySelector('.werkzeugblock.selected .aufruf.offen'))
report.phone.focusOnTerminal = Boolean(sheet && sheet.contains(document.activeElement))

// 3. The veil closes it, and the focus goes back to the tapped row.
document.querySelector('.veil').click()
report.veil = { closed: await closed(), open: terminalSheet.open }
await wait(100)
report.veil.focusBack = document.activeElement === row

// 4. The key closes it.
row.click()
await wait(500)
report.key = { before: Boolean(dialog()) }
window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
report.key.closed = await closed()

// 5. A short pull of the head does not close it, a long one does.
row.click()
await wait(500)
const head = dialog().querySelector('.head')
pointer(head, 'pointerdown', 100)
pointer(head, 'pointermove', 130)
await wait(60)
report.pull = { shiftShort: dialog().querySelector('.content').style.transform }
pointer(head, 'pointerup', 130)
await wait(100)
report.pull.stillOpen = Boolean(dialog())
pointer(head, 'pointerdown', 100)
pointer(head, 'pointermove', 220)
await wait(60)
report.pull.shiftLong = dialog().querySelector('.content').style.transform
pointer(head, 'pointerup', 220)
report.pull.closed = await closed()
await wait(100)
report.pull.focusBack = document.activeElement === row

// 6. A shell call whose run is gone (the service was restarted): the chat
// asks for it by its run's number, its line in the terminal stands under the
// message's key, and the tap still finds it.
const shell = {
  id: 'm3', rolle: 'assistant', content: 'x',
  abschnitte: [
    { art: 'content', text: 'I run three commands one after the other and then tell you what they said. ' },
    ...[1, 2, 3].map((n) => ({ art: 'werkzeug', aufruf_id: 's' + n })),
    { art: 'content', text: 'These are the results.' },
  ],
  werkzeuge: [1, 2, 3].map((n) => ({
    aufruf_id: 's' + n, name: 'run_command', argumente: { command: 'echo ' + n },
    ergebnis: 'ok', fehlgeschlagen: false, lauf_nummer: n,
  })),
  stats: {},
}
zustand.nachrichten = [shell]
scene.nachricht = shell
await wait(600)
const shellWindow = await openBlock()
const shellRows = shellWindow.querySelectorAll('.aufruf')
report.shell = { rows: shellRows.length }
shellRows[1].click()
await wait(500)
const shellSheet = dialog()
report.shell.sheet = Boolean(shellSheet)
report.shell.markedKey = shellSheet?.querySelector('.werkzeugblock.selected .aufruf')?.getAttribute('data-key') ?? null
report.shell.markedOpen = Boolean(shellSheet?.querySelector('.werkzeugblock.selected .aufruf.offen'))
// The list fits: no button to jump to its end hovers over the rows.
report.shell.jumpButton = Boolean(document.querySelector('.runter'))

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>sheet</title>
<style>body { margin: 0; background: #fff; }</style>
<div id="root"></div><pre id="ergebnis"></pre>
<script>
  // The page's frame clock is a timer: headless Chrome on a machine without
  // a display does not deliver animation frames.
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
    """Wait until the page has written its report and read it over the debug
    port; the page's animations run on the browser's real clock."""
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
            "--window-size=390,844",
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
    if shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists():
        pytest.skip("no node or no frontend dependencies on this machine")
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-sheet-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL
            % {
                "nachricht": "../../src/teile/Nachricht.svelte",
                "sheet": "../../src/phone/TerminalSheet.svelte",
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


# --- In the browser ---------------------------------------------------------


@needs_chrome
def test_the_tap_on_a_call_raises_the_terminal_sheet_at_exactly_that_call(report):
    phone = report["phone"]
    assert phone["sheet"] is True and phone["dialog"] is True, phone
    # The page carries no catalog: the word shown is the key of the one that exists.
    assert phone["label"] == "terminal.titel" and phone["head"] == "terminal.titel", phone
    # The call that was tapped (the third of the message) stands marked and
    # unfolded in the tool inside the sheet.
    assert phone["markedKey"] == "m2#2", phone
    assert phone["markedOpen"] is True, phone
    # The column of the desktop stays shut.
    assert phone["offen"] is False, phone


@needs_chrome
def test_the_rows_of_the_open_block_are_44_px_on_the_phone_page_only(report):
    assert report["phone"]["rowHeight"] >= 44, report["phone"]
    assert report["desktop"]["rowHeight"] < 30, report["desktop"]


@needs_chrome
def test_silence_the_same_tap_on_the_desktop_page_opens_the_column(report):
    desktop = report["desktop"]
    assert desktop["sheet"] is False and desktop["dialog"] is False, desktop
    assert desktop["modul"] == "terminal" and desktop["offen"] is True, desktop


@needs_chrome
def test_the_veil_and_the_key_close_the_sheet_and_the_focus_goes_back_to_the_row(report):
    assert report["veil"]["closed"] is True and report["veil"]["open"] is False, report["veil"]
    assert report["veil"]["focusBack"] is True, report["veil"]
    assert report["key"]["before"] is True and report["key"]["closed"] is True, report["key"]


@needs_chrome
def test_the_head_pulled_down_closes_the_sheet_only_when_pulled_far(report):
    pull = report["pull"]
    assert pull["shiftShort"] == "translateY(30px)", pull
    assert pull["stillOpen"] is True, pull
    assert pull["shiftLong"] == "translateY(120px)", pull
    assert pull["closed"] is True and pull["focusBack"] is True, pull


@needs_chrome
def test_a_shell_call_without_its_run_is_still_found_by_the_tap(report):
    shell = report["shell"]
    assert shell["rows"] == 3, shell
    assert shell["sheet"] is True, shell
    # The second call of the message, under the key its line carries.
    assert shell["markedKey"] == "m3#1", shell
    assert shell["markedOpen"] is True, shell
    assert shell["jumpButton"] is False, shell


# --- The wiring ---------------------------------------------------------------


def test_the_chat_page_holds_the_sheet_and_the_sheet_holds_the_terminal_tool():
    chat = (SRC / "phone" / "ChatView.svelte").read_text(encoding="utf-8")
    assert "import TerminalSheet from './TerminalSheet.svelte'" in chat
    assert re.search(r"<TerminalSheet\s*/>", chat)
    sheet = (SRC / "phone" / "TerminalSheet.svelte").read_text(encoding="utf-8")
    assert "import Sheet from './Sheet.svelte'" in sheet
    assert "import ModulTerminal from '../teile/ModulTerminal.svelte'" in sheet
    # The head carries the existing word and nothing else.
    assert sheet.count("t('terminal.titel')") == 2


def test_the_phone_branch_of_the_tap_raises_the_sheet_and_the_desktop_branch_the_column():
    source = (SRC / "lib" / "callSelection.svelte.js").read_text(encoding="utf-8")
    opening = source[source.index("export async function openCall("):]
    opening = opening[: opening.index("\n}\n")]
    assert opening.index("terminalSheet.open = true") < opening.index("moduleShow('terminal')")
    assert re.search(r"if \(onPhonePage\(\)\) \{\s*terminalSheet\.open = true\s*return\s*\}", opening)


def test_the_row_height_rule_is_scoped_to_the_phone_page():
    source = (SRC / "teile" / "Nachricht.svelte").read_text(encoding="utf-8")
    assert re.search(r":global\(html\[data-phone\]\) \.aufruf \{ min-height: 44px; \}", source)
