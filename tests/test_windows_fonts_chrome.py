"""The faces of the interface by system, measured in a real browser.

Windows has no fixed-width face under the name `monospace` that anyone wants
(it is Courier New) and no weight 500 in Segoe UI, and its `normal` line is a
third taller than a Mac's. The tokens now name a Windows face for each, and
`body` and `.button` state their line height. `global.css` and
`codeblock.css` are built as shipped and drawn in headless Chrome at
1920 x 1080 with a code block of an answer, two buttons, a line of text and
the window of the working folder (a missing folder and the path field),
the answers of the service made up in the page. The page reports:

* the two tokens carry the Windows faces in the places the order names;
* the pre, the code and the numbers of a code block stand in the house's
  fixed face, the paths of the folder window in the house's face;
* the buttons and the line of text have a number for a line height, and on
  this Mac stand as high as they did before (29, 29, 17 px, within half a pixel);
* the source has no list of fixed-width faces beside the token (two
  exceptions that name the token first or are not the window's).

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
from tests.test_window_terminal_keys import _run as _terminal_run

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

# What the house's lines stood at on a Mac before the change, in pixels. The
# face's own "normal" is rounded differently by the browsers one meets there:
# a button was 29 high in the window's own browser pane, 29.5 in the
# desktop Chrome of an earlier measurement and 30 in this headless one; the
# stated line height sits in the middle of the three, within half a pixel of
# each but the last.
BUTTON_HEIGHT = 29.5
PRIMARY_HEIGHT = 29.5
TEXT_LINE_HEIGHT = 17
# A code block of three lines (its lines have a height of their own).
BLOCK_HEIGHT = 83.94
HEIGHT_TOLERANCE = 0.5

SHELL = """<script>
  import Arbeitsordner from '../../src/teile/Arbeitsordner.svelte'
  let { html } = $props()
</script>

<div id="proben" style="width: 640px; position: relative;">
  <button class="button" id="knopf">Ag</button>
  <button class="button primary" id="haupt">Ag</button>
  <div id="zeile">Ag</div>
  <div id="antwort">{@html html}</div>
</div>
<Arbeitsordner />
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import %(codeblock)r
import english from %(english)r
import { texte } from %(texts)r
import { zustand } from %(zustand)r
import { ordnerZustand } from %(arbeitsordner)r
import { rendern, nummernspalte } from %(markdown)r

texte.sprache = 'en'
texte.katalog = english
window.fetch = async (address) => {
  const url = String(address)
  const body = url.includes('/filesystem/folder-dialog') ? { verfuegbar: false }
    : url.includes('/ordnerstand') ? { fehlend: ['C:\\\\Weg\\\\Ordner'] } : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
zustand.chats = [{ id: 'c1', title: 'Chat', working_dirs: ['C:\\\\Weg\\\\Ordner'] }]
zustand.aktiverChat = 'c1'
ordnerZustand.fehlend = ['C:\\\\Weg\\\\Ordner']
ordnerZustand.maskeOffen = true
const html = rendern('```js\\nconst a = 1\\nconst b = 2\\n```') +
  '<div class="codeblock nummeriert"><pre>' + nummernspalte('x\\ny') + '<code>x\\ny</code></pre></div>'
mount(Shell, { target: document.getElementById('wurzel'), props: { html } })
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
for (let k = 0; k < 80 && !(document.querySelector('.fehlt .wo') && document.querySelector('.pfadfeld')); k += 1) await wait(100)
await wait(400)
const root = getComputedStyle(document.documentElement)
const family = (el) => getComputedStyle(el).fontFamily
const probe = (token) => {
  const el = document.createElement('span')
  el.style.fontFamily = `var(${token})`
  document.body.appendChild(el)
  const value = getComputedStyle(el).fontFamily
  el.remove()
  return value
}
const height = (el) => Math.round(el.getBoundingClientRect().height * 100) / 100
const block = document.querySelector('#antwort .codeblock')
const report = {
  tokenFixed: root.getPropertyValue('--schrift-fest').trim(),
  tokenText: root.getPropertyValue('--schrift').trim(),
  probeFixed: probe('--schrift-fest'),
  probeText: probe('--schrift'),
  pre: family(block.querySelector('pre')),
  code: family(block.querySelector('code')),
  numbers: family(document.querySelector('#antwort .code-nummern')),
  missingPath: family(document.querySelector('.fehlt .wo')),
  field: family(document.querySelector('.pfadfeld')),
  bodyLine: getComputedStyle(document.body).lineHeight,
  buttonLine: getComputedStyle(document.getElementById('knopf')).lineHeight,
  button: height(document.getElementById('knopf')),
  primary: height(document.getElementById('haupt')),
  text: height(document.getElementById('zeile')),
  block: height(block),
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
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
        return report


def _run_case() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-windows-fonts-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "codeblock": "../../src/stil/codeblock.css",
                "english": "../../../app/locales/en.json",
                "zustand": "../../src/lib/zustand.svelte.js",
                "texts": "../../src/lib/texte.svelte.js",
                "arbeitsordner": "../../src/lib/arbeitsordner.svelte.js",
                "markdown": "../../src/lib/markdown.js",
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
        (folder / "measure.html").write_text(PAGE % {"cases": CASES, "links": links}, encoding="utf-8")
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


def _names(listing: str) -> list[str]:
    return [part.strip() for part in re.split(r",(?![^()]*\))", listing)]


def test_the_fixed_face_names_a_windows_face_after_the_mac_ones_and_before_the_generic_name(report):
    names = [name.strip("'\"") for name in _names(report["tokenFixed"])]
    assert names.index("Menlo") < names.index("Cascadia Mono") < names.index("Consolas") < names.index("monospace"), names


def test_the_text_face_names_segoe_ui_variable_right_before_segoe_ui(report):
    names = [name.strip("'\"") for name in _names(report["tokenText"])]
    assert names[names.index("Segoe UI") - 1] == "Segoe UI Variable Text", names


def test_a_code_block_stands_in_one_fixed_face_numbers_and_code_alike(report):
    assert report["pre"] == report["code"] == report["numbers"] == report["probeFixed"], report


def test_the_paths_of_the_folder_window_stand_in_the_text_face(report):
    assert report["missingPath"] == report["field"] == report["probeText"], report


def test_the_body_and_the_button_state_a_line_height_as_a_number(report):
    assert report["bodyLine"] != "normal" and report["buttonLine"] != "normal", report
    assert report["bodyLine"].endswith("px") and report["buttonLine"].endswith("px"), report


def test_silence_on_a_mac_buttons_text_and_a_code_block_stand_as_high_as_before(report):
    assert abs(report["button"] - BUTTON_HEIGHT) <= HEIGHT_TOLERANCE, report
    assert abs(report["primary"] - PRIMARY_HEIGHT) <= HEIGHT_TOLERANCE, report
    assert abs(report["text"] - TEXT_LINE_HEIGHT) <= HEIGHT_TOLERANCE, report
    assert abs(report["block"] - BLOCK_HEIGHT) <= HEIGHT_TOLERANCE, report


def test_the_terminal_is_given_the_value_of_the_token():
    assert _terminal_run("windows")["__font"] == "TOKEN-VALUE"


def test_no_list_of_fixed_width_faces_is_left_beside_the_token():
    found = []
    for path in sorted(SRC.rglob("*")):
        if path.suffix not in {".css", ".svelte", ".js"} or path.name == "global.css":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "ui-monospace" in line:
                found.append(str(path.relative_to(SRC)))
    # Two files stay: the studio bar's fallback behind the token, and the phone's log.
    assert sorted(set(found)) == ["phone/parts/Log.svelte", "teile/StudioPromptBar.svelte"], found


def test_the_named_places_take_the_token_and_not_a_list_of_their_own():
    web_app = (SRC / "teile" / "SettingsWebApp.svelte").read_text(encoding="utf-8")
    assert "font-family: var(--schrift-fest);\n    font-size: 12.5px;" in web_app
    mask = (SRC / "teile" / "MCPMaske.svelte").read_text(encoding="utf-8")
    assert "font: 400 12.5px/1.4 var(--schrift-fest);" in mask
    watch = (SRC / "lib" / "geometriewache.js").read_text(encoding="utf-8")
    assert watch.count("var(--schrift-fest)") == 2
    folder = (SRC / "teile" / "Arbeitsordner.svelte").read_text(encoding="utf-8")
    assert folder.count("font-family: var(--schrift);") == 3
