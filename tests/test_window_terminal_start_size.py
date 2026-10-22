"""The CLI tab starts the client with the size its box really has.

The real module (frontend/src/lib/windowTerminal.js) is run in Node against
stand-ins: a fit that gives no size for a box that is not laid out and the
box's size once it is, a shell that records the size every start asks for,
and a frame clock the scene steps by hand. A scene plays the box changing
while the tab opens.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "frontend" / "src" / "lib"
WINDOW_TERMINAL = LIB / "windowTerminal.js"
TERMINAL_RESIZE = LIB / "terminalResize.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")

DRIVER = r"""
import { readFileSync, writeFileSync } from 'fs'
import { pathToFileURL } from 'url'
const [source, resizeSource, built, scenes] = process.argv.slice(2)
const standIns = `
const world = globalThis.world
class Xterm {
  constructor() {
    this.cols = 80
    this.rows = 24
    this.options = {}
    this.buffer = { active: { viewportY: 0, baseY: 0 } }
    this.parser = { registerCsiHandler: (id, handler) => { world.handlers.push({ id, handler }) } }
    world.xterm = this
  }
  loadAddon() {}
  open() {}
  focus() {}
  attachCustomKeyEventHandler() {}
  onResize() {}
  onData(listener) { world.typed = listener }
  write() {}
  scrollToBottom() {}
  resize(cols, rows) { this.cols = cols; this.rows = rows }
}
class FitAddon {
  proposeDimensions() { return world.box ? { ...world.box } : undefined }
  fit() { if (world.box) world.xterm.resize(world.box.cols, world.box.rows) }
}
class WebglAddon { onContextLoss() {} }
class WebLinksAddon {}
const t = (key) => key
const texte = { sprache: 'en' }
const zustand = { aktiverChat: '' }
const system = 'mac'
`
const strip = (file) => readFileSync(file, 'utf-8').replace(/^import .*$/gm, '')
writeFileSync(built, standIns + strip(resizeSource) + strip(source))

const results = {}
let run = 0
for (const [name, steps] of Object.entries(JSON.parse(scenes))) {
  const world = { box: null, room: null, starts: [], sent: [], handlers: [], typed: null, frames: [], observer: null, connected: true }
  globalThis.world = world
  globalThis.window = {
    exeHuelle: { terminal: {
      start: (request) => { world.starts.push([request.cols, request.rows]); return Promise.resolve({ pid: 1 }) },
      write: (data) => world.sent.push(data),
      resize() {},
      onData() {},
      onExit: (listener) => { world.exit = listener },
    } },
    matchMedia: () => ({ matches: true, addEventListener() {} }),
    open() {},
  }
  const holder = { style: {}, get isConnected() { return world.connected }, get parentElement() { return world.room } }
  globalThis.document = {
    documentElement: { getAttribute: () => 'dunkel' },
    createElement: () => holder,
  }
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' })
  globalThis.MutationObserver = class { observe() {} }
  globalThis.ResizeObserver = class { constructor(listener) { world.observer = listener } observe() {} disconnect() {} }
  globalThis.requestAnimationFrame = (step) => { world.frames.push(step) }
  run += 1
  const terminal = await import(`${pathToFileURL(built).href}?scene=${run}`)
  const root = { appendChild() {}, removeChild() {} }
  // Leading steps set the room the box lies in; the box as it is when the tab
  // is shown is the next step.
  while (steps[0][0] === 'room') world.room = steps.shift()[1]
  const [, first] = steps.shift()
  world.box = first
  const leave = terminal.show(root)
  const seen = []
  for (const [kind, data] of steps) {
    if (kind === 'frame') {
      const waiting = world.frames.splice(0)
      waiting.forEach((step) => step())
    } else if (kind === 'box') {
      world.box = data
      world.observer()
    } else if (kind === 'fit_ready') {
      // The drawing got its cells: the fit gives a size, nobody is told.
      world.box = data
    } else if (kind === 'room') {
      world.room = data
      world.observer()
    } else if (kind === 'typed') {
      world.typed(data)
    } else if (kind === 'exit') {
      world.exit(0)
    } else if (kind === 'ready') {
      // The client asks where the cursor stands: its screen is up.
      world.handlers.filter(({ id }) => id.final === 'n').forEach(({ handler }) => handler([6]))
    } else if (kind === 'leave') {
      world.connected = false
      leave()
    }
    await Promise.resolve()
    seen.push(world.starts.map((start) => [...start]))
  }
  results[name] = { seen, sent: world.sent }
}
console.log(JSON.stringify(results))
"""

SCENES = {
    # The box has its size when the tab opens and keeps it: one start, with it.
    "a_steady_box": [
        ["box", {"cols": 88, "rows": 58}],
        ["frame"],
        ["frame"],
        ["frame"],
    ],
    # The first size the fit gives is a small one and the box takes its real
    # size at the next frame, as a column does that is still being laid out.
    "a_box_that_grows_while_the_tab_opens": [
        ["box", {"cols": 44, "rows": 30}],
        ["frame"],
        ["box", {"cols": 88, "rows": 58}],
        ["frame"],
        ["frame"],
        ["frame"],
    ],
    # A box that has no size yet: nothing starts until it reports one.
    "a_box_without_a_size": [
        ["box", None],
        ["frame"],
        ["frame"],
        ["box", {"cols": 88, "rows": 58}],
        ["frame"],
        ["frame"],
        ["frame"],
    ],
    # The room the box lies in has no size yet, while the fit already gives
    # the smallest size it ever gives (two columns, one row): not a size to
    # start a client with.
    "a_room_without_a_size": [
        ["room", {"clientWidth": 0, "clientHeight": 0}],
        ["box", {"cols": 2, "rows": 1}],
        ["frame"],
        ["frame"],
        ["frame"],
        ["room", {"clientWidth": 700, "clientHeight": 900}],
        ["box", {"cols": 88, "rows": 58}],
        ["frame"],
        ["frame"],
    ],
    # The room has a size and the drawing no cells to count with yet: the
    # next frame looks again, and the client is not left unstarted.
    "a_drawing_that_has_no_cells_yet": [
        ["room", {"clientWidth": 700, "clientHeight": 900}],
        ["box", None],
        ["frame"],
        ["frame"],
        ["fit_ready", {"cols": 88, "rows": 58}],
        ["frame"],
        ["frame"],
        ["frame"],
    ],
    # The drawing never gets cells to count with: the client starts anyway,
    # as it always did, with the size the drawing has.
    "a_drawing_that_never_has_cells": [
        ["room", {"clientWidth": 700, "clientHeight": 900}],
        ["box", None],
        *[["frame"]] * 130,
    ],
    # What is typed before the client was started waits for its screen and
    # goes to it then, whole.
    "typed_before_the_start": [
        ["box", {"cols": 88, "rows": 58}],
        ["typed", "ab"],
        ["frame"],
        ["frame"],
        ["typed", "c"],
        ["ready"],
    ],
    # A box whose size never holds still: the client is started after all.
    "a_box_that_never_holds_still": [
        ["box", {"cols": 44, "rows": 30}],
        *[step for _ in range(65) for step in (["fit_ready", {"cols": 88, "rows": 58}], ["frame"], ["fit_ready", {"cols": 44, "rows": 30}], ["frame"])],
    ],
    # The client ends and Enter starts it again: at the size the box has then,
    # behind a gate that is shut, with nothing left of what was typed for the
    # one that ended.
    "a_client_started_again_after_its_end": [
        ["box", {"cols": 88, "rows": 58}],
        ["frame"],
        ["frame"],
        ["typed", "stale"],
        ["exit"],
        ["fit_ready", {"cols": 100, "rows": 50}],
        ["typed", "\r"],
        ["frame"],
        ["frame"],
        ["typed", "fresh"],
        ["ready"],
    ],
    # Enter after the end while the room has no size: nothing starts, and the
    # next Enter, once the room has one, does.
    "enter_after_the_end_in_a_room_without_a_size": [
        ["box", {"cols": 88, "rows": 58}],
        ["frame"],
        ["frame"],
        ["exit"],
        ["room", {"clientWidth": 0, "clientHeight": 0}],
        ["typed", "\r"],
        ["frame"],
        ["room", {"clientWidth": 700, "clientHeight": 900}],
        ["frame"],
        ["frame"],
        ["typed", "\r"],
        ["frame"],
        ["frame"],
    ],
    # The tab is left before the box has settled.
    "a_tab_left_before_the_start": [
        ["box", {"cols": 88, "rows": 58}],
        ["frame"],
        ["leave"],
        ["frame"],
        ["frame"],
    ],
}


@pytest.fixture(scope="module")
def scenes(tmp_path_factory):
    folder = tmp_path_factory.mktemp("window-terminal-start-size")
    driver = folder / "driver.mjs"
    driver.write_text(DRIVER, encoding="utf-8")
    ran = subprocess.run(
        [
            "node",
            str(driver),
            str(WINDOW_TERMINAL),
            str(TERMINAL_RESIZE),
            str(folder / "built.mjs"),
            json.dumps(SCENES),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert ran.returncode == 0, ran.stderr
    return json.loads(ran.stdout)


@needs_node
def test_a_box_that_keeps_its_size_starts_the_client_with_it_once(scenes):
    """The silent case: nothing changes for a box that is right from the
    start — one start, with the box's size, after it stood still for two
    frames."""
    assert scenes["a_steady_box"]["seen"] == [[], [[88, 58]], [[88, 58]]]


@needs_node
def test_a_box_that_grows_while_the_tab_opens_gets_the_client_at_its_final_size(scenes):
    """The client is not started at the size of a box that is still being laid
    out: it would keep the head it drew for that size."""
    seen = scenes["a_box_that_grows_while_the_tab_opens"]["seen"]
    assert all(starts == [] for starts in seen[:3])
    assert seen[-1] == [[88, 58]]


@needs_node
def test_a_box_without_a_size_starts_nothing_until_it_has_one(scenes):
    seen = scenes["a_box_without_a_size"]["seen"]
    assert seen[:3] == [[], [], []]
    assert seen[-1] == [[88, 58]]


@needs_node
def test_a_tab_that_is_left_before_the_box_settled_starts_nothing(scenes):
    assert scenes["a_tab_left_before_the_start"]["seen"][-1] == []


@needs_node
def test_a_room_without_a_size_starts_nothing_even_where_the_fit_gives_the_smallest_size(scenes):
    seen = scenes["a_room_without_a_size"]["seen"]
    assert all(starts == [] for starts in seen[:5])
    assert seen[-1] == [[88, 58]]


@needs_node
def test_a_drawing_without_cells_is_looked_at_again_and_starts_when_it_has_them(scenes):
    seen = scenes["a_drawing_that_has_no_cells_yet"]["seen"]
    assert seen[:3] == [[], [], []]
    assert seen[-1] == [[88, 58]]


@needs_node
def test_a_drawing_that_never_gets_cells_starts_the_client_after_all(scenes):
    """The bound on the wait: the tab is never left blank for good."""
    seen = scenes["a_drawing_that_never_has_cells"]["seen"]
    assert seen[100] == []
    assert seen[-1] == [[80, 24]]


@needs_node
def test_what_is_typed_before_the_client_starts_reaches_it_once_its_screen_is_up(scenes):
    """Keys typed in the frames before the start are not lost to the gate
    that the start shuts."""
    scene = scenes["typed_before_the_start"]
    assert scene["sent"] == ["abc"]


@needs_node
def test_a_box_that_never_holds_still_starts_the_client_after_all(scenes):
    seen = scenes["a_box_that_never_holds_still"]["seen"]
    assert seen[100] == []
    assert len(seen[-1]) == 1


@needs_node
def test_enter_after_the_end_starts_the_client_again_at_the_size_the_box_has_then(scenes):
    """The first client took the box as it was; the second is started with the
    box as it is after the end, and what was typed for the first never reaches
    it."""
    scene = scenes["a_client_started_again_after_its_end"]
    assert scene["seen"][-1] == [[88, 58], [100, 50]]
    assert scene["sent"] == ["fresh"]


@needs_node
def test_an_enter_that_found_no_room_can_be_given_again(scenes):
    """The end is kept until a client was started: a tab that could not start
    one is not left unable to."""
    seen = scenes["enter_after_the_end_in_a_room_without_a_size"]["seen"]
    assert seen[4] == [[88, 58]]
    # The room gets its size: the client that ended is not started by that,
    # only by an Enter.
    assert seen[5] == seen[6] == seen[7] == seen[8] == [[88, 58]]
    assert seen[-1] == [[88, 58], [88, 58]]
