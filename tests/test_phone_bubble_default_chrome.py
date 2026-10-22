"""The colour field "own bubble colour" of the phone's look settings shows the
default of the look the page draws, measured in a real browser.

`phone/settings/Look.svelte` is built as shipped and drawn in headless Chrome
on a phone-sized page. What the phone page does when the look it draws changes
(it puts the look on the document and says so in `lookPick.drawn`) is done by
the page's own script, in the same order. The page reports what the field
shows after each change of the look, with no new choice in between:

* "auto" on a light device draws Snow, and the field shows Snow's default;
* the device turning dark makes it Exe's default, turning light again Snow's;
* each look, chosen, shows its own default;
* an own bubble colour stays under every change.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests.test_phone_reattach_chrome import PAGE, VITE_CONFIG, _drive, _free_port

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
PHONE = FRONTEND / "src" / "phone"

CHROME_MARK = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import Look from %(look)r
</script>

<div id="phone" style="width: 390px; height: 780px; position: relative; overflow: hidden;">
  <Look />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { zustand } from %(zustand)r
import { lookPick } from %(store)r

document.documentElement.setAttribute('data-modus', 'dunkel')
// What the phone page does when the look it draws changes: the look goes on
// the document, then the page says which look it draws.
window.setLook = (look) => {
  document.documentElement.setAttribute('data-modus', look)
  lookPick.drawn = look
}
window.zustand = zustand
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const field = () => document.querySelector('input[type=color]')
const css = () => getComputedStyle(document.documentElement).getPropertyValue('--blase').trim()
const shown = async (look) => {
  window.setLook(look)
  await wait(250)
  return { field: field().value, css: css() }
}
await wait(400)
report.start = field().value
report.snow = await shown('snow')
report.dark = await shown('dunkel')
report.back = await shown('snow')
report.pearl = await shown('hell')
window.zustand.blasenfarbe = '#ff0000'
await wait(150)
report.own = [await shown('snow'), await shown('dunkel')]
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


def _run_case(cases: str) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-phone-bubble-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"look": "../../src/phone/settings/Look.svelte"}, encoding="utf-8"
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "zustand": "../../src/lib/zustand.svelte.js",
                "store": "../../src/phone/phone.svelte.js",
            },
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        # The style sheet of the interface is a file of its own beside the script.
        sheets = sorted((folder / "out").glob("*.css"))
        assert sheets, "the build made no style sheet"
        page = PAGE.replace(
            '<script src="out/entry.js"></script>',
            f'<link rel="stylesheet" href="out/{sheets[0].name}"><script src="out/entry.js"></script>',
        )
        (folder / "measure.html").write_text(page % {"cases": cases}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--no-first-run", "--disable-background-networking",
                "--allow-file-access-from-files", "--touch-events=enabled", "--window-size=390,780",
                f"--remote-debugging-port={port}", f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            return asyncio.run(_drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def measured() -> dict:
    return _run_case(CASES)


class TestInTheBrowser:
    pytestmark = CHROME_MARK

    def test_auto_on_a_light_device_shows_the_default_of_snow(self, measured):
        assert measured["snow"]["field"] == "#e5e5e5", measured["snow"]
        assert measured["snow"]["field"] == measured["snow"]["css"].lower()

    def test_the_device_turning_dark_shows_the_default_of_exe_and_light_again_the_one_of_snow(self, measured):
        assert measured["dark"]["field"] == "#616161", measured["dark"]
        assert measured["back"]["field"] == "#e5e5e5", measured["back"]

    def test_pearl_shows_its_own_default_and_it_is_neither_of_the_others(self, measured):
        pearl = measured["pearl"]
        assert pearl["field"] == pearl["css"].lower(), pearl
        assert pearl["field"] not in ("#e5e5e5", "#616161")

    def test_silence_an_own_bubble_colour_stays_under_every_change(self, measured):
        assert [row["field"] for row in measured["own"]] == ["#ff0000", "#ff0000"], measured["own"]


def test_the_phone_page_says_which_look_it_draws_whenever_that_changes():
    holder = (PHONE / "Phone.svelte").read_text(encoding="utf-8")
    assert re.search(r"\$effect\(\(\) => \{\s*lookPick\.drawn = look\s*\}\)", holder)
    store = (PHONE / "phone.svelte.js").read_text(encoding="utf-8")
    assert "drawn: null" in store


def test_the_field_reads_its_default_again_after_the_drawn_look_without_a_timer():
    look = (PHONE / "settings" / "Look.svelte").read_text(encoding="utf-8")
    assert "void lookPick.drawn" in look and "tick().then(" in look
    assert "setTimeout" not in look


def test_silence_the_desktop_card_is_the_one_it_was():
    desktop = (FRONTEND / "src" / "teile" / "SystemPrompt.svelte").read_text(encoding="utf-8")
    assert "tick().then(() => {" in desktop and "lookPick" not in desktop
