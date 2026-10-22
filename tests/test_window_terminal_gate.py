"""The CLI tab's gate: what is typed before the client's screen is up waits —
and does not wait for a program that asks for input itself.

The real module (frontend/src/lib/windowTerminal.js) is run in Node against
stand-ins: a drawing that hands every control sequence to the handlers
registered for it, a shell that records what it is sent, a page with nothing
on it. A scene plays what is typed, what the program writes and its end.
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
SHELL_TERMINAL = ROOT / "fenster-electron" / "terminal.js"
TERMINAL_RESIZE = LIB / "terminalResize.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")

DRIVER = r"""
import { readFileSync, writeFileSync } from 'fs'
import { pathToFileURL } from 'url'
const [source, resizeSource, built, scenes] = process.argv.slice(2)
const standIns = `
const world = globalThis.world
class Xterm {
  constructor(options) {
    this.cols = 80
    this.rows = 24
    this.options = {}
    this.buffer = { active: { viewportY: 0, baseY: 0 } }
    this.parser = { registerCsiHandler: (id, handler) => { world.handlers.unshift({ id, handler }) } }
    this.constructed = options
    world.xterm = this
  }
  loadAddon() {}
  open() {}
  focus() {}
  attachCustomKeyEventHandler() {}
  onResize() {}
  onData(listener) { world.typed = listener }
  write(data, done) { world.draw(data); if (done) done() }
  paste(text) { world.typed(text) }
  scrollToBottom() {}
  resize(cols, rows) { this.cols = cols; this.rows = rows }
}
class FitAddon {
  proposeDimensions() { return { ...world.box } }
  fit() { world.xterm.resize(world.box.cols, world.box.rows) }
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

const ANSWER = '\x1b[1;1R'
const results = {}
let run = 0
for (const [name, steps] of Object.entries(JSON.parse(scenes))) {
  const world = { handlers: [], typed: null, sent: [], output: null, exit: null, foreign: false, hold: false, box: { cols: 80, rows: 24 }, observer: null }
  // Leading steps that set the world the scene runs in.
  while (steps.length && ['foreign', 'hold'].includes(steps[0][0])) {
    const [setting, value] = steps.shift()
    world[setting] = value
  }
  world.draw = (data) => {
    for (const [, prefix, numbers, final] of String(data).matchAll(/\x1b\[(\??)([0-9;]*)([A-Za-z])/g)) {
      const params = numbers.split(';').filter(Boolean).map(Number)
      const taken = world.handlers
        .filter(({ id }) => (id.prefix ?? '') === prefix && id.final === final)
        .some(({ handler }) => handler(params))
      if (!taken && prefix === '' && final === 'n' && params[0] === 6) world.typed(ANSWER)
    }
  }
  globalThis.world = world
  globalThis.window = {
    exeHuelle: { terminal: {
      start: () => {
        const answer = world.foreign ? { pid: 1, foreign: true } : { pid: 1 }
        // Held until the scene lets the shell answer.
        return world.hold ? new Promise((answered) => { world.answer = () => answered(answer) }) : Promise.resolve(answer)
      },
      write: (data) => world.sent.push(data),
      resize: () => {},
      onData: (listener) => { world.output = listener },
      onExit: (listener) => { world.exit = listener },
    } },
    matchMedia: () => ({ matches: true, addEventListener() {} }),
    open() {},
  }
  globalThis.document = {
    documentElement: { getAttribute: () => 'dunkel' },
    createElement: () => ({ isConnected: true, style: {} }),
  }
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' })
  globalThis.requestAnimationFrame = (step) => step()
  globalThis.MutationObserver = class { observe() {} }
  globalThis.ResizeObserver = class { constructor(listener) { world.observer = listener } observe() {} disconnect() {} }
  run += 1
  const terminal = await import(`${pathToFileURL(built).href}?scene=${run}`)
  terminal.show({ appendChild() {}, removeChild() {} })
  await Promise.resolve()
  const seen = []
  const columns = []
  for (const [kind, data] of steps) {
    if (kind === 'typed') world.typed(data)
    else if (kind === 'pasted') world.xterm.paste(data)
    else if (kind === 'program') world.output(data)
    else if (kind === 'end') world.exit(0)
    else if (kind === 'answer') world.answer()
    else if (kind === 'box') { world.box = { cols: data, rows: 24 }; world.observer() }
    await Promise.resolve()
    seen.push([...world.sent])
    columns.push(world.xterm.cols)
  }
  results[name] = { sent: world.sent, seen, columns }
}
console.log(JSON.stringify(results))
"""

# What the terminal answers when the program asks where the cursor stands.
CURSOR_ANSWER = "\x1b[1;1R"

# How the client's output reaches the page before its screen is up, as
# measured at its start: the cursor's shape, the colour of the cursor, the
# head with the wordmark — ending on the start of a line — and then its first
# question for the cursor's position.
SHAPE = "\x1b[?12l\x1b[?25h"
CURSOR_COLOUR = "\x1b]12;#ecebe6\x1b\\"
HEAD = "\x1b[?12l\x1b[?25h\r\n  ██╗  the head\x1b[0m\r\n\r\n"
ASKS_FOR_THE_CURSOR = "\x1b[6n"

SENTENCE = (
    "I would like a calmer footer than plain white, so that one sees at a glance how full the context is, "
    "because naïve café charts — plain numbers — do not help anyone in a hurry."
)  # Longer than one row, with characters beyond ASCII.

SCENES = {
    # A long sentence, once as a quick run of keys and once pasted, while the
    # client starts, and once typed and once pasted while it runs.
    "sentence_typed_while_starting": [
        *[["typed", character] for character in SENTENCE],
        ["program", HEAD + ASKS_FOR_THE_CURSOR],
    ],
    "sentence_pasted_while_starting": [
        ["pasted", SENTENCE],
        ["program", HEAD + ASKS_FOR_THE_CURSOR],
    ],
    "sentence_pasted_while_running": [
        ["program", HEAD + ASKS_FOR_THE_CURSOR],
        ["pasted", SENTENCE],
    ],
    # A program that is not the client, asking for a line before any screen as
    # one that asks for a password does: it writes its question, and neither
    # asks for the cursor nor switches bracketed paste on.
    "a_program_that_asks": [
        ["foreign", True],
        ["program", "Password: "],
        ["typed", "secret"],
        ["typed", "\r"],
    ],
    # What was typed before the shell said which program it started.
    "typed_before_the_answer": [
        ["foreign", True],
        ["hold", True],
        ["typed", "se"],
        ["answer", ""],
        ["typed", "cret"],
    ],
    # The client as it starts: nothing it writes before its question for the
    # cursor opens the gate, not even a piece that ends in the middle of a line.
    "the_client_on_its_way_up": [
        ["typed", "a"],
        ["program", SHAPE],
        ["program", CURSOR_COLOUR],
        ["program", HEAD[:40]],
        ["typed", "b"],
        ["program", HEAD[40:]],
        ["typed", "c"],
        ["program", ASKS_FOR_THE_CURSOR],
    ],
    "interrupt_while_waiting": [
        ["typed", "a"],
        ["typed", "\x03"],
    ],
    "pasted_while_waiting": [
        ["pasted", "a long line of text"],
        ["program", HEAD + ASKS_FOR_THE_CURSOR],
    ],
    # An Enter typed before the shell answered reaches the program as an Enter.
    "enter_before_the_answer": [
        ["foreign", True],
        ["hold", True],
        ["typed", "se\r"],
        ["answer", ""],
    ],
    # The program ends before the shell's answer comes: nothing is sent to it.
    "ended_before_the_answer": [
        ["foreign", True],
        ["hold", True],
        ["typed", "se"],
        ["end", ""],
        ["answer", ""],
    ],
    # The drawing follows a narrower box at once for a program that never
    # asks where the cursor stands.
    "narrower_for_a_program_that_asks": [
        ["foreign", True],
        ["program", "Password: "],
        ["box", 60],
    ],
    "pasted_to_a_program_that_asks": [
        ["foreign", True],
        ["pasted", "/Users/a/probe\\ datei.txt"],
    ],
}


@pytest.fixture(scope="module")
def scenes(tmp_path_factory):
    folder = tmp_path_factory.mktemp("window-terminal-gate")
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
        encoding="utf-8",
        timeout=60,
    )
    assert ran.returncode == 0, ran.stderr
    return json.loads(ran.stdout)


@needs_node
def test_a_program_that_is_not_the_client_gets_what_is_typed_at_once(scenes):
    """It asks for a line before any screen, as a password prompt does; it
    never asks for the cursor and never switches bracketed paste on. What is
    typed for it reaches it, an Enter as an Enter."""
    scene = scenes["a_program_that_asks"]
    assert scene["seen"] == [[], ["secret"], ["secret", "\r"]]


@needs_node
def test_what_was_typed_before_the_shell_named_the_program_reaches_it_with_the_answer(scenes):
    scene = scenes["typed_before_the_answer"]
    assert scene["seen"] == [[], ["se"], ["se", "cret"]]


@needs_node
def test_the_client_keeps_the_gate_shut_until_its_screen_is_up(scenes):
    """The client's output before its question for the cursor — control
    sequences, its head in two pieces of which the first ends in the middle
    of a line — is no place to type: what is typed waits for the screen."""
    scene = scenes["the_client_on_its_way_up"]
    *waiting, with_the_screen = scene["seen"]
    assert all(seen == [] for seen in waiting)
    assert with_the_screen == ["abc", CURSOR_ANSWER]


@needs_node
def test_the_interrupt_key_never_waits_and_what_waited_stays(scenes):
    assert scenes["interrupt_while_waiting"]["seen"] == [[], ["\x03"]]


@needs_node
def test_a_pasted_text_waits_for_the_screen_like_keys_do(scenes):
    """What a drop or a paste types goes through the same gate."""
    scene = scenes["pasted_while_waiting"]
    assert scene["seen"][0] == []
    assert scene["seen"][1] == ["a long line of text", CURSOR_ANSWER]


@needs_node
def test_a_dropped_path_reaches_a_program_that_is_not_the_client_at_once(scenes):
    assert scenes["pasted_to_a_program_that_asks"]["seen"] == [["/Users/a/probe\\ datei.txt"]]


# --- The shell's side: which program it says it started -----------------------

SHELL_SCRIPT = """
const t = require(%(module)s)
const handlers = {}
const spawned = []
const pty = { spawn(file) { const term = { pid: 70 + spawned.length, file, onData() {}, onExit() {}, kill() {} }; spawned.push(term); return term } }
const contents = { id: 1, isDestroyed: () => false, send() {}, once() {} }
const run = async (command) => {
  const terminals = t.createTerminals({
    ipcMain: { handle: (name, fn) => { handlers[name] = fn }, on() {} },
    pty, address: 'http://127.0.0.1:1', command, log() {}, exists: () => true,
  })
  const answer = await handlers['terminal-start']({ sender: contents }, {})
  terminals.stopAll()
  return answer
}
;(async () => {
  console.log(JSON.stringify({
    ownCommand: t.clientCommand({ env: { EXE_AI_CLI: '/elsewhere/probe' }, repoRoot: '/repo' }),
    sourceCommand: t.clientCommand({ env: {}, repoRoot: '/repo', platform: 'darwin' }),
    packagedCommand: t.clientCommand({ env: {}, packaged: true, resourcesPath: '/App/Resources', platform: 'darwin' }),
    ownAnswer: await run(t.clientCommand({ env: { EXE_AI_CLI: '/elsewhere/probe' }, repoRoot: '/repo' })),
    clientAnswer: await run(t.clientCommand({ env: {}, repoRoot: '/repo', platform: 'darwin' })),
  }))
})()
"""


@needs_node
def test_the_shell_says_that_a_program_other_than_the_client_was_started():
    ran = subprocess.run(
        ["node", "-e", SHELL_SCRIPT % {"module": json.dumps(str(SHELL_TERMINAL))}],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert ran.returncode == 0, ran.stderr
    shell = json.loads(ran.stdout)
    # EXE_AI_CLI names a program for a trial run: it is not the client.
    assert shell["ownCommand"]["foreign"] is True
    assert shell["ownAnswer"] == {"pid": 70, "foreign": True}
    # The client, from the source tree and packaged, is answered as before.
    assert "foreign" not in shell["sourceCommand"]
    assert "foreign" not in shell["packagedCommand"]
    assert shell["clientAnswer"] == {"pid": 71}


@needs_node
def test_a_long_sentence_arrives_whole_and_in_order_on_every_way_it_is_typed(scenes):
    """Typed key by key or pasted, while the client starts and while it
    runs: the client gets the sentence from its first character."""
    typed = scenes["sentence_typed_while_starting"]["sent"]
    assert typed == [SENTENCE, CURSOR_ANSWER]
    assert scenes["sentence_pasted_while_starting"]["sent"] == [SENTENCE, CURSOR_ANSWER]
    assert scenes["sentence_pasted_while_running"]["sent"] == [CURSOR_ANSWER, SENTENCE]


@needs_node
def test_an_enter_typed_before_the_shell_answered_reaches_a_foreign_program_as_an_enter(scenes):
    assert scenes["enter_before_the_answer"]["sent"] == ["se\r"]


@needs_node
def test_an_answer_that_comes_after_the_program_ended_sends_nothing(scenes):
    assert scenes["ended_before_the_answer"]["sent"] == []


@needs_node
def test_the_drawing_follows_a_narrower_box_at_once_for_a_foreign_program(scenes):
    """The drawing waits for the client's question for the cursor only; a
    program that never asks must not leave it at the old width."""
    assert scenes["narrower_for_a_program_that_asks"]["columns"][-1] == 60
