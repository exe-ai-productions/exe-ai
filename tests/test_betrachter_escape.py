"""Escape inside the PDF viewer closes the reader over the window.

With the focus inside Chromium's PDF viewer the key arrives at the viewer, a
content of its own, and never at the page — so the reader stayed open under a
key that closes it everywhere else. The shell hears Escape at the viewer and
says it to the page over the bridge; the page closes an open reader.

What can run is RUN, in node: the rule that tells the viewer from the window,
the shell's listener cut from main.js by name, and the bridge call with a
stand-in for electron. The reader component is read.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "fenster-electron"
MAIN = SHELL / "main.js"
PRELOAD = SHELL / "preload.js"
RULE = SHELL / "adressregel.js"
READER = ROOT / "frontend/src/teile/Bildschau.svelte"

VIEWER = "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai"


def _node(script: str) -> Any:
    if not shutil.which("node"):
        pytest.skip("node is missing")
    run = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def _cut(pattern: str, name: str) -> str:
    source = MAIN.read_text(encoding="utf-8")
    found = re.search(pattern, source, re.S)
    assert found, f"{name} not found in main.js"
    return found.group(0).strip() + "\n"


def test_the_viewer_is_told_from_the_window_and_the_tools_by_its_address():
    result = _node(f"""
const rules = require({json.dumps(str(RULE))})
console.log(JSON.stringify({{
  index: rules.isPdfViewer('{VIEWER}/index.html'),
  stream: rules.isPdfViewer('{VIEWER}/d2f3e988-f124'),
  window: rules.isPdfViewer('http://127.0.0.1:8090/app/'),
  tools: rules.isPdfViewer('devtools://devtools/bundled/devtools_app.html'),
  other: rules.isPdfViewer('chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/index.html'),
  lookalike: rules.isPdfViewer('{VIEWER}x/index.html'),
  empty: rules.isPdfViewer(''),
  nothing: rules.isPdfViewer(null),
}}))
""")
    assert result == {
        "index": True, "stream": True, "window": False, "tools": False,
        "other": False, "lookalike": False, "empty": False, "nothing": False,
    }


def _listener(*, address: str, key: str = "Escape", kind: str = "keyDown",
              focused: bool = True, destroyed: bool = False, window: bool = True) -> list:
    """What the window's page is sent when `key` goes `kind` at a content
    that shows `address`."""
    function = _cut(r"\nfunction betrachterTaste\(inhalt, eingabe\) \{\n.*?\n\}\n", "betrachterTaste")
    return _node(f"""
const regel = require({json.dumps(str(RULE))})
const sent = []
let fenster = {json.dumps(window)} ? {{
  isDestroyed: () => {json.dumps(destroyed)},
  isFocused: () => {json.dumps(focused)},
  webContents: {{ send: (...args) => sent.push(args) }},
}} : null
{function}
betrachterTaste({{ getURL: () => {json.dumps(address)} }}, {{ type: {json.dumps(kind)}, key: {json.dumps(key)} }})
console.log(JSON.stringify(sent))
""")


def test_escape_going_down_at_the_viewer_is_told_to_the_page_once():
    """Falls over without the fix: nothing heard the viewer at all."""
    assert _listener(address=f"{VIEWER}/index.html") == [["betrachter-escape"]]


@pytest.mark.parametrize("key", ["Enter", "a", "ArrowDown", "Tab", " "])
def test_no_other_key_is_told(key):
    assert _listener(address=f"{VIEWER}/index.html", key=key) == []


def test_a_key_coming_up_is_not_told():
    assert _listener(address=f"{VIEWER}/index.html", kind="keyUp") == []
    assert _listener(address=f"{VIEWER}/index.html", kind="char") == []


@pytest.mark.parametrize("address", [
    "http://127.0.0.1:8090/app/",
    "devtools://devtools/bundled/devtools_app.html",
    "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/index.html",
    "",
])
def test_escape_anywhere_else_is_the_pages_own_business(address):
    """Silence probe: at the window and at the developer tools Escape goes
    the way it always went, and the shell says nothing."""
    assert _listener(address=address) == []


def test_a_viewer_in_another_window_does_not_close_this_windows_reader():
    assert _listener(address=f"{VIEWER}/index.html", focused=False) == []


def test_without_a_window_or_with_a_destroyed_one_nothing_is_sent_and_nothing_fails():
    assert _listener(address=f"{VIEWER}/index.html", window=False) == []
    assert _listener(address=f"{VIEWER}/index.html", destroyed=True) == []


def test_every_content_is_listened_to_in_the_one_hook():
    """Set in the hook every content passes through: the viewer is one of
    them, whichever window opened it."""
    source = MAIN.read_text(encoding="utf-8")
    hook = re.search(r"app\.on\('web-contents-created', \(ereignis, inhalt\) => \{\n(.*?)\n\}\)", source, re.S)
    assert hook, "web-contents-created hook not found"
    assert "inhalt.on('before-input-event', (ereignis, eingabe) => betrachterTaste(inhalt, eingabe))" in hook.group(1)
    # The key itself is never held back: the viewer gets it as it came.
    function = _cut(r"\nfunction betrachterTaste\(inhalt, eingabe\) \{\n.*?\n\}\n", "betrachterTaste")
    assert "preventDefault" not in function


def _bridge(body: str) -> Any:
    return _node(f"""
const Module = require('module')
const exposed = {{}}
const listening = []
const removed = []
const electron = {{
  contextBridge: {{ exposeInMainWorld: (name, api) => {{ exposed[name] = api }} }},
  ipcRenderer: {{
    invoke: () => Promise.resolve(null),
    on: (channel, listener) => listening.push([channel, listener]),
    removeListener: (channel, listener) => removed.push([channel, listener]),
    send: () => {{}},
  }},
}}
const load = Module._load
Module._load = function (request, ...rest) {{
  return request === 'electron' ? electron : load.call(this, request, ...rest)
}}
require({json.dumps(str(PRELOAD))})
const bridge = exposed.exeHuelle
{body}
""")


def test_the_bridge_calls_back_on_the_viewer_channel_and_hands_back_the_way_to_stop():
    result = _bridge("""
const calls = []
const stop = bridge.aufBetrachterEscape(() => calls.push('closed'))
listening[0][1]({}, 'ignored')
stop()
console.log(JSON.stringify({
  channels: listening.map((l) => l[0]),
  calls,
  removedSame: removed.length === 1 && removed[0][0] === 'betrachter-escape' && removed[0][1] === listening[0][1],
  stopIsFunction: typeof stop === 'function',
}))
""")
    assert result == {
        "channels": ["betrachter-escape"], "calls": ["closed"],
        "removedSame": True, "stopIsFunction": True,
    }


def test_the_bridge_ignores_a_callback_that_is_none():
    result = _bridge("""
console.log(JSON.stringify({ answer: bridge.aufBetrachterEscape(null) ?? null, listening: listening.length }))
""")
    assert result == {"answer": None, "listening": 0}


def test_the_reader_closes_on_the_message_only_while_it_is_open_and_only_in_the_shell():
    source = READER.read_text(encoding="utf-8")
    effect = re.search(r"\$effect\(\(\) => \{\n\s*const huelle = .*?\n\s*\}\)\n", source, re.S)
    assert effect, "the listener for the viewer's Escape is not there"
    body = effect.group(0)
    # Only with the shell's bridge; in a browser nothing is listened for.
    assert "window.exeHuelle" in body
    assert "typeof huelle.aufBetrachterEscape !== 'function'" in body
    # An open reader closes; a message with the reader shut changes nothing.
    assert re.search(r"if \(bildschau\.offen\) closeReader\(\)", body)
    # The way to stop listening is handed back, so a part built anew does not
    # leave its old listener reading along.
    assert "return huelle.aufBetrachterEscape(" in body
