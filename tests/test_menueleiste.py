"""The sign of the program in the menu bar (macOS) or notification area
(Windows): drawn in full while the service answers, dimmed while it does not,
with three entries — open the window, end the service, end the program — and
staying when the window is closed.

`fenster-electron/menueleiste.js` is plain node: electron's `Tray`, `Menu` and
`nativeImage` are handed in, so it runs here with stand-ins. `main.js` requires
electron and cannot run outside a packaged window; the pieces that decide
what the entries do are cut from its source by name and run for real in node,
as tests/test_shell_single_instance.py does.
"""

from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL_FOLDER = ROOT / "fenster-electron"
MODULE = SHELL_FOLDER / "menueleiste.js"
MAIN = SHELL_FOLDER / "main.js"
IMAGES = SHELL_FOLDER / "anzeige"
PACKAGE = SHELL_FOLDER / "package.json"


def _node(script: str) -> Any:
    if not shutil.which("node"):
        pytest.skip("node is missing")
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def _source() -> str:
    return MAIN.read_text(encoding="utf-8")


def _piece(pattern: str, name: str) -> str:
    match = re.search(pattern, _source(), re.S)
    assert match, f"{name} not found"
    return match.group(0).strip() + "\n"


# --- The module, with stand-ins for electron ---------------------------------------

STAND_INS = """
const module_ = require(%(module)s)
const log = []
const trays = []
class Tray {
  constructor(image) {
    this.image = image
    this.calls = []
    this.handlers = {}
    this.menus = []
    this.destroyed = false
    trays.push(this)
  }
  setImage(image) { this.image = image; this.calls.push(['setImage', image.file]) }
  setToolTip(text) { this.tip = text }
  setContextMenu(menu) { this.menu = menu; this.menus.push(menu) }
  on(name, handler) { this.handlers[name] = handler }
  destroy() { this.destroyed = true }
  isDestroyed() { return this.destroyed }
}
const Menu = { buildFromTemplate: (template) => template }
const nativeImage = { createFromPath: (file) => ({ file: require('path').basename(file) }) }
const timers = {
  callback: null, every: null, cleared: false,
  setInterval(callback, every) { this.callback = callback; this.every = every; return 7 },
  clearInterval(handle) { this.cleared = handle },
}
const calls = []
let answering = true
const options = (extra = {}) => ({
  Tray, Menu, nativeImage, folder: '/images', platform: 'darwin', timers,
  answers: async () => answering,
  openWindow: () => calls.push('open'),
  endService: async () => { calls.push('end-service') },
  endProgram: () => calls.push('end-program'),
  log: (line) => log.push(line),
  ...extra,
})
const settle = () => new Promise((done) => setImmediate(done));
"""


def _run(body: str) -> Any:
    return _node(
        STAND_INS % {"module": json.dumps(str(MODULE))}
        + "\n(async () => {\n"
        + body
        + "\n})().catch((error) => { console.error(error); process.exit(1) })\n"
    )


def test_a_service_that_answers_is_drawn_in_full_and_one_that_does_not_is_dimmed():
    result = _run("""
const sign = module_.start(options())
const first = trays[0].image.file
await settle()
const answered = trays[0].image.file
answering = false
await sign.look()
const silent = trays[0].image.file
answering = true
await sign.look()
console.log(JSON.stringify({ first, answered, silent, back: trays[0].image.file }))
""")
    # Up at once, dimmed; the first look makes it true.
    assert result == {
        "first": "menueleisteDimTemplate.png",
        "answered": "menueleisteTemplate.png",
        "silent": "menueleisteDimTemplate.png",
        "back": "menueleisteTemplate.png",
    }


def test_the_image_is_set_only_where_the_state_changes():
    result = _run("""
const sign = module_.start(options())
await settle()
await sign.look()
await sign.look()
answering = false
await sign.look()
await sign.look()
console.log(JSON.stringify(trays[0].calls))
""")
    assert result == [
        ["setImage", "menueleisteTemplate.png"],
        ["setImage", "menueleisteDimTemplate.png"],
    ]


def test_a_look_that_fails_counts_as_a_service_that_does_not_answer():
    result = _run("""
answering = true
const sign = module_.start(options({ answers: async () => { throw new Error('refused') } }))
await settle()
console.log(JSON.stringify({ image: trays[0].image.file, log }))
""")
    assert result["image"] == "menueleisteDimTemplate.png"
    assert result["log"] == ["Menu bar: looking at the service failed: refused"]


def test_only_the_newest_look_counts_when_looks_overlap():
    """A probe that began before the service ended can come back after the one
    that began after it: the older answer must not draw the sign in full."""
    result = _run("""
const pending = []
const sign = module_.start(options({ answers: () => new Promise((done) => pending.push(done)) }))
const second = sign.look()
pending[1](false)
await second
pending[0](true)
await settle()
console.log(JSON.stringify({ probes: pending.length, calls: trays[0].calls, image: trays[0].image.file }))
""")
    assert result == {"probes": 2, "calls": [], "image": "menueleisteDimTemplate.png"}


def test_the_service_is_looked_at_on_a_timer_and_the_timer_ends_with_the_sign():
    result = _run("""
const sign = module_.start(options())
await settle()
const timer = { callback: typeof timers.callback, every: timers.every }
answering = false
await timers.callback()
const afterTick = trays[0].image.file
sign.remove()
answering = true
await sign.look()
console.log(JSON.stringify({
  timer, afterTick, cleared: timers.cleared, destroyed: trays[0].destroyed,
  untouched: trays[0].image.file,
}))
""")
    assert result["timer"] == {"callback": "function", "every": 2000}
    assert result["afterTick"] == "menueleisteDimTemplate.png"
    assert result["cleared"] == 7 and result["destroyed"] is True
    # A look that comes after the sign is down sets nothing.
    assert result["untouched"] == "menueleisteDimTemplate.png"


def test_the_menu_has_three_entries_and_each_does_its_own_thing():
    result = _run("""
module_.start(options())
await settle()
const entries = trays[0].menu
const labels = entries.map((entry) => entry.label)
const done = []
for (const entry of entries) {
  calls.length = 0
  await entry.click()
  done.push([...calls])
}
console.log(JSON.stringify({ labels, done }))
""")
    assert result["labels"] == ["Open Window", "Stop Service", "Quit Exe AI"]
    # The service is ended by one entry only, the window opened by one only,
    # and the program ended by one only.
    assert result["done"] == [["open"], ["end-service"], ["end-program"]]


def test_a_service_that_cannot_be_ended_is_logged_and_the_sign_looks_again():
    result = _run("""
module_.start(options({
  endService: async () => { throw new Error('refused') },
  endFailed: () => calls.push('told'),
}))
await settle()
answering = false
await trays[0].menu[1].click()
console.log(JSON.stringify({ log, calls, image: trays[0].image.file }))
""")
    assert result["log"] == ["Menu bar: ending the service failed: refused"]
    # The user is told, once.
    assert result["calls"] == ["told"]
    # The look after it found the service silent all the same.
    assert result["image"] == "menueleisteDimTemplate.png"


def test_after_ending_the_service_the_sign_turns_dim_at_once():
    result = _run("""
module_.start(options({ endService: async () => { answering = false } }))
await settle()
const before = trays[0].image.file
await trays[0].menu[1].click()
console.log(JSON.stringify({ before, after: trays[0].image.file }))
""")
    assert result == {"before": "menueleisteTemplate.png", "after": "menueleisteDimTemplate.png"}


def test_a_service_that_ends_tells_nobody_of_a_failure():
    result = _run("""
module_.start(options({ endFailed: () => calls.push('told') }))
await settle()
await trays[0].menu[1].click()
console.log(JSON.stringify(calls))
""")
    assert result == ["end-service"]


def test_a_telling_that_fails_is_logged_and_the_sign_still_looks_again():
    result = _run("""
module_.start(options({
  endService: async () => { throw new Error('refused') },
  endFailed: () => { throw new Error('no window') },
}))
await settle()
answering = false
await trays[0].menu[1].click()
console.log(JSON.stringify({ log, image: trays[0].image.file }))
""")
    assert result["log"] == [
        "Menu bar: ending the service failed: refused",
        "Menu bar: telling about the failure failed: no window",
    ]
    assert result["image"] == "menueleisteDimTemplate.png"


def test_the_failed_telling_that_is_a_rejection_is_logged_too():
    result = _run("""
module_.start(options({
  endService: async () => { throw new Error('refused') },
  endFailed: async () => { throw new Error('no window') },
}))
await settle()
await trays[0].menu[1].click()
console.log(JSON.stringify(log))
""")
    assert result[-1] == "Menu bar: telling about the failure failed: no window"


def test_the_same_words_again_leave_the_menu_as_it_is():
    result = _run("""
const sign = module_.start(options())
await settle()
sign.setWords({ openWindow: 'Exe AI öffnen' })
sign.setWords({ openWindow: 'Exe AI öffnen' })
sign.setWords({ openWindow: 'Exe AI öffnen', stray: 'x' })
sign.setWords(null)
console.log(JSON.stringify(trays[0].menus.length))
""")
    # At the start, for the German word, and back to the English ones.
    assert result == 3


GERMAN = "{ openWindow: 'Exe AI öffnen', endService: 'Dienst beenden', endProgram: 'Exe AI beenden' }"


def test_the_menu_is_set_anew_in_the_words_a_page_sends():
    result = _run("""
const sign = module_.start(options())
await settle()
sign.setWords(%s)
calls.length = 0
const entries = trays[0].menu
for (const entry of entries) await entry.click()
console.log(JSON.stringify({
  menus: trays[0].menus.length, labels: entries.map((entry) => entry.label), calls,
}))
""" % GERMAN)
    # Built twice — at the start and for the words — and the entries still act.
    assert result == {
        "menus": 2,
        "labels": ["Exe AI öffnen", "Dienst beenden", "Exe AI beenden"],
        "calls": ["open", "end-service", "end-program"],
    }


def test_a_word_the_page_left_out_stays_english_and_a_later_sending_follows_it():
    result = _run("""
const sign = module_.start(options())
await settle()
sign.setWords({ openWindow: 'Exe AI öffnen', endService: '   ', endProgram: 42, tip: 'other', stray: 'x' })
const partial = trays[0].menu.map((entry) => entry.label)
sign.setWords({ endService: 'Dienst beenden' })
const later = trays[0].menu.map((entry) => entry.label)
sign.setWords(null)
console.log(JSON.stringify({ partial, later, back: trays[0].menu.map((entry) => entry.label), tip: trays[0].tip }))
""")
    assert result["partial"] == ["Exe AI öffnen", "Stop Service", "Quit Exe AI"]
    # Every sending stands for itself: a word sent earlier does not stay.
    assert result["later"] == ["Open Window", "Dienst beenden", "Quit Exe AI"]
    assert result["back"] == ["Open Window", "Stop Service", "Quit Exe AI"]
    assert result["tip"] == "Exe AI"


def test_words_sent_after_the_sign_is_down_set_nothing():
    result = _run("""
const sign = module_.start(options())
await settle()
sign.remove()
sign.setWords(%s)
console.log(JSON.stringify({ menus: trays[0].menus.length }))
""" % GERMAN)
    assert result == {"menus": 1}


def _notice(body: str) -> Any:
    """Runs the shell's half of the notice: the handler of the page's words
    and the waiting notice, cut out of main.js."""
    handler = _piece(r"ipcMain\.on\('menu-words'.*?\n\}\)\n", "the words handler")
    state = _piece(r"let pageTold = false\n.*?\n\}\n", "the notice state")
    tell = _piece(r"async function tellStopFailed\(\) \{.*?\n\}\n", "tellStopFailed")
    script = f"""
const calls = []
const kontextmenue = {{ wordsFrom: (sent) => sent }}
let menuWords = null
let sign = {{ setWords: (sent) => calls.push(['words', sent]) }}
const ipcMain = {{ on: (name, handler) => {{ ipc = handler }} }}
let ipc = null
const page = {{ send: (...message) => calls.push(['send', ...message]) }}
let fenster = null
const makeWindow = () => ({{ webContents: page, isDestroyed: () => false }})
async function openWindow() {{ calls.push('open'); if (!fenster) fenster = makeWindow() }}
function bringWindowForward() {{ calls.push('forward') }}
{handler}
{state}
{tell}
(async () => {{
{body}
  process.stdout.write(JSON.stringify(calls) + "\\n")
}})()
"""
    return _node(script)


def test_a_failed_end_with_the_page_standing_shows_the_message_at_once_and_once():
    calls = _notice("""
fenster = makeWindow()
ipc({ sender: page }, { openWindow: 'x' })
calls.length = 0
await tellStopFailed()
ipc({ sender: page }, { openWindow: 'x' })
""")
    assert calls == [
        "open", "forward", ["send", "shell-notice", "service-stop-failed"],
        ["words", {"openWindow": "x"}],
    ]


def test_a_failed_end_with_the_window_closed_waits_for_the_page_and_shows_it_once():
    calls = _notice("""
await tellStopFailed()
const before = [...calls]
ipc({ sender: page }, { openWindow: 'x' })
ipc({ sender: page }, { openWindow: 'x' })
calls.unshift(['before', before])
""")
    # Nothing is sent to a page that has not told its words; then exactly one.
    assert calls[0] == ["before", ["open", "forward"]]
    assert calls.count(["send", "shell-notice", "service-stop-failed"]) == 1


def test_a_window_that_cannot_come_up_leaves_no_notice_waiting():
    # The program is ending: nothing opens, and nothing may wait for a later page.
    calls = _notice("""
openWindow = async () => { calls.push('open') }
await tellStopFailed()
fenster = makeWindow()
ipc({ sender: page }, { openWindow: 'x' })
""")
    assert calls == ["open", "forward", ["words", {"openWindow": "x"}]]


def test_a_menu_that_cannot_be_set_does_not_hold_the_notice_back():
    calls = _notice("""
sign = { setWords: () => { throw new Error('tray gone') } }
console.error = (...line) => calls.push(['error', line.join(' ')])
fenster = makeWindow()
ipc({ sender: page }, {})
calls.length = 0
await tellStopFailed()
ipc({ sender: page }, { openWindow: 'x' })
""")
    assert ["send", "shell-notice", "service-stop-failed"] in calls
    assert ["error", "Menu bar: setting the words failed: tray gone"] in calls


def test_the_words_of_another_window_neither_set_the_menu_nor_hand_over_the_notice():
    calls = _notice("""
fenster = makeWindow()
await tellStopFailed()
calls.length = 0
ipc({ sender: { other: true } }, { openWindow: 'x' })
""")
    assert calls == []


def test_a_page_that_loads_again_has_to_tell_its_words_before_it_gets_the_notice():
    source = _source()
    # The window's own page (a frame inside it loading is not a new page).
    assert re.search(r"did-navigate', \(\) => \{ pageTold = false \}\)", source)
    assert "did-start-loading" not in source[source.index("pageTold = false"):][:300]


def test_the_bridge_and_the_shell_use_one_channel_for_the_notice():
    preload = (MAIN.parent / "preload.js").read_text(encoding="utf-8")
    assert "'shell-notice'" in preload and "'shell-notice'" in _source()
    page = (MAIN.parents[1] / "frontend" / "src" / "lib" / "shellWords.js").read_text(encoding="utf-8")
    # The page listens before it tells its words, and shows the notice as a failure.
    assert page.index("onShellNotice") < page.index("menuWords?.(words)")
    assert "service-stop-failed" in page and "menue.sign_stop_failed" in page


@pytest.mark.parametrize(
    ("platform", "full", "dim", "click"),
    [
        ("darwin", "menueleisteTemplate.png", "menueleisteDimTemplate.png", False),
        ("win32", "notificationArea.png", "notificationAreaDim.png", True),
    ],
)
def test_each_system_has_its_own_images_and_its_own_click(platform, full, dim, click):
    result = _run(f"""
module_.start(options({{ platform: '{platform}' }}))
await settle()
const tray = trays[0]
console.log(JSON.stringify({{
  full: module_.imageFile(true, '{platform}'), dim: module_.imageFile(false, '{platform}'),
  shown: tray.image.file, click: 'click' in tray.handlers,
  opens: tray.handlers.click ? (tray.handlers.click(), calls.slice()) : [],
}}))
""")
    assert (result["full"], result["dim"], result["shown"]) == (full, dim, full)
    assert result["click"] is click
    assert result["opens"] == (["open"] if click else [])


# --- The images -----------------------------------------------------------------------


def _size(file: Path) -> tuple[int, int]:
    header = file.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", header[16:24])  # type: ignore[return-value]


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("menueleisteTemplate", (22, 18)),
        ("menueleisteDimTemplate", (22, 18)),
        ("notificationArea", (16, 16)),
        ("notificationAreaDim", (16, 16)),
    ],
)
def test_every_image_has_its_double_size_beside_it(name, size):
    assert _size(IMAGES / f"{name}.png") == size
    assert _size(IMAGES / f"{name}@2x.png") == (size[0] * 2, size[1] * 2)


def test_the_template_images_are_black_and_the_dimmed_one_has_less_alpha():
    pil = pytest.importorskip("PIL.Image")
    full = pil.open(IMAGES / "menueleisteTemplate.png").convert("RGBA")
    dim = pil.open(IMAGES / "menueleisteDimTemplate.png").convert("RGBA")
    # Black wherever there is anything: the system colours a template image
    # by its alpha alone.
    assert all(pixel[:3] == (0, 0, 0) for pixel in full.getdata() if pixel[3])
    assert all(pixel[:3] == (0, 0, 0) for pixel in dim.getdata() if pixel[3])
    assert full.getchannel("A").getextrema()[1] == 255
    assert dim.getchannel("A").getextrema()[1] < 255
    # The same shape in both, only weaker: every pixel at about a third.
    assert all(
        abs(weak[3] - strong[3] * 0.35) <= 1 for strong, weak in zip(full.getdata(), dim.getdata(), strict=True)
    )


# --- What main.js does with it -----------------------------------------------------


def test_closing_the_window_no_longer_ends_the_program():
    source = _source()
    closing = re.search(r"^app\.on\('window-all-closed', \(\) => \{\n(.*?)\n\}\)\n", source, re.S | re.M)
    assert closing, "the handler of the last window is not found"
    # It ends the program only where there is no sign to keep it.
    assert closing.group(1).strip() == "if (!sign) app.quit()"
    # The window no longer ends the program when it is gone.
    assert "fenster.on('closed', () => app.quit())" not in source


def test_the_sign_goes_up_with_the_program_and_its_entries_are_wired():
    source = _source()
    ready = source.index("app.whenReady().then(async () => {")
    assert "setUpSign()" in source[ready : ready + 800]
    # The sign's entries wait while the start is under way.
    start = source[ready : ready + 1200]
    assert start.index("opening = true") < start.index("dienstAnbinden()") < start.index("opening = false")
    setting = _piece(r"\nfunction setUpSign\(\) \{\n.*?\n\}\n", "setUpSign")
    for wired in (
        "answers: antwortet",
        "openWindow,",
        "endService: endServiceFromMenu",
        "endProgram: () => app.quit()",
    ):
        assert wired in setting
    # Taken down with the program.
    assert "sign.remove()" in source


def test_the_dock_asks_for_a_window_where_there_is_none():
    source = _source()
    # At the start of a line: the handlers inside blocks are indented.
    handler = re.search(r"^app\.on\('activate', \(\) => \{\n(.*?)\n\}\)\n", source, re.S | re.M)
    assert handler, "the dock's handler is not found"
    assert handler.group(1).strip() == "if (sign && (!fenster || fenster.isDestroyed())) openWindow()"


def _second_start(*, sign: bool, window: str) -> list:
    """The handler of the lock block, with the sign up or not and the window
    there, closed or never built; a second start comes in."""
    pieces = "\n".join([
        _piece(r"\nfunction bringWindowForward\(\) \{\n.*?\n\}\n", "bringWindowForward"),
        _piece(r"\nif \(app\.requestSingleInstanceLock\(\)\) \{\n.*?\n\}\n", "the lock"),
    ])
    script = f"""
const calls = []
const listeners = {{}}
const app = {{
  requestSingleInstanceLock: () => true,
  on(name, f) {{ listeners[name] = f }},
  whenReady: () => ({{ then() {{}} }}),
}}
console.log = () => {{}}
let sign = {'{}' if sign else 'null'}
async function openWindow() {{ calls.push('open') }}
const fenster = {{
  none: null,
  gone: {{ isDestroyed: () => true }},
  open: {{
    isDestroyed: () => false, isMinimized: () => false,
    show: () => calls.push('show'), focus: () => calls.push('focus'),
  }},
}}[{json.dumps(window)}]
{pieces}
listeners['second-instance']()
process.stdout.write(JSON.stringify(calls) + "\\n")
"""
    return _node(script)


@pytest.mark.parametrize("window", ["gone", "none"])
def test_a_second_start_opens_a_window_where_the_program_runs_on_in_the_menu_bar(window):
    assert _second_start(sign=True, window=window) == ["open"]


def test_a_second_start_brings_the_window_forward_where_there_is_one():
    assert _second_start(sign=True, window="open") == ["show", "focus"]


@pytest.mark.parametrize("window", ["gone", "none"])
def test_without_a_sign_a_second_start_opens_nothing(window):
    # The program would have ended with its window; before the window exists
    # there is nothing to raise either.
    assert _second_start(sign=False, window=window) == []


def test_the_module_ships_with_the_program():
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    files = package["build"]["files"]
    assert "menueleiste.js" in files
    # The images stand in the folder the shell already ships.
    assert "anzeige/**" in files


# --- The pieces of main.js that decide what the entries do -------------------------


def _open_window(
    *,
    window: str,
    quit_: bool = False,
    answering: bool = True,
    busy: bool = False,
    service: str = "none",
    ending: bool = False,
) -> dict:
    """Runs openWindow. ``window``: ``none`` (never built), ``interface`` (a
    window on the interface), ``splash`` (a window on the splash or an error
    page), ``gone`` (a window that was closed). ``service``: ``none``,
    ``ours`` (a service of ours that is coming up), ``found`` (one found
    running at the start) or ``found-gone`` (one found at the start whose
    process has since gone). ``answering``: whether the service answers its
    port. ``ending``: an end of the service is under way."""
    piece = _piece(r"\nasync function openWindow\(\) \{\n.*?\n\}\n", "openWindow")
    script = f"""
const calls = []
const ADDRESS = 'http://127.0.0.1:8123'
let beendet = {str(quit_).lower()}
let opening = {str(busy).lower()}
let dienstFehlgeschlagen = true
let dienstAntwortete = true
let endingService = {"null" if not ending else "new Promise((done) => setImmediate(() => { calls.push('ended'); done() }))"}
let kind = {'null' if service != 'ours' else "{ pid: 1 }"}
let dienstVorgefunden = {'null' if service not in ('found', 'found-gone') else "{ pid: 2, port: 8123 }"}
const dienstsuche = {{ processAlive: (pid) => {str(service != 'found-gone').lower()} }}
const page = (url) => ({{
  isDestroyed: () => false,
  webContents: {{
    getURL: () => url,
    executeJavaScript: async (code) => {{ calls.push(['page', code]) }},
  }},
}})
let fenster = {{
  none: null,
  interface: page(ADDRESS + '/app/'),
  splash: page('file:///splash.html'),
  gone: {{ isDestroyed: () => true }},
}}[{json.dumps(window)}]
async function antwortet() {{ calls.push('asked'); return {str(answering).lower()} }}
function bringWindowForward() {{ calls.push('forward') }}
function fensterBauen() {{ calls.push('build') }}
async function dienstStarten() {{ calls.push(['start', dienstFehlgeschlagen, dienstAntwortete]) }}
async function warten() {{ calls.push('wait') }}
{piece}
(async () => {{
  await openWindow()
  process.stdout.write(JSON.stringify({{ calls, opening }}) + "\\n")
}})()
"""
    return _node(script)


def test_a_window_on_the_interface_with_a_service_that_answers_is_only_brought_forward():
    assert _open_window(window="interface")["calls"] == ["forward", "asked"]


def test_a_window_whose_service_was_ended_gets_the_service_back_and_loads_again():
    # No second window: the one there is waits for the service anew.
    assert _open_window(window="interface", answering=False)["calls"] == [
        "forward", "asked", ["page", "delete document.body.dataset.zustand"],
        ["start", False, False], "wait",
    ]


def test_a_window_left_on_the_splash_or_an_error_page_loads_the_interface_when_asked_for():
    # The service may have come up since: the interface is loaded, the
    # service is started only where it does not answer (dienstStarten asks
    # that itself).
    # A failure mark that stands on the page is taken off first.
    assert _open_window(window="splash")["calls"] == [
        "forward", ["page", "delete document.body.dataset.zustand"], ["start", False, False], "wait",
    ]


@pytest.mark.parametrize("service", ["ours", "found"])
def test_a_service_that_is_coming_up_or_was_found_is_not_started_a_second_time(service):
    assert _open_window(window="splash", service=service)["calls"] == [
        "forward", ["page", "delete document.body.dataset.zustand"], "wait",
    ]


def test_a_window_asked_for_while_the_service_ends_waits_for_the_end_and_then_starts_it():
    """"End service" and, at once, "Open window": the old process is still
    shutting down. The window waits for it and starts the service after."""
    assert _open_window(window="gone", answering=False, ending=True)["calls"] == [
        "ended", "build", ["start", False, False], "wait",
    ]


def test_a_service_found_at_the_start_whose_process_has_gone_is_started_again():
    """The sign dims when such a service is ended from a terminal or crashes;
    asking for the window then must not wait for a service that is not there."""
    assert _open_window(window="interface", answering=False, service="found-gone")["calls"] == [
        "forward", "asked", ["page", "delete document.body.dataset.zustand"],
        ["start", False, False], "wait",
    ]


@pytest.mark.parametrize("window", ["gone", "none"])
def test_without_a_window_a_new_one_is_built_and_waits_for_the_service(window):
    # The flags of the earlier start are cleared first.
    assert _open_window(window=window)["calls"] == ["build", ["start", False, False], "wait"]


def test_a_program_that_is_ending_opens_no_window():
    assert _open_window(window="gone", quit_=True)["calls"] == []


def test_a_second_ask_while_one_is_under_way_is_let_go_and_the_first_is_not_disturbed():
    result = _open_window(window="gone", busy=True)
    assert result["calls"] == []
    # The flag of the one under way is left as it was found.
    assert result["opening"] is True


def test_the_flag_of_a_finished_ask_is_down_again():
    assert _open_window(window="gone")["opening"] is False


def _end_service(*, kind_during=None) -> dict:
    """Runs endServiceFromMenu with a running service of ours that is found
    by its note. ``kind_during``: what ``kind`` becomes while the service
    ends (another start began)."""
    pieces = "\n".join([
        _piece(r"\nlet endingService = null\n", "endingService"),
        _piece(r"\nfunction endServiceFromMenu\(\) \{\n.*?\n\}\n", "endServiceFromMenu"),
        _piece(r"\nasync function endServiceNow\(\) \{\n.*?\n\}\n", "endServiceNow"),
    ])
    script = f"""
const calls = []
const PORT = 8123
const path = require('path')
const app = {{ isPackaged: false }}
let kind = {{ own: 'process' }}
let dienstVorgefunden = {{ pid: 1, port: 8123 }}
let dienstAntwortete = false
console.log = (line) => calls.push(line)
const dienstsuche = {{
  dataRoot: () => '/root',
  runningService: async () => ({{ pid: 7, port: 8123 }}),
}}
async function endRunningService(running) {{
  calls.push(['end', running.pid])
  {'kind = ' + kind_during if kind_during else ''}
  return 'ended'
}}
{pieces}
(async () => {{
  const during = (() => {{ const promise = endServiceFromMenu(); return [endingService === promise, promise] }})()
  await during[1]
  process.stdout.write(JSON.stringify({{
    calls, kind, dienstVorgefunden, dienstAntwortete, markedWhileEnding: during[0], markedAfter: endingService,
  }}) + "\\n")
}})()
"""
    return _node(script)


def test_ending_the_service_from_the_sign_ends_the_process_and_forgets_the_service():
    # The process is waited for, as before an update: the model server goes
    # after the port, and a window opened in between must not start a second
    # service on the same folder.
    assert _end_service() == {
        "calls": [["end", 7], "Service: ended from the menu bar (pid 7; ended)"],
        "kind": None,
        "dienstVorgefunden": None,
        # Its end from here on is the one asked for, not a failed start.
        "dienstAntwortete": True,
        # The end is noted while it is under way, and let go of afterwards.
        "markedWhileEnding": True,
        "markedAfter": None,
    }


def test_a_start_that_began_while_the_service_ended_is_not_forgotten():
    result = _end_service(kind_during="{ another: 'start' }")
    assert result["kind"] == {"another": "start"}


def test_a_sign_that_cannot_be_set_up_is_logged_and_leaves_the_program_as_it_was():
    piece = _piece(r"\nfunction setUpSign\(\) \{\n.*?\n\}\n", "setUpSign")
    script = f"""
const calls = []
console.error = (...line) => calls.push(line.join(' '))
const path = require('path')
const __dirname = '/shell'
const process_ = {{ platform: 'darwin' }}
const Tray = class {{}}, Menu = {{}}, nativeImage = {{}}
const antwortet = () => true
function openWindow() {{}}
async function endServiceFromMenu() {{}}
async function tellStopFailed() {{}}
const app = {{ quit() {{}} }}
const menueleiste = {{ start() {{ throw new Error('no such image') }} }}
let sign = 'before'
{piece.replace('process.platform', 'process_.platform')}
setUpSign()
process.stdout.write(JSON.stringify({{ calls, sign }}) + "\\n")
"""
    assert _node(script) == {
        "calls": ["Menu bar: the sign could not be set up: no such image"],
        "sign": None,
    }
