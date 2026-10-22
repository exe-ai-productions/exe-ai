"""The bars of a document in the preview frame and of the manual, measured in a real browser.

A document the model wrote is drawn in a frame of its own (a `srcdoc`), so the
house rule of rolling without a bar on show (stil/global.css) does not reach
into it: on Windows its long page showed the classic bar. The frame now
carries the rule as the first thing of the document, with no weight — a
document that states its own `scrollbar-width` anywhere keeps it. The pages of
the manual (static/help) are pages of their own too: the one scroller that had
the thin dark bar of the sidebar kept it, the page and the tables did not; now
every surface that rolls wears it.

The wrapper of the frame (`lib/vorschauschutz.js`) is built into a page with
three documents in sandboxed frames the way the rail makes them, each one
reporting from inside; the two manual pages are read from a web server of this
test, in a frame that shares its origin.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import functools
import http.server
import shutil
import subprocess
import threading
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import test_pdf_pages_chrome as harness

ROOT = harness.ROOT
FRONTEND = harness.FRONTEND

pytestmark = harness.pytestmark

LONG = "<p>line</p>" * 200

DOCUMENTS = {
    "plain": f"<!doctype html><html><body>{LONG}</body></html>",
    "own": f"<!doctype html><html><style>html {{ scrollbar-width: auto }}</style><body>{LONG}</body></html>",
    "inner": (
        "<!doctype html><html><body><div id=\"x\" style=\"height: 50px; overflow: auto\">"
        f"{LONG}</div></body></html>"
    ),
}

REPORT = (
    "<script>parent.postMessage(JSON.stringify({ name: '%s', "
    "root: getComputedStyle(document.documentElement).scrollbarWidth, "
    "inner: document.getElementById('x') ? getComputedStyle(document.getElementById('x')).scrollbarWidth : null }), '*')"
    "</script>"
)

SHELL = """<script>
  import { mitSchutzregel } from '../../src/lib/vorschauschutz.js'
  let { documents } = $props()
</script>

{#each Object.entries(documents) as [name, text] (name)}
  <iframe title={name} srcdoc={mitSchutzregel(text)} sandbox="allow-scripts" style="width: 300px; height: 200px"></iframe>
{/each}
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import '../../src/stil/global.css'

const documents = %(documents)s
window.__seen = {}
window.addEventListener('message', (e) => {
  try { const report = JSON.parse(e.data); window.__seen[report.name] = report } catch { /* a foreign message */ }
})
mount(Shell, { target: document.getElementById('wurzel'), props: { documents } })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
for (let k = 0; k < 100 && Object.keys(window.__seen).length < 3; k += 1) await wait(100)
const manual = {}
for (const path of ['/help/', '/help/de/']) {
  const frame = document.createElement('iframe')
  frame.style.cssText = 'width: 1200px; height: 800px'
  frame.src = path
  document.body.appendChild(frame)
  await new Promise((resolve) => { frame.onload = resolve })
  await wait(300)
  const inside = frame.contentDocument
  const look = (el) => ({ width: getComputedStyle(el).scrollbarWidth, colour: getComputedStyle(el).scrollbarColor })
  manual[path] = {
    page: look(inside.documentElement),
    table: look(inside.querySelector('.tafel')),
    sidebar: look(inside.querySelector('aside.sidebar')),
  }
}
document.getElementById('ergebnis').textContent = JSON.stringify({ frames: window.__seen, manual })
"""


def _run() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-frame-bars-{uuid4().hex}"
    folder.mkdir(parents=True)
    server = None
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        entry = ENTRY_JS % {"documents": harness.json.dumps({k: v + REPORT % k for k, v in DOCUMENTS.items()})}
        (folder / "entry.js").write_text(entry, encoding="utf-8")
        (folder / "vite.config.js").write_text(harness.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        links = "\n".join(
            f'<link rel="stylesheet" href="out/{sheet.name}">' for sheet in sorted((folder / "out").glob("*.css"))
        )
        (folder / "measure.html").write_text(
            harness.PAGE % {"cases": CASES, "links": links}, encoding="utf-8"
        )
        (folder / "help").symlink_to(ROOT / "static" / "help")
        web_port = harness._free_port()
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", web_port), functools.partial(harness._Handler, directory=str(folder))
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = harness._free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--no-first-run", "--disable-background-networking",
                "--window-size=1920,1080", f"--remote-debugging-port={port}",
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
def report() -> dict:
    return _run()


def test_a_long_document_in_the_frame_rolls_without_a_bar_on_show(report):
    plain = report["frames"]["plain"]
    assert plain["root"] == "none", plain


def test_a_scroller_inside_the_document_wears_the_rule_too(report):
    assert report["frames"]["inner"]["inner"] == "none", report["frames"]["inner"]


def test_a_document_that_states_its_own_bar_keeps_it(report):
    assert report["frames"]["own"]["root"] == "auto", report["frames"]["own"]


@pytest.mark.parametrize("path", ["/help/", "/help/de/"])
def test_the_page_and_the_tables_of_the_manual_wear_the_thin_bar_of_its_sidebar(report, path):
    for place in ("page", "table"):
        look = report["manual"][path][place]
        assert look["width"] == "thin", (path, place, look)
        assert "76, 75, 69" in look["colour"], (path, place, look)


def test_silence_the_manual_sidebar_keeps_the_bar_it_had(report):
    assert report["manual"]["/help/"]["sidebar"]["width"] == "thin", report["manual"]["/help/"]
