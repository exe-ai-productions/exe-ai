"""The window opens on the frame colour of the look shown last.

The shell's window is there before any page is, and it used to open dark
whatever look the interface then showed — a light look started on a dark
window with a dark splash and jumped. Four parts carry the colour, and each
is run for real here:

- the page tells the shell the solid tone of its frame, at its start and on
  every change of the look (`frontend/src/lib/zustand.svelte.js`),
- the bridge carries it on one channel (`fenster-electron/preload.js`),
- the shell takes `#rrggbb` and nothing else, keeps it beside the window's
  geometry and builds its next window on it (`fenster-electron/main.js`),
- the splash takes it as its ground and picks its ink by the brightness of
  that ground (`fenster-electron/anzeige/index.html`).

`main.js` requires electron and cannot run outside a window, so its functions
are lifted out of the source by name and run in node with thin stand-ins,
the way the shell's other test modules do; the file the colour is kept in is
a real one in a temporary folder.
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
SHELL = ROOT / "fenster-electron" / "main.js"
PRELOAD = ROOT / "fenster-electron" / "preload.js"
SPLASH = ROOT / "fenster-electron" / "anzeige" / "index.html"
STATE = ROOT / "frontend" / "src" / "lib" / "zustand.svelte.js"
SHEET = ROOT / "frontend" / "src" / "stil" / "global.css"

MOUNE = "#cfe0bf"
PEARL = "#d9cfba"
SNOW = "#e2e2e2"
DARK = "#151514"

# What the channel must turn away: no colour at all, a short or a long hex,
# a named colour, and a colour with something behind it.
NOT_A_COLOUR = ["", "red", "#fff", "#cfe0b", "#cfe0bf00", "#cfe0bg", "#cfe0bf;x", " #cfe0bf", None, 13623487]


def _run(script: str) -> Any:
    if not shutil.which("node"):
        pytest.skip("node is missing")
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def _piece(source: Path, pattern: str, name: str) -> str:
    match = re.search(pattern, source.read_text(encoding="utf-8"), re.S)
    assert match, f"{name} not found"
    return match.group(0).strip() + "\n"


# The pieces under test, by name — outside the scripts below, because an
# f-string expression may not carry a backslash.


def _file_pieces() -> str:
    return "\n".join([
        _piece(SHELL, r"\nfunction geometrieSchreiben\(fenster\) \{\n.*?\n\}\n", "geometrieSchreiben"),
        _piece(SHELL, r"\nconst FRAME_COLOUR = [^\n]+\n", "FRAME_COLOUR"),
        _piece(SHELL, r"\nfunction windowFileRead\(\) \{\n.*?\n\}\n", "windowFileRead"),
        _piece(SHELL, r"\nfunction frameColourRead\(\) \{\n.*?\n\}\n", "frameColourRead"),
        _piece(SHELL, r"\nfunction frameColourKeep\(colour\) \{\n.*?\n\}\n", "frameColourKeep"),
        # The frame's scheme shares the file; writing the geometry reads it.
        _piece(SHELL, r"\nconst FRAME_SCHEMES = [^\n]+\n", "FRAME_SCHEMES"),
        _piece(SHELL, r"\nfunction frameSchemeRead\(\) \{\n.*?\n\}\n", "frameSchemeRead"),
        # The folded sidebar shares the file too; writing the geometry reads it.
        _piece(SHELL, r"\nfunction sidebarFoldedRead\(\) \{\n.*?\n\}\n", "sidebarFoldedRead"),
    ])


def _channel_piece() -> str:
    return _piece(SHELL, r"\nipcMain\.on\('frame-colour', .*?\n\}\)\n", "the channel")


def _window_pieces() -> str:
    return "\n".join([
        _piece(SHELL, r"\nfunction menuBarOptions\(\) \{\n.*?\n\}\n", "menuBarOptions"),
        _piece(SHELL, r"\nconst AUTO_GROUND_DARK = [^\n]+\n", "AUTO_GROUND_DARK"),
        _piece(SHELL, r"\nconst AUTO_GROUND_LIGHT = [^\n]+\n", "AUTO_GROUND_LIGHT"),
        _piece(SHELL, r"\nfunction autoGround\(\) \{\n.*?\n\}\n", "autoGround"),
        _piece(SHELL, r"\nfunction fensterBauen\(\) \{\n.*?\n\}\n", "fensterBauen"),
    ])


# --- the shell keeps the colour beside the geometry -------------------------


def _kept(tmp_path: Path, body: str, *, before: str | None = None) -> Any:
    """Run `body` against a real window file; hand back what it returns and
    what the file holds afterwards (None where there is none)."""
    file = tmp_path / "fenster.json"
    if before is not None:
        file.write_text(before, encoding="utf-8")
    script = f"""
const fs = require('fs')
const geometriedatei = () => {json.dumps(str(file))}
{_file_pieces()}
const result = (() => {{
{body}
}})()
const file = fs.existsSync(geometriedatei()) ? fs.readFileSync(geometriedatei(), 'utf8') : null
console.log(JSON.stringify({{ result, file }}))
"""
    return _run(script)


def test_a_colour_is_kept_and_read_again(tmp_path):
    out = _kept(tmp_path, f"frameColourKeep({json.dumps(MOUNE)}); return frameColourRead()")
    assert out["result"] == MOUNE
    assert json.loads(out["file"]) == {"colour": MOUNE}


def test_the_colour_is_kept_in_lower_case(tmp_path):
    out = _kept(tmp_path, "frameColourKeep('#CFE0BF'); return frameColourRead()")
    assert out["result"] == MOUNE
    assert json.loads(out["file"]) == {"colour": MOUNE}


def test_the_colour_stands_beside_the_geometry_and_leaves_it_alone(tmp_path):
    """The silence check for the window's place: its four numbers stay."""
    place = {"x": 40, "y": 60, "width": 1300, "height": 900}
    out = _kept(tmp_path, f"frameColourKeep({json.dumps(PEARL)})", before=json.dumps(place))
    assert json.loads(out["file"]) == {**place, "colour": PEARL}


def test_writing_the_geometry_keeps_the_colour(tmp_path):
    """Closing the window writes its place; the colour in the same file must
    still be there for the next start."""
    out = _kept(
        tmp_path,
        "geometrieSchreiben({ getNormalBounds: () => ({ x: 1, y: 2, width: 900, height: 700 }) })",
        before=json.dumps({"x": 40, "y": 60, "width": 1300, "height": 900, "colour": MOUNE}),
    )
    assert json.loads(out["file"]) == {"x": 1, "y": 2, "width": 900, "height": 700, "colour": MOUNE}


def test_the_place_is_read_as_before_from_a_file_that_also_holds_the_colour(tmp_path):
    """The silence check for reading: the four numbers come back and nothing
    else — what is handed back goes into the window's options as it is."""
    file = tmp_path / "fenster.json"
    file.write_text(
        json.dumps({"x": 40, "y": 60, "width": 1300, "height": 900, "colour": MOUNE}), encoding="utf-8"
    )
    reader = _piece(SHELL, r"\nfunction geometrieLesen\(\) \{\n.*?\n\}\n", "geometrieLesen")
    script = f"""
const fs = require('fs')
const MIN_BREITE = 720, MIN_HOEHE = 480
const screen = {{ getAllDisplays: () => [{{ workArea: {{ x: 0, y: 0, width: 2560, height: 1440 }} }}] }}
const geometriedatei = () => {json.dumps(str(file))}
{reader}
console.log(JSON.stringify(geometrieLesen()))
"""
    assert _run(script) == {"x": 40, "y": 60, "width": 1300, "height": 900}


def test_writing_the_geometry_without_a_colour_writes_the_place_alone(tmp_path):
    """The silence check: a window that never heard a colour writes the file
    it always wrote."""
    out = _kept(
        tmp_path,
        "geometrieSchreiben({ getNormalBounds: () => ({ x: 1, y: 2, width: 900, height: 700 }) })",
    )
    assert json.loads(out["file"]) == {"x": 1, "y": 2, "width": 900, "height": 700}


@pytest.mark.parametrize("value", NOT_A_COLOUR)
def test_only_rrggbb_is_kept(tmp_path, value):
    before = json.dumps({"x": 40, "y": 60, "width": 1300, "height": 900, "colour": DARK})
    out = _kept(tmp_path, f"frameColourKeep({json.dumps(value)}); return frameColourRead()", before=before)
    assert out["result"] == DARK
    assert out["file"] == before


def test_nothing_is_written_where_there_is_no_file_and_no_colour(tmp_path):
    out = _kept(tmp_path, "frameColourKeep('red'); return frameColourRead()")
    assert out == {"result": None, "file": None}


def test_the_same_colour_is_not_written_twice(tmp_path):
    """A look that stays tells its colour again at every start; the file is
    left as it stands — byte for byte, spacing included."""
    before = '{ "colour": "#cfe0bf",   "x": 1, "y": 2, "width": 900, "height": 700 }'
    out = _kept(tmp_path, f"frameColourKeep({json.dumps(MOUNE)})", before=before)
    assert out["file"] == before


@pytest.mark.parametrize("held", [
    '{"colour": "url(javascript:alert(1))"}', '{"colour": 7}', '{"colour": "#fff"}',
    '["#cfe0bf"]', "not json", "null",
])
def test_a_file_that_holds_no_colour_reads_as_none(tmp_path, held):
    """Whatever stands in the file — edited by hand, cut off, another shape —
    only a colour comes out of it, or nothing."""
    out = _kept(tmp_path, "return frameColourRead()", before=held)
    assert out["result"] is None


# --- the channel hears the main window's page and no other ------------------


def _channel(tmp_path: Path, *, sender: str, window: str = "alive") -> Any:
    file = tmp_path / "fenster.json"
    windows = {
        "alive": "{ isDestroyed: () => false, webContents: page }",
        "destroyed": "{ isDestroyed: () => true, webContents: page }",
        "none": "null",
    }
    script = f"""
const fs = require('fs')
const geometriedatei = () => {json.dumps(str(file))}
const heard = {{}}
const ipcMain = {{ on: (channel, listener) => {{ heard[channel] = listener }} }}
const page = {{ id: 1 }}
const other = {{ id: 2 }}
let fenster = {windows[window]}
{_file_pieces()}
{_channel_piece()}
heard['frame-colour']({{ sender: {sender} }}, {json.dumps(MOUNE)})
console.log(JSON.stringify({{ channels: Object.keys(heard), kept: frameColourRead() }}))
"""
    return _run(script)


def test_the_channel_keeps_what_the_main_window_says(tmp_path):
    assert _channel(tmp_path, sender="page") == {"channels": ["frame-colour"], "kept": MOUNE}


def test_the_channel_does_not_hear_another_window(tmp_path):
    assert _channel(tmp_path, sender="other")["kept"] is None


@pytest.mark.parametrize("window", ["none", "destroyed"])
def test_the_channel_keeps_nothing_without_a_main_window(tmp_path, window):
    assert _channel(tmp_path, sender="page", window=window)["kept"] is None


# --- the window is built on the colour --------------------------------------


def _window(kept: str | None, *, dark: bool = False) -> Any:
    script = f"""
const path = require('path')
const topbar = require({json.dumps(str(SHELL.parent / 'topbar.js'))})
const nativeTheme = {{ shouldUseDarkColors: {json.dumps(dark)} }}
const BREITE = 1280, HOEHE = 820, MIN_BREITE = 720, MIN_HOEHE = 480
function geometrieLesen() {{ return null }}
function geometrieSchreiben() {{}}
function frameColourRead() {{ return {json.dumps(kept)} }}
function frameSchemeRead() {{ return null }}
function sidebarFoldedRead() {{ return false }}
function frameSchemeApply() {{ return false }}
let dienstFehlgeschlagen = false
function fehlstartSchreiben() {{}}
let fenster = null
let hilfefenster = null
const app = {{ quit() {{}} }}
const built = []
const loaded = []
const logged = []
const print = console.log
console.log = (...words) => logged.push(words.join(' '))
class BrowserWindow {{
  constructor(options) {{ built.push(options); this.webContents = {{ on() {{}} }} }}
  loadFile(file, options) {{ loaded.push([path.basename(file), options === undefined ? null : options]) }}
  on() {{}}
}}
function istHandbuch() {{ return false }}
{_window_pieces()}
fensterBauen()
print(JSON.stringify({{ options: built[0], loaded, logged }}))
"""
    return _run(script)


def _the_ground_is_named(out: Any, colour: str) -> None:
    """The first line of the log names the ground, the second the top bar the
    window was built with (the options themselves: tests/test_top_bar.py)."""
    first, second = out["logged"]
    assert first == f"Window ground: {colour}"
    assert second.startswith("Window top bar: {")


@pytest.mark.parametrize("colour", [MOUNE, PEARL, DARK])
def test_the_window_and_the_splash_start_on_the_kept_colour(colour):
    """And the shell's log names the ground it opened on."""
    out = _window(colour)
    assert out["options"]["backgroundColor"] == colour
    assert out["loaded"] == [["index.html", {"query": {"ground": colour}}]]
    _the_ground_is_named(out, colour)


def test_without_a_kept_colour_the_window_opens_on_the_colour_of_auto():
    """The first start: the ground of window and splash is the frame tone of
    the look Auto — Exe where the system is dark, Snow where it is light."""
    for dark, colour in ((True, DARK), (False, SNOW)):
        out = _window(None, dark=dark)
        assert out["options"]["backgroundColor"] == colour
        assert out["loaded"] == [["index.html", {"query": {"ground": colour}}]]
        _the_ground_is_named(out, colour)


def test_a_kept_colour_wins_over_the_system_and_the_system_only_decides_without_one():
    """Silence check: the kept colour is the ground whichever way the system
    leans, so a chosen look is not painted over by Auto."""
    for dark in (True, False):
        assert _window(MOUNE, dark=dark)["options"]["backgroundColor"] == MOUNE


def test_the_two_grounds_of_auto_are_the_frame_tones_of_exe_and_snow():
    """The shell's two constants and the stylesheet's solid frame tones are
    one pair of colours: Auto shows Snow on a light device (the root rule)
    and Exe on a dark one (the media query)."""
    shell = SHELL.read_text(encoding="utf-8")
    sheet = SHEET.read_text(encoding="utf-8")
    dark = re.search(r"^const AUTO_GROUND_DARK = '(#[0-9a-f]{6})'$", shell, re.M)
    light = re.search(r"^const AUTO_GROUND_LIGHT = '(#[0-9a-f]{6})'$", shell, re.M)
    assert dark and light
    assert dark.group(1) == DARK
    assert light.group(1) == SNOW
    # Snow's tone is the one the root rule without a chosen look carries.
    snow_block = re.search(r":root\[data-modus='snow'\],\s*:root:not\(\[data-modus\]\) \{(.*?)\n\}", sheet, re.S)
    assert snow_block and f"--bg-seite: {SNOW}" in snow_block.group(1)
    # Exe's tone is the one the dark-device media query hands to Auto.
    dark_block = re.search(r"@media \(prefers-color-scheme: dark\) \{\s*:root:not\([^{]*\{(.*?)\n  \}", sheet, re.S)
    assert dark_block and f"--bg-seite: {DARK}" in dark_block.group(1)


# --- the bridge --------------------------------------------------------------


def _bridge(call: str) -> Any:
    script = f"""
const Module = require('module')
const exposed = {{}}
const sent = []
const electron = {{
  contextBridge: {{ exposeInMainWorld: (name, api) => {{ exposed[name] = api }} }},
  ipcRenderer: {{
    invoke: () => Promise.resolve(''), on: () => {{}}, removeListener: () => {{}},
    send: (...args) => sent.push(args),
  }},
}}
const load = Module._load
Module._load = function (request, ...rest) {{
  return request === 'electron' ? electron : load.call(this, request, ...rest)
}}
require({json.dumps(str(PRELOAD))})
exposed.exeHuelle.{call}
console.log(JSON.stringify(sent))
"""
    return _run(script)


def test_the_bridge_sends_the_colour_on_its_own_channel():
    assert _bridge(f"frameColour({json.dumps(MOUNE)})") == [["frame-colour", MOUNE]]


def test_the_bridge_sends_a_string_whatever_the_page_hands_it():
    """What crosses is a string; whether it is a colour is the shell's call."""
    assert _bridge("frameColour(undefined)") == [["frame-colour", ""]]
    assert _bridge("frameColour({ toString: () => 'x' })") == [["frame-colour", "x"]]


# --- the splash --------------------------------------------------------------


def _splash_script() -> str:
    match = re.search(r"<script>(.*?)</script>", SPLASH.read_text(encoding="utf-8"), re.S)
    assert match, "the splash has no script"
    return match.group(1)


def _splash(search: str) -> dict[str, str]:
    script = f"""
const set = {{}}
const location = {{ search: {json.dumps(search)} }}
const document = {{ documentElement: {{ style: {{ setProperty: (name, value) => {{ set[name] = value }} }} }} }};
{_splash_script()}
console.log(JSON.stringify(set))
"""
    return _run(script)


@pytest.mark.parametrize("ground, ink, scheme", [
    (MOUNE, "#1a1a18", "light"),
    (PEARL, "#1a1a18", "light"),
    ("#dbe5f3", "#1a1a18", "light"),
    (DARK, "#ecebe6", "dark"),
    ("#1a1538", "#ecebe6", "dark"),
])
def test_the_splash_takes_the_ground_and_picks_its_ink_by_brightness(ground, ink, scheme):
    assert _splash("?ground=" + ground.replace("#", "%23")) == {
        "--ground": ground, "--ink": ink, "color-scheme": scheme,
    }


@pytest.mark.parametrize("search", [
    "", "?ground=", "?ground=red", "?ground=%23fff", "?ground=%23cfe0bf%3Bbackground%3Aurl(x)",
    "?other=%23cfe0bf",
])
def test_the_splash_stays_as_it_is_without_a_colour(search):
    """The silence check: no address, an empty one, or anything that is not
    `#rrggbb` sets nothing — the dark ground and the light ink stand."""
    assert _splash(search) == {}


def test_the_splash_draws_ground_and_ink_from_what_the_script_sets():
    """With nothing set the two fall back to the dark ground and the light
    ink; the wordmark is drawn in the ink, and the words stay."""
    page = SPLASH.read_text(encoding="utf-8")
    assert "background: var(--ground, #141413); color: var(--ink, #ecebe6);" in page
    assert 'stroke="currentColor"' in page
    assert "#ecebe6" not in page.split("</script>", 1)[1]
    assert "<p>Starting …</p>" in page


def test_the_splash_draws_the_mark_as_strong_as_the_start_page():
    """The mark of the splash and the wordmark of the start page stand at the
    same half strength, so the one does not jump when the other follows."""
    splash = SPLASH.read_text(encoding="utf-8")
    assert "svg { display: block; margin: 0 auto 14px; opacity: 0.5; }" in splash
    page = (ROOT / "frontend" / "src" / "App.svelte").read_text(encoding="utf-8")
    rule = page.split(".marke .wortmarke {", 1)[1].split("}", 1)[0]
    assert "opacity: 0.5;" in rule


def test_the_splash_and_the_frame_agree_on_ink_and_threshold():
    """One rule in two places that cannot share a file: the splash is a bare
    page of the shell, the frame's ink is drawn by the interface."""
    state = STATE.read_text(encoding="utf-8")
    assert "> 0.45" in state and "hell ? '#1a1a18' : '#ecebe6'" in state
    splash = _splash_script()
    assert "> 0.45" in splash and "light ? '#1a1a18' : '#ecebe6'" in splash
    weights = "0.2126 * r + 0.7152 * g + 0.0722 * b"
    assert weights in state and weights in splash


# --- the page tells the shell ------------------------------------------------


def _teller() -> str:
    return "\n".join([
        _piece(STATE, r"\nlet frameLookTold = ''\n", "frameLookTold"),
        _piece(STATE, r"\nfunction frameColourToShell\(look, drawn = null\) \{\n.*?\n\}\n", "frameColourToShell"),
    ])


def _told(shell: str, looks: list[list[str]]) -> Any:
    """Call the teller once per look, each with the value the sheet gives
    `--bg-seite` under it; hand back what the shell heard and how often the
    sheet was asked."""
    script = f"""
const told = []
let asked = 0
const window = {{ exeHuelle: {shell} }}
const looks = {json.dumps(looks)}
let now = ''
const document = {{ documentElement: {{}} }}
const getComputedStyle = () => {{
  asked += 1
  return {{ getPropertyValue: (name) => (name === '--bg-seite' ? now : '') }}
}}
{_teller()}
for (const [look, value] of looks) {{ now = value; frameColourToShell(look) }}
console.log(JSON.stringify({{ told, asked }}))
"""
    return _run(script)


SHELL_THAT_LISTENS = "{ frameColour: (colour) => told.push(colour) }"


def test_the_page_tells_the_frame_colour_of_its_look():
    assert _told(SHELL_THAT_LISTENS, [["moune", MOUNE]])["told"] == [MOUNE]


def test_a_change_of_the_look_is_told_and_a_look_that_stays_is_not():
    looks = [["moune", MOUNE], ["moune", MOUNE], ["hell", PEARL], ["hell", PEARL], ["moune", MOUNE]]
    assert _told(SHELL_THAT_LISTENS, looks)["told"] == [MOUNE, PEARL, MOUNE]


def test_a_look_that_stays_does_not_ask_the_sheet_again():
    """Dragging on the own gradient redraws the frame per pointer event;
    reading the computed style each time would recalculate the styles."""
    out = _told(SHELL_THAT_LISTENS, [["eigen:dunkel", DARK]] * 40)
    assert out == {"told": [DARK], "asked": 1}


def test_the_own_gradient_tells_again_when_it_turns_light():
    looks = [["eigen:dunkel", DARK], ["eigen:dunkel", DARK], ["eigen:hell", PEARL]]
    assert _told(SHELL_THAT_LISTENS, looks)["told"] == [DARK, PEARL]


def test_the_colour_is_told_as_the_shell_takes_it():
    """As the sheet writes it — with room around it, in capitals — it still
    reaches the shell as plain lower-case `#rrggbb`."""
    assert _told(SHELL_THAT_LISTENS, [["moune", "  #CFE0BF "]])["told"] == [MOUNE]


@pytest.mark.parametrize("value", ["", "rgb(207, 224, 191)", "#fff", "var(--bg)", "transparent"])
def test_what_is_not_a_hex_colour_is_not_told(value):
    """And the look is not taken as told: the next redraw asks again."""
    out = _told(SHELL_THAT_LISTENS, [["moune", value], ["moune", MOUNE]])
    assert out == {"told": [MOUNE], "asked": 2}


@pytest.mark.parametrize("shell", ["undefined", "{}", "{ frameColour: 'no function' }"])
def test_without_a_shell_nothing_is_told_and_nothing_fails(shell):
    """The silence check: in a browser there is no bridge at all, and an
    older shell has one without this call. The sheet is not even asked."""
    assert _told(shell, [["moune", MOUNE], ["hell", PEARL]]) == {"told": [], "asked": 0}


def _painted(look: str) -> list[str]:
    """Run the painter itself and hand back what it did, in order."""
    painter = _piece(STATE, r"\nexport function rahmenNeuZeichnen\(modus\) \{\n.*?\n\}\n", "rahmenNeuZeichnen")
    script = f"""
const steps = []
const RAHMEN_FELDER_MAX = 8
const EIGENER_VERLAUF = 'eigen'
const zustand = {{ verlauf: {{}} }}
const lookFuer = (modus) => modus
const tonVorgabeFuer = () => 0
const vorgabenFuer = () => ['#101010', '#202020']
const farbtonDrehen = (colour) => colour
const luma = () => 0.1
function setzeFallsAnders() {{}}
function nimmFallsDa() {{}}
function frameColourToShell(told, drawn = null) {{ steps.push('told ' + told + (drawn ? ' drawn ' + drawn : '')) }}
const DARK_LOOKS = []
function frameSchemeToShell() {{}}
const document = {{ documentElement: {{
  style: {{}},
  getAttribute: () => null,
  hasAttribute: () => true,
  setAttribute: (name) => steps.push('set ' + name),
  removeAttribute: (name) => steps.push('removed ' + name),
}} }}
{painter.replace("export function", "function")}
rahmenNeuZeichnen({json.dumps(look)})
console.log(JSON.stringify(steps))
"""
    return _run(script)


def test_every_look_tells_its_colour_once_its_attributes_stand():
    """The sheet hangs the frame's tone on the look's attributes, so the
    colour is read after the painter has set or taken them — for a fixed
    look and for the own gradient alike. The own gradient names which of its
    two sets of values it stands on."""
    assert _painted("moune") == ["removed data-eigen", "told moune"]
    assert _painted("eigen") == [
        "set data-eigen", "told eigen:dunkel:#101010 drawn #101010"
    ]


def _own_gradient(states: list[dict | None], shell: str = SHELL_THAT_LISTENS) -> Any:
    """The painter and the real teller together: the own gradient is painted
    once per state (the user's choice stored under `eigen`, or none) and the
    result is what the shell heard and how often the sheet was asked."""
    painter = _piece(STATE, r"\nexport function rahmenNeuZeichnen\(modus\) \{\n.*?\n\}\n", "rahmenNeuZeichnen")
    script = f"""
const told = []
let asked = 0
const window = {{ exeHuelle: {shell} }}
const RAHMEN_FELDER_MAX = 8
const EIGENER_VERLAUF = 'eigen'
const zustand = {{ verlauf: {{}} }}
const lookFuer = (modus) => modus
const tonVorgabeFuer = () => 0
const vorgabenFuer = () => ['#101010', '#202020']
const farbtonDrehen = (colour, tone) => (tone ? '#' + colour.slice(1).split('').reverse().join('') : colour)
const luma = () => 0.1
function setzeFallsAnders() {{}}
function nimmFallsDa() {{}}
const DARK_LOOKS = []
function frameSchemeToShell() {{}}
const document = {{ documentElement: {{
  style: {{}},
  getAttribute: () => null,
  hasAttribute: () => true,
  setAttribute: () => {{}},
  removeAttribute: () => {{}},
}} }}
const getComputedStyle = () => {{
  asked += 1
  return {{ getPropertyValue: () => '#abcdef' }}
}}
{_teller()}
{painter.replace("export function", "function")}
for (const state of {json.dumps(states)}) {{
  zustand.verlauf = state ? {{ eigen: state }} : {{}}
  rahmenNeuZeichnen('eigen')
}}
console.log(JSON.stringify({{ told, asked }}))
"""
    return _run(script)


def test_the_own_gradient_tells_the_first_colour_of_its_gradient():
    """The shell opens on one colour; for the own gradient that is the first
    colour of the gradient as it is drawn, not the sheet's plain tone."""
    out = _own_gradient([{"farben": ["#ff2d95", "#2d95ff"]}])
    assert out == {"told": ["#ff2d95"], "asked": 0}


def test_the_own_gradient_tells_the_turned_first_colour():
    out = _own_gradient([{"farben": ["#102030", "#2d95ff"], "ton": 40}])
    assert out["told"] == ["#030201"]


def test_a_new_first_colour_is_told_again_and_an_unchanged_one_is_not():
    states = [
        {"farben": ["#ff2d95", "#2d95ff"]},
        {"farben": ["#ff2d95", "#00aa00"]},  # a later stop changes: same first colour
        {"farben": ["#ff2d95", "#00aa00"]},
        {"farben": ["#12ab34", "#00aa00"]},
    ]
    assert _own_gradient(states) == {"told": ["#ff2d95", "#12ab34"], "asked": 0}


def test_a_first_colour_that_is_no_hex_colour_is_not_told():
    """Silence probe: nothing is told for it, and the sheet's tone does not
    stand in for it — as before, the shell keeps what it had."""
    out = _own_gradient([{"farben": ["rebeccapurple", "#2d95ff"]}])
    assert out == {"told": [], "asked": 0}


def test_the_own_gradient_without_a_choice_tells_the_default_gradients_start():
    assert _own_gradient([None]) == {"told": ["#101010"], "asked": 0}


@pytest.mark.parametrize("shell", ["undefined", "{}"])
def test_the_own_gradient_without_a_shell_tells_nothing(shell):
    assert _own_gradient([{"farben": ["#ff2d95", "#2d95ff"]}], shell) == {"told": [], "asked": 0}


def test_every_look_gives_its_frame_a_colour_the_shell_takes():
    """The shell takes `#rrggbb` only, and the page reads the tone as the
    sheet writes it. A look whose frame tone were written any other way — or
    a tone registered as a typed property, which is handed out as `rgb()` —
    would leave the window on the colour of the look before."""
    sheet = re.sub(r"/\*.*?\*/", "", SHEET.read_text(encoding="utf-8"), flags=re.S)
    tones = re.findall(r"--bg-seite:\s*([^;]+);", sheet)
    assert len(tones) >= 5
    assert [tone for tone in tones if not re.fullmatch(r"#[0-9a-f]{6}", tone.strip())] == []
    assert not re.search(r"@property\s+--bg-seite\b", sheet)
