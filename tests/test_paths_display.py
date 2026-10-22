"""How a path is shown and named: slashes everywhere, the folder's own name.

`frontend/src/lib/paths.js` is a plain module and is run in node rather than
read. A Windows path is shown with forward slashes; a Mac path comes back
exactly as it was, including a backslash that is a letter of a file's name.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "frontend" / "src" / "lib" / "paths.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _run(calls: list[tuple[str, str]]) -> list:
    script = (
        "import(process.argv[1]).then((m) => {"
        " const calls = JSON.parse(process.argv[2]);"
        " console.log(JSON.stringify(calls.map(([name, arg]) => m[name](arg))))"
        "})"
    )
    done = subprocess.run(
        ["node", "-e", script, MODULE.as_uri(), json.dumps(calls)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def test_a_windows_path_is_shown_with_slashes():
    paths = [
        "C:\\Users\\exe\\Test Ordner",
        "C:/Users/exe/gemischt\\datei.txt",
        "\\\\server\\share\\Projekt",
        "notizen\\absatz1.txt",
        "C:\\",
    ]
    shown = _run([("displayPath", p) for p in paths])
    assert shown == [
        "C:/Users/exe/Test Ordner",
        "C:/Users/exe/gemischt/datei.txt",
        "//server/share/Projekt",
        "notizen/absatz1.txt",
        "C:/",
    ]


def test_silence_a_mac_path_and_plain_text_come_back_unchanged():
    texts = ["/Users/exe/Projekt", "/Users/exe/a\\b", "app/main.py", "", "x"]
    assert _run([("displayPath", p) for p in texts]) == texts


def test_the_name_of_a_folder_is_its_last_part_on_either_system():
    paths = [
        "C:\\Users\\exe\\Test Ordner",
        "C:\\Users\\exe\\Test Ordner\\",
        "\\\\server\\share\\Projekt",
        "C:\\",
        "C:",
        "/Users/exe/Projekt",
        "/Users/exe/a\\b",
        "/",
        "",
    ]
    assert _run([("lastPart", p) for p in paths]) == [
        "Test Ordner",
        "Test Ordner",
        "Projekt",
        "C:/",
        "C:/",
        "Projekt",
        "a\\b",
        "/",
        "/",
    ]


def test_the_terminal_shows_the_folder_of_a_run_with_slashes():
    """The folder under a run's command is shown the way every path is; the
    command itself is never rewritten — a shell needs its backslashes."""
    markup = (ROOT / "frontend" / "src" / "teile" / "ModulTerminal.svelte").read_text(encoding="utf-8")
    assert "<span>{displayPath(eintrag.lauf.folder)}</span>" in markup
    assert 'title={displayPath(eintrag.lauf.folder)}' in markup
    assert "hervorheben(eintrag.lauf.befehl, 'bash')" in markup
