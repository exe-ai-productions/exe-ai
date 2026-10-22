"""The infos card of an enlarged picture, in a real browser.

`StudioPictureInfo.svelte` is built as shipped (with the program's real texts
for the card) and drawn in headless Chrome. A picture that was enlarged
carries its drawing values and ``upscaled`` (factor and size):

* the card shows a row of its own under the height, "×4 → 2048 × 3072", the
  factor with the decimal sign of the language, and only the size where the
  factor is not known;
* "Use" writes the drawing values (512 × 768) into the fields and nothing of
  the enlarging;
* a picture that was drawn shows no such row.

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
  import StudioPictureInfo from '../../src/teile/StudioPictureInfo.svelte'
</script>

<div style="position: relative; width: 900px; height: 600px;">
  <StudioPictureInfo />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { bildInfo } from '../../src/lib/studiobilder.svelte.js'
import { infoUebernehmen } from '../../src/lib/studiobilder.svelte.js'
import { werte } from '../../src/lib/studio.svelte.js'
import { texte } from '../../src/lib/texte.svelte.js'
import '../../src/stil/global.css'

window.bildInfo = bildInfo
window.werte = werte
window.texte = texte
window.infoUebernehmen = infoUebernehmen
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
const catalog = %(catalog)s
const rows = () => Array.from(document.querySelectorAll('.infozeile')).map((row) => ({
  name: row.querySelector('.infoname').textContent.trim(),
  value: row.querySelector('.infowert').textContent.trim(),
}))
const show = async (language, values) => {
  window.texte.katalog = catalog[language]
  window.texte.sprache = language
  window.bildInfo.werte = values
  await wait(300)
  return rows()
}
const drawn = { prompt: 'a lighthouse', breite: 512, hoehe: 768, schritte: 6, seed: 7 }
const report = {}
report.enlarged = await show('en', { ...drawn, upscaled: { faktor: 4, breite: 2048, hoehe: 3072 } })
report.german = await show('de', { ...drawn, upscaled: { faktor: 1.5, breite: 1536, hoehe: 2304 } })
report.sizeOnly = await show('en', { ...drawn, upscaled: { breite: 2048, hoehe: 2048 } })
report.plain = await show('en', drawn)

// "Use" on the enlarged picture.
await show('en', { ...drawn, upscaled: { faktor: 4, breite: 2048, hoehe: 3072 } })
window.werte.breite = 999
window.werte.hoehe = 999
document.querySelector('.uebernehmen').click()
await wait(300)
report.used = {
  breite: window.werte.breite, hoehe: window.werte.hoehe,
  upscaled: window.werte.upscaled ?? null, cardGone: document.querySelector('.infokarte') === null,
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>info</title>
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


def _catalog() -> dict:
    """The program's own texts the card reads, in both languages."""
    result = {}
    for language in ("de", "en"):
        texts = json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        result[language] = {
            "bild": texts["bild"], "studio": {"uebernehmen": texts["studio"]["uebernehmen"]},
            "app": {"schliessen": texts["app"]["schliessen"]},
        }
    return result


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
    folder = FRONTEND / "node_modules" / f".harness-upscaled-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        page = folder / "measure.html"
        page.write_text(
            PAGE % {"cases": CASES % {"catalog": json.dumps(_catalog())}}, encoding="utf-8",
        )
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


def _names(rows: list[dict]) -> list[str]:
    return [row["name"] for row in rows]


def test_an_enlarged_picture_shows_a_row_of_its_own_under_the_height(report):
    rows = report["enlarged"]
    english = _catalog()["en"]["bild"]
    assert _names(rows)[:4] == [english[k] for k in ("prompt", "breite", "hoehe", "upscaled")]
    assert rows[3]["value"] == "×4 → 2048 × 3072"
    # The drawing values of the original stand as they were.
    assert rows[1]["value"] == "512" and rows[2]["value"] == "768"


def test_the_factor_has_the_decimal_sign_of_the_language(report):
    rows = report["german"]
    assert "Hochskaliert" in _names(rows)
    assert next(r for r in rows if r["name"] == "Hochskaliert")["value"] == "×1,5 → 1536 × 2304"


def test_where_the_factor_is_not_known_only_the_size_stands(report):
    row = next(r for r in report["sizeOnly"] if r["name"] == "Upscaled")
    assert row["value"] == "2048 × 2048"


def test_use_writes_the_drawing_values_and_nothing_of_the_enlarging(report):
    used = report["used"]
    assert (used["breite"], used["hoehe"]) == (512, 768)
    assert used["upscaled"] is None
    assert used["cardGone"] is True


def test_silence_a_drawn_picture_shows_no_such_row(report):
    assert "Upscaled" not in _names(report["plain"])
