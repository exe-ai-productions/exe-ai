"""The plus menu of the input bar carries the switch "Suspend instructions for
this chat", measured in headless Chrome as shipped.

* Three rows: upload files, create a picture, and — last — the switch with the
  text that stood on the settings page. The signs are 18 px in a column of 20,
  in the text colour, the rows at least 38 px high.
* The switch is `menuitemcheckbox` with `aria-checked`; a click flips it and the
  menu stays open. The sign shows the state: the bubble with its dots while the
  instructions are in force, the plain bubble in the quiet ink while they are
  suspended.
* Before any chat exists the value is held in `zustand.pendingPromptOff`; with a
  chat open the switch is the chat's own and goes to the service.

The real input bar is built and drawn; the service's answers are made up in the
page. Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests.model_windows_page import _free_port, _read_result

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

SHELL = """<script>
  import Eingabeleiste from '../../src/teile/Eingabeleiste.svelte'
</script>

<div id="bar" style="width: 720px; padding: 300px 20px 20px 20px;"><Eingabeleiste senden={() => {}} abbrechen={() => {}} /></div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import german from '../../../app/locales/de.json'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand } from '../../src/lib/zustand.svelte.js'
import '../../src/stil/global.css'

texte.katalog = german
zustand.modelle = [{ id: 'm', name: 'Model', context_tokens: 1000 }]
zustand.modellId = 'm'
window.__zustand = zustand
window.__calls = []
let chats = []
window.__setChats = (list) => { chats = list }
window.fetch = async (input, init) => {
  const url = String(input && input.url || input)
  const path = url.replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const method = (init && init.method) || 'GET'
  const json = (body) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  if (method === 'PATCH' && /^\\/chats\\/[^/]+$/.test(path)) {
    const id = path.split('/')[2]
    const patch = JSON.parse(init.body)
    window.__calls.push({ id, patch })
    chats = chats.map((c) => (c.id === id ? { ...c, ...patch } : c))
    return json(chats.find((c) => c.id === id))
  }
  if (path === '/chats') return json(chats)
  return json({})
}
try {
  mount(Shell, { target: document.getElementById('root') })
} catch (failure) {
  window.__mountError = String(failure && failure.stack || failure)
}
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

PAGE = """<!doctype html><meta charset=utf-8><title>menu</title>
<style>body { margin: 0; background: #2a2a28; }</style>
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

CASES = r"""
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
await wait(800)
if (window.__mountError) throw new Error(window.__mountError)
const probe = document.createElement('span')
document.body.appendChild(probe)
const colourOf = (variable) => { probe.style.cssText = 'color: var(' + variable + ');'; return getComputedStyle(probe).color }
const report = { tokens: { text: colourOf('--text'), still: colourOf('--text-still'), quiet: colourOf('--text-leise') } }
const rect = (node) => { const r = node.getBoundingClientRect(); return { width: r.width, height: r.height } }
const rows = () => Array.from(document.querySelectorAll('.klappmenue > button'))
const describe = () => rows().map((row) => {
  const sign = row.querySelector('.menuezeichen')
  const drawing = sign.querySelector('svg')
  return {
    role: row.getAttribute('role'), checked: row.getAttribute('aria-checked'), height: rect(row).height,
    column: rect(sign), drawing: rect(drawing), colour: getComputedStyle(sign).color,
    dots: drawing.querySelectorAll('circle').length, text: row.textContent.trim(),
    gap: parseFloat(getComputedStyle(row).columnGap),
  }
})
const plus = () => document.querySelector('.round.plus')

// 1. No chat yet: the menu, its three rows, and the switch.
plus().click(); await wait(500)
report.open = describe()
report.menuOpenAtStart = Boolean(document.querySelector('.klappmenue'))
const third = () => rows()[2]
third().click(); await wait(300)
report.afterFlip = { rows: describe(), menuStillOpen: Boolean(document.querySelector('.klappmenue')), held: window.__zustand.pendingPromptOff, calls: window.__calls.length }
third().click(); await wait(300)
report.afterFlipBack = { rows: describe(), held: window.__zustand.pendingPromptOff }
third().click(); await wait(300)

// 2. A chat open: the chat's own value counts, not the held one; a flip goes to the service.
window.__setChats([{ id: 'c', title: 'x', prompt_aus: false }])
window.__zustand.chats = [{ id: 'c', title: 'x', prompt_aus: false }]
window.__zustand.aktiverChat = 'c'
await wait(400)
report.chatOpen = { rows: describe(), held: window.__zustand.pendingPromptOff }
third().click(); await wait(600)
report.chatFlip = { rows: describe(), calls: [...window.__calls], held: window.__zustand.pendingPromptOff }
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    if sys.platform != "darwin":
        pytest.skip("the browser run of the interface is checked on macOS only")
    if shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists():
        pytest.skip("no node or no frontend dependencies on this machine")
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-plus-menu-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        built = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=300,
        )
        assert built.returncode == 0, (built.stdout + built.stderr)[-2500:]
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=900,900", f"--remote-debugging-port={port}",
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


def _near(value: float, expected: float, tolerance: float = 0.5) -> bool:
    return abs(value - expected) <= tolerance


def test_the_menu_has_three_rows_and_the_switch_stands_last_with_the_text_of_the_settings(report):
    rows = report["open"]
    assert len(rows) == 3, rows
    assert rows[2]["text"] == "Anweisungen für diesen Chat aussetzen"
    assert "hochladen" in rows[0]["text"].lower() or "dateien" in rows[0]["text"].lower()


def test_the_signs_are_18_px_in_a_column_of_20_in_the_text_colour_and_the_rows_38_high(report):
    for index, row in enumerate(report["open"][:2]):
        assert _near(row["drawing"]["width"], 18) and _near(row["drawing"]["height"], 18), row
        assert _near(row["column"]["width"], 20) and _near(row["column"]["height"], 20), row
        assert row["colour"] == report["tokens"]["text"], (index, row)
    for row in report["open"]:
        assert row["height"] >= 38 - 0.5, row
        # No label breaks over two lines: the menu is as wide as its longest row.
        assert row["height"] <= 40.5, row
        assert _near(row["gap"], 12), row


def test_the_switch_is_a_menu_item_checkbox_that_follows_its_state(report):
    start = report["open"][2]
    assert start["role"] == "menuitemcheckbox" and start["checked"] == "false", start
    assert start["dots"] == 3, "in force: the bubble with its three dots"
    assert _near(start["drawing"]["width"], 18) and start["colour"] == report["tokens"]["text"], start
    flipped = report["afterFlip"]["rows"][2]
    assert flipped["checked"] == "true" and flipped["dots"] == 0, flipped
    assert flipped["colour"] == report["tokens"]["still"], flipped
    back = report["afterFlipBack"]["rows"][2]
    assert back["checked"] == "false" and back["dots"] == 3, back


def test_a_flip_leaves_the_menu_open_and_before_a_chat_only_holds_the_value(report):
    assert report["menuOpenAtStart"] and report["afterFlip"]["menuStillOpen"]
    assert report["afterFlip"]["held"] is True and report["afterFlipBack"]["held"] is False
    assert report["afterFlip"]["calls"] == 0, "no chat, nothing is sent to the service"


def test_with_a_chat_open_a_held_value_still_counts_and_a_flip_goes_to_the_service(report):
    opened = report["chatOpen"]
    # The value still held (true after the third flip) counts as set for the chat that now exists ...
    assert opened["rows"][2]["checked"] == "true", opened
    flip = report["chatFlip"]
    # ... and a flip settles it with the service: the chat's own value now, nothing held any more.
    assert flip["calls"] == [{"id": "c", "patch": {"prompt_aus": False}}], flip
    assert flip["rows"][2]["checked"] == "false", flip
    assert report["chatFlip"]["held"] is False


def test_the_new_sign_is_the_house_drawing_word_for_word_and_the_picture_icon_has_no_status_colour():
    page = (FRONTEND / "src" / "teile" / "Hauszeichen.svelte").read_text(encoding="utf-8")
    block = page.split("zeichen === 'speech_bubble_dots'}", 1)[1].split("{:else if", 1)[0]
    assert 'd="M14 12 H50 A8 8 0 0 1 58 20 V38 A8 8 0 0 1 50 46 H32 L20 56 V46 H14 A8 8 0 0 1 6 38 V20 A8 8 0 0 1 14 12 Z" stroke-width="5"' in block
    for cx in ("18", "32", "46"):
        assert f'<circle cx="{cx}" cy="29" r="2.75" fill="currentColor" stroke="none" />' in block
    bar = (FRONTEND / "src" / "teile" / "Eingabeleiste.svelte").read_text(encoding="utf-8")
    assert "bildIconFarbe" not in bar and "bildStandHolen" not in bar and "api.bildmodelle" not in bar
    # The pulse while Image-Turbo runs is no colour and stays.
    assert 'class="menuezeichen bildicon" class:pulst={turboAn}' in bar
