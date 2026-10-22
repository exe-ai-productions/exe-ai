"""``exe`` without a command starts the chat, and the chat needs a terminal.
Started from a pipe or from a program with no terminal — the model's
``run_command`` is one — it ends at once with the sentence for a missing
terminal and the code 2, instead of waiting for somebody to type until its
caller gives up."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from cli import main as main_module
from tests.cli.stub_service import StubService
from tests.cli.test_setup import run_program, texts


def test_without_a_command_and_without_a_terminal_it_says_so_and_ends_with_two(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    started: list[bool] = []

    def fake_run(*args: object, **kwargs: object) -> int:
        started.append(True)
        return 0

    monkeypatch.setattr(main_module, "_run", fake_run)
    began = time.monotonic()
    code = run_program(stub, tmp_path, monkeypatch, terminal=False)
    assert code == 2
    assert time.monotonic() - began < 5
    assert capsys.readouterr().err.strip() == texts().t("cli.needs_terminal", program="exe")
    assert started == []


def test_with_a_terminal_the_chat_is_started_as_before(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[bool] = []

    def fake_run(*args: object, **kwargs: object) -> int:
        started.append(True)
        return 0

    monkeypatch.setattr(main_module, "_run", fake_run)
    assert run_program(stub, tmp_path, monkeypatch, terminal=True) == 0
    assert started == [True]


def test_a_command_without_a_terminal_runs_as_before(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_program(stub, tmp_path, monkeypatch, "theme", "pearl", terminal=False)
    assert code == 0
    assert texts().t("cli.needs_terminal", program="exe") not in capsys.readouterr().err


def test_a_message_from_a_script_does_not_need_a_terminal_either(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_program(stub, tmp_path, monkeypatch, "-p", "hello", terminal=False)
    assert code in (0, 1)
    assert texts().t("cli.needs_terminal", program="exe") not in capsys.readouterr().err
