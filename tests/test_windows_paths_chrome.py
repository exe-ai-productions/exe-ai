"""Windows paths in the interface, measured in a real browser.

The folder chip with its list, the working-folder window, the preview tab
and the permission card are built as shipped and drawn in headless Chrome
with the answers of the service made up in the page, and Windows paths
(`C:\\Users\\exe\\Test Ordner`, `\\\\server\\share\\Projekt`, `C:\\`) in place
of Mac ones. The page reports:

* the chip and its list name the folder, not the path: `Test Ordner`,
  `Projekt`, `C:/`; the tooltip shows the whole path with slashes;
* "show in the file manager" still sends the path the way Windows wrote it;
* a path the service refuses leaves the window open, the text in its field
  and the reason in the window; a path in quotes is sent on as it was typed
  (the service takes the quotes off) and closes the window;
* the preview tab and its address line show a path with slashes;
* the permission card of a file tool shows the file's path — not the first
  text of the call, which for a write is the file's body — with slashes and
  without the dollar sign; a shell command keeps its dollar sign, its
  colours and its backslashes; the unfolded arguments stay as recorded.

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
  import FolderChip from '../../src/teile/FolderChip.svelte'
  import Arbeitsordner from '../../src/teile/Arbeitsordner.svelte'
  import ModulVorschau from '../../src/teile/ModulVorschau.svelte'
  import QuestionBox from '../../src/teile/QuestionBox.svelte'
  let { cards } = $props()
</script>

<div id="chipbox"><FolderChip open={true} /></div>
<Arbeitsordner />
<div id="vorschau" style="width: 640px; height: 420px; position: relative;"><ModulVorschau /></div>
{#each cards as card (card.id)}
  <div class="karte" id={card.id} style="width: 640px; position: relative;">
    <QuestionBox kind="tool" question={card.question} answerTool={() => {}} answerAsk={() => {}} onLater={() => {}} />
  </div>
{/each}
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import { texte } from %(texts)r
import { zustand } from %(zustand)r
import { ordnerZustand } from %(arbeitsordner)r
import { tabOeffnen } from %(tabs)r

texte.sprache = 'en'
texte.katalog = english
window.ordnerZustand = ordnerZustand
window.calls = []
window.reject = 'D:\\\\Rejected'
window.fetch = async (address, options = {}) => {
  const method = (options.method || 'GET').toUpperCase()
  const url = String(address)
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  if (url.includes('/filesystem/folder-dialog')) return json({ verfuegbar: false })
  if (url.includes('/ordnerstand')) return json({ fehlend: [] })
  if (url.includes('/ordnerwissen/')) return json({})
  if (method === 'PATCH' && url.includes('/chats/c1')) {
    const body = JSON.parse(options.body)
    window.calls.push({ method, url, body })
    if ((body.working_dirs || []).includes(window.reject)) {
      return json({ detail: 'That folder does not exist.' }, 400)
    }
    return json({ id: 'c1', working_dirs: body.working_dirs, project_id: null })
  }
  if (method !== 'GET') {
    window.calls.push({ method, url, body: options.body ? JSON.parse(options.body) : null })
    return json({})
  }
  return json({})
}

const folders = ['C:\\\\Users\\\\exe\\\\Test Ordner', '\\\\\\\\server\\\\share\\\\Projekt', 'C:\\\\']
zustand.chats = [{ id: 'c1', title: 'Chat', working_dirs: folders }]
zustand.aktiverChat = 'c1'
tabOeffnen('c1', {
  name: 'notizen\\\\absatz1.txt', art: 'json', inhalt: '{}', pfad: 'C:\\\\x\\\\notizen\\\\absatz1.txt',
})
const cards = [
  {
    id: 'datei',
    question: {
      name: 'write_file', chatId: 'c1', aufrufId: 'a1',
      argumente: { content: 'Eine gute Frage', path: 'C:\\\\x\\\\notizen\\\\absatz1.txt' },
      grund: 'Outside the shared folders',
      grundWert: 'C:\\\\x\\\\notizen',
    },
  },
  {
    id: 'befehl',
    question: {
      name: 'run_command', chatId: 'c1', aufrufId: 'a2',
      argumente: { command: 'dir C:\\\\x\\\\notizen' },
      grund: 'Outside the shared folders',
      grundWert: 'C:\\\\x\\\\notizen',
    },
  },
]
mount(Shell, { target: document.getElementById('wurzel'), props: { cards } })
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
const text = (node) => (node?.textContent || '').replace(/\s+/g, ' ').trim()
for (let k = 0; k < 80 && !document.querySelector('.chip'); k += 1) await wait(100)
await wait(500)

const report = {}

// --- The chip and its list ------------------------------------------------
const chip = document.querySelector('.chip')
report.chipName = text(chip.querySelector('.name'))
report.chipCount = text(chip.querySelector('.count'))
report.chipTitle = chip.getAttribute('title')
const rows = Array.from(document.querySelectorAll('.menu .row')).filter((r) => r.title)
report.rowNames = rows.map((r) => text(r.querySelector('.label')))
report.rowTitles = rows.map((r) => r.title)
window.calls.length = 0
rows[0].querySelector('.mini')?.click()
await wait(150)
report.showCall = window.calls.map((c) => c.body)

// --- The working-folder window --------------------------------------------
const typeInto = async (value) => {
  const field = document.querySelector('.pfadfeld')
  if (!field) return
  field.value = value
  field.dispatchEvent(new Event('input', { bubbles: true }))
  await wait(60)
}
window.ordnerZustand.maskeOffen = true
for (let k = 0; k < 30 && !document.querySelector('.pfadfeld'); k += 1) await wait(100)
await wait(300)
window.calls.length = 0
await typeInto(window.reject)
Array.from(document.querySelectorAll('.knopfreihe .button.primary')).at(-1)?.click()
await wait(500)
report.refused = {
  open: Boolean(document.querySelector('.pfadfeld')),
  field: document.querySelector('.pfadfeld')?.value ?? null,
  reason: text(document.querySelector('.zurueckmeldung.fehler')),
  stateOpen: window.ordnerZustand.maskeOffen,
  sent: window.calls.map((c) => c.body.working_dirs.at(-1)),
}
const quoted = '"C:\\Users\\exe\\Neu Ordner"'
window.calls.length = 0
await typeInto(quoted)
Array.from(document.querySelectorAll('.knopfreihe .button.primary')).at(-1)?.click()
await wait(700)
report.accepted = {
  open: Boolean(document.querySelector('.pfadfeld')),
  stateOpen: window.ordnerZustand.maskeOffen,
  reason: window.ordnerZustand.shareError,
  sent: window.calls.map((c) => c.body.working_dirs.at(-1)),
  quoted,
}

// --- The preview tab ----------------------------------------------------------
const preview = document.getElementById('vorschau')
const address = preview.querySelector('.adresse-name')
report.preview = {
  tab: text(preview.querySelector('.reiter-name')),
  address: text(address),
  title: address?.getAttribute('title'),
}

// --- The permission cards -----------------------------------------------------
const cardOf = (id) => {
  const root = document.getElementById(id)
  const command = root.querySelector('.command')
  return {
    line: text(command),
    dollar: Boolean(command?.querySelector('.quiet')),
    coloured: Boolean(command?.querySelector('span:not(.quiet):not(.unfold)')),
    reason: text(root.querySelector('.reason')),
    marked: Array.from(command?.querySelectorAll('mark.outside') ?? []).map(text),
  }
}
report.fileCard = cardOf('datei')
report.shellCard = cardOf('befehl')
document.getElementById('datei').querySelector('button.command')?.click()
await wait(200)
report.unfolded = Array.from(document.getElementById('datei').querySelectorAll('.arguments dd')).map(text)
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
    folder = FRONTEND / "node_modules" / f".harness-windows-paths-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "english": "../../../app/locales/en.json",
                "zustand": "../../src/lib/zustand.svelte.js",
                "texts": "../../src/lib/texte.svelte.js",
                "arbeitsordner": "../../src/lib/arbeitsordner.svelte.js",
                "tabs": "../../src/lib/vorschautabs.svelte.js",
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


def test_the_chip_and_its_list_name_the_folder_and_the_tooltip_shows_slashes(report):
    assert report["chipName"] == "Test Ordner", report
    assert report["chipCount"] == "+2", report
    assert report["chipTitle"] == "C:/Users/exe/Test Ordner\n//server/share/Projekt\nC:/", report
    assert report["rowNames"] == ["Test Ordner", "Projekt", "C:/"], report
    assert report["rowTitles"] == [
        "C:/Users/exe/Test Ordner", "//server/share/Projekt", "C:/",
    ], report


def test_showing_a_folder_in_the_file_manager_sends_the_path_as_windows_wrote_it(report):
    assert report["showCall"] == [{"chat_id": "c1", "pfad": "C:\\Users\\exe\\Test Ordner"}], report


def test_a_refused_path_keeps_the_window_open_with_its_text_and_says_why(report):
    refused = report["refused"]
    assert refused["open"] is True and refused["stateOpen"] is True, refused
    assert refused["field"] == "D:\\Rejected", refused
    assert refused["reason"] == "That folder does not exist.", refused
    assert refused["sent"] == ["D:\\Rejected"], refused


def test_a_quoted_path_goes_to_the_service_as_typed_and_an_accepted_one_closes_the_window(report):
    accepted = report["accepted"]
    assert accepted["sent"] == [accepted["quoted"]], accepted
    assert accepted["stateOpen"] is False, accepted
    assert accepted["reason"] == "", accepted


def test_the_preview_tab_and_its_address_line_show_slashes(report):
    assert report["preview"] == {
        "tab": "notizen/absatz1.txt",
        "address": "C:/x/notizen/absatz1.txt",
        "title": "C:/x/notizen/absatz1.txt",
    }, report


def test_the_card_of_a_file_tool_shows_the_path_without_a_dollar_sign(report):
    card = report["fileCard"]
    assert card["line"].startswith("C:/x/notizen/absatz1.txt"), card
    assert "Eine gute Frage" not in card["line"], card
    assert card["dollar"] is False and card["coloured"] is False, card
    # The file's line does not carry the folder as it was written (slashes
    # here, backslashes in the reason), so it follows the sentence.
    assert card["reason"] == "Outside the shared folders: C:/x/notizen", card
    assert card["marked"] == [], card
    assert report["unfolded"] == ["Eine gute Frage", "C:\\x\\notizen\\absatz1.txt"], report


def test_silence_a_shell_command_keeps_its_dollar_sign_colours_and_backslashes(report):
    card = report["shellCard"]
    assert card["line"] == "$ dir C:\\x\\notizen", card
    assert card["dollar"] is True and card["coloured"] is True, card
    # The marker lies over the path as it stands in the command, backslashes
    # and all, and the line under it reads the same; the reason names no path.
    assert card["marked"] == ["C:\\x\\notizen"], card
    assert card["reason"] == "Outside the shared folders", card
