"""The columns give way when the window shrinks: the chat keeps its minimum
width, the right column folds first, then the left, and each comes back by
itself once the room returns (`frontend/src/lib/columnRoom.js`, the glue in
`columnRoom.svelte.js`, wired in `App.svelte`). The picture studio's columns
give way the same way; what it takes from the two columns and hands back
lives in `studioColumns.svelte.js`.

The arithmetic is run in node on the real file; the glue is compiled and run
against the real arithmetic with the two state objects it reads stubbed.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_agentenampel import _pruefordner

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend/src"
ARITHMETIC = FRONTEND / "lib/columnRoom.js"
GLUE = FRONTEND / "lib/columnRoom.svelte.js"
STUDIO_COLUMNS = FRONTEND / "lib/studioColumns.svelte.js"
APP = (FRONTEND / "App.svelte").read_text(encoding="utf-8")
HANDLE = (FRONTEND / "teile/Seitengriff.svelte").read_text(encoding="utf-8")
SHELL = (ROOT / "fenster-electron/main.js").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

SIGN_BAR, CHAT_AIR, CHAT_MIN = 52, 16, 420


def _constant(name: str) -> int:
    found = re.search(rf"export const {name} = (\d+)", ARITHMETIC.read_text(encoding="utf-8"))
    assert found, f"{name} is not a named constant of columnRoom.js"
    return int(found.group(1))


def _reference(case: dict) -> dict:
    """The rule, written out as the list of states tried in order."""
    left, right, last = case["left"], case["right"], case["last"]
    tries = [(left, right)]
    if last == "right":
        tries += [(False, right), (False, False)]
    else:
        tries += [(left, False), (False, False)]
    for l, r in tries:
        room = (
            case["windowWidth"]
            - (case["leftWidth"] if l else SIGN_BAR)
            - (case["rightWidth"] if r else SIGN_BAR)
            - CHAT_AIR
        )
        if room >= CHAT_MIN:
            return {"left": l, "right": r}
    return {"left": False, "right": False}


def _node(script: str, cwd: Path) -> dict:
    driver = cwd / "lauf.mjs"
    driver.write_text(script, encoding="utf-8")
    run = subprocess.run(
        ["node", driver.name], cwd=cwd, capture_output=True, text=True, timeout=120
    )
    assert run.returncode == 0, (run.stdout + run.stderr)[-2000:]
    return json.loads(run.stdout.split("---REPORT---", 1)[1].strip())


def test_the_minimum_width_and_the_signs_are_named_constants():
    assert _constant("CHAT_MIN") == CHAT_MIN
    assert _constant("CHAT_AIR") == CHAT_AIR
    assert _constant("SIGN_BAR") == SIGN_BAR


def test_the_seam_handle_and_the_folding_read_the_same_numbers():
    """One spelling of the three numbers: the handle that clamps a drag and
    the rule that folds a column cannot drift apart."""
    assert "from '../lib/columnRoom.js'" in HANDLE
    for name in ("CHAT_MIN", "CHAT_AIR", "SIGN_BAR"):
        assert f"const {name} =" not in HANDLE
    assert "from './columnRoom.js'" in GLUE.read_text(encoding="utf-8")


def test_the_app_folds_to_fit_and_watches_the_window():
    assert "import { fitColumns, watchWindowWidth } from './lib/columnRoom.svelte.js'" in APP
    assert "$effect(() => watchWindowWidth())" in APP
    assert "$effect(() => fitColumns())" in APP


def test_the_window_cannot_be_dragged_below_a_size_the_two_signs_and_the_chat_fit_in():
    """Electron holds the minimum size; the folded state — two bars of signs
    beside the chat's minimum — must fit inside it, or the rule could not be
    kept at the smallest window."""
    assert re.search(r"minWidth: MIN_BREITE, minHeight: MIN_HOEHE", SHELL)
    width = int(re.search(r"const MIN_BREITE = (\d+)", SHELL).group(1))
    assert 2 * SIGN_BAR + CHAT_AIR + CHAT_MIN <= width


def test_the_saved_layout_is_never_written_by_the_folding():
    """Folding for room is the window's doing, not the person's choice."""
    source = GLUE.read_text(encoding="utf-8")
    assert "layoutSpeichern" not in source
    assert "anzeige.js" not in source


@needs_node
def test_the_rule_matches_the_list_of_states_it_is_written_as():
    rng = random.Random(7)
    cases = [
        {
            "windowWidth": rng.randrange(760, 2200),
            "leftWidth": rng.randrange(285, 401),
            "rightWidth": rng.randrange(364, 901),
            "left": rng.random() < 0.8,
            "right": rng.random() < 0.8,
            "last": rng.choice([None, "left", "right"]),
        }
        for _ in range(2000)
    ]
    with _pruefordner() as folder:
        report = _node(
            f"""
import {{ openColumns }} from {ARITHMETIC.as_uri()!r}
const cases = {json.dumps(cases)}
console.log('---REPORT---' + JSON.stringify(cases.map((c) => openColumns(c))))
""",
            folder,
        )
    expected = [_reference(case) for case in cases]
    assert report == expected
    # Silence probe in the generated set: some cases fold nothing, some fold.
    assert any(c["left"] and c["right"] and got == {"left": True, "right": True}
               for c, got in zip(cases, report, strict=True))
    assert any(c["right"] and not got["right"] for c, got in zip(cases, report, strict=True))


_PROLOGUE = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const listeners = {}
globalThis.window = {
  innerWidth: 1440,
  addEventListener: (name, fn) => { listeners[name] = fn },
  removeEventListener: (name) => { delete listeners[name] },
}
writeFileSync('arbeitsleiste.mjs',
  "export const leiste = { offen: true, breite: 364, modul: 'cli' }\\n" +
  "export const zeitweiseOeffnen = () => { const was = leiste.offen; leiste.offen = true; return was }\\n")
writeFileSync('zustand.mjs',
  "export const zustand = { seitenleisteEingeklappt: false, seitenBreite: 314 }\\n" +
  "export const istSeitenleisteSchmal = () => window.innerWidth < 760\\n")
writeFileSync('columnRoom.mjs', readFileSync(%(arithmetic)r, 'utf-8'))
const build = (path, name, extra = []) => {
  let code = compileModule(readFileSync(path, 'utf-8'), { filename: name, generate: 'client' }).js.code
    .replace('./arbeitsleiste.svelte.js', './arbeitsleiste.mjs')
    .replace('./zustand.svelte.js', './zustand.mjs')
    .replace('./columnRoom.js', './columnRoom.mjs')
    .replace('./columnRoom.svelte.js', './gebaut.mjs')
  writeFileSync(name.replace('.svelte.js', '.built.mjs'), code)
}
build(%(glue)r, 'gebaut.mjs')
build(%(studio_columns)r, 'studioColumns.svelte.js')
const { leiste } = await import('./arbeitsleiste.mjs')
const { zustand } = await import('./zustand.mjs')
const { fitColumns, watchWindowWidth } = await import('./gebaut.mjs')
const { columnsForStudio, columnsBack } = await import('./studioColumns.built.mjs')
const stop = watchWindowWidth()
const studio = { offen: false }
const settle = () => { fitColumns(); fitColumns(); fitColumns() }
const resize = (width) => { window.innerWidth = width; listeners.resize(); settle() }
const shape = () => ({ left: !zustand.seitenleisteEingeklappt, right: leiste.offen })
const openStudio = () => { columnsForStudio(); studio.offen = true; settle() }
const closeStudio = () => { studio.offen = false; columnsBack(); settle() }
const report = {}
settle()
"""

_EPILOGUE = """
console.log('---REPORT---' + JSON.stringify(report))
process.exit(0)
"""


def _columns(scenario: str) -> dict:
    script = (
        _PROLOGUE
        % {
            "arithmetic": str(ARITHMETIC),
            "glue": str(GLUE),
            "studio_columns": str(STUDIO_COLUMNS),
        }
        + scenario
        + _EPILOGUE
    )
    with _pruefordner() as folder:
        return _node(script, folder)


@needs_node
def test_the_columns_fold_for_room_and_come_back_by_themselves():
    report = _columns("""
// Room enough: nothing moves.
settle()
report.roomy = shape()

// Narrower: the tools fold first, the sidebar stays.
resize(1000)
report.at1000 = shape()
// A drawer window: nothing beside the chat, nothing changes.
resize(700)
report.at700 = shape()
// Room again: the tools come back by themselves.
resize(1440)
report.backAt1440 = shape()

// Narrower still: both fold, the tools first and the sidebar after.
resize(800)
report.at800 = shape()
// Some room: the sidebar comes back before the tools do.
resize(1100)
report.at1100 = shape()
resize(1200)
report.at1200 = shape()

// The person opens the tools in a window too narrow for both: the sidebar
// gives way, not the tools they just asked for.
resize(1000)
leiste.offen = true
settle()
report.toolsAskedAt1000 = shape()
// ... and it comes back when the tools fold again.
leiste.offen = false
settle()
report.toolsFoldedAt1000 = shape()

// The person folds the sidebar themselves while the tools were folded for
// room: the room is there, the tools come back.
leiste.offen = true
resize(1440)
resize(1000)
zustand.seitenleisteEingeklappt = true
settle()
report.sidebarFoldedByHand = shape()

report.listenerStopped = (stop(), 'resize' in listeners)
""")
    both, only_left = {"left": True, "right": True}, {"left": True, "right": False}
    neither = {"left": False, "right": False}
    # Silence probe: with room enough no width and no column moves.
    assert report["roomy"] == both
    # The tools fold first, then (800) the sidebar too ...
    assert report["at1000"] == only_left
    assert report["at800"] == neither
    # ... a drawer window changes nothing ...
    assert report["at700"] == only_left
    # ... and they come back in the order the room allows: sidebar first.
    assert report["backAt1440"] == both
    assert report["at1100"] == only_left
    assert report["at1200"] == both
    # What the person asks for last gives way last.
    assert report["toolsAskedAt1000"] == {"left": False, "right": True}
    assert report["toolsFoldedAt1000"] == only_left
    # A column folded by hand is not brought back; the other one is.
    assert report["sidebarFoldedByHand"] == {"left": False, "right": True}
    assert report["listenerStopped"] is False


BOTH = {"left": True, "right": True}
ONLY_LEFT = {"left": True, "right": False}
NEITHER = {"left": False, "right": False}


@needs_node
def test_the_studio_columns_give_way_and_come_back_like_the_chats():
    report = _columns("""
openStudio()
report.openAt1440 = shape()
resize(1000)
report.at1000 = shape()
resize(800)
report.at800 = shape()
resize(1100)
report.at1100 = shape()
resize(1440)
report.backAt1440 = shape()
closeStudio()
report.closed = shape()
""")
    # Silence probe: room enough, the studio shows both columns open.
    assert report["openAt1440"] == BOTH
    # Narrower: the tools fold first, then the sidebar — as in the chat.
    assert report["at1000"] == ONLY_LEFT
    assert report["at800"] == NEITHER
    # With some room the sidebar comes back before the tools do ...
    assert report["at1100"] == ONLY_LEFT
    # ... and both are back once there is room for both.
    assert report["backAt1440"] == BOTH
    assert report["closed"] == BOTH


@needs_node
def test_a_studio_opened_in_a_narrow_window_opens_what_there_is_room_for():
    report = _columns("""
resize(1000)
report.before = shape()
openStudio()
report.during = shape()
resize(1440)
report.wide = shape()
closeStudio()
report.after = shape()
""")
    # The tools were folded for room: the person still has them open.
    assert report["before"] == ONLY_LEFT
    assert report["during"] == ONLY_LEFT
    assert report["wide"] == BOTH
    assert report["after"] == BOTH


@needs_node
def test_the_tools_the_studio_opened_for_itself_stay_closed_when_it_closes():
    """The studio opens the tools column only for itself. Folded for room
    while the studio stood, it must not come back once the person had it
    closed before — not at once and not when the window gets wider."""
    report = _columns("""
leiste.offen = false
settle()
report.before = shape()
openStudio()
report.openAt1440 = shape()
resize(1000)
report.at1000 = shape()
closeStudio()
report.closedAt1000 = shape()
resize(1440)
report.closedAt1440 = shape()
""")
    assert report["before"] == {"left": True, "right": False}
    assert report["openAt1440"] == BOTH
    assert report["at1000"] == ONLY_LEFT
    assert report["closedAt1000"] == ONLY_LEFT
    # Silence probe for the bookkeeping: the fold for room is let go of.
    assert report["closedAt1440"] == ONLY_LEFT


@needs_node
def test_a_sidebar_folded_by_hand_before_the_studio_is_folded_again_after_it():
    report = _columns("""
zustand.seitenleisteEingeklappt = true
settle()
openStudio()
resize(1000)
report.studioAt1000 = shape()
closeStudio()
report.after1000 = shape()
resize(1440)
report.after1440 = shape()
""")
    # The studio unfolds the sidebar; with the sidebar open the tools fold.
    assert report["studioAt1000"] == ONLY_LEFT
    # Closed, the sidebar goes back to the way the person had it, and the
    # tools, which only gave way for the studio's sidebar, come back.
    assert report["after1000"] == {"left": False, "right": True}
    assert report["after1440"] == {"left": False, "right": True}


@needs_node
def test_what_the_person_folds_inside_the_studio_stays_folded():
    report = _columns("""
openStudio()
leiste.offen = false
zustand.seitenleisteEingeklappt = true
settle()
closeStudio()
report.after = shape()
resize(1000)
resize(1440)
report.after1440 = shape()
""")
    assert report["after"] == NEITHER
    assert report["after1440"] == NEITHER


@needs_node
def test_what_the_person_asks_for_last_gives_way_last_in_the_studio():
    report = _columns("""
resize(1000)
openStudio()
report.during = shape()
leiste.offen = true
settle()
report.toolsAsked = shape()
leiste.offen = false
settle()
report.toolsFolded = shape()
""")
    assert report["during"] == ONLY_LEFT
    # The person opens the tools in a window too narrow for both: the
    # sidebar gives way, not the tools just asked for.
    assert report["toolsAsked"] == {"left": False, "right": True}
    assert report["toolsFolded"] == ONLY_LEFT


@needs_node
def test_a_drawer_window_leaves_the_columns_alone_for_the_studio():
    report = _columns("""
leiste.offen = false
resize(700)
report.before = shape()
openStudio()
report.during = shape()
closeStudio()
report.after = shape()
""")
    # Below the drawer's width the tools are a sheet: the studio does not
    # open it over the surface.
    assert report["before"] == ONLY_LEFT
    assert report["during"] == ONLY_LEFT
    assert report["after"] == ONLY_LEFT


def test_the_studio_leaves_the_columns_to_one_module():
    """The studio store hands the columns over and takes them back through
    the module that knows the rule; it does not write them itself."""
    store = (FRONTEND / "lib/studio.svelte.js").read_text(encoding="utf-8")
    assert "from './studioColumns.svelte.js'" in store
    assert "zeitweiseOeffnen" not in store
    glue = GLUE.read_text(encoding="utf-8")
    assert "studio" not in glue.split("*/", 1)[1], "the fold rule reads no studio state"
