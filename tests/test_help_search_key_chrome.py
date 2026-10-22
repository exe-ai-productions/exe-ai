"""The key beside the search field of the manual is the one this system presses.

Both pages of the manual wrote "⌘ K" beside the field on every system, though
a PC has no command key. Now the Mac (and a browser that names no system)
shows "⌘ K", any other system the name of its control key — "Ctrl K" in the
English page, "Strg K" in the German one. Pressing Ctrl+K or Cmd+K focuses the
field as before.

The pages as the service hands them out, opened in a real Chrome whose
platform is stood in by the test. Skipped where there is no Chrome.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests.test_speech_server_projector_memory import _free_port, _read_result

pytestmark = pytest.mark.platforms(
    "darwin", reason="the browser run of the interface is checked on macOS only"
)

HELP = Path(__file__).resolve().parent.parent / "static" / "help"
PAGES = {"en": HELP / "index.html", "de": HELP / "de" / "index.html"}

# Runs before the page does: names a system (and an English device, so the
# English page does not hand the visitor on to the German one).
CASES = """
Object.defineProperty(navigator, 'language', { get: () => 'en-US' })
Object.defineProperty(navigator, 'userAgentData', { get: () => undefined })
Object.defineProperty(navigator, 'platform', { get: () => '%s' })
"""

FOOT = """<script>
  window.addEventListener('load', () => setTimeout(() => {
    const input = document.getElementById('manual-search')
    const label = document.querySelector('#search-form kbd').textContent
    const press = (extra) => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', bubbles: true, ...extra }))
    press({ ctrlKey: true })
    const afterCtrl = document.activeElement === input
    input.blur()
    press({ metaKey: true })
    const afterMeta = document.activeElement === input
    const out = document.createElement('pre')
    out.id = 'ergebnis'
    out.textContent = JSON.stringify({ label, afterCtrl, afterMeta })
    document.body.appendChild(out)
  }, 300))
</script>"""


def _label(language: str, platform: str) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = Path(__file__).resolve().parent.parent / "frontend" / f".harness-help-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        source = PAGES[language].read_text(encoding="utf-8")
        head = "<script>" + (CASES % platform) + "</script>"
        page = folder / "measure.html"
        page.write_text(source.replace("<script>", head + "<script>", 1).replace("</body>", FOOT + "</body>"), encoding="utf-8")
        port = _free_port()
        chrome = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1920,1080", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", page.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            raw = asyncio.run(_read_result(port, limit=60.0))
        finally:
            prozessstopp.beenden(chrome, frist=5)
        assert raw, "the page reported nothing"
        return json.loads(raw)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.parametrize(
    ("language", "platform", "expected"),
    [
        ("en", "Win32", "Ctrl K"),
        ("de", "Win32", "Strg K"),
        ("en", "Linux x86_64", "Ctrl K"),
        ("de", "Linux x86_64", "Strg K"),
        ("en", "MacIntel", "⌘ K"),
        ("de", "MacIntel", "⌘ K"),
    ],
)
def test_the_key_beside_the_field_is_the_one_of_the_system(language, platform, expected):
    result = _label(language, platform)
    assert result["label"] == expected


@pytest.mark.parametrize("platform", ["Win32", "MacIntel"])
def test_both_ways_of_pressing_k_still_focus_the_field(platform):
    result = _label("de", platform)
    assert result["afterCtrl"] and result["afterMeta"]
