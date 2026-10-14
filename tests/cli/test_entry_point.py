"""The one program in its client role: ``--cli`` hands the command line to
the terminal client, a packaged program called exe is the client by its
name, the service's own switches come first, and the command on the path —
the file the links point at — reaches the program through its link.

The last two tests run the built package where there is one (dist/, after
``pyinstaller deploy/exe-ai-terminal.spec``) and are skipped where there is
none: a test machine does not build the package to run the suite."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import start
from app import __version__

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "deploy" / "exe"

posix = pytest.mark.skipif(sys.platform == "win32", reason="the wrapper is a shell script")

# The two programs of the Windows folder build, written with the slash every
# system reads as a separator: the name is what is under test, and a
# backslash is part of the name anywhere but on Windows.
CLIENT_EXE = "C:/Programs/Exe AI/resources/exe-ai-terminal/exe.exe"
SERVICE_EXE = "C:/Programs/Exe AI/resources/exe-ai-terminal/Exe AI.exe"


def test_cli_hands_the_rest_of_the_line_to_the_client(capsys: pytest.CaptureFixture[str]) -> None:
    assert start.main(["--cli", "--version"]) == 0
    assert capsys.readouterr().out == __version__ + "\n"


def test_cli_help_is_the_clients_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert start.main(["--cli", "--help", "--lang", "en"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Run exe on its own or with options, a command, or both.")
    assert re.search(r"^  install\s", out, re.M)


def _frozen_as(monkeypatch: pytest.MonkeyPatch, executable: str) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", executable)


def test_a_packaged_program_called_exe_is_the_client_by_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _frozen_as(monkeypatch, CLIENT_EXE)
    assert start._ist_cli_programm() is True
    assert start.main(["--version"]) == 0
    assert capsys.readouterr().out == __version__ + "\n"


def test_the_service_exe_and_a_source_run_are_not_the_client_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The silence probe, twice: the service's own exe keeps its name, and
    an interpreter that happens to be called exe is not packaged."""
    _frozen_as(monkeypatch, SERVICE_EXE)
    assert start._ist_cli_programm() is False
    monkeypatch.delattr(sys, "frozen")
    monkeypatch.setattr(sys, "executable", "/somewhere/bin/exe")
    assert start._ist_cli_programm() is False


def test_serve_comes_before_the_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client starts the service from its own file with ``--serve``;
    that start is the service, whatever the file is called."""
    _frozen_as(monkeypatch, CLIENT_EXE)
    served: list[bool] = []

    def serve(*, with_window: bool = True) -> int:
        served.append(with_window)
        return 0

    monkeypatch.setattr(start, "_terminal_bedienen", serve)
    monkeypatch.setattr(start, "_cli_bedienen", lambda argumente: pytest.fail("taken for the client"))
    assert start.main(["--serve"]) == 0
    assert served == [False]


# --- the wrapper the links point at ------------------------------------------


def _wrapped(tmp_path: Path) -> tuple[Path, Path]:
    """The wrapper beside a stand-in program that prints what it was
    called with, laid out the way the installed app lays them out."""
    resources = tmp_path / "Exe AI.app" / "Contents" / "Resources"
    (resources / "bin").mkdir(parents=True)
    wrapper = resources / "bin" / "exe"
    shutil.copy(WRAPPER, wrapper)
    program = resources / "exe-ai-terminal" / "Exe AI"
    program.parent.mkdir()
    program.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    return wrapper, program


def _calls(command: list[str]) -> list[str]:
    run = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return run.stdout.splitlines()


@posix
def test_the_wrapper_reaches_the_program_through_a_link(tmp_path: Path) -> None:
    wrapper, _program = _wrapped(tmp_path)
    link = tmp_path / "usr" / "local" / "bin" / "exe"
    link.parent.mkdir(parents=True)
    link.symlink_to(wrapper)
    assert _calls([str(link), "--version"]) == ["--cli", "--version"]
    assert _calls([str(link), "--chat", "a chat with spaces"]) == ["--cli", "--chat", "a chat with spaces"]


@posix
def test_the_wrapper_follows_a_chain_of_links_to_its_end(tmp_path: Path) -> None:
    """A link to a link — a folder of the user's own on the path, pointing
    at the placed link — and a relative one, counted from where it lies."""
    wrapper, _program = _wrapped(tmp_path)
    placed = tmp_path / "usr" / "local" / "bin" / "exe"
    placed.parent.mkdir(parents=True)
    placed.symlink_to(wrapper)
    own = tmp_path / "home" / "bin" / "exe"
    own.parent.mkdir(parents=True)
    own.symlink_to(placed)
    assert _calls([str(own), "--version"]) == ["--cli", "--version"]
    relative = tmp_path / "usr" / "local" / "bin" / "exe-too"
    relative.symlink_to("exe")
    assert _calls([str(relative), "--help"]) == ["--cli", "--help"]


@posix
def test_the_wrapper_works_without_a_link_as_well(tmp_path: Path) -> None:
    wrapper, _program = _wrapped(tmp_path)
    assert _calls([str(wrapper), "install"]) == ["--cli", "install"]


@posix
def test_the_wrapper_is_executable_in_the_repository() -> None:
    assert os.access(WRAPPER, os.X_OK), "the packer copies the mode it finds"


# --- the built package, where there is one -----------------------------------


def _built_program() -> Path:
    if sys.platform == "win32":
        program = ROOT / "dist" / "Exe AI" / "exe.exe"
    else:
        program = ROOT / "dist" / "Exe AI" / "Exe AI"
    if not program.is_file():
        pytest.skip("no built package in dist/")
    if program.stat().st_mtime < (ROOT / "cli" / "main.py").stat().st_mtime:
        # What it says is what the client said when it was built.
        pytest.skip("the built package is older than the client's sources")
    return program


def _packaged(*arguments: str) -> str:
    program = _built_program()
    switches = [] if sys.platform == "win32" else ["--cli"]
    run = subprocess.run([str(program), *switches, *arguments], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    return run.stdout


def test_the_built_package_says_its_version() -> None:
    assert _packaged("--version") == __version__ + "\n"


def test_the_built_package_knows_the_commands() -> None:
    out = _packaged("--help", "--lang", "en")
    for word in ("service start", "service run", "service stop", "service status", "install", "--url", "--chat"):
        assert re.search(rf"^  {re.escape(word)}\s", out, re.M), word
