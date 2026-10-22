"""The fixed thinking pill gives up its word when the input bar goes narrow.

A model that always or never thinks has a pill with its bulb and a word
beside it ("Never thinks"). In the narrow form of the bar the other words
step aside (the folder, the mode); this one stayed, and at the narrowest
chat column the row ran past the bar by several pixels. Now the bulb stands
alone; the word stays in the tooltip and in the tree for a screen reader.

The real input bar is built as shipped and drawn in headless Chrome, the
answers of the service made up in the page (the models and their thinking
profiles). The page reports, for a model that never thinks, one that thinks
in stages and one that always thinks, in both languages and at several
widths of the chat column, what the row looks like.

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
  import Eingabeleiste from '../../src/teile/Eingabeleiste.svelte'
</script>

<div id="leiste" style="position: relative;"><Eingabeleiste senden={() => {}} abbrechen={() => {}} /></div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import german from %(german)r
import { texte } from %(texts)r
import { zustand } from %(zustand)r
import { modellwahl } from %(models)r

const answer = (body) => new Response(JSON.stringify(body), {
  status: 200, headers: { 'Content-Type': 'application/json' },
})
window.fetch = async () => answer({})
const capabilities = { tool_calls: true, vision: true }
zustand.modelle = [
  { id: 'never', name: 'mimo-v2.5', group: 'cloud', anbieter: 'x', capabilities,
    denkprofil: { art: 'nie', stufen: [], standard: null, nativ: {} } },
  { id: 'always', name: 'mimo-v2.5', group: 'cloud', anbieter: 'x', capabilities,
    denkprofil: { art: 'immer', stufen: [], standard: null, nativ: {} } },
  { id: 'levels', name: 'mimo-v2.5', group: 'cloud', anbieter: 'x', capabilities,
    denkprofil: { art: 'stufen', stufen: ['off', 'low', 'medium', 'high'], standard: 'medium', nativ: {} } },
]
zustand.modellId = 'never'
modellwahl.geladen = true
window.__use = (model, language) => {
  texte.sprache = language
  texte.katalog = language === 'en' ? english : german
  zustand.modellId = model
}
window.__use('never', 'en')
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
const COLUMNS = %(columns)s
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
for (let k = 0; k < 80 && !document.querySelector('.bar-row .part .name'); k += 1) await wait(100)
await wait(300)
const leiste = document.getElementById('leiste')
const report = {}
for (const language of ['en', 'de']) {
  for (const model of ['never', 'always', 'levels']) {
    window.__use(model, language)
    for (const column of COLUMNS) {
      leiste.style.width = `${column}px`
      await wait(700)
      const row = document.querySelector('.bar-row')
      const rowBox = row.getBoundingClientRect()
      const left = document.querySelector('.bar-row .linkegruppe').getBoundingClientRect()
      const right = document.querySelector('.bar-row .rechts')
      const rightBox = right.getBoundingClientRect()
      const pill = document.querySelector('.bar-row .pille')
      const word = pill.querySelector('.wort')
      const wordBox = word && word.getBoundingClientRect()
      const lamps = document.querySelector('.bar-row .part .lamps')
      const microphone = document.querySelector('.bar-row .rechts button[aria-label]:not(.pille)')
      const send = document.querySelector('.bar-row .rechts .aktion')
      const inside = (el) => {
        const box = el.getBoundingClientRect()
        return box.left >= rowBox.left - 0.5 && box.right <= rowBox.right + 0.5
      }
      report[`${language}/${model}/${column}`] = {
        state: row.className.replace(/svelte-\S+/g, '').trim(),
        overlap: left.right - rightBox.left,
        pastTheBar: Math.max(0, ...[...right.children].map((child) => child.getBoundingClientRect().right - rowBox.right)),
        oneLine: new Set([...row.children].map((child) => Math.round(child.getBoundingClientRect().top))).size === 1,
        word: word ? word.textContent : null,
        wordSeen: Boolean(word) && wordBox.width > 2 && getComputedStyle(word).clipPath === 'none',
        wordWidth: wordBox ? wordBox.width : 0,
        title: pill.getAttribute('title'),
        pillWidth: pill.getBoundingClientRect().width,
        lamps: Boolean(lamps) && getComputedStyle(lamps).display !== 'none',
        nameCut: (() => { const name = document.querySelector('.bar-row .part .name'); return name.scrollWidth > name.clientWidth + 0.5 })(),
        microphoneIn: microphone ? inside(microphone) : null,
        sendIn: send ? inside(send) : null,
        dots: pill.querySelectorAll('.punkte i').length,
      }
    }
  }
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
%(links)s
<style>html { --stufenfaktor: 1; } html, body { margin: 0; } #wurzel { width: 1920px; position: relative; }</style>
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

COLUMNS = [420, 480, 540, 900, 1600]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 180.0) -> dict:
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


def _run_case() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-pill-word-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "english": "../../../app/locales/en.json",
                "german": "../../../app/locales/de.json",
                "zustand": "../../src/lib/zustand.svelte.js",
                "texts": "../../src/lib/texte.svelte.js",
                "models": "../../src/lib/modelle.svelte.js",
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
        (folder / "measure.html").write_text(
            PAGE % {"cases": CASES % {"columns": json.dumps(COLUMNS)}, "links": links}, encoding="utf-8"
        )
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1920,1080",
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
    return _run_case()


def _states(report: dict, model: str, *, narrow: bool) -> list[tuple[str, dict]]:
    return [
        (key, state)
        for key, state in report.items()
        if key.split("/")[1] == model and ("narrow" in state["state"]) == narrow
    ]


def test_nothing_of_the_row_runs_past_the_bar_or_into_the_other_group_at_any_width(report):
    for key, state in report.items():
        assert state["oneLine"], (key, state)
        assert state["overlap"] <= 0.5, (key, state)
        assert state["pastTheBar"] <= 0.5, (key, state)
        assert state["microphoneIn"] and state["sendIn"], (key, state)


def test_the_narrowest_column_goes_narrow_with_the_pill_of_a_model_that_never_thinks(report):
    for language in ("en", "de"):
        state = report[f"{language}/never/420"]
        assert "narrow" in state["state"], state


def test_in_the_narrow_form_the_fixed_pill_shows_the_bulb_alone_and_keeps_its_word_in_the_tooltip(report):
    seen = 0
    for model, expected in (("never", {"en": "Never thinks", "de": "Denkt nie"}),
                            ("always", {"en": "Always thinks", "de": "Denkt immer"})):
        for language, word in expected.items():
            for key, state in _states(report, model, narrow=True):
                if not key.startswith(f"{language}/"):
                    continue
                seen += 1
                assert not state["wordSeen"], (key, state)
                assert state["word"] == word and state["title"] == word, (key, state)
    assert seen >= 4, report


def test_with_a_fixed_pill_the_name_of_the_model_stays_whole_at_every_width(report):
    """The room the word gave up goes to the name: no cut, with the lamps
    in the row where the room allows them and without them where it does
    not."""
    for key, state in report.items():
        if key.split("/")[1] in ("never", "always"):
            assert not state["nameCut"], (key, state)


def test_a_model_with_stages_keeps_its_dots_in_every_form(report):
    for key, state in report.items():
        if key.split("/")[1] == "levels":
            assert state["dots"] == 3 and state["word"] is None, (key, state)


def test_the_tight_form_has_no_lamps_in_the_row_and_the_narrow_one_keeps_them(report):
    for key, state in report.items():
        tight = "tight" in state["state"]
        narrow = "narrow" in state["state"] and not tight
        if tight:
            assert not state["lamps"], (key, state)
        if narrow:
            assert state["lamps"], (key, state)


def test_silence_the_wide_bar_keeps_the_word_beside_the_bulb_and_the_lamps_beside_the_name(report):
    for language in ("en", "de"):
        for model, word in (("never", "Never thinks" if language == "en" else "Denkt nie"),
                            ("always", "Always thinks" if language == "en" else "Denkt immer")):
            state = report[f"{language}/{model}/1600"]
            assert state["state"] == "bar-row", state
            assert state["wordSeen"] and state["word"] == word and state["lamps"], state


def test_the_word_comes_back_with_the_room(report):
    """The form is measured afresh when the column grows again: from the
    narrow column the word is shown once the full form fits."""
    for language in ("en", "de"):
        narrow = report[f"{language}/never/420"]
        wide = report[f"{language}/never/900"]
        assert not narrow["wordSeen"] and wide["wordSeen"], (narrow, wide)
        assert wide["pillWidth"] > narrow["pillWidth"] + 20, (narrow, wide)
