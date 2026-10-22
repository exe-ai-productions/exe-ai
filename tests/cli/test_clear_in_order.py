"""``/clear`` empties the field of the history, and the chat stays as it is.
It takes its place among the pieces of the history, whenever it is sent:
what was written before it goes with the field — a shell line's output
included — and what is written after it stands in the emptied field."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from cli import commands
from cli.interfaces import Context
from tests.cli.program import (
    EMPTIED,
    ENTER,
    FULL_COLOURS,
    Gated,
    Run,
    run_client,
    taped_history,
    terminal,
)
from tests.cli.stub_service import StubService, eventually

ASKED = "What grows in the shade"
ANSWERED = "Hello."

EARLY = "an early piece"
LATER = "a later piece"


def test_sent_beside_a_running_answer_it_takes_what_was_written_before_it_with_it(
    gated: Gated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    tape = taped_history(monkeypatch)

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: gated.watchers == 1)
        type_in(ASKED + ENTER)
        eventually(lambda: ctx.session.answering and gated.running() == 1)
        ctx.screen.print_above(EARLY)
        eventually(lambda: EARLY in tape.getvalue())
        type_in("/clear" + ENTER)
        eventually(lambda: EMPTIED in tape.getvalue())
        ctx.screen.print_above(LATER)
        eventually(lambda: LATER in tape.getvalue())
        assert gated.running() == 1
        gated.gate.set()
        eventually(lambda: gated.running() == 0 and not ctx.session.answering)
        type_in("/quit" + ENTER)

    with gated.http() as http:
        assert run_client(http, tmp_path, monkeypatch, drive, output=output).code == 0
    assert tape.getvalue().count(EMPTIED) == 1
    before, after = tape.getvalue().split(EMPTIED)
    assert EARLY in before
    assert EARLY not in after
    # What was written after the emptying stands in the emptied field.
    assert LATER in after
    # The chat is as it was.
    assert [held["title"] for held in gated.chats.values()] == [ASKED]


def test_sent_beside_an_answer_that_is_over_by_then_it_still_takes_its_place(
    gated: Gated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whether an answer still runs when the command gets to the screen
    makes no difference: what was written until then goes with the field
    like any piece of the answer."""
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    tape = taped_history(monkeypatch)

    def only_after_the_answer(ctx: Context, argument: str) -> None:
        gated.gate.set()
        eventually(lambda: gated.running() == 0 and not ctx.session.answering)
        ctx.screen.print_above(EARLY)
        ctx.screen.clear()

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        assert isinstance(ctx.commands, commands.Commands)
        # The command as it is, only later: it gets to the screen once the
        # answer it was sent beside is over.
        ctx.commands.register(commands.Command("clear", "cli.cmd_clear", only_after_the_answer))
        eventually(lambda: gated.watchers == 1)
        type_in(ASKED + ENTER)
        eventually(lambda: ctx.session.answering and gated.running() == 1)
        type_in("/clear" + ENTER)
        eventually(lambda: EMPTIED in tape.getvalue())
        ctx.screen.print_above(LATER)
        eventually(lambda: LATER in tape.getvalue())
        type_in("/quit" + ENTER)

    with gated.http() as http:
        assert run_client(http, tmp_path, monkeypatch, drive, output=output).code == 0
    assert tape.getvalue().count(EMPTIED) == 1
    before, after = tape.getvalue().split(EMPTIED)
    assert ANSWERED in before
    assert EARLY in before
    assert EARLY not in after
    assert LATER in after


@pytest.mark.skipif(sys.platform == "win32", reason="the shell of the test is a POSIX one")
def test_waiting_behind_a_shell_line_it_takes_that_lines_last_output_with_it(
    stub: StubService,
    stub_http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No answer runs: the command waits in the queue behind the shell
    line and is taken the moment that line is over — with everything the
    line printed."""
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    tape = taped_history(monkeypatch)
    go_on = tmp_path / "go-on"
    waiting = f"while [ ! -e {shlex.quote(str(go_on))} ]; do sleep 0.02; done"
    # Each line is typed in two halves, so it stands in the tape only once
    # the shell has printed it.
    line = f'!echo shell-li""ne-1; {waiting}; echo shell-li""ne-2; sleep 0.05; echo shell-li""ne-3'
    printed = ("shell-line-1", "shell-line-2", "shell-line-3")

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(line + ENTER)
        eventually(lambda: printed[0] in tape.getvalue())
        # Behind the shell line, which still runs.
        type_in("/clear" + ENTER)
        go_on.touch()
        eventually(lambda: EMPTIED in tape.getvalue())
        ctx.screen.print_above(LATER)
        eventually(lambda: LATER in tape.getvalue())
        type_in("/quit" + ENTER)

    assert run_client(stub_http, tmp_path, monkeypatch, drive, output=output).code == 0
    assert tape.getvalue().count(EMPTIED) == 1
    before, after = tape.getvalue().split(EMPTIED)
    assert all(word in before for word in printed)
    assert not any(word in after for word in printed)
    assert LATER in after


def test_sent_while_nothing_runs_the_field_is_emptied_once_and_the_chat_stays(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    tape = taped_history(monkeypatch)

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(ASKED + ENTER)
        eventually(lambda: ANSWERED in tape.getvalue())
        # Over on both sides: the next line is taken in its own turn.
        eventually(lambda: stub.running() == 0 and not ctx.session.answering)
        type_in("/clear" + ENTER)
        eventually(lambda: EMPTIED in tape.getvalue())
        ctx.screen.print_above(LATER)
        eventually(lambda: LATER in tape.getvalue())
        type_in("/quit" + ENTER)

    assert run_client(stub_http, tmp_path, monkeypatch, drive, output=output).code == 0
    assert tape.getvalue().count(EMPTIED) == 1
    before, after = tape.getvalue().split(EMPTIED)
    assert ANSWERED in before
    assert ANSWERED not in after
    assert LATER in after
    # The chat is as it was.
    assert [held["title"] for held in stub.chats.values()] == [ASKED]
