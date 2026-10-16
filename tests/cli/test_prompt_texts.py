"""``/memory`` and ``/system`` and their words from outside: the text goes
to the editor of the computer and what comes back is saved — or nothing is
sent. The service is the stand-in and the editor a small script."""

from __future__ import annotations

import shlex
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cli import commands, outside
from cli.interfaces import Context
from cli.main import main
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, model

SCRIPT = """\
import os, sys
path = sys.argv[1]
mode = os.environ.get("EDITOR_MODE", "append")
text = open(path, encoding="utf-8").read()
if mode == "append":
    open(path, "w", encoding="utf-8").write(text + "A new line.\\n")
elif mode == "empty":
    open(path, "w", encoding="utf-8").close()
elif mode == "fail":
    open(path, "w", encoding="utf-8").write(text + "Never taken.\\n")
    sys.exit(2)
elif mode == "same":
    pass
"""


def texts() -> Texts:
    return Texts("en")


@pytest.fixture(autouse=True)
def the_editor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "fake_editor.py"
    script.write_text(SCRIPT, encoding="utf-8")
    # The editor line is split the way the system splits a command line: with
    # double quotes on Windows, where the words keep a single quote.
    quote = (lambda word: f'"{word}"') if sys.platform == "win32" else shlex.quote
    monkeypatch.setenv("VISUAL", f"{quote(sys.executable)} {quote(str(script))}")
    monkeypatch.delenv("EDITOR_MODE", raising=False)


@pytest.fixture
def tool(
    stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client
) -> Context:
    stub.models = [model("local", "Local Model")]
    stub.long_texts["/memory"] = "Likes tea.\n"
    stub.long_texts["/system-prompt"] = "Answer briefly.\n"
    context = wire(stub_http)
    context.renderer = RecordingRenderer()
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    return context


# --- /memory -----------------------------------------------------------------------------


def test_memory_saves_what_the_editor_gave_back_and_says_so(tool, stub):
    tool.commands.run("/memory")
    assert stub.text_writes == [("/memory", "Likes tea.\nA new line.\n")]
    assert tool.renderer.notices == [texts().t("gedaechtnis.gesichert")]
    assert tool.renderer.errors == []


def test_memory_emptied_says_everything_is_forgotten(tool, stub, monkeypatch):
    monkeypatch.setenv("EDITOR_MODE", "empty")
    tool.commands.run("/memory")
    assert stub.text_writes == [("/memory", "")]
    assert tool.renderer.notices == [texts().t("gedaechtnis.geleert")]


def test_memory_unchanged_sends_nothing_and_says_nothing(tool, stub, monkeypatch):
    monkeypatch.setenv("EDITOR_MODE", "same")
    tool.commands.run("/memory")
    assert stub.text_writes == []
    assert tool.renderer.notices == [] and tool.renderer.errors == []


def test_memory_after_an_error_code_sends_nothing_and_says_nothing(tool, stub, monkeypatch):
    monkeypatch.setenv("EDITOR_MODE", "fail")
    tool.commands.run("/memory")
    assert stub.text_writes == []
    assert tool.renderer.notices == [] and tool.renderer.errors == []
    assert stub.long_texts["/memory"] == "Likes tea.\n"


def test_memory_that_the_service_refuses_says_it_could_not_be_saved(tool, stub):
    stub.refuse_writes = True
    tool.commands.run("/memory")
    assert tool.renderer.errors == [texts().t("gedaechtnis.nicht_gesichert")]
    assert tool.renderer.notices == []


# --- /system -----------------------------------------------------------------------------


def test_system_saves_the_instructions_and_leaves_the_memory_alone(tool, stub):
    tool.commands.run("/system")
    assert stub.text_writes == [("/system-prompt", "Answer briefly.\nA new line.\n")]
    assert stub.long_texts["/memory"] == "Likes tea.\n"
    assert tool.renderer.notices == [texts().t("systemprompt.gesichert")]


def test_system_emptied_says_so(tool, stub, monkeypatch):
    monkeypatch.setenv("EDITOR_MODE", "empty")
    tool.commands.run("/system")
    assert tool.renderer.notices == [texts().t("systemprompt.geleert")]


def test_system_that_the_service_refuses_says_so(tool, stub):
    stub.refuse_writes = True
    tool.commands.run("/system")
    assert tool.renderer.errors == [texts().t("systemprompt.nicht_gesichert")]


def test_system_unchanged_sends_nothing(tool, stub, monkeypatch):
    monkeypatch.setenv("EDITOR_MODE", "same")
    tool.commands.run("/system")
    assert stub.text_writes == []
    assert tool.renderer.notices == []


# --- From outside ------------------------------------------------------------------------


def run_outside(
    stub: StubService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *words: str,
    terminal: bool,
) -> int:
    monkeypatch.setattr(outside, "has_terminal", lambda: terminal)
    with create_pipe_input() as pipe:
        net = threading.Timer(20.0, pipe.close)
        net.start()
        try:
            with create_app_session(input=pipe, output=DummyOutput()):
                return main(
                    [*words, "--lang", "en"],
                    http=stub.http(),
                    prefs_path=tmp_path / "cli.json",
                )
        finally:
            net.cancel()


def test_exe_memory_without_a_terminal_says_what_to_give_and_writes_nothing(
    stub, tmp_path, monkeypatch, capsys
):
    stub.models = [model("local", "Local Model")]
    code = run_outside(stub, tmp_path, monkeypatch, "memory", terminal=False)
    assert code == 2
    assert capsys.readouterr().err.strip() == texts().t("cli.needs_terminal", program="exe")
    assert stub.text_writes == []


def test_exe_memory_at_a_terminal_saves_and_says_so(stub, tmp_path, monkeypatch, capsys):
    stub.models = [model("local", "Local Model")]
    stub.long_texts["/memory"] = "Likes tea.\n"
    code = run_outside(stub, tmp_path, monkeypatch, "memory", terminal=True)
    assert code == 0
    assert stub.text_writes == [("/memory", "Likes tea.\nA new line.\n")]
    assert capsys.readouterr().out.strip() == texts().t("gedaechtnis.gesichert")


def test_exe_system_at_a_terminal_saves_the_instructions(stub, tmp_path, monkeypatch, capsys):
    stub.models = [model("local", "Local Model")]
    code = run_outside(stub, tmp_path, monkeypatch, "system", terminal=True)
    assert code == 0
    assert [route for route, _ in stub.text_writes] == ["/system-prompt"]
    assert capsys.readouterr().out.strip() == texts().t("systemprompt.gesichert")


# --- Through the screen that runs --------------------------------------------------------


def test_memory_typed_at_the_running_screen_lends_the_terminal_and_saves(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The real screen: the line goes in as keys, the editor runs while the
    block stands aside, and the screen goes on and ends with its next
    line."""
    from tests.cli.program import Run, run_client
    from tests.cli.stub_service import eventually

    stub.models = [model("local", "Local Model")]
    stub.long_texts["/memory"] = "Likes tea.\n"

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in("/memory\r")
        eventually(lambda: stub.text_writes)
        type_in("/quit\r")

    with stub.http() as http:
        run = run_client(http, tmp_path, monkeypatch, drive)
    assert run.code == 0
    assert stub.text_writes == [("/memory", "Likes tea.\nA new line.\n")]
