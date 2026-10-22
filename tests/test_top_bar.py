"""The window buttons stand in the first row of the sidebar on the Mac.

macOS drew a bar of its own: grey, darker than the frame under it, in no look's
colour. On the Mac the shell now leaves the system's bar out of the main
window (`fenster-electron/topbar.js`), the page draws no strip of its own
either, and the three window buttons stand in the first row of the sidebar in
front of the mark - over the signs of the narrow bar, 20 px wider, while the
sidebar is folded. The options are a function of the platform name and the
folded state, so node runs them here as the shell does; the parts that need a
window are read from the sources.

Where there is no Mac, nothing changes: the options are empty, the page makes
no room, and the splash keeps its strip to grab.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from tests.conftest import node_script

ROOT = Path(__file__).resolve().parent.parent
SHELL = ROOT / "fenster-electron"
APP = ROOT / "frontend" / "src" / "App.svelte"
SRC = ROOT / "frontend" / "src"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _run(body: str):
    script = f"""
import bar from {json.dumps((SHELL / "topbar.js").as_uri())}
console.log(JSON.stringify((() => {{
{body}
}})()))
"""
    done = node_script(script)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@needs_node
def test_on_the_mac_the_window_is_built_without_the_bar_of_the_system():
    options = _run("return bar.topBarOptions('darwin')")
    assert options["titleBarStyle"] == "hidden"
    assert set(options["trafficLightPosition"]) == {"x", "y"}


@needs_node
@pytest.mark.parametrize("platform", ["win32", "linux", "freebsd", ""])
def test_silence_where_there_is_no_mac_the_options_and_the_arguments_stay_empty(platform):
    result = _run(f"return [bar.topBarOptions({platform!r}), bar.topBarArguments({platform!r})]")
    assert result == [{}, []]


@needs_node
def test_the_page_is_told_by_an_argument_of_the_bridge_and_only_on_the_mac():
    result = _run("return [bar.topBarArguments('darwin'), bar.TOP_BAR_ARGUMENT]")
    assert result == [[result[1]], result[1]]
    preload = (SHELL / "preload.js").read_text(encoding="utf-8")
    assert f"topBar: process.argv.includes({result[1]!r})" in preload


def test_the_main_window_takes_the_options_and_the_argument_from_the_one_place():
    main = (SHELL / "main.js").read_text(encoding="utf-8")
    assert "const topbar = require('./topbar')" in main
    build = main.split("function fensterBauen() {", 1)[1].split("fenster.loadFile(", 1)[0]
    assert "const topBarOptions = topbar.topBarOptions(process.platform, sidebarFoldedRead())" in build
    assert "...topBarOptions," in build
    assert "additionalArguments: topbar.topBarArguments(process.platform)," in build
    # the rule is written once: no second place names the style
    assert "titleBarStyle" not in main
    # the log line that names the options the window was built with
    assert "Window top bar: ${JSON.stringify(topBarOptions)}" in build


def test_silence_no_other_window_of_the_shell_leaves_out_its_bar():
    main = (SHELL / "main.js").read_text(encoding="utf-8")
    assert main.count("...topBarOptions,") == 1  # spread into one window only
    assert "overrideBrowserWindowOptions: { width: 900, height: 720, ...menuBarOptions() }" in main
    # Windows keeps what it had: the menu bar rule is the one it was
    assert "return process.platform === 'darwin' ? {} : { autoHideMenuBar: true }" in main


def test_the_new_file_is_in_the_package():
    package = json.loads((SHELL / "package.json").read_text(encoding="utf-8"))
    assert "topbar.js" in package["build"]["files"]


def test_the_splash_has_a_strip_to_grab_only_where_the_page_draws_the_bar():
    page = (SHELL / "anzeige" / "index.html").read_text(encoding="utf-8")
    assert "window.exeHuelle && window.exeHuelle.topBar" in page
    assert "[data-top-bar]::before" in page and "-webkit-app-region: drag" in page


@needs_node
def test_the_window_buttons_stand_in_the_middle_of_the_first_row():
    result = _run("return { centre: bar.FIRST_ROW_CENTRE, height: bar.BUTTON_HEIGHT, open: bar.topBarOptions('darwin').trafficLightPosition, folded: bar.topBarOptions('darwin', true).trafficLightPosition }")
    # 8 of the window body + 14 of the row's padding + half of its 40 px button
    assert result["centre"] == 8 + 14 + 20
    assert result["open"]["y"] + result["height"] / 2 == result["centre"] and result["open"]["y"] == 36
    assert result["open"]["x"] == 18 and result["folded"] == {"x": 10, "y": 36}


@needs_node
def test_the_buttons_are_centred_over_the_narrow_bar_when_folded():
    folded = _run("return bar.buttonsAt(true)")
    # three buttons of 12 px with their gaps are 52 px wide; the folded bar is 72
    assert folded["x"] * 2 + 52 == 72


def test_the_shell_moves_the_buttons_when_the_page_says_the_sidebar_folded_or_opened():
    preload = (SHELL / "preload.js").read_text(encoding="utf-8")
    assert "ipcRenderer.send('sidebar-folded', folded === true)" in preload
    main = (SHELL / "main.js").read_text(encoding="utf-8")
    handler = main.split("ipcMain.on('sidebar-folded'", 1)[1].split("})", 1)[0]
    assert "process.platform !== 'darwin'" in handler
    assert "event.sender !== fenster.webContents" in handler
    assert "fenster.setWindowButtonPosition(topbar.buttonsAt(is))" in handler
    assert "sidebarFoldedKeep(is)" in handler
    # kept beside the geometry, and read again when the window is built
    assert "topbar.topBarOptions(process.platform, sidebarFoldedRead())" in main
    assert "...(folded ? { folded } : {})," in main


def test_the_page_draws_no_strip_above_the_columns():
    app = APP.read_text(encoding="utf-8")
    assert "top-bar" not in app and "ownTopBar" not in app
    assert 'class="fenster">\n  <!-- The drawing on the frame' in app


def test_the_page_tells_the_shell_which_shape_the_sidebar_has():
    app = APP.read_text(encoding="utf-8")
    assert "reportRail(zustand.seitenleisteEingeklappt || narrow.now)" in app
    lib = (SRC / "lib" / "windowButtons.svelte.js").read_text(encoding="utf-8")
    assert "window.exeHuelle?.sidebarFolded?.(Boolean(folded))" in lib
    assert "SEITENLEISTE_SCHMAL_ABFRAGE" in lib


def test_the_narrow_rail_is_wider_only_where_the_window_buttons_stand():
    lib = (SRC / "lib" / "windowButtons.svelte.js").read_text(encoding="utf-8")
    assert "export const RAIL_WIDTH = windowButtonsInPage ? 72 : 52" in lib
    assert "export const MARK_LEFT = windowButtonsInPage ? 86 : 18" in lib
    assert "export const RAIL_TOP = windowButtonsInPage ? 58 : 12" in lib
    assert "windowButtonsInPage = typeof window !== 'undefined' && Boolean(window.exeHuelle?.topBar)" in lib
    app = APP.read_text(encoding="utf-8")
    assert app.count("zustand.seitenleisteEingeklappt ? RAIL_WIDTH : zustand.seitenBreite") == 2
    rail = (SRC / "teile" / "Seitenleiste.svelte").read_text(encoding="utf-8")
    assert "width: var(--rail-width, 52px);" in rail and "padding: var(--rail-top, 12px) 0 12px;" in rail
    assert "padding: 14px 12px 12px var(--mark-left, 18px);" in rail


def test_the_first_row_of_the_sidebar_and_the_head_of_the_right_column_grab_the_window():
    rail = (SRC / "teile" / "Seitenleiste.svelte").read_text(encoding="utf-8")
    style = rail.split("<style>", 1)[1]
    assert re.search(r"\.markenkopf\.grab \{\s*-webkit-app-region: drag;", style)
    assert re.search(r"\.markenkopf\.grab :global\(button\) \{\s*-webkit-app-region: no-drag;", style)
    assert re.search(r"\.grab-strip \{[^}]*-webkit-app-region: drag;", style)
    assert 'class:grab={windowButtonsInPage}' in rail and '{#if windowButtonsInPage}' in rail
    column = (SRC / "teile" / "Arbeitsleiste.svelte").read_text(encoding="utf-8")
    assert '<div class="kopf" class:grab={windowButtonsInPage}>' in column
    assert re.search(r"\.kopf\.grab \{\s*-webkit-app-region: drag;", column)
    assert re.search(r"\.kopf\.grab :global\(button\),\s*\.kopf\.grab :global\(input\) \{\s*-webkit-app-region: no-drag;", column)
