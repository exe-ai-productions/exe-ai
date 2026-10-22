"""The windows that save a provider show the reason Anthropic gave, in a real browser.

The mask of the desktop (``Anbietermaske.svelte``) and the one of the phone
(``AddProvider.svelte``) are built as shipped and drawn in headless Chrome with
the service made up in the page. Saving a provider the service reports as not
reachable shows the sentence the answer carries (``hinweis``) instead of
"Saved, but not reachable"; an answer without one shows that old line, and a
reachable provider "Provider saved", as before. Skipped where there is no
Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import test_studio_generate_stays_chrome as page

FRONTEND = page.FRONTEND
SENTENCE = (
    "anthropic is not reachable: This API key is not scoped to a workspace, so this request "
    "must include the anthropic-workspace-id header."
)

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import Anbietermaske from '../../src/teile/Anbietermaske.svelte'
  import AddProvider from '../../src/phone/cloud/AddProvider.svelte'
  const phone = new URLSearchParams(location.search).get('scenario') === 'phone'
</script>

<div style="width: 420px; padding: 16px; position: relative;">
  {#if phone}<AddProvider />{:else}<Anbietermaske />{/if}
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { meldungen } from %(zustand)r

window.__saved = { id: 'anthropic', api_key_env: 'ANTHROPIC_API_KEY', erreichbar: false, hinweis: null }
window.fetch = async (address, options) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path === '/providers' && options?.method === 'POST' ? window.__saved : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
document.documentElement.dataset.modus = 'hell'
window.__meldungen = meldungen
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const phone = new URLSearchParams(location.search).get('scenario') === 'phone'
const keyField = () => document.querySelector('input[type=password]')
for (let k = 0; k < 100 && !keyField(); k += 1) await wait(100)
await wait(300)

const set = (input, value) => {
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
}
const press = async () => {
  const label = 'modell.verbinden'
  const button = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === label)
  button.click()
  await wait(700)
  const list = window.__meldungen.liste
  return list.length ? { text: list[list.length - 1].text, kind: list[list.length - 1].art } : null
}
const report = { phone }
const variants = {
  refused: { id: 'anthropic', api_key_env: 'ANTHROPIC_API_KEY', erreichbar: false, hinweis: %(sentence)r },
  silent: { id: 'anthropic', api_key_env: 'ANTHROPIC_API_KEY', erreichbar: false, hinweis: null },
  reachable: { id: 'anthropic', api_key_env: 'ANTHROPIC_API_KEY', erreichbar: true, hinweis: null },
}
for (const [name, saved] of Object.entries(variants)) {
  window.__saved = saved
  window.__meldungen.liste.length = 0
  set(keyField(), 'sk-ant-api03-invented-key-123')
  await wait(200)
  report[name] = await press()
}

document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def reports() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-provider-refusal-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {"global": "../../src/stil/global.css", "zustand": "../../src/lib/zustand.svelte.js"},
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(page.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(
            page.PAGE % {"cases": CASES % {"sentence": SENTENCE}}, encoding="utf-8",
        )
        out: dict = {}
        for scenario in ("desktop", "phone"):
            port = page._free_port()
            browser = subprocess.Popen(
                [
                    program, "--headless=new", "--no-first-run", "--disable-background-networking",
                    "--allow-file-access-from-files", "--window-size=900,900",
                    f"--remote-debugging-port={port}", f"--user-data-dir={folder / ('profile-' + scenario)}",
                    (folder / "measure.html").as_uri() + f"?scenario={scenario}",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            try:
                out[scenario] = asyncio.run(page._drive(port))
            finally:
                prozessstopp.beenden(browser, frist=5)
        return out
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.parametrize("scenario", ["desktop", "phone"])
def test_the_sentence_of_the_provider_is_what_the_window_shows(reports, scenario):
    shown = reports[scenario]["refused"]
    assert shown == {"text": SENTENCE, "kind": "warnung"}, reports[scenario]


@pytest.mark.parametrize("scenario", ["desktop", "phone"])
def test_silence_without_a_sentence_the_old_line_and_for_a_reachable_one_the_old_success(reports, scenario):
    report = reports[scenario]
    assert report["silent"] == {"text": "modell.anbieter_da_nicht_erreichbar", "kind": "warnung"}, report
    assert report["reachable"] == {"text": "modell.anbieter_da", "kind": "erfolg"}, report
