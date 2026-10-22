"""What a document in the preview frame may run, measured in a real browser.

A document the model wrote is drawn in a frame of its own (a `srcdoc`,
`sandbox="allow-scripts"`, no shared origin). It carries a rule of its own
(`lib/vorschauschutz.js`) and inherits the rule of the page that holds the
frame (`app/inhaltssicherheit.py`); both are enforced and the stricter one
wins. A page that cannot run is not a preview of that page, so the document
may run `eval`, a WebAssembly module and a worker made from a `blob:` — while
the way out stays shut.

Both layers are in the measurement: the wrapper of the frame is built into a
page that is served with the very header the service puts on its pages, and
the document reports from inside the frame.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import functools
import http.server
import json
import shutil
import subprocess
import threading
from uuid import uuid4

import pytest

from app import appfenster, inhaltssicherheit, prozessstopp
from tests import test_pdf_pages_chrome as harness

FRONTEND = harness.FRONTEND

pytestmark = harness.pytestmark

# Every document reports to the page around it by name and in one message.
POST = (
    "const post = (name, value) => parent.postMessage("
    "JSON.stringify({ name, value: String(value) }), '*');"
)

DOCUMENTS = {
    "eval": "<script>" + POST + "try { post('eval', eval('1 + 2')) } catch (e) { post('eval', e.name) }</script>",
    "function": (
        "<script>" + POST + "try { post('function', new Function('return 5')()) } "
        "catch (e) { post('function', e.name) }</script>"
    ),
    # The smallest valid module: the magic number and the version.
    "wasm": (
        "<script>" + POST + "try { WebAssembly.instantiate(new Uint8Array([0,97,115,109,1,0,0,0]))"
        ".then(() => post('wasm', 'ok'), (e) => post('wasm', e.name)) } catch (e) { post('wasm', e.name) }</script>"
    ),
    "worker": (
        "<script>" + POST + "try { const url = URL.createObjectURL(new Blob(['postMessage(7)']));"
        "const worker = new Worker(url); worker.onmessage = (e) => post('worker', e.data);"
        "worker.onerror = () => post('worker', 'error') } catch (e) { post('worker', e.name) }</script>"
    ),
    # The way out, from the frame and from inside a worker: both are refused.
    "fetch": (
        "<script>" + POST + "let violated = '';"
        "document.addEventListener('securitypolicyviolation', (e) => { violated = e.violatedDirective });"
        "fetch('http://127.0.0.1:%(foreign)s/x').then(() => post('fetch', 'reached'),"
        " () => setTimeout(() => post('fetch', 'blocked ' + violated), 200))</script>"
    ),
    "worker_fetch": (
        "<script>" + POST + "try { const url = URL.createObjectURL(new Blob(["
        "\"fetch('http://127.0.0.1:%(foreign)s/x').then(() => postMessage('reached'), () => postMessage('blocked'))\"]));"
        "const worker = new Worker(url); worker.onmessage = (e) => post('worker_fetch', e.data);"
        "worker.onerror = () => post('worker_fetch', 'error') } catch (e) { post('worker_fetch', e.name) }</script>"
    ),
}

SHELL = """<script>
  import { mitSchutzregel } from '../../src/lib/vorschauschutz.js'
  let { documents } = $props()
</script>

{#each Object.entries(documents) as [name, text] (name)}
  <iframe title={name} srcdoc={mitSchutzregel(text)} sandbox="allow-scripts" style="width: 200px; height: 100px"></iframe>
{/each}
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'

const documents = %(documents)s
window.__seen = {}
window.addEventListener('message', (e) => {
  try { const report = JSON.parse(e.data); window.__seen[report.name] = report.value } catch { /* a foreign message */ }
})
mount(Shell, { target: document.getElementById('wurzel'), props: { documents } })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
for (let k = 0; k < 100 && Object.keys(window.__seen).length < %(count)d; k += 1) await wait(100)
await wait(500)
document.getElementById('ergebnis').textContent = JSON.stringify({ seen: window.__seen })
"""


class _WithPageRule(harness._Handler):
    """The harness folder, every page with the rule the service puts on its pages."""

    def end_headers(self) -> None:
        self.send_header(inhaltssicherheit.KOPFZEILE, inhaltssicherheit.REGEL)
        super().end_headers()


def _run() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-frame-scripts-{uuid4().hex}"
    folder.mkdir(parents=True)
    server = None
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        foreign = harness._free_port()
        documents = {name: text % {"foreign": foreign} if "%(foreign)s" in text else text for name, text in DOCUMENTS.items()}
        (folder / "entry.js").write_text(ENTRY_JS % {"documents": json.dumps(documents)}, encoding="utf-8")
        (folder / "vite.config.js").write_text(harness.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(
            harness.PAGE % {"cases": CASES % {"count": len(DOCUMENTS)}, "links": ""}, encoding="utf-8"
        )
        web_port = harness._free_port()
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", web_port), functools.partial(_WithPageRule, directory=str(folder))
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = harness._free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--no-first-run", "--disable-background-networking",
                "--mute-audio", "--use-mock-keychain", "--password-store=basic",
                "--window-size=1280,800", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", f"http://127.0.0.1:{web_port}/measure.html",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            return harness.asyncio.run(harness._drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        if server:
            server.shutdown()
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def seen() -> dict:
    return _run()["seen"]


def test_a_document_in_the_frame_runs_eval(seen):
    assert seen["eval"] == "3", seen
    assert seen["function"] == "5", seen


def test_a_document_in_the_frame_loads_a_webassembly_module(seen):
    assert seen["wasm"] == "ok", seen


def test_a_document_in_the_frame_starts_a_worker_from_a_blob(seen):
    assert seen["worker"] == "7", seen


def test_silence_the_way_out_stays_shut_from_the_frame(seen):
    assert seen["fetch"].startswith("blocked connect-src"), seen


def test_silence_the_way_out_stays_shut_from_inside_a_worker(seen):
    assert seen["worker_fetch"] == "blocked", seen
