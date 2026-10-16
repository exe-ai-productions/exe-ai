"""The text editor of the computer, as the commands with long texts use it:
which program is started, what comes back, and what stays quiet. The editor
is a small script of the test; nothing is drawn."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cli import editor
from cli.interfaces import Screen
from tests.cli.conftest import RecordingRenderer


class PlainScreen(Screen):
    """A screen that does nothing, so the terminal is handed over as it is."""


def found(*present: str):
    """A ``which`` that knows only the names given."""
    return lambda name: f"/usr/bin/{name}" if name in present else None


# --- Which editor ------------------------------------------------------------------------


def test_visual_goes_before_editor():
    assert editor.command({"VISUAL": "micro", "EDITOR": "nano"}, windows=False) == ["micro"]


def test_editor_is_taken_where_visual_is_empty():
    assert editor.command({"VISUAL": "  ", "EDITOR": "nano"}, windows=False) == ["nano"]


def test_a_value_with_switches_is_split_into_words_like_a_shell_would():
    words = editor.command({"VISUAL": "code --wait --new-window 'my file'"}, windows=False)
    assert words == ["code", "--wait", "--new-window", "my file"]


def test_a_value_whose_quotes_never_close_names_no_editor():
    words = editor.command({"VISUAL": "code 'oops", "EDITOR": "nano"}, windows=False)
    assert words == ["nano"]


def test_on_windows_without_a_variable_the_notepad_is_the_editor():
    assert editor.command({}, windows=True, which=found("nano")) == ["notepad"]


def test_on_windows_a_backslash_path_in_quotes_stays_whole():
    words = editor.command({"VISUAL": r'"C:\Program Files\Editor\ed.exe" --wait'}, windows=True)
    assert words == [r"C:\Program Files\Editor\ed.exe", "--wait"]


def test_otherwise_the_first_usual_editor_on_the_path_is_taken():
    assert editor.command({}, windows=False, which=found("emacs", "pico")) == ["pico"]
    assert editor.command({}, windows=False, which=found("editor", "nano")) == ["editor"]


def test_where_none_is_found_it_is_vi():
    assert editor.command({}, windows=False, which=found()) == ["vi"]


# --- Editing -----------------------------------------------------------------------------

SCRIPT = """\
import os, sys
path = sys.argv[1]
record = os.environ.get("EDITOR_RECORD")
if record:
    open(record, "w", encoding="utf-8").write(path)
mode = os.environ.get("EDITOR_MODE", "append")
if mode == "append":
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\\nOne more line.\\n")
elif mode == "empty":
    open(path, "w", encoding="utf-8").close()
elif mode == "blanks":
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\\n\\n   \\n")
elif mode == "fail":
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\\nNever taken.\\n")
    sys.exit(3)
"""


@pytest.fixture
def tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A context that holds only the screen and the renderer the editor
    needs, with the script as the editor."""
    script = tmp_path / "fake_editor.py"
    script.write_text(SCRIPT, encoding="utf-8")
    # The editor line is split the way the system splits a command line: with
    # double quotes on Windows, where the words keep a single quote.
    quote = (lambda word: f'"{word}"') if sys.platform == "win32" else shlex.quote
    monkeypatch.setenv("VISUAL", f"{quote(sys.executable)} {quote(str(script))}")
    monkeypatch.setenv("EDITOR_RECORD", str(tmp_path / "path.txt"))
    monkeypatch.delenv("EDITOR_MODE", raising=False)
    context = SimpleNamespace(screen=PlainScreen(), renderer=RecordingRenderer())
    context.record = tmp_path / "path.txt"
    return context


def test_the_saved_text_comes_back(tool):
    assert editor.edit(tool, "First line.\n") == "First line.\n\nOne more line.\n"
    assert tool.renderer.errors == [] and tool.renderer.notices == []


def test_the_file_is_gone_afterwards(tool):
    editor.edit(tool, "First line.\n")
    assert not Path(tool.record.read_text(encoding="utf-8")).parent.exists()


def test_the_text_was_in_the_file_the_editor_opened(tool, monkeypatch):
    monkeypatch.setenv("EDITOR_MODE", "empty")
    # An editor that empties the file brings an empty text back.
    assert editor.edit(tool, "Something.\n") == ""


def test_a_text_that_only_gained_blanks_at_its_edges_is_nothing_to_take_over(tool, monkeypatch):
    monkeypatch.setenv("EDITOR_MODE", "blanks")
    assert editor.edit(tool, "Same words.") is None


def test_an_error_code_drops_the_text_and_says_nothing(tool, monkeypatch):
    monkeypatch.setenv("EDITOR_MODE", "fail")
    assert editor.edit(tool, "Before.") is None
    assert tool.renderer.errors == [] and tool.renderer.notices == []
    assert not Path(tool.record.read_text(encoding="utf-8")).parent.exists()


def test_an_editor_that_cannot_be_started_is_said_in_the_systems_words(tool, monkeypatch):
    monkeypatch.setenv("VISUAL", "no-such-editor-0f3a")
    assert editor.edit(tool, "Before.") is None
    # What the system says for a program it cannot start: the words are its
    # own, so they are asked of it instead of written down here.
    with pytest.raises(OSError) as asked:
        subprocess.run(["no-such-editor-0f3a"], check=False)
    assert tool.renderer.errors == [str(asked.value)]


def test_the_editor_is_never_started_through_a_shell(tool, monkeypatch):
    seen: list[dict[str, Any]] = []
    real = subprocess.run

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append({"args": args, "kwargs": kwargs})
        return real(*args, **kwargs)

    monkeypatch.setattr(editor.subprocess, "run", spy)
    editor.edit(tool, "Text.")
    assert len(seen) == 1
    assert isinstance(seen[0]["args"][0], list)
    assert not seen[0]["kwargs"].get("shell")


def test_the_terminal_is_lent_for_as_long_as_the_editor_runs(tool):
    lent: list[str] = []

    class Lending(Screen):
        def hand_over(self, work):
            lent.append("before")
            result = work()
            lent.append("after")
            return result

    tool.screen = Lending()
    editor.edit(tool, "Text.")
    assert lent == ["before", "after"]
