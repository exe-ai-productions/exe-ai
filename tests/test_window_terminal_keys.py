"""The CLI tab's key switch off a Mac: which keys the page keeps, which the
browser handles, which go to the client.

The real module (frontend/src/lib/windowTerminal.js) is run in Node against
stand-ins, once for each system: a drawing that records the switch handed to
`attachCustomKeyEventHandler` and has a selection to be told about, a shell
that records what it is sent, a page with nothing on it. Events are made up
with the fields the switch reads; the switch's answer is `false` where the
drawing must not act on the key, and `stopPropagation` tells whether the
page's own key handler is kept from it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "frontend" / "src" / "lib"
WINDOW_TERMINAL = LIB / "windowTerminal.js"
TERMINAL_RESIZE = LIB / "terminalResize.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")

DRIVER = r"""
import { readFileSync, writeFileSync } from 'fs'
import { pathToFileURL } from 'url'
const [source, resizeSource, built, scenes, system] = process.argv.slice(2)
const standIns = `
const world = globalThis.world
class Xterm {
  constructor(options) {
    this.constructed = options
    this.cols = 80
    this.rows = 24
    this.options = {}
    this.buffer = { active: { viewportY: 0, baseY: 0 } }
    this.parser = { registerCsiHandler() {} }
    world.xterm = this
  }
  loadAddon() {}
  open() {}
  focus() {}
  attachCustomKeyEventHandler(handler) { world.handler = handler }
  hasSelection() { return world.selection }
  onResize() {}
  onData() {}
  write() {}
  scrollToBottom() {}
  resize() {}
}
class FitAddon { proposeDimensions() { return { cols: 80, rows: 24 } } fit() {} }
class WebglAddon { onContextLoss() {} }
class WebLinksAddon {}
const t = (key) => key
const texte = { sprache: 'en' }
const zustand = { aktiverChat: '' }
const system = ${JSON.stringify(system)}
`
const strip = (file) => readFileSync(file, 'utf-8').replace(/^import .*$/gm, '')
writeFileSync(built, standIns + strip(resizeSource) + strip(source))

const world = { handler: null, selection: false, sent: [] }
globalThis.world = world
globalThis.window = {
  exeHuelle: { terminal: {
    start: () => Promise.resolve({ pid: 1 }),
    write: (data) => world.sent.push(data),
    resize: () => {},
    onData: () => {},
    onExit: () => {},
  } },
  matchMedia: () => ({ matches: true, addEventListener() {} }),
  open() {},
}
globalThis.document = {
  documentElement: { getAttribute: () => 'dunkel' },
  createElement: () => ({ isConnected: true, style: {} }),
}
globalThis.getComputedStyle = () => ({ getPropertyValue: (name) => (name === '--schrift-fest' ? 'TOKEN-VALUE' : '') })
globalThis.requestAnimationFrame = (step) => step()
globalThis.MutationObserver = class { observe() {} }
globalThis.ResizeObserver = class { observe() {} disconnect() {} }
const terminal = await import(pathToFileURL(built).href)
terminal.ensureTerminal()

const results = {}
for (const [name, { key, mods = {}, selection = false, type = 'keydown' }] of Object.entries(JSON.parse(scenes))) {
  world.selection = selection
  const event = {
    type, key, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...mods,
    stopped: false, stopPropagation() { this.stopped = true },
  }
  const toTheDrawing = world.handler(event)
  results[name] = { toTheDrawing, pageNotReached: event.stopped, sent: [...world.sent] }
}
results.__font = world.xterm.constructed.fontFamily
console.log(JSON.stringify(results))
"""

CTRL = {"ctrlKey": True}
META = {"metaKey": True}

KEYS = {
    "ctrl-n": {"key": "n", "mods": CTRL},
    "ctrl-comma": {"key": ",", "mods": CTRL},
    "ctrl-b": {"key": "b", "mods": CTRL},
    "ctrl-k": {"key": "k", "mods": CTRL},
    "ctrl-j": {"key": "j", "mods": CTRL},
    "ctrl-a": {"key": "a", "mods": CTRL},
    "ctrl-backtick": {"key": "`", "mods": CTRL},
    "ctrl-c-selected": {"key": "c", "mods": CTRL, "selection": True},
    "ctrl-c-bare": {"key": "c", "mods": CTRL},
    "ctrl-v": {"key": "v", "mods": CTRL},
    "ctrl-shift-v": {"key": "v", "mods": {"ctrlKey": True, "shiftKey": True}},
    "cmd-n": {"key": "n", "mods": META},
    "cmd-comma": {"key": ",", "mods": META},
    "cmd-b": {"key": "b", "mods": META},
    "cmd-j": {"key": "j", "mods": META},
    "cmd-k": {"key": "k", "mods": META},
    "cmd-c": {"key": "c", "mods": META, "selection": True},
    "plain-n": {"key": "n"},
    "ctrl-n-up": {"key": "n", "mods": CTRL, "type": "keyup"},
}


def _run(system: str) -> dict:
    stamp = uuid4().hex
    driver = ROOT / "frontend" / f"window_terminal_keys.{stamp}.pruefung.mjs"
    built = ROOT / "frontend" / f"window_terminal_keys.{stamp}.gebaut.mjs"
    driver.write_text(DRIVER, encoding="utf-8")
    try:
        done = subprocess.run(
            [
                "node", driver.name, str(WINDOW_TERMINAL), str(TERMINAL_RESIZE), built.name,
                json.dumps(KEYS), system,
            ],
            cwd=ROOT / "frontend", capture_output=True, text=True, timeout=60, check=False,
        )
    finally:
        driver.unlink(missing_ok=True)
        built.unlink(missing_ok=True)
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def windows() -> dict:
    return _run("windows")


@pytest.fixture(scope="module")
def mac() -> dict:
    return _run("mac")


@pytest.fixture(scope="module")
def other() -> dict:
    return _run("other")


@pytest.mark.parametrize("name", ["ctrl-n", "ctrl-comma", "ctrl-b", "ctrl-k"])
def test_windows_gives_the_pages_ctrl_shortcuts_to_the_page(windows, name):
    # The switch says "not the drawing's" and does not stop the event: it
    # goes on up to the page, which acts on it.
    assert windows[name]["toTheDrawing"] is False, (name, windows[name])
    assert windows[name]["pageNotReached"] is False, (name, windows[name])
    assert windows[name]["sent"] == [], (name, windows[name])


@pytest.mark.parametrize("name", ["ctrl-j", "ctrl-a"])
def test_windows_leaves_ctrl_j_and_ctrl_a_to_the_client(windows, name):
    assert windows[name]["toTheDrawing"] is True, (name, windows[name])
    assert windows[name]["pageNotReached"] is True, (name, windows[name])


def test_ctrl_backtick_stays_with_the_page_on_both_systems(windows, mac):
    for report in (windows, mac):
        assert report["ctrl-backtick"]["toTheDrawing"] is False, report["ctrl-backtick"]
        assert report["ctrl-backtick"]["pageNotReached"] is False, report["ctrl-backtick"]


def test_windows_copies_a_selection_with_ctrl_c_and_pastes_with_ctrl_v(windows):
    for name in ("ctrl-c-selected", "ctrl-v"):
        # Kept from the page and from the client alike: the browser does it.
        assert windows[name]["toTheDrawing"] is False, (name, windows[name])
        assert windows[name]["pageNotReached"] is True, (name, windows[name])
        assert windows[name]["sent"] == [], (name, windows[name])


def test_windows_without_a_selection_ctrl_c_stays_the_clients_interrupt(windows):
    assert windows["ctrl-c-bare"]["toTheDrawing"] is True, windows["ctrl-c-bare"]
    assert windows["ctrl-c-bare"]["pageNotReached"] is True, windows["ctrl-c-bare"]


def test_other_systems_follow_windows(other, windows):
    assert other == windows


def test_silence_on_a_mac_cmd_keys_go_to_the_page_and_ctrl_keys_to_the_client(mac):
    for name in ("cmd-n", "cmd-comma", "cmd-b", "cmd-j", "cmd-k"):
        assert mac[name]["toTheDrawing"] is False, (name, mac[name])
        assert mac[name]["pageNotReached"] is False, (name, mac[name])
    for name in ("ctrl-n", "ctrl-comma", "ctrl-b", "ctrl-j", "ctrl-k", "ctrl-a", "ctrl-c-selected",
                 "ctrl-c-bare", "ctrl-v"):
        assert mac[name]["toTheDrawing"] is True, (name, mac[name])
        assert mac[name]["pageNotReached"] is True, (name, mac[name])


def test_silence_cmd_c_and_other_keys_are_as_before_on_both_systems(windows, mac):
    assert mac["cmd-c"]["toTheDrawing"] is True and mac["cmd-c"]["pageNotReached"] is True, mac["cmd-c"]
    for report in (windows, mac):
        assert report["plain-n"]["toTheDrawing"] is True, report["plain-n"]
        assert report["ctrl-n-up"]["toTheDrawing"] is True, report["ctrl-n-up"]
        assert report["ctrl-shift-v"]["toTheDrawing"] is True, report["ctrl-shift-v"]
