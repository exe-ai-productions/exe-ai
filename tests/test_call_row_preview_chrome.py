"""The row of a call in the chat names the file, not its content, in a real browser.

`Nachricht.svelte` is built as shipped and drawn in headless Chrome with an
answer whose block holds calls whose models wrote the arguments in the wrong
order (`content` before `path`, the new text before the path, `limit` before
`path`, `depth` before `path`). The block is opened and every row is read:

* each file call shows its path, not the start of its text or a number, and
  the label read out for it names the file;
* the preview of each row is the very text the terminal's own line for the
  same call carries (`historie` of `lib/werkzeughistorie.js`, the list the
  Terminal tab draws);
* a shell command shows its command, a background run its number, a call with
  no arguments no preview, a call whose only argument is an object the start
  of that object as before;
* a click on a row still opens that call in the terminal.

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
  import Nachricht from '../../src/teile/Nachricht.svelte'
  import { scene } from './scene.svelte.js'
</script>

<div style="width: 640px; margin: 0 auto;">
  <Nachricht
    nachricht={scene.nachricht}
    laeuft={false}
    istLetzte={true}
    marke={null}
    neuErzeugen={() => {}}
    neuSenden={() => {}}
  />
</div>
"""

SCENE_JS = """export const scene = $state({ nachricht: { id: 'm1', rolle: 'assistant', content: '' } })
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import { callSelection } from '../../src/lib/callSelection.svelte.js'
import { historie } from '../../src/lib/werkzeughistorie.js'
import '../../src/stil/global.css'

window.scene = scene
window.callSelection = callSelection
window.historie = historie
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
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const scene = window.scene
const calls = [
  { name: 'write_file', argumente: { content: 'A good question', path: 'notes/paragraph1.txt' } },
  { name: 'edit_file', argumente: { new_text: 'the new text', old_text: 'the old text', path: 'src/module.py' } },
  { name: 'read_file', argumente: { limit: 200, path: 'docs/README.md' } },
  { name: 'list_dir', argumente: { depth: 2, path: '/tmp/work' } },
  { name: 'run_command', argumente: { command: 'ls -la' } },
  { name: 'run_command', argumente: { command: 'sleep 30' }, lauf_nummer: 3 },
  { name: 'ping', argumente: {} },
  { name: 'configure', argumente: { options: { depth: 1 } } },
].map((call, k) => ({
  aufruf_id: 'c' + k, ergebnis: 'ok', fehlgeschlagen: false, ...call,
}))
const nachricht = {
  id: 'm1', rolle: 'assistant', content: 'Done.',
  abschnitte: [
    { art: 'content', text: 'I go through the files.' },
    ...calls.map((c) => ({ art: 'werkzeug', aufruf_id: c.aufruf_id })),
    { art: 'content', text: 'Done.' },
  ],
  werkzeuge: calls, stats: {},
}
scene.nachricht = nachricht
for (let k = 0; k < 100 && !document.querySelector('.block-head'); k += 1) await wait(100)
await wait(300)
document.querySelector('.block-head').click()
for (let k = 0; k < 50 && document.querySelectorAll('.block-window .aufruf').length < calls.length; k += 1) await wait(100)
await wait(300)

const rows = Array.from(document.querySelectorAll('.block-window .aufruf'))
const report = {
  rows: rows.map((row) => ({
    name: row.querySelector('.wz-name')?.textContent ?? '',
    preview: row.querySelector('.wz-vorschau')?.textContent ?? null,
    number: row.querySelector('.wz-nummer')?.textContent ?? null,
    label: row.getAttribute('aria-label'),
  })),
  terminal: window.historie([nachricht], []).filter((e) => e.art === 'aufruf').map((e) => ({ name: e.name, kurz: e.kurz })),
}
rows[0].click()
await wait(300)
report.click = { key: window.callSelection.key, counter: window.callSelection.counter }
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>call rows</title>
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


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-callrows-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1920,1080", f"--remote-debugging-port={port}",
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


def test_every_file_call_shows_its_path_not_the_start_of_its_text(report):
    rows = report["rows"]
    assert [r["name"] for r in rows[:4]] == ["write_file", "edit_file", "read_file", "list_dir"]
    assert [r["preview"] for r in rows[:4]] == [
        "notes/paragraph1.txt", "src/module.py", "docs/README.md", "/tmp/work",
    ]


def test_the_label_read_out_names_the_file(report):
    labels = [r["label"] for r in report["rows"][:4]]
    assert labels[0].startswith("write_file, notes/paragraph1.txt")
    assert "A good question" not in labels[0]
    assert labels[2].startswith("read_file, docs/README.md")


def test_the_row_shows_what_the_terminal_line_of_the_same_call_carries(report):
    terminal = report["terminal"]
    shown = {(r["name"], r["preview"]) for r in report["rows"][:4]}
    for entry in terminal:
        if entry["name"] in ("write_file", "edit_file", "read_file", "list_dir"):
            assert (entry["name"], entry["kurz"]) in shown, (entry, shown)


def test_silence_a_command_a_run_number_no_arguments_and_an_object(report):
    rows = report["rows"]
    assert rows[4]["name"] == "run_command" and rows[4]["preview"] == "ls -la"
    assert rows[5]["number"] == "#3" and rows[5]["preview"] == "sleep 30"
    assert rows[6]["name"] == "ping" and rows[6]["preview"] is None
    assert rows[7]["name"] == "configure" and rows[7]["preview"] == '{"depth":1}'


def test_silence_a_click_on_a_row_still_opens_the_call_in_the_terminal(report):
    assert report["click"]["key"] == "m1#0"
    assert report["click"]["counter"] >= 1
