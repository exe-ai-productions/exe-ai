"""On Windows the title bar of the window suits the look.

The system draws the title bar there by its own setting: on a light Windows
it stood white over a dark look. Three parts carry the look's scheme, and
each is run for real here:

- the page says `dark`, `light` or — while the look follows the device —
  `system`, whenever that changes and not before the look the service keeps
  has arrived (`frontend/src/lib/zustand.svelte.js`),
- the bridge carries it on one channel (`fenster-electron/preload.js`),
- the shell hands it to the system as the theme of the window frame, keeps
  it beside the window's geometry and sets it again at its next start, before
  the window is built (`fenster-electron/main.js`). Only on Windows: on every
  other system nothing is set and nothing is kept.

The shell's functions are lifted out of the source by name and run in node
with thin stand-ins, the way the test of the frame colour does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.moduswahl import MODI
from tests.test_shell_frame_colour import (
    DARK,
    SHELL,
    SNOW,
    STATE,
    _bridge,
    _file_pieces,
    _piece,
    _run,
    _window_pieces,
)

SCHEMES = ["dark", "light", "system"]
NOT_A_SCHEME = ["", "Dark", "auto", "dunkel", DARK, None, 1, True, ["dark"]]
ELSEWHERE = ["darwin", "linux"]

# What the page says for each look the service takes. "auto" follows the
# device; the own gradient says it by its own brightness and is run apart.
SCHEME_OF = {
    "auto": "system",
    "hell": "light",
    "heaven": "light",
    "moune": "light",
    "snow": "light",
    "dunkel": "dark",
    "darkmatter": "dark",
}


def _scheme_pieces() -> str:
    return "\n".join([
        _piece(SHELL, r"\nfunction frameSchemeKeep\(scheme\) \{\n.*?\n\}\n", "frameSchemeKeep"),
        _piece(SHELL, r"\nfunction frameSchemeApply\(scheme\) \{\n.*?\n\}\n", "frameSchemeApply"),
        _piece(SHELL, r"\nipcMain\.on\('frame-scheme', .*?\n\}\)\n", "the channel"),
    ])


def _start_pieces() -> str:
    return "\n".join([
        _piece(SHELL, r"\nconst FRAME_SCHEMES = [^\n]+\n", "FRAME_SCHEMES"),
        _piece(SHELL, r"\nfunction frameSchemeApply\(scheme\) \{\n.*?\n\}\n", "frameSchemeApply"),
        _window_pieces(),
    ])


def _page_pieces() -> str:
    painter = _piece(STATE, r"\nexport function rahmenNeuZeichnen\(modus\) \{\n.*?\n\}\n", "rahmenNeuZeichnen")
    return "\n".join([
        _piece(STATE, r"\nconst DARK_LOOKS = [^\n]+\n", "DARK_LOOKS"),
        _piece(STATE, r"\nlet frameSchemeTold = ''\n", "frameSchemeTold"),
        _piece(STATE, r"\nlet keptLookArrived = false\n", "keptLookArrived"),
        _piece(STATE, r"\nexport function darstellungAnwenden\(wert\) \{\n.*?\n\}\n", "darstellungAnwenden")
        .replace("export function", "function"),
        _piece(STATE, r"\nfunction frameSchemeToShell\(scheme\) \{\n.*?\n\}\n", "frameSchemeToShell"),
        painter.replace("export function", "function"),
    ])


# A theme that starts where the system has it and notes every time it is set.
THEME = """
const set = []
const nativeTheme = {
  source: 'system',
  get themeSource() { return this.source },
  set themeSource(scheme) { this.source = scheme; set.push(scheme) },
}
"""


def _heard(
    tmp_path: Path, schemes: list[Any], *, platform: str = "win32", sender: str = "page",
    window: str = "alive", before: str | None = None, first: str = "",
) -> Any:
    """Run `first`, then say each scheme on the channel; hand back how the
    theme was set, what the shell logged and what the window file holds
    afterwards."""
    file = tmp_path / "fenster.json"
    if before is not None:
        file.write_text(before, encoding="utf-8")
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
const logged = []
const print = console.log
console.log = (...words) => logged.push(words.join(' '))
let writes = 0
const write = fs.writeFileSync
fs.writeFileSync = (...args) => {{ writes += 1; return write(...args) }}
{THEME}
;(function (process) {{
{_file_pieces()}
{_scheme_pieces()}
{first}
for (const scheme of {json.dumps(schemes)}) heard['frame-scheme']({{ sender: {sender} }}, scheme)
}})({{ platform: {json.dumps(platform)} }})
const kept = fs.existsSync(geometriedatei()) ? JSON.parse(fs.readFileSync(geometriedatei(), 'utf8')) : null
print(JSON.stringify({{ set, logged, kept, writes, source: nativeTheme.source }}))
"""
    return _run(script)


# --- the shell sets the theme of the frame, on Windows ----------------------


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_on_windows_the_frame_takes_the_scheme_of_the_look(tmp_path, scheme):
    out = _heard(tmp_path, [scheme])
    assert out["set"] == [scheme]
    assert out["logged"] == [f"Window frame: {scheme}"]
    assert out["kept"] == {"scheme": scheme}


def test_a_look_that_follows_the_device_leaves_the_frame_to_the_system(tmp_path):
    """A forced theme would also be what the page is told the device
    prefers; the frame goes back to the system and that is kept."""
    out = _heard(tmp_path, ["dark", "system"])
    assert out["set"] == ["dark", "system"]
    assert out["source"] == "system"
    assert out["kept"] == {"scheme": "system"}


def test_a_frame_already_on_the_scheme_is_not_set_again(tmp_path):
    """The system starts on `system`: saying it sets nothing, and it is
    still kept for the next start. A scheme said twice is written once."""
    first = _heard(tmp_path, ["system"])
    assert first["set"] == [] and first["logged"] == []
    assert first["kept"] == {"scheme": "system"}
    twice = _heard(tmp_path, ["dark", "dark"], before="{}")
    assert twice["set"] == ["dark"] and twice["writes"] == 1


@pytest.mark.parametrize("platform", ELSEWHERE)
@pytest.mark.parametrize("scheme", SCHEMES)
def test_elsewhere_nothing_is_set_and_nothing_is_kept(tmp_path, platform, scheme):
    out = _heard(tmp_path, [scheme], platform=platform)
    assert out == {"set": [], "logged": [], "kept": None, "writes": 0, "source": "system"}


@pytest.mark.parametrize("value", NOT_A_SCHEME)
def test_only_the_three_schemes_are_taken(tmp_path, value):
    out = _heard(tmp_path, [value])
    assert out["set"] == [] and out["kept"] is None


@pytest.mark.parametrize(("sender", "window"), [("other", "alive"), ("page", "destroyed"), ("page", "none")])
def test_the_channel_hears_only_the_main_window(tmp_path, sender, window):
    out = _heard(tmp_path, ["dark"], sender=sender, window=window)
    assert out["set"] == [] and out["kept"] is None


# --- the scheme stands beside the colour and the geometry -------------------


def test_keeping_the_scheme_leaves_place_and_colour_alone(tmp_path):
    held = {"x": 10, "y": 20, "width": 900, "height": 700, "colour": DARK}
    out = _heard(tmp_path, ["dark"], before=json.dumps(held))
    assert out["kept"] == {**held, "scheme": "dark"}


def _file(tmp_path: Path, body: str, before: dict[str, Any]) -> Any:
    file = tmp_path / "fenster.json"
    file.write_text(json.dumps(before), encoding="utf-8")
    script = f"""
const fs = require('fs')
const geometriedatei = () => {json.dumps(str(file))}
{_file_pieces()}
{body}
console.log(fs.readFileSync(geometriedatei(), 'utf8'))
"""
    return _run(script)


def test_writing_the_geometry_keeps_the_scheme_and_the_colour(tmp_path):
    held = {"x": 1, "y": 2, "width": 3, "height": 4, "colour": DARK, "scheme": "light"}
    moved = {"x": 50, "y": 60, "width": 1000, "height": 800}
    out = _file(tmp_path, f"geometrieSchreiben({{ getNormalBounds: () => ({json.dumps(moved)}) }})", held)
    assert out == {**moved, "colour": DARK, "scheme": "light"}


def test_keeping_a_colour_keeps_the_scheme(tmp_path):
    out = _file(tmp_path, "frameColourKeep('#CFE0BF')", {"colour": DARK, "scheme": "dark"})
    assert out == {"colour": "#cfe0bf", "scheme": "dark"}


@pytest.mark.parametrize("held", ["Dark", "auto", "", None, 1])
def test_a_file_that_holds_no_scheme_reads_as_none_and_writes_none(tmp_path, held):
    """The silence check: what is not a scheme is not carried into the next
    write of the place either."""
    moved = {"x": 5, "y": 6, "width": 700, "height": 500}
    body = f"""
if (frameSchemeRead() !== null) throw new Error('read a scheme')
geometrieSchreiben({{ getNormalBounds: () => ({json.dumps(moved)}) }})
"""
    assert _file(tmp_path, body, {"scheme": held}) == moved


# --- the start --------------------------------------------------------------


def _start(platform: str, kept: str | None, colour: str | None = None) -> Any:
    """Build the window; hand back what happened in order and the options."""
    script = f"""
const path = require('path')
const topbar = require({json.dumps(str(SHELL.parent / 'topbar.js'))})
const BREITE = 1280, HOEHE = 820, MIN_BREITE = 720, MIN_HOEHE = 480
function geometrieLesen() {{ return null }}
function geometrieSchreiben() {{}}
function frameColourRead() {{ return {json.dumps(colour)} }}
function frameSchemeRead() {{ return {json.dumps(kept)} }}
function sidebarFoldedRead() {{ return false }}
let dienstFehlgeschlagen = false
function fehlstartSchreiben() {{}}
let fenster = null
let hilfefenster = null
const app = {{ quit() {{}} }}
const steps = []
const print = console.log
console.log = (...words) => steps.push('log ' + words.join(' '))
const nativeTheme = {{
  source: 'system',
  get themeSource() {{ return this.source }},
  set themeSource(scheme) {{ this.source = scheme; steps.push('theme ' + scheme) }},
  get shouldUseDarkColors() {{ return this.source === 'dark' }},
}}
let options = null
class BrowserWindow {{
  constructor(given) {{ options = given; steps.push('window'); this.webContents = {{ on() {{}} }} }}
  loadFile() {{}}
  on() {{}}
}}
function istHandbuch() {{ return false }}
;(function (process) {{
{_start_pieces()}
fensterBauen()
}})({{ platform: {json.dumps(platform)} }})
print(JSON.stringify({{ steps, options }}))
"""
    return _run(script)


def _bar(platform: str) -> str:
    """The log line that names the top bar the window was built with: the
    options themselves are tested in tests/test_top_bar.py, here only that the
    start logs them after the ground and before the window."""
    options = '{"titleBarStyle":"hidden","trafficLightPosition":{"x":18,"y":36}}' if platform == "darwin" else "{}"
    return f"Window top bar: {options}"


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_what_was_kept_is_what_the_next_start_sets(tmp_path, scheme):
    """The real read and the real setter on a real file, as the start
    joins them: the scheme a run kept is the one the next run sets, and
    setting it writes nothing."""
    kept = _heard(tmp_path, [scheme])["kept"]
    out = _heard(tmp_path, [], before=json.dumps(kept), first="frameSchemeApply(frameSchemeRead())")
    assert out["set"] == [scheme] and out["writes"] == 0
    elsewhere = _heard(
        tmp_path, [], platform="darwin", before=json.dumps(kept), first="frameSchemeApply(frameSchemeRead())",
    )
    assert elsewhere["set"] == []


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_on_windows_the_start_sets_the_kept_scheme_before_the_window(scheme):
    """And before the ground is chosen: with no colour kept, the ground is the
    one of the look Auto on the scheme just set."""
    out = _start("win32", scheme)
    ground = DARK if scheme == "dark" else SNOW
    assert out["steps"] == [
        f"theme {scheme}", f"log Window frame: {scheme}", f"log Window ground: {ground}", f"log {_bar('win32')}", "window",
    ]


@pytest.mark.parametrize("kept", ["system", None])
def test_on_windows_a_start_without_a_forced_scheme_sets_nothing(kept):
    assert _start("win32", kept)["steps"] == [f"log Window ground: {SNOW}", f"log {_bar('win32')}", "window"]


@pytest.mark.parametrize("platform", ELSEWHERE)
def test_elsewhere_the_start_sets_nothing(platform):
    assert _start(platform, "dark")["steps"] == [f"log Window ground: {SNOW}", f"log {_bar(platform)}", "window"]


def test_the_start_window_keeps_its_ground_and_takes_no_title_bar_option():
    """The silence check: the kept colour is the window's ground as before,
    and the window is still the system's own — no title bar of its own."""
    out = _start("win32", "dark", colour=DARK)
    assert out["options"]["backgroundColor"] == DARK
    assert out["steps"][-3] == f"log Window ground: {DARK}"
    assert not {"titleBarStyle", "titleBarOverlay", "frame"} & set(out["options"])


# --- the bridge -------------------------------------------------------------


def test_the_bridge_sends_the_scheme_on_its_own_channel():
    assert _bridge("frameScheme('dark')") == [["frame-scheme", "dark"]]
    assert _bridge("frameScheme(undefined)") == [["frame-scheme", ""]]


# --- the page ---------------------------------------------------------------


ARRIVES = ["<the kept look arrives>"]


def _said(
    looks: list[list[Any]], shell: str = "{ frameScheme: (scheme) => said.push(scheme) }", *, arrived: bool = True,
) -> Any:
    """Run the painter once per entry — the name it is called with, the look
    that resolves to, the brightness of the own gradient and, as an optional
    fourth, whether "auto" is on (the root then carries no `data-modus`) —
    and hand back what the shell was told. The look the service keeps has
    arrived before the first entry, through the function the page takes it
    with; with `arrived=False` it arrives where the entry `ARRIVES` stands."""
    if arrived:
        looks = [ARRIVES, *looks]
    script = f"""
const said = []
const window = {{ exeHuelle: {shell} }}
const RAHMEN_FELDER_MAX = 8
const EIGENER_VERLAUF = 'eigen'
const zustand = {{ verlauf: {{}} }}
let resolved = ''
let brightness = 0
let named = true
const lookFuer = () => resolved
const tonVorgabeFuer = () => 0
const vorgabenFuer = () => ['#101010', '#202020']
const farbtonDrehen = (colour) => colour
const luma = () => brightness
function setzeFallsAnders() {{}}
function nimmFallsDa() {{}}
function frameColourToShell() {{}}
function codefarbenSetzen() {{}}
function blasenfarbeSetzen() {{}}
function chatlayoutSetzen() {{}}
const chatlayoutAusGespeichert = () => ({{}})
const document = {{ documentElement: {{
  style: {{}}, getAttribute: () => null, hasAttribute: (name) => name === 'data-modus' && named,
  setAttribute() {{}}, removeAttribute() {{}},
}} }}
{_page_pieces()}
for (const [modus, look, bright, auto] of {json.dumps(looks)}) {{
  if (modus === {json.dumps(ARRIVES[0])}) {{ darstellungAnwenden({{}}); continue }}
  resolved = look; brightness = bright; named = !(auto || modus === 'auto')
  rahmenNeuZeichnen(modus)
}}
console.log(JSON.stringify(said))
"""
    return _run(script)


def test_every_look_the_service_takes_has_a_scheme():
    """A look added later has to be given its scheme here, and in the page."""
    assert set(MODI) == set(SCHEME_OF) | {"eigen"}


@pytest.mark.parametrize("look", [look for look in SCHEME_OF if look != "auto"])
def test_a_fixed_look_says_its_scheme(look):
    assert _said([[look, look, 0]]) == [SCHEME_OF[look]]


@pytest.mark.parametrize("resolved", ["dunkel", "hell"])
def test_auto_says_system_whatever_it_resolves_to(resolved):
    assert _said([["auto", resolved, 0]]) == ["system"]


def test_the_own_gradient_says_its_scheme_by_its_brightness():
    assert _said([["eigen", "eigen", 0.1]]) == ["dark"]
    assert _said([["eigen", "eigen", 0.9]]) == ["light"]
    assert _said([["eigen", "eigen", 0.1], ["eigen", "eigen", 0.9]]) == ["dark", "light"]


def test_the_same_look_under_auto_is_said_again():
    """Exe and "auto" on a dark device draw the same look; the frame has to
    go back to the system all the same, and to dark again afterwards."""
    looks = [["dunkel", "dunkel", 0], ["auto", "dunkel", 0], ["dunkel", "dunkel", 0]]
    assert _said(looks) == ["dark", "system", "dark"]


@pytest.mark.parametrize("look", ["dunkel", "hell"])
def test_a_redraw_under_the_name_of_the_look_auto_stands_on_still_says_system(look):
    """A change of the frame's gradient redraws under the look's own name
    while "auto" is on. That must not force a scheme: the look could no
    longer follow the device."""
    assert _said([["auto", look, 0], [look, look, 0, True]]) == ["system"]
    assert _said([[look, look, 0, True]]) == ["system"]


@pytest.mark.parametrize(("kept", "scheme"), [("heaven", "light"), ("dunkel", "dark"), ("auto", "system")])
def test_the_default_look_the_page_starts_on_is_not_said(kept, scheme):
    """The page draws the default look first and the kept one once the
    service has answered. Only the kept one is said — also where it is the
    default itself — or the title bar would turn over at every start."""
    resolved = "dunkel" if kept == "auto" else kept
    start = [["dunkel", "dunkel", 0], ARRIVES, [kept, resolved, 0]]
    assert _said(start, arrived=False) == [scheme]


def test_a_read_that_never_arrives_says_nothing():
    assert _said([["dunkel", "dunkel", 0], ["heaven", "heaven", 0]], arrived=False) == []


def test_a_scheme_that_stays_is_not_said_again():
    looks = [["dunkel", "dunkel", 0], ["darkmatter", "darkmatter", 0], ["dunkel", "dunkel", 0]]
    assert _said(looks) == ["dark"]
    assert _said([["hell", "hell", 0], ["moune", "moune", 0], ["heaven", "heaven", 0]]) == ["light"]


@pytest.mark.parametrize("shell", ["undefined", "{}", "{ frameScheme: 'no function' }"])
def test_without_a_shell_nothing_is_said_and_nothing_fails(shell):
    assert _said([["dunkel", "dunkel", 0], ["auto", "hell", 0]], shell=shell) == []
