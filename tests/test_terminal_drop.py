"""A file dropped on the CLI tab is typed as a path, the way a terminal of
the computer types it (frontend/src/lib/droppedPaths.js, windowTerminal.js,
teile/Terminal.svelte, fenster-electron/preload.js).

The writing of the path is pure and run in Node; the wiring of the tab and of
the bridge is read off the source — Electron itself is not here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "frontend" / "src" / "lib"
TAB = ROOT / "frontend" / "src" / "teile" / "Terminal.svelte"
PRELOAD = ROOT / "fenster-electron" / "preload.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _written(paths: list[str], platform: str) -> str:
    script = (
        "import(process.argv[1]).then((m) => console.log(JSON.stringify("
        "m.droppedText(JSON.parse(process.argv[2]), process.argv[3]))))"
    )
    done = subprocess.run(
        ["node", "-e", script, (LIB / "droppedPaths.js").as_uri(), json.dumps(paths), platform],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(done.stdout)


@needs_node
def test_a_path_goes_as_it_is_and_a_blank_takes_a_backslash():
    assert _written(["/Users/a/notes.txt"], "mac") == "/Users/a/notes.txt"
    assert _written(["/Users/a/probe datei.txt"], "mac") == "/Users/a/probe\\ datei.txt"


@needs_node
def test_several_files_stand_apart_by_one_blank_in_the_order_dropped():
    assert _written(["/a/one.txt", "/b/two words.txt"], "other") == "/a/one.txt /b/two\\ words.txt"


@needs_node
def test_a_quote_and_a_backslash_in_a_name_are_escaped_too():
    assert _written(["/a/it's.txt"], "mac") == "/a/it\\'s.txt"
    assert _written(['/a/"q".txt'], "mac") == '/a/\\"q\\".txt'


@needs_node
def test_on_windows_each_path_stands_in_quotation_marks():
    assert _written(["C:\\Users\\a\\probe datei.txt", "D:\\x.txt"], "windows") == (
        '"C:\\Users\\a\\probe datei.txt" "D:\\x.txt"'
    )


@needs_node
def test_silence_a_file_without_a_path_is_not_typed():
    # The bridge names an empty path for a file that does not lie on the disk.
    assert _written(["", "/a/b.txt", ""], "mac") == "/a/b.txt"
    assert _written([""], "mac") == ""


def test_the_bridge_names_the_path_of_a_dropped_file_through_electrons_own_call():
    source = PRELOAD.read_text(encoding="utf-8")

    assert "const { contextBridge, ipcRenderer, webUtils } = require('electron')" in source
    assert "webUtils.getPathForFile(file)" in source
    # A refusal of the call is an empty path, not an error in the page.
    assert "catch {\n        return ''" in source


def test_the_tab_takes_only_files_and_leaves_every_other_drag_alone():
    source = TAB.read_text(encoding="utf-8")

    assert "event.dataTransfer?.types?.includes('Files')" in source
    assert source.count("if (!carriesFiles(event)) return") == 2
    assert "ondragover={overTab} ondrop={dropped}" in source
    # A typed drop stops at the tab, so the window does not attach the same
    # file to the chat as well; one that could not be typed goes on to it.
    assert "if (typeDropped(event.dataTransfer.files)) event.stopPropagation()" in source


def test_the_paths_go_in_as_a_paste_through_the_gate_of_every_key():
    source = (LIB / "windowTerminal.js").read_text(encoding="utf-8")
    start = source.index("export function typeDropped(")
    body = source[start : source.index("\n}\n", start)]

    # A paste: the client reads it as what a dropped file is, and the
    # terminal's own `onData` hands it to the same gate as a key.
    assert "xterm.paste(text)" in body
    assert "shell.write" not in body
    # Nothing is typed into a client that has ended or has no bridge call.
    assert "session.ended" in body
    assert "shell?.pathOf" in body
