"""The info marks on the pages Instructions and Memory, measured in a real browser.

`SystemPrompt.svelte` is built as shipped and drawn in headless Chrome with
the answers of the service made up in the page, once on the page Instructions
and once on the page Memory. The page reports, for Instructions: one mark,
beside "Greeting & preferred name" (the switch to suspend the instructions
moved into the plus menu of the input bar), none beside the name field; for Memory: three marks, beside "Exe AI
Memory", "Send to cloud models and custom servers" and "Remove image
metadata". Each mark is 14 by 14 px, 6 px after the name and centred on its
line, and shows its approved sentence when pressed, first in English, then
(the catalogue switched) in German, under the name. And what stays: a press
on a mark switches no switch and calls no route, and no row carries a line
under its name.

The build of the harness links the built stylesheet, so every size probe
reads the real tokens.

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
LOCALES = ROOT / "app" / "locales"

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

# The approved sentences (English, German), in the order of the pages.
SENTENCES = {
    'editor.info_anrede_schalter': (
        'Displays a greeting and includes your preferred name in requests to the model. Note that with cloud models, your name is sent to the provider.',
        'Zeigt eine Begrüßung an und übermittelt dem Modell bei jeder Anfrage den Namen. Bei Cloud-Modellen wird der Name an den jeweiligen Anbieter übertragen.',
    ),
    'gedaechtnis.info_an_lokal': (
        'Sends your memory profile (rules and facts Exe AI knows about you) with every request to local models. Data remains on this computer.',
        'Übermittelt das Gedächtnis (Regeln und Fakten, die Exe AI über den Nutzer gespeichert hat) bei jeder Anfrage an lokale Modelle. Die Daten verbleiben auf diesem Computer.',
    ),
    'gedaechtnis.info_an_cloud': (
        'Also sends your memory with requests to cloud models and custom servers, meaning data leaves this computer.',
        'Sendet das Gedächtnis ebenfalls bei Anfragen an Cloud-Modelle und eigene Server mit. In diesem Fall verlässt es den Computer.',
    ),
    'bildschutz.info_titel': (
        'Removes prompts, settings, and EXIF data from every uploaded or generated image prior to saving.',
        'Entfernt Prompts, Einstellungen und EXIF-Daten aus allen hochgeladenen oder generierten Bildern, bevor diese gespeichert werden.',
    ),
}

INSTRUCTIONS_NAMES = ["Greeting & preferred name"]
MEMORY_NAMES = ["Exe AI Memory", "Send to cloud models and custom servers", "Remove image metadata"]

SHELL = """<script>
  import SystemPrompt from %(page)r
</script>

<div id="frame" style="width: 1400px; height: 900px; position: relative;">
  <SystemPrompt offen={true} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import german from %(german)r
import { texte } from %(texts)r
import { zustand } from %(zustand)r

texte.sprache = 'en'
texte.katalog = english
window.calls = []
window.fetch = async (address, options = {}) => {
  const method = (options.method || 'GET').toUpperCase()
  if (method !== 'GET') window.calls.push(method + ' ' + String(address))
  return new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
window.texte = texte
window.german = german
zustand.promptOffen = true
zustand.promptStart = %(start)r
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
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js' },
  },
})
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const root = document.getElementById('frame')
const text = (node) => (node?.textContent || '').replace(/\s+/g, ' ').trim()
const round = (value) => Math.round(value * 10) / 10
const marksOf = () => Array.from(root.querySelectorAll('.mark'))
for (let k = 0; k < 80 && marksOf().length === 0; k += 1) await wait(100)
await wait(500)

const holderOf = (mark) => mark.closest('.beschriftung')
const switchStates = () => Array.from(root.querySelectorAll('[role=switch]')).map((s) => s.getAttribute('aria-checked'))
const label = (holder) => Array.from(holder.childNodes).filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim()
const measure = (mark) => {
  const holder = holderOf(mark)
  const nameNode = Array.from(holder.childNodes).find((n) => n.nodeType === 3)
  const range = document.createRange()
  range.selectNodeContents(nameNode)
  const name = range.getBoundingClientRect()
  const box = mark.getBoundingClientRect()
  return {
    label: label(holder),
    width: round(box.width), height: round(box.height),
    gap: round(box.left - name.right),
    off: round(Math.abs(box.top + box.height / 2 - (name.top + name.height / 2))),
  }
}
const sentences = async () => {
  const found = []
  for (const mark of marksOf()) {
    mark.click()
    await wait(60)
    const holder = holderOf(mark)
    const bubble = holder.querySelector('.bubble')
    found.push({
      label: label(holder), sentence: text(bubble),
      below: bubble ? bubble.getBoundingClientRect().top >= mark.getBoundingClientRect().bottom - 1 : false,
    })
  }
  document.body.click()
  await wait(60)
  return found
}

const report = {}
report.closedBubbles = root.querySelectorAll('.bubble').length
report.marks = marksOf().map(measure)
report.fieldRowMarks = Array.from(root.querySelectorAll('.anredefeld')).reduce((n, f) => n + f.closest('.schalterzeile').querySelectorAll('.mark').length, 0)
report.rowLines = Array.from(root.querySelectorAll('.schalterzeile .beschriftung')).map((h) => text(h) === label(h))
const before = switchStates()
window.calls.length = 0
report.english = await sentences()
texte.sprache = 'de'
texte.katalog = german
await wait(100)
report.german = await sentences()
report.switchesStay = JSON.stringify(before) === JSON.stringify(switchStates())
report.calls = window.calls
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
%(links)s
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1280px; position: relative; }</style>
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
        return report


def _run_case(start: str) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-info-marks-instructions-memory-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"page": "../../src/teile/SystemPrompt.svelte"},
            encoding="utf-8",
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "english": "../../../app/locales/en.json",
                "german": "../../../app/locales/de.json",
                "zustand": "../../src/lib/zustand.svelte.js",
                "start": start,
                "texts": "../../src/lib/texte.svelte.js",
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
        assert links, "the build emitted no stylesheet: the colour probes would measure nothing"
        (folder / "measure.html").write_text(
            PAGE % {"cases": CASES, "links": links}, encoding="utf-8"
        )
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1280,900",
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
def instructions() -> dict:
    return _run_case("system")


@pytest.fixture(scope="module")
def memory() -> dict:
    return _run_case("memory")


def _catalogue(language: str) -> dict:
    return json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))


def _check_marks(report: dict, names: list[str], keys: list[str]):
    assert [mark["label"] for mark in report["marks"]] == names, report["marks"]
    for mark in report["marks"]:
        assert mark["width"] == 14 and mark["height"] == 14, mark
        assert abs(mark["gap"] - 6) <= 0.5, mark
        assert mark["off"] <= 1, mark
    for language, index in (("english", 0), ("german", 1)):
        rows = report[language]
        assert [row["sentence"] for row in rows] == [SENTENCES[key][index] for key in keys], (language, rows)
        assert all(row["below"] for row in rows), rows


def test_the_instructions_page_has_one_mark_14_px_wide_6_px_after_the_name_with_its_sentence(instructions):
    _check_marks(instructions, INSTRUCTIONS_NAMES, ["editor.info_anrede_schalter"])


def test_the_name_field_row_of_the_instructions_page_has_no_mark(instructions):
    assert instructions["fieldRowMarks"] == 0, instructions


def test_the_memory_page_has_three_marks_14_px_wide_6_px_after_the_name_with_their_sentences(memory):
    _check_marks(
        memory, MEMORY_NAMES,
        ["gedaechtnis.info_an_lokal", "gedaechtnis.info_an_cloud", "bildschutz.info_titel"],
    )


def test_every_key_is_in_both_catalogues_with_the_approved_sentence():
    english, german = _catalogue("en"), _catalogue("de")
    for key, (en, de) in SENTENCES.items():
        group, name = key.split(".")
        assert english[group][name] == en, key
        assert german[group][name] == de, key


def test_silence_a_press_switches_nothing_calls_nothing_and_no_row_gets_a_second_line(instructions, memory):
    for report in (instructions, memory):
        assert report["switchesStay"] is True, report
        assert report["calls"] == [], report["calls"]
        assert report["closedBubbles"] == 0, report
        assert all(report["rowLines"]), report["rowLines"]
