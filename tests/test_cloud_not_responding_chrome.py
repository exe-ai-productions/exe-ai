"""A provider that does not answer: a quiet dot and the words, measured in a
real browser.

`ModelleCloud.svelte` is built as shipped, with a sidebar column of its own,
and drawn in headless Chrome with the answers of the service made up in the
page: OpenAI (key set, answers, one model), a provider with its key set that
does not answer, an own server without a key that does not answer, and one
whose key is missing. The page reports, for the two that do not answer and are
not waiting for a key: in the left column a dot of 7 px in the quiet ink and
"Not responding" in 11 px on the quiet text; in the table's state column and
in the head of its card the same dot with the words in 13 px; no model row and
no tick under them. And what stays: an answering provider says "connected"
and its count, the one with the key missing says so in red, and the old words
"not connected" stay in the catalogue of texts for the pages that read them.

The build of the harness links the built stylesheet, so every colour and size
probe reads the real tokens.

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

SHELL = """<script>
  import ModelleCloud from %(cloud)r
  import { zustand } from %(zustand)r
</script>

<div style="display: flex; width: 1280px; height: 860px;">
  <nav id="leiste" style="width: 320px; flex: none; overflow: auto;">
    {#if zustand.menuSections}{@render zustand.menuSections.snippet?.()}{/if}
  </nav>
  <main id="seite" style="flex: 1; min-width: 0; overflow: auto; position: relative;">
    <ModelleCloud offen={true} />
  </main>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import { zustand } from %(zustand)r
import { texte } from %(texts)r

texte.sprache = 'en'
texte.katalog = english
const base = { group: 'cloud', capabilities: {}, timeout_enabled: true }
const all = [
  { ...base, id: 'openai/gpt-a', modell: 'gpt-a', name: 'gpt-a', anbieter: 'openai', anbieter_name: 'OpenAI', erreichbar: true,
    schluessel_env: 'OPENAI_API_KEY', schluessel_gesetzt: true, angeheftet: true },
  { ...base, id: 'limbo', name: 'limbo', anbieter: 'limbo', anbieter_name: 'Limbo', erreichbar: false,
    schluessel_env: 'LIMBO_API_KEY', schluessel_gesetzt: true },
  { ...base, id: 'omlx', name: 'omlx', anbieter: 'omlx', anbieter_name: 'omlx', erreichbar: false },
  { ...base, id: 'nokey', name: 'nokey', anbieter: 'nokey', anbieter_name: 'Nokey', erreichbar: false,
    schluessel_env: 'NOKEY_API_KEY', schluessel_gesetzt: false },
]
zustand.modelle = all.filter((m) => m.erreichbar)
window.fetch = async (address) => {
  const full = String(address)
  const path = full.replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path === '/models' ? all : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
window.zustand = zustand
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
const page = () => document.getElementById('seite')
const text = (node) => (node?.textContent || '').replace(/\s+/g, ' ').trim()
const look = (node) => getComputedStyle(node)
const px = (value) => Math.round(parseFloat(value) * 10) / 10
const probe = (token, property = 'color') => {
  const node = document.createElement('i')
  node.style[property] = `var(${token})`
  document.body.appendChild(node)
  const value = getComputedStyle(node)[property]
  node.remove()
  return value
}
const column = () => page().querySelector('nav.providers')
const rowOf = (name) => Array.from(column().querySelectorAll('.menuezeile')).find((row) => text(row.querySelector('.titel')) === name)
for (let k = 0; k < 60 && !(column() && column().querySelectorAll('.menuezeile').length === 4
  && page().querySelectorAll('[role=row].line').length === 4); k += 1) await wait(100)
if (!column() || column().querySelectorAll('.menuezeile').length !== 4) throw new Error('the page did not render the providers')
await wait(600)
const click = async (node) => { node.click(); await wait(400) }
const report = {}

const dot = (node) => {
  const disc = node?.querySelector('svg.lp circle.scheibe')
  return disc ? {
    diameter: Math.round(parseFloat(disc.getAttribute('r')) * 2),
    ink: look(disc).fill === probe('--text-still'),
    quiet: node.querySelector('svg.lp').getAttribute('data-farbe'),
  } : null
}
report.column = {}
for (const name of ['Limbo', 'omlx', 'Nokey', 'OpenAI']) {
  const row = rowOf(name)
  const word = row.querySelector('.count')
  const models = []
  for (let node = row.nextElementSibling; node && !node.classList.contains('menuezeile'); node = node.nextElementSibling) {
    if (node.classList.contains('listenzeile') && !node.classList.contains('dazu')) models.push(text(node))
  }
  report.column[name] = {
    word: text(word), size: word ? px(look(word).fontSize) : null,
    ink: word ? look(word).color === probe('--text-leise') : null,
    red: word ? look(word).color === probe('--rot-text') : null,
    gap: word ? look(word).columnGap : null,
    dot: dot(word), models,
  }
}
const lines = Array.from(page().querySelectorAll('[role=row].line'))
const lineOf = (name) => lines.find((row) => text(row.querySelector('.name .text')) === name)
report.table = {}
for (const name of ['Limbo', 'omlx', 'Nokey', 'OpenAI']) {
  const cell = lineOf(name).querySelector('.state')
  report.table[name] = {
    word: text(cell), size: px(look(cell).fontSize), gap: look(cell).columnGap,
    ink: look(cell).color === probe('--text-leise'),
    green: look(cell).color === probe('--gruen-text'),
    dot: dot(cell),
    models: text(lineOf(name).querySelectorAll('[role=cell]')[2]),
    key: text(lineOf(name).querySelector('.key')),
    keyRed: look(lineOf(name).querySelector('.key')).color === probe('--rot-text'),
  }
}
report.head = {}
for (const name of ['Limbo', 'omlx', 'Nokey', 'OpenAI']) {
  await click(rowOf(name))
  const word = page().querySelector('.provider-head .state-word')
  report.head[name] = {
    word: text(word), size: px(look(word).fontSize), weight: look(word).fontWeight, gap: look(word).columnGap,
    ink: look(word).color === probe('--text-leise'),
    green: look(word).color === probe('--gruen-text'),
    dot: dot(word),
    tick: page().querySelectorAll('.model-row').length,
  }
}
document.title = 'open'
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


def _run_case() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-cloud-silent-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {
                "cloud": "../../src/teile/ModelleCloud.svelte",
                "zustand": "../../src/lib/zustand.svelte.js",
            },
            encoding="utf-8",
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "english": "../../../app/locales/en.json",
                "zustand": "../../src/lib/zustand.svelte.js",
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
def measured() -> dict:
    return _run_case()


def _text(language: str, key: str) -> str:
    return json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))["status"][key]


def test_the_new_words_stand_in_both_languages():
    assert _text("en", "not_responding") == "Not responding"
    assert _text("de", "not_responding") == "antwortet nicht"


def test_in_the_column_a_provider_that_does_not_answer_wears_a_quiet_dot_and_the_words(measured):
    for name in ("Limbo", "omlx"):
        row = measured["column"][name]
        assert row["word"] == "Not responding", row
        assert row["size"] == 11 and row["ink"] and row["gap"] == "6px", row
        assert row["dot"] == {"diameter": 7, "ink": True, "quiet": "still"}, row
        assert row["models"] == [], row


def test_in_the_table_the_state_column_has_the_same_dot_and_the_words_in_13_px(measured):
    for name in ("Limbo", "omlx"):
        cell = measured["table"][name]
        assert cell["word"] == "Not responding" and cell["size"] == 13 and cell["ink"], cell
        assert cell["gap"] == "8px", cell
        assert cell["dot"] == {"diameter": 7, "ink": True, "quiet": "still"}, cell
        assert cell["models"] == "-", cell


def test_in_the_head_of_the_card_the_state_is_the_same_dot_and_the_words_in_13_px(measured):
    for name in ("Limbo", "omlx"):
        head = measured["head"][name]
        assert head["word"] == "Not responding" and head["size"] == 13 and head["weight"] == "400", head
        assert head["gap"] == "8px", head
        assert head["ink"] and head["dot"] == {"diameter": 7, "ink": True, "quiet": "still"}, head
        assert head["tick"] == 0, head


def test_silence_an_answering_provider_and_one_with_its_key_missing_say_what_they_said(measured):
    openai = measured["column"]["OpenAI"]
    assert openai["word"] == "1/1" and openai["dot"] is None, openai
    assert measured["table"]["OpenAI"]["word"] == "connected" and measured["table"]["OpenAI"]["green"]
    assert measured["head"]["OpenAI"]["word"] == "connected" and measured["head"]["OpenAI"]["green"]
    nokey = measured["column"]["Nokey"]
    assert nokey["word"] == "Key missing" and nokey["red"] and nokey["dot"] is None, nokey
    assert measured["table"]["Nokey"]["key"] == "Key missing" and measured["table"]["Nokey"]["keyRed"]
    # It is not waiting for an answer but for its key: the old word stays.
    assert measured["table"]["Nokey"]["word"] == "not connected" and measured["table"]["Nokey"]["dot"] is None
    assert measured["head"]["Nokey"]["word"] == "not connected" and measured["head"]["Nokey"]["dot"] is None


def test_silence_the_old_words_stay_for_the_pages_that_read_them():
    assert _text("en", "nicht_erreichbar") == "not connected"
    assert _text("de", "nicht_erreichbar") == "nicht verbunden"
    sources = {
        name: (FRONTEND / "src" / name).read_text(encoding="utf-8")
        for name in ("teile/ModelleLokal.svelte", "phone/cloud/ProviderView.svelte")
    }
    for name, source in sources.items():
        assert "status.nicht_erreichbar" in source, name
